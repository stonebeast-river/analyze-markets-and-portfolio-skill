"""Bind stored calculations to exact frozen inputs and replay without the live DB."""
import hashlib
import math
from pathlib import Path

from .indicators import indicator_rows, quote_indicator_rows, series_indicator_rows
from .lineage import canonical, computational_input, freeze_inputs, prefix_lineages, read_frozen_inputs
from .models import Bar, Observation, Quote


def calculator_sources():
    root=Path(__file__).parent
    return [{'name':name,'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),
             'source':(root/name).read_text(encoding='utf-8-sig')}
            for name in ('indicators.py','lineage.py','models.py','conventions.py','market_scan.py','reproduction.py')]


def calculate_from_frozen(kind,inputs):
    if kind=='bars':return indicator_rows([Bar(**row) for row in inputs])
    if kind=='quotes':return quote_indicator_rows([Quote(**row) for row in inputs])
    if kind=='observations':
        return series_indicator_rows([Observation(**row) for row in inputs],limit=len(inputs))
    raise ValueError('Unsupported indicator input kind')


def measurement_matches(stored,calculated):
    left=stored['value'];right=calculated.value
    values_match=(left is None and right is None) or (type(left) in (int,float) and type(right) in (int,float)
                 and math.isclose(left,right,rel_tol=1e-10,abs_tol=1e-10))
    quality_matches=stored['quality']==calculated.quality
    # A source-use restriction does not alter the calculation; eligibility still rejects it.
    if stored['quality']=='unverified_for_volume_confirmation' and calculated.quality=='locally_derived':
        quality_matches=('volume' in stored['name'] or stored['name'] in {'vwap','obv'})
    return values_match and quality_matches and all(stored[field]==getattr(calculated,field) for field in
           ('name','symbol','interval','timestamp','input_provider','price_basis','unit','currency','parameters'))


def freeze_indicator(store,row,directory,cache,*,as_of=None):
    lineage=row['parameters'].get('input_lineage')
    if not isinstance(lineage,dict) or lineage.get('format')!='ordered_inputs_v1':
        return {'status':'missing_generation_lineage','recomputed_matches':False}
    key=canonical(lineage)
    if key not in cache:
        kind=lineage['kind'];identity=lineage['series_identity'];count=lineage['row_count']
        if type(count)!=int or count<=0 or count>100000:
            return {'status':'invalid_input_window','recomputed_matches':False}
        if kind=='bars':
            inputs=store.get_bars(identity['symbol'],identity['interval'],provider=identity['provider'],
                                  price_basis=identity['price_basis'],limit=count,as_of=lineage['last_timestamp'])
        elif kind=='quotes':
            inputs=[quote for quote in store.get_quotes([identity['symbol']],as_of=lineage['last_timestamp'])
                    if quote['provider']==identity['provider'] and quote['as_of']==lineage['last_timestamp']]
        elif kind=='observations':
            inputs=[obs for obs in store.get_observations(identity['dataset'],identity['identity'],limit=count,
                    as_of=lineage['last_timestamp'],publication_as_of=as_of)
                    if all(obs[field]==identity[field] for field in ('provider','revision','price_basis'))]
        else:
            return {'status':'unsupported_input_kind','recomputed_matches':False}
        normalized=[computational_input(item,kind) for item in inputs]
        actual=prefix_lineages(normalized,kind)
        if not actual or actual[-1]!=lineage:
            cache[key]={'status':'source_inputs_changed_or_missing','recomputed_matches':False}
        else:
            reference=freeze_inputs(directory,kind,normalized)
            calculated=calculate_from_frozen(kind,normalized)
            cache[key]={'status':'inputs_frozen','input_reference':reference,
                        'calculated':{(item.name,item.timestamp):item for item in calculated}}
    cached=cache[key]
    if cached['status']!='inputs_frozen':return cached
    calculated=cached['calculated'].get((row['name'],row['timestamp']))
    matched=calculated is not None and measurement_matches(row,calculated)
    return {'status':'reproduced' if matched else 'calculation_mismatch',
            'recomputed_matches':matched,'input_reference':cached['input_reference'],
            'source_usage_downgrade_preserved':row['quality']=='unverified_for_volume_confirmation'}


def replay_indicator(directory,row,reference):
    inputs=read_frozen_inputs(directory,reference)
    calculated=calculate_from_frozen(reference['kind'],inputs)
    selected=next((item for item in calculated if item.name==row['name'] and item.timestamp==row['timestamp']),None)
    return selected is not None and measurement_matches(row,selected)
