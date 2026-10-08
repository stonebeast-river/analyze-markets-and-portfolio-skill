"""Bounded raw-history refresh with per-provider checkpoints and periodic full audits."""
import hashlib
import zlib
import os
import uuid
from pathlib import Path
from datetime import datetime,timedelta,timezone

from .conventions import price_basis_name
from .indicators import indicator_rows_grouped
from .lineage import canonical,computational_input,freeze_inputs,read_frozen_inputs
from .models import Observation
from .responses import ResponseVault
from .http import HttpClient


DEFAULT_HISTORY_REFRESH={'incremental_enabled':True,'overlap_calendar_days':45,
                         'full_refresh_interval_hours':168,'maximum_baseline_rows':5000}


def rows_digest(rows):
    return hashlib.sha256(canonical([computational_input(row,'bars') for row in rows])).hexdigest()


def normalized_baseline(rows):
    return [{'computational_input':computational_input(row,'bars'),'raw':row.raw,
             'source_receipts':row.source_receipts} for row in rows]


def freeze_baseline(directory,rows):
    values=normalized_baseline(rows);kind='history_collection_baseline'
    digest=hashlib.sha256(canonical({'schema_version':1,'kind':kind,'inputs':values})).hexdigest()
    root=Path(directory).resolve();relative='inputs/'+digest+'.json.gz'
    path=(root/relative).resolve()
    if root not in path.parents:raise ValueError('Baseline archive path leaves its directory')
    reference={'kind':kind,'path':relative,'sha256':digest,'row_count':len(values)}
    if path.exists():
        try:read_frozen_inputs(root,reference)
        except (KeyError,TypeError,ValueError,OSError,EOFError,zlib.error):
            quarantine=root/'quarantine'/(digest+'-'+uuid.uuid4().hex+'.json.gz')
            quarantine.parent.mkdir(parents=True,exist_ok=True)
            os.replace(path,quarantine)
    return freeze_inputs(root,kind,values)


