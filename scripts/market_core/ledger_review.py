"""Tri-state reviews against sealed evidence; never reinterpret a prior condition."""
import json
import math
import operator
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .conventions import parse_time
from .research import ledger_append
from .task_health import cash_calendar
from .workflow import read_prepared,verify_research


OPS={'gt':operator.gt,'ge':operator.ge,'lt':operator.lt,'le':operator.le,'eq':operator.eq}


def evaluate_condition(rule,register,*,baseline_cutoff):
    if not isinstance(rule,dict):return {'result':None,'reason':'original_condition_requires_manual_review'}
    if 'all_of' in rule or 'any_of' in rule:
        if ('all_of' in rule and 'any_of' in rule):return {'result':None,'reason':'ambiguous_logical_condition'}
        key='all_of' if 'all_of' in rule else 'any_of'
        if not isinstance(rule[key],list) or not rule[key]:return {'result':None,'reason':'empty_or_invalid_logical_condition'}
        children=[evaluate_condition(child,register,baseline_cutoff=baseline_cutoff) for child in rule[key]]
        values=[child['result'] for child in children]
        result=(False if False in values else None if None in values else True) if key=='all_of' else (True if True in values else None if None in values else False)
        return {'result':result,'children':children,'operator':key}
    if rule.get('kind')!='indicator':return {'result':None,'reason':'primary_event_or_manual_condition_not_automatically_verified'}
    required=('identity','metric','provider','interval','price_basis','unit','currency','operator','threshold')
    if any(key not in rule for key in required):return {'result':None,'reason':'incomplete_metric_condition_contract'}
    if rule['operator'] not in OPS or type(rule['threshold']) not in (int,float) or not math.isfinite(rule['threshold']):
        return {'result':None,'reason':'invalid_threshold_contract'}
    matches=[]
    for key,fact in register.items():
        row=fact['record']
        if (fact['identity']==rule['identity'] and row.get('name')==rule['metric'] and
            all(row.get(field)==rule[field] for field in ('interval','price_basis','unit','currency')) and
            row.get('input_provider')==rule['provider']):matches.append((key,fact))
    if not matches:return {'result':None,'reason':'matching_metric_evidence_missing'}
    key,fact=max(matches,key=lambda pair:parse_time(pair[1]['as_of']))
    if not fact['eligible']:return {'result':None,'reason':'metric_evidence_ineligible','evidence_id':key}
    row=fact['record'];stamp=row['timestamp']
    if len(stamp)==10:
        calendar=cash_calendar(rule.get('market_calendar'))
        if calendar is None or not calendar['coverage_start']<=stamp<=calendar['coverage_end']:
            return {'result':None,'reason':'daily_metric_calendar_missing','evidence_id':key}
        close=calendar.get('early_closes',{}).get(stamp,calendar['close'])
        observed=datetime.fromisoformat(stamp+'T'+close).replace(tzinfo=ZoneInfo(calendar['timezone']))
    else:observed=parse_time(stamp)
    required_after=parse_time(rule.get('not_before') or baseline_cutoff)
    if observed<=required_after:return {'result':None,'reason':'no_post_baseline_observation','evidence_id':key}
    value=row['value']
    if type(value) not in (int,float) or not math.isfinite(value):return {'result':None,'reason':'metric_value_missing'}
    return {'result':OPS[rule['operator']](value,rule['threshold']),'evidence_id':key,'value':value,
            'operator':rule['operator'],'threshold':rule['threshold'],'observation_complete_at':observed.isoformat()}


def review_ledger(ledger_path,directory,*,append=False):
    target,inputs,_=read_prepared(directory);verified=verify_research(directory)
    if verified['status'] not in {'ok','partial'}:raise ValueError('Cannot review against failed/unmatched frozen calculations')
    path=Path(ledger_path).resolve()
    entries=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    originals={};latest={}
    for row in entries:originals.setdefault(row['thesis_id'],row);latest[row['thesis_id']]=row
    results=[]
    for thesis_id,baseline in originals.items():
        confirmation=evaluate_condition(baseline['confirmation'],inputs['evidence_register'],baseline_cutoff=baseline['cutoff'])
        invalidation=evaluate_condition(baseline['invalidation'],inputs['evidence_register'],baseline_cutoff=baseline['cutoff'])
        prior_status=latest[thesis_id]['status']
        if prior_status in {'invalidated','expired'}:status=prior_status
        elif confirmation['result'] is True and invalidation['result'] is True:status='not yet testable'
        elif invalidation['result'] is True:status='invalidated'
        elif confirmation['result'] is True:status='strengthened'
        elif confirmation['result'] is False and invalidation['result'] is False:status='unchanged'
        else:status='not yet testable'
        horizon=baseline['horizon']
        if (prior_status not in {'invalidated','expired'} and isinstance(horizon,dict) and horizon.get('review_deadline')
                and parse_time(inputs['cutoff'])>parse_time(horizon['review_deadline'])):status='expired'
        result={'thesis_id':thesis_id,'status':status,'confirmation':confirmation,'invalidation':invalidation,
                'review_cutoff':inputs['cutoff'],'original_cutoff':baseline['cutoff'],'original_preserved':True}
        if append:
            entry=dict(baseline);entry.update(created_at=datetime.now(timezone.utc).isoformat(),status=status,
                review_as_of=inputs['cutoff'],condition_review=result,review_input_sha256=json.loads((target/'input-seal.json').read_text(encoding='utf-8'))['sha256'])
            if status in {'invalidated','expired','not yet testable'}:entry['action_relevance']='none'
            with tempfile.TemporaryDirectory(dir=path.parent) as scratch:
                entry_path=Path(scratch)/'entry.json';entry_path.write_text(json.dumps(entry,ensure_ascii=False),encoding='utf-8')
                result['append_result']=ledger_append(path,entry_path)
        results.append(result)
    return {'reviews':results,'append':append,'basis':'original conditions and horizons; sealed new observations; no outcome rewriting'}
