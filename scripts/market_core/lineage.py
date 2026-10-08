"""Deterministic computational inputs, independent of SQLite receive timestamps."""
import gzip
import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .conventions import interval_name, price_basis_name


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode('utf-8')


def computational_input(value,kind):
    row=asdict(value) if is_dataclass(value) else value
    if kind=='bars':
        keys=('provider','symbol','interval','timestamp','open','high','low','close','volume','amount',
              'volume_unit','amount_unit','currency','session','price_basis','source_url','quality')
        numbers=('open','high','low','close','volume','amount')
    elif kind=='quotes':
        keys=('provider','symbol','as_of','name','asset_class','currency','session','last','previous_close',
              'open','high','low','volume','amount','volume_unit','amount_unit','book_volume_unit',
              'turnover_pct','volume_ratio_vendor','pe_ttm','pb','market_cap','inner_volume','outer_volume',
              'bid_book','ask_book','source_url','quality','latency')
        numbers=('last','previous_close','open','high','low','volume','amount','turnover_pct',
                 'volume_ratio_vendor','pe_ttm','pb','market_cap','inner_volume','outer_volume')
    elif kind=='observations':
        keys=('provider','dataset','identity','as_of','value','unit','currency','publication','revision',
              'price_basis','quality','source_url','latency')
        numbers=()
    else:
        raise ValueError('Unknown computational input kind')
    result={key:row.get(key) for key in keys}
    for key in numbers:
        if result[key] is not None:result[key]=float(result[key])
    if 'interval' in result:result['interval']=interval_name(result['interval'])
    if 'price_basis' in result:result['price_basis']=price_basis_name(result['price_basis'])
    if kind=='observations' and type(result['value']) in (int,float):result['value']=float(result['value'])
    if kind=='quotes':
        for key in ('bid_book','ask_book'):
            result[key]=[{name:float(number) for name,number in level.items()} for level in result[key] or []]
    return result


def prefix_lineages(rows,kind):
    """Hash ordered inputs using length framing, preserving the exact recursive seed."""
    digest=hashlib.sha256();result=[]
    normalized=[computational_input(row,kind) for row in rows]
    time_key='timestamp' if kind=='bars' else 'as_of'
    for index,row in enumerate(normalized):
        payload=canonical(row)
        digest.update(len(payload).to_bytes(8,'big'));digest.update(payload)
        selector_keys={'bars':('provider','symbol','interval','price_basis'),
                       'quotes':('provider','symbol'),
                       'observations':('provider','dataset','identity','revision','price_basis')}[kind]
        result.append({'format':'ordered_inputs_v1','kind':kind,'sha256':digest.hexdigest(),
                       'row_count':index+1,'first_timestamp':normalized[0][time_key],
                       'last_timestamp':row[time_key],
                       'series_identity':{key:normalized[0][key] for key in selector_keys}})
    return result


def freeze_inputs(directory,kind,rows):
    payload={'schema_version':1,'kind':kind,'inputs':rows}
    data=canonical(payload);digest=hashlib.sha256(data).hexdigest()
    relative=Path('inputs')/(digest+'.json.gz');path=Path(directory)/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with path.open('xb') as handle:handle.write(gzip.compress(data,mtime=0))
    return {'path':relative.as_posix(),'sha256':digest,'row_count':len(rows),'kind':kind}


def read_frozen_inputs(directory,reference):
    path=(Path(directory)/reference['path']).resolve()
    root=Path(directory).resolve()
    if root not in path.parents:raise ValueError('Frozen input path leaves research run')
    data=gzip.decompress(path.read_bytes())
    if hashlib.sha256(data).hexdigest()!=reference['sha256']:raise ValueError('Frozen calculation inputs were changed')
    value=json.loads(data)
    if value['kind']!=reference['kind'] or len(value['inputs'])!=reference['row_count']:
        raise ValueError('Frozen calculation input contract differs')
    return value['inputs']
