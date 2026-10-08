"""SQLite evidence storage with adjustment-safe identities and read-time health."""
import json
import gzip
import hashlib
import sqlite3
import zlib
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .conventions import SHANGHAI, interval_name, parse_time, price_basis_name
from .http import redact_error
from .models import Bar
from .sessions import quote_freshness
from .responses import ResponseVault

SCHEMA_VERSION = 5
SCHEMAS = {
    "quotes": "provider TEXT NOT NULL,symbol TEXT NOT NULL,as_of TEXT NOT NULL,name TEXT,asset_class TEXT,currency TEXT,session TEXT,last REAL,previous_close REAL,open REAL,high REAL,low REAL,volume REAL,amount REAL,volume_unit TEXT,amount_unit TEXT,book_volume_unit TEXT,turnover_pct REAL,volume_ratio_vendor REAL,pe_ttm REAL,pb REAL,market_cap REAL,inner_volume REAL,outer_volume REAL,bid_book_json TEXT NOT NULL,ask_book_json TEXT NOT NULL,source_url TEXT,quality TEXT NOT NULL,latency TEXT NOT NULL,raw_json TEXT NOT NULL,collected_at TEXT NOT NULL,PRIMARY KEY(provider,symbol,as_of)",
    "bars": "provider TEXT NOT NULL,symbol TEXT NOT NULL,interval TEXT NOT NULL,timestamp TEXT NOT NULL,open REAL NOT NULL,high REAL NOT NULL,low REAL NOT NULL,close REAL NOT NULL,volume REAL,amount REAL,volume_unit TEXT,amount_unit TEXT,currency TEXT,session TEXT,price_basis TEXT NOT NULL,source_url TEXT,quality TEXT NOT NULL,raw_json TEXT NOT NULL,collected_at TEXT NOT NULL,PRIMARY KEY(provider,symbol,interval,timestamp,price_basis)",
    "observations": "provider TEXT NOT NULL,dataset TEXT NOT NULL,identity TEXT NOT NULL,as_of TEXT NOT NULL,value_json TEXT NOT NULL,unit TEXT,currency TEXT,publication TEXT,revision TEXT NOT NULL,price_basis TEXT,latency TEXT,quality TEXT,source_url TEXT,raw_json TEXT NOT NULL,collected_at TEXT NOT NULL,PRIMARY KEY(provider,dataset,identity,as_of,revision)",
    "indicators": "symbol TEXT NOT NULL,interval TEXT NOT NULL,timestamp TEXT NOT NULL,name TEXT NOT NULL,value REAL,parameters_json TEXT NOT NULL,input_provider TEXT NOT NULL,quality TEXT NOT NULL,price_basis TEXT NOT NULL,unit TEXT,currency TEXT,calculated_at TEXT NOT NULL,PRIMARY KEY(symbol,interval,timestamp,name,input_provider,price_basis)",
    "provider_runs": "id INTEGER PRIMARY KEY AUTOINCREMENT,provider TEXT NOT NULL,dataset TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT NOT NULL,status TEXT NOT NULL,row_count INTEGER NOT NULL,error TEXT,details_json TEXT NOT NULL",
}