def collect_cn_history(pipeline,provider,symbol,profile,start_date,end_date,adjustment,*,now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Collection clock requires a timezone')
    policy={**DEFAULT_HISTORY_REFRESH,**profile.get('history_refresh',{})}
    overlap=policy['overlap_calendar_days'];full_hours=policy['full_refresh_interval_hours'];cap=policy['maximum_baseline_rows']
    if type(overlap)!=int or not 1<=overlap<=365 or type(cap)!=int or not 100<=cap<=10000:
        raise ValueError('History overlap or baseline bound is invalid')
    if type(full_hours) not in (int,float) or not 1<=full_hours<=8760:
        raise ValueError('Periodic full-refresh interval is invalid')
    basis=price_basis_name(adjustment)
    key=provider.name+'|'+symbol+'|1d|'+basis
    states=pipeline.store.get_observations('history_collection_checkpoint',key,limit=1)
    checkpoint=states[-1]['value'] if states else None
    stored=pipeline.store.get_bars(symbol,'1d',provider=provider.name,price_basis=basis,limit=cap+1,as_of=end_date)
    stored=[row for row in stored if row.timestamp>=start_date]
    if len(stored)>cap:raise ValueError('Configured history exceeds the bounded collection baseline')
    mode='full';reason='no_verified_collection_checkpoint';request_start=start_date
    baseline_directory=pipeline.database.parent/'history-baselines'
    if not policy['incremental_enabled']:reason='incremental_disabled'
    elif basis!='unadjusted':reason='adjusted_history_requires_full_source_refresh'
    elif checkpoint:
        try:
            age=(now-datetime.fromisoformat(checkpoint['last_full_refresh_at'])).total_seconds()/3600
            prior=pipeline.store.get_bars(symbol,'1d',provider=provider.name,price_basis=basis,limit=cap+1,
                                          as_of=checkpoint['baseline_end'])
            prior=[row for row in prior if row.timestamp>=checkpoint['baseline_start']]
            valid=(stored and checkpoint['provider']==provider.name and checkpoint['price_basis']==basis
                   and checkpoint['full_window_start']<=start_date and checkpoint['baseline_rows']==len(prior)
                   and checkpoint['baseline_sha256']==rows_digest(prior)
                   and stored[-1].timestamp<=checkpoint['baseline_end'])
            if age<0 or age>=full_hours:reason='periodic_full_refresh_due'
            elif not valid:reason='baseline_changed_missing_or_scope_expanded'
            else:
                try:
                    archived=read_frozen_inputs(baseline_directory,checkpoint['normalized_baseline_reference'])
                    if canonical(archived)!=canonical(normalized_baseline(prior)):
                        raise ValueError('Normalized baseline archive differs from current rows')
                    require_http=isinstance(getattr(provider,'client',None),HttpClient) and pipeline.response_vault is not None
                    checked=set()
                    for row in prior:
                        if require_http and not row.source_receipts:
                            raise ValueError('HTTP source baseline has no original response dependency')
                        for reference in row.source_receipts:
                            receipt_key=canonical(reference)
                            if receipt_key not in checked:
                                ResponseVault.verify_reference(reference);checked.add(receipt_key)
                    mode='incremental';reason='verified_raw_baseline_with_bounded_overlap'
                    recent=datetime.fromisoformat(stored[-1].timestamp[:10]).date()-timedelta(days=overlap)
                    request_start=max(start_date,recent.isoformat())
                except (KeyError,TypeError,ValueError,OSError,EOFError,zlib.error):
                    reason='baseline_source_archive_missing_or_invalid'
        except (KeyError,TypeError,ValueError):reason='unusable_collection_checkpoint'
    def fetch_window(begin):
        values=list(provider.fetch_bars(symbol,start_date=begin,end_date=end_date,frequency='d',adjustment=adjustment))
        if not values:raise ValueError('Source completed without history rows')
        if any(row.provider!=provider.name or row.symbol!=symbol or row.interval!='1d' or
               row.price_basis!=basis or not begin<=row.timestamp<=end_date for row in values):
            raise ValueError('History response does not match its provider/identity/basis/window contract')
        if len({row.timestamp for row in values})!=len(values):
            raise ValueError('History response contains duplicate dates')
        return values
    rows=fetch_window(request_start)
    # A full requested baseline is authoritative for this local bounded version;
    # incremental refresh replaces only actually returned dates, retaining receipts.
    previous={row.timestamp:row for row in stored}
    recovery=None
    if mode=='incremental':
        missing=sorted({stamp for stamp in previous if request_start<=stamp<=end_date}-{row.timestamp for row in rows})
        if missing:
            recovery={'missing_previously_stored_overlap_dates':missing,'incomplete_request_start':request_start,
                      'incomplete_response_rows':len(rows),'additional_full_attempts':1}
            client=getattr(provider,'client',None);receipt=getattr(client,'last_response_receipt',None)
            if isinstance(client,HttpClient) and client.archive and receipt and receipt.get('status') in {'http_ok','cache_hit'}:
                client.archive.reject(receipt,'Incremental history omitted known overlap dates')
            mode='full';reason='incremental_response_omitted_baseline_dates';request_start=start_date
            rows=fetch_window(request_start)
    if mode=='full' and not set(previous).issubset({row.timestamp for row in rows}):
        raise ValueError('Full refresh omitted previously stored dates inside the requested scope')
    consolidated={} if mode=='full' else dict(previous)
    consolidated.update({row.timestamp:row for row in rows})
    sequence=[consolidated[stamp] for stamp in sorted(consolidated)]
    if len(sequence)>cap:raise ValueError('New history exceeds the bounded baseline')
    indicators=indicator_rows_grouped(sequence)
    changed=sum(stamp in previous and computational_input(previous[stamp],'bars')!=computational_input(row,'bars')
                for stamp,row in ((row.timestamp,row) for row in rows))
    financial_fields=('open','high','low','close','volume','amount','volume_unit','amount_unit','currency','session','price_basis')
    financial_changed=sum(row.timestamp in previous and any(getattr(previous[row.timestamp],field)!=getattr(row,field)
                          for field in financial_fields) for row in rows)
    count=pipeline.store.upsert_bars(rows)
    derived=pipeline.store.upsert_indicators(indicators)
    contract={'mode':mode,'reason':reason,'requested_start':request_start,'requested_end':end_date,
              'baseline_start':start_date,'provider':provider.name,'price_basis':basis,
              'source_rows':count,'new_source_dates':sum(row.timestamp not in previous for row in rows),
              'overlap_rows_changed':changed,'indicator_input_rows':len(sequence),'indicator_rows':derived,
              'financial_rows_changed':financial_changed,'provenance_only_rows_changed':changed-financial_changed,
              'atomic_publisher_revision_verified':False,'row_response_provenance_retained':True,
              'historical_revision_check_scope':'full_requested_window' if mode=='full' else 'returned_overlap_only'}
    if recovery:contract['bounded_full_recovery']=recovery
    state={'provider':provider.name,'symbol':symbol,'price_basis':basis,
           'full_window_start':start_date if mode=='full' else checkpoint['full_window_start'],
           'baseline_start':sequence[0].timestamp,'baseline_end':sequence[-1].timestamp,
           'last_full_refresh_at':now.isoformat() if mode=='full' else checkpoint['last_full_refresh_at'],
           'last_success_at':now.isoformat(),'baseline_rows':len(sequence),'baseline_sha256':rows_digest(sequence),
           'normalized_baseline_reference':freeze_baseline(baseline_directory,sequence),
           'last_refresh_contract':contract}
    pipeline.store.upsert_observations([Observation('local_collection_control','history_collection_checkpoint',key,
        now.isoformat(),state,unit='collection_control_metadata',quality='local_collection_checkpoint',
        source_url='local_collection_control_not_financial_evidence')])
    return count,{'kind':'cn_history_refresh','collection_refresh_contract':contract}