class MarketStore:
    def __init__(self, path, *, read_only=False):
        self.path = Path(path).expanduser().resolve()
        self.read_only = read_only
        self.response_vault = None
        self._response_offset = 0
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError("Evidence database does not exist; collect or initialize it first")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) if self.read_only else sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.create_function("at_or_before", 2, self._at_or_before)
        if not self.read_only:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _at_or_before(value, cutoff):
        try:
            return int(parse_time(value) <= parse_time(cutoff))
        except (ValueError, TypeError):
            return 0

    def initialize(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            for table, schema in SCHEMAS.items():
                db.execute(f"CREATE TABLE IF NOT EXISTS {table}({schema})")
            for table in ('quotes', 'bars', 'observations'):
                columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
                if 'source_receipts_json' not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN source_receipts_json TEXT NOT NULL DEFAULT '[]'")
            # Rebuild legacy PKs in one transaction. Retain uncertain old indicator identities as unverified.
            for table in ("bars", "observations", "indicators"):
                actual = [r["name"] for r in sorted(db.execute(f"PRAGMA table_info({table})"), key=lambda r: r["pk"]) if r["pk"]]
                expected = {"bars": ["provider", "symbol", "interval", "timestamp", "price_basis"],
                            "observations": ["provider", "dataset", "identity", "as_of", "revision"],
                            "indicators": ["symbol", "interval", "timestamp", "name", "input_provider", "price_basis"]}[table]
                if actual == expected:
                    continue
                records = [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
                db.execute(f"ALTER TABLE {table} RENAME TO {table}_legacy_migration")
                db.execute(f"CREATE TABLE {table}({SCHEMAS[table]})")
                if table in ('bars', 'observations'):
                    db.execute(f"ALTER TABLE {table} ADD COLUMN source_receipts_json TEXT NOT NULL DEFAULT '[]'")
                columns = [r["name"] for r in db.execute(f"PRAGMA table_info({table})")]
                for row in records:
                    if table in ("bars", "indicators"):
                        row["interval"] = interval_name(row["interval"])
                    if table == "bars":
                        row["price_basis"] = price_basis_name(row.get("price_basis") or "unknown")
                        if row["provider"] == "baostock_free_history":
                            flag = json.loads(row.get("raw_json") or "{}").get("adjustflag")
                            row["price_basis"] = {"1":"hfq","2":"qfq","3":"unadjusted"}.get(flag,row["price_basis"])
                    elif table == "indicators":
                        row.update(price_basis="legacy_unknown", quality="legacy_basis_unverified", unit="unknown", currency="")
                    else:
                        row["revision"] = row.get("revision") or "unknown"
                    db.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", [row.get(col, "") for col in columns])
                db.execute(f"DROP TABLE {table}_legacy_migration")
            db.execute("CREATE INDEX IF NOT EXISTS idx_bars_lookup ON bars(symbol,interval,timestamp)")
            db.execute("INSERT OR REPLACE INTO meta VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    def _write(self, table, records):
        if self.read_only:raise PermissionError('Read-only evidence stores cannot create receipts or write data')
        records = list(records)
        if not records:
            return 0
        checked = set()
        for row in records:
            for reference in json.loads(row.get('source_receipts_json', '[]')):
                key = json.dumps(reference, sort_keys=True)
                if key not in checked:
                    ResponseVault.verify_reference(reference)
                    checked.add(key)
        # Freeze the source-normalized receipt before upsert can replace revised historical values.
        payload=json.dumps({"schema_version":SCHEMA_VERSION,"table":table,"rows":records},ensure_ascii=False,sort_keys=True,allow_nan=False).encode("utf-8")
        digest=hashlib.sha256(payload).hexdigest()
        archive=self.path.parent/"receipts"/table
        archive.mkdir(parents=True,exist_ok=True)
        target=archive/(digest+".json.gz")
        if not target.exists():
            with target.open("xb") as handle:
                handle.write(gzip.compress(payload,mtime=0))
        columns = list(records[0])
        with self.connect() as db:
            db.executemany(f"INSERT OR REPLACE INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                           [[row[column] for column in columns] for row in records])
        return len(records)

    def upsert_quotes(self, rows):
        payload = []
        for quote in rows:
            row = asdict(quote)
            for name in ("bid_book", "ask_book", "raw", "source_receipts"):
                row[name + "_json"] = json.dumps(row.pop(name), ensure_ascii=False)
            row["collected_at"] = self._now()
            payload.append(row)
        return self._write("quotes", payload)

    def upsert_bars(self, rows):
        payload = []
        for bar in rows:
            row = asdict(bar)
            row["interval"] = interval_name(row["interval"])
            row["price_basis"] = price_basis_name(row["price_basis"])
            row["raw_json"] = json.dumps(row.pop("raw"), ensure_ascii=False,allow_nan=False)
            row['source_receipts_json'] = json.dumps(row.pop('source_receipts'), ensure_ascii=False,allow_nan=False)
            row["collected_at"] = self._now()
            payload.append(row)
        return self._write("bars", payload)

    def upsert_observations(self, rows):
        payload = []
        for observation in rows:
            row = asdict(observation)
            row["revision"] = row["revision"] or "unknown"
            for name in ("value", "raw", "source_receipts"):
                row[name + "_json"] = json.dumps(row.pop(name), ensure_ascii=False,allow_nan=False)
            row["collected_at"] = self._now()
            payload.append(row)
        return self._write("observations", payload)

    def upsert_indicators(self, rows):
        payload = []
        for indicator in rows:
            row = asdict(indicator)
            row["interval"] = interval_name(row["interval"])
            row["price_basis"] = price_basis_name(row["price_basis"])
            row["parameters_json"] = json.dumps(row.pop("parameters"), ensure_ascii=False)
            row["calculated_at"] = self._now()
            payload.append(row)
        return self._write("indicators", payload)

    def record_run(self, provider, dataset, started_at, status, row_count, *, error="", details=None):
        details=dict(details or {})
        if self.response_vault:
            details['response_receipts']=list(self.response_vault.events[self._response_offset:])
        with self.connect() as db:
            db.execute("INSERT INTO provider_runs(provider,dataset,started_at,finished_at,status,row_count,error,details_json) VALUES(?,?,?,?,?,?,?,?)",
                       (provider,dataset,started_at,self._now(),status,row_count,redact_error(error),json.dumps(details, ensure_ascii=False)))
        if self.response_vault:self._response_offset=len(self.response_vault.events)

    def source_trace(self, kind, identity, *, dataset=None, interval='1d', provider=None, limit=10, as_of=None):
        """Bounded row-to-byte verification, with legacy/TCP rows explicitly unlinked."""
        if kind not in {'quote', 'bar', 'observation'} or not 1 <= limit <= 100:
            raise ValueError('Use quote/bar/observation and a trace limit from 1 to 100')
        table = {'quote': 'quotes', 'bar': 'bars', 'observation': 'observations'}[kind]
        identity_column = 'identity' if kind == 'observation' else 'symbol'
        time_column = 'timestamp' if kind == 'bar' else 'as_of'
        where, params = f'{identity_column}=? AND at_or_before({time_column},?)', [identity, as_of or self._now()]
        if provider:
            where += ' AND provider=?'; params.append(provider)
        if kind == 'bar':
            where += ' AND interval=?'; params.append(interval_name(interval))
        elif kind == 'observation':
            if not dataset: raise ValueError('An observation trace requires its dataset')
            where += ' AND dataset=?'; params.append(dataset)
        with self.connect() as db:
            records = db.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY {time_column} DESC LIMIT ?',
                                 [*params, limit]).fetchall()
        results, verified = [], {}
        for source in records:
            row = dict(source); checks = []
            for reference in json.loads(row.get('source_receipts_json', '[]')):
                key = json.dumps(reference, sort_keys=True)
                if key not in verified:
                    try: verified[key] = ResponseVault.verify_reference(reference)
                    except (OSError, ValueError, KeyError, TypeError, EOFError, zlib.error) as exc:
                        verified[key] = {'status': 'invalid', 'error': redact_error(str(exc))}
                checks.append(verified[key])
            status = ('verified_original_responses' if all(item['status'] == 'verified' for item in checks)
                      else 'invalid_original_response') if checks else 'normalized_receipt_only'
            results.append({'provider': row['provider'], 'identity': row[identity_column],
                            'observation_time': row[time_column], 'status': status,
                            'row_sha256': hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest(),
                            'responses': checks})
        status = 'invalid' if any(row['status'] == 'invalid_original_response' for row in results) else (
            'verified' if results and all(row['status'] == 'verified_original_responses' for row in results)
            else 'partial' if results else 'missing')
        return {'status': status, 'kind': kind, 'identity': identity, 'dataset': dataset,
                'limit': limit, 'rows': results, 'historical_links_inferred': False,
                'scope': 'explicit parser response dependencies; byte integrity does not by itself recheck financial meaning'}

    def get_bars(self, symbol, interval, *, provider=None, price_basis=None, limit=500, as_of=None):
        where, params = "symbol=? AND interval=?", [symbol, interval_name(interval)]
        if provider:
            where += " AND provider=?"
            params.append(provider)
        if price_basis:
            where += " AND price_basis=?"
            params.append(price_basis_name(price_basis))
        if as_of:
            where += " AND at_or_before(timestamp,?)"
            params.append(as_of)
        with self.connect() as db:
            records = db.execute(f"SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY provider,price_basis ORDER BY timestamp DESC) AS rn FROM bars WHERE {where}) WHERE rn<=? ORDER BY timestamp", [*params,limit]).fetchall()
        result = []
        for record in records:
            row = dict(record)
            row.pop("rn")
            row.pop("collected_at")
            row["raw"] = json.loads(row.pop("raw_json"))
            row['source_receipts'] = json.loads(row.pop('source_receipts_json', '[]'))
            result.append(Bar(**row))
        return result

    def get_observations(self, dataset, identity=None, *, limit=500, as_of=None, publication_as_of=None, include_raw=False):
        where, params = "dataset=?", [dataset]
        if identity:
            where += " AND identity=?"
            params.append(identity)
        if as_of:
            where += " AND at_or_before(as_of,?) AND (COALESCE(publication,'') IN ('','unknown') OR at_or_before(publication,?))"
            params.extend([as_of, publication_as_of or as_of])
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY provider,identity,revision ORDER BY as_of DESC) AS rn FROM observations WHERE {where}) WHERE rn<=? ORDER BY as_of", [*params,limit]).fetchall()
        return [self._decode(dict(row),include_raw=include_raw) for row in rows]

    def get_quotes(self, identities=None, *, as_of=None):
        cutoff=as_of or self._now()
        where="at_or_before(as_of,?)";params=[cutoff]
        if identities:
            where+=" AND symbol IN ("+','.join('?' for _ in identities)+")"
            params.extend(identities)
        with self.connect() as db:
            records=db.execute(f"SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY provider,symbol ORDER BY as_of DESC) AS rn FROM quotes WHERE {where}) WHERE rn=1",params).fetchall()
        rows=[self._decode(dict(row)) for row in records]
        for row in rows: row['freshness']=quote_freshness(row,cutoff)
        return rows

    def get_indicators(self, identities, *, intervals=None, as_of=None):
        if not identities or len(identities)>100:
            raise ValueError('Targeted indicators require from 1 to 100 identities')
        where='symbol IN ('+','.join('?' for _ in identities)+') AND at_or_before(timestamp,?)'
        params=[*identities,as_of or self._now()]
        if intervals:
            where+=' AND interval IN ('+','.join('?' for _ in intervals)+')'
            params.extend(interval_name(value) for value in intervals)
        with self.connect() as db:
            rows=db.execute(f'SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY symbol,interval,name,input_provider,price_basis ORDER BY timestamp DESC) AS rn FROM indicators WHERE {where}) WHERE rn=1',params).fetchall()
        return [self._decode(dict(row)) for row in rows]

    @staticmethod
    def _decode(row,*,include_raw=False):
        for name in ("value", "parameters", "bid_book", "ask_book", "source_receipts"):
            if name + "_json" in row:
                row[name] = json.loads(row.pop(name + "_json"))
        raw=row.pop("raw_json", None)
        if include_raw:row['raw']=json.loads(raw or '{}')
        row.pop("rn", None)
        return row

    def _latest(self, db, table, groups, timestamp, cutoff):
        publication_filter = " AND (COALESCE(publication,'') IN ('','unknown') OR at_or_before(publication,?))" if table == "observations" else ""
        if table == "observations":
            publication_filter += " AND dataset NOT IN ('instrument_listing','industry_classification')"
        params = [cutoff, cutoff] if publication_filter else [cutoff]
        if table != "observations": params = [cutoff]
        rows = db.execute(f"SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY {groups} ORDER BY {timestamp} DESC) AS rn FROM {table} WHERE at_or_before({timestamp},?){publication_filter}) WHERE rn=1", params).fetchall()
        return [self._decode(dict(row)) for row in rows if parse_time(row[timestamp]) <= parse_time(cutoff)]

    def universe(self, *, limit=200, as_of=None):
        cutoff = as_of or self._now()
        with self.connect() as db:
            listings = db.execute("SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY provider,identity ORDER BY as_of DESC) AS rn FROM observations WHERE dataset='instrument_listing' AND at_or_before(as_of,?)) WHERE rn=1", (cutoff,)).fetchall()
            prices = {row[0] for row in db.execute("SELECT DISTINCT symbol FROM bars WHERE at_or_before(timestamp,?) UNION SELECT DISTINCT symbol FROM quotes WHERE at_or_before(as_of,?) UNION SELECT DISTINCT identity FROM observations WHERE dataset='fund_unit_nav' AND at_or_before(as_of,?)", (cutoff,cutoff,cutoff))}
        identities = {row["identity"] for row in listings} | prices
        providers, types = {}, {}
        for row in listings:
            providers[row["provider"]] = providers.get(row["provider"],0)+1
            value = json.loads(row["value_json"])
            kind = value.get("provider_type") or value.get("scope") or "unknown"
            types[kind] = types.get(kind,0)+1
        ordered = sorted(identities)
        return {"symbols":ordered if limit is None else ordered[:limit],"total_count":len(identities),
                "listed_count":len(listings),"price_covered_count":len(prices),"price_symbols":sorted(prices),
                "provider_counts":providers,"provider_types":types,"truncated":limit is not None and len(ordered)>limit}

    def health(self, *, recent_runs=100, as_of=None):
        cutoff = as_of or self._now()
        with self.connect() as db:
            runs = [dict(row) for row in db.execute("SELECT * FROM provider_runs ORDER BY id DESC LIMIT ?", (recent_runs,))]
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("quotes", "bars", "observations", "indicators")}
            quotes = self._latest(db, "quotes", "provider,symbol", "as_of", cutoff)
        latest = {}
        for row in runs:
            latest.setdefault(f"{row['provider']}:{row['dataset']}", row)
        current_problems = [row for row in latest.values() if row["status"] != "ok"]
        freshness = [{"symbol": q["symbol"], "provider": q["provider"], "as_of": q["as_of"], **quote_freshness(q, cutoff)} for q in quotes]
        stale = [row for row in freshness if row["status"] == "stale"]
        unknown = [row for row in freshness if row["status"] in {"unknown", "unavailable", "incomplete"}]
        failed = [row for row in current_problems if row["status"] == "failed"]
        partial = [row for row in current_problems if row["status"] == "partial"]
        missing = [row for row in current_problems if row["status"] == "not_configured"]
        status = "failed" if failed else "partial" if partial else "stale" if stale else "incomplete" if missing or unknown else "ok" if latest else "uninitialized"
        return {"database": str(self.path), "as_of": cutoff, "status": status, "row_counts": counts, "latest_by_dataset": latest,
                "latest_problem_count": len(current_problems)+len(stale)+len(unknown), "stale_quote_count": len(stale), "stale_quotes": stale,
                "unknown_freshness": unknown, "quote_freshness": freshness, "partial": partial, "unconfigured": missing,
                "recent_failures": [row for row in runs if row["status"] == "failed"][:20],
                "freshness_policy": "CN quotes: official exchange calendar and trading clock; other datasets require task-specific checks"}

    def snapshot(self, *, observation_limit=100, as_of=None,quote_limit=50,indicator_limit=300):
        cutoff = as_of or self._now()
        with self.connect() as db:
            quotes = self._latest(db,"quotes","provider,symbol","as_of",cutoff)
            indicators = self._latest(db,"indicators","symbol,interval,name,input_provider,price_basis","timestamp",cutoff)
            bars = self._latest(db,"bars","provider,symbol,interval,price_basis","timestamp",cutoff)
            observations = self._latest(db,"observations","provider,dataset,identity,revision","as_of",cutoff)
        for quote in quotes:
            quote["freshness"] = quote_freshness(quote, cutoff)
        quote_count=len(quotes);indicator_count=len(indicators)
        quotes.sort(key=lambda row:(row.get('asset_class')!='index',-(row.get('amount') or 0),row['symbol']))
        return {"generated_at": self._now(), "as_of": cutoff, "database": str(self.path), "latest_quotes": quotes[:quote_limit],
                "latest_bars": bars, "latest_indicators": indicators[:indicator_limit], "recent_observations": observations,
                "quote_count":quote_count,"indicator_count":indicator_count,
                "quote_sample_truncated":quote_count>quote_limit,"indicator_sample_truncated":indicator_count>indicator_limit,
                "observation_policy": "latest per provider/dataset/identity/revision; instrument catalogues excluded; use discover for catalogue coverage and evidence for histories",
                "history_limit": observation_limit, "health": self.health(as_of=cutoff),
                "historical_cutoff_note": "An observation-date cutoff alone does not establish point-in-time publication availability"}
