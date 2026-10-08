"""Field-specific public-minute reconciliation; never normalize conflicting volume."""
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
import math
from .models import Observation


def audit_intraday_quality(rows,previous=()):
    prior={(b.provider,b.symbol,b.interval,b.timestamp,b.price_basis):b for b in previous}
    groups=defaultdict(list)
    for b in rows:
        if b.interval=='1m':groups[(b.provider,b.symbol)].append(b)
    audits=[]
    for (provider,symbol),bars in groups.items():
        bars.sort(key=lambda b:b.timestamp)
        meta=bars[-1].raw.get('metadata') or {};zone_name=meta.get('exchangeTimezoneName')
        revisions=[]
        for b in bars:
            old=prior.get((b.provider,b.symbol,b.interval,b.timestamp,b.price_basis))
            changed=[field for field in ('open','high','low','close','volume') if old is not None and getattr(old,field)!=getattr(b,field)]
            if changed:revisions.append({'timestamp':b.timestamp,'changed_fields':changed})
        volume_revisions=sum('volume' in x['changed_fields'] for x in revisions)
        dependencies={}
        for bar in bars:
            related=[bar,prior.get((bar.provider,bar.symbol,bar.interval,bar.timestamp,bar.price_basis))]
            for item in related:
                if item is not None:
                    for ref in item.source_receipts:dependencies[ref['receipt_sha256']]=ref
        state='unverified_metadata_or_window';details={};contradiction=False
        quote_volume=meta.get('regularMarketVolume');quote_time=meta.get('regularMarketTime')
        if zone_name and type(quote_time) in {int,float} and type(quote_volume) in {int,float} and math.isfinite(quote_volume) and quote_volume>=0:
            zone=ZoneInfo(zone_name);quote=datetime.fromtimestamp(quote_time,timezone.utc)
            day=quote.astimezone(zone).date()
            selected=[b for b in bars if datetime.fromisoformat(b.timestamp).astimezone(zone).date()==day]
            regular=(meta.get('currentTradingPeriod') or {}).get('regular') or {}
            if selected and all(b.volume is not None and math.isfinite(b.volume) and b.volume>=0 and b.volume_unit=='share' for b in selected):
                last_end=datetime.fromisoformat(selected[-1].timestamp)+timedelta(minutes=1)
                first=datetime.fromisoformat(selected[0].timestamp)
                same_regular_day=regular.get('start') is not None and datetime.fromtimestamp(regular['start'],timezone.utc).astimezone(zone).date()==day
                if same_regular_day and first.timestamp()>=regular['start'] and quote>=last_end and quote.timestamp()<=regular.get('end',0):
                    total=sum(b.volume for b in selected)
                    contradiction=total>quote_volume+1
                    state='completed_bar_sum_exceeds_later_vendor_cumulative' if contradiction else 'compatible_wider_cumulative_window_not_exact_reconciliation'
                    details={'quote_timestamp_utc':quote.isoformat(),'last_completed_bar_end_utc':last_end.isoformat(),
                        'completed_bar_volume_sum_shares':total,'vendor_cumulative_volume_shares':quote_volume,
                        'difference_shares':total-quote_volume,
                        'difference_over_vendor_cumulative':(total/quote_volume-1) if quote_volume else None}
        audits.append({'provider':provider,'symbol':symbol,'interval':'1m','volume_reconciliation_state':state,
            'volume_comparison':details,'overlap_revisions':revisions,'volume_revision_count':volume_revisions,
            'volume_confirmation_eligible':False if contradiction or volume_revisions or state=='unverified_metadata_or_window' else None,
            'volume_usage':'retained provider reports; no whole-day volume or institutional-flow confirmation without matched scope and source review',
            'price_latest_snapshot_retained':True,'conflicting_volume_normalized':False,
            'source_url':bars[-1].source_url,'source_receipts':list(dependencies.values()),
            'original_versions_retained_in_raw_and_normalized_receipts':True})
    return audits


def quality_observations(audits,cutoff):
    return [Observation('local_intraday_quality','intraday_source_quality',x['symbol'],cutoff,x,
        unit='field_specific_reconciliation_and_revision_audit',quality='locally_reviewed_source_consistency',
        source_url=x['source_url'],source_receipts=x['source_receipts'],
        raw={'local_audit_not_independent_market_source':True}) for x in audits]


def mark_volume_indicator_quality(indicators,audits):
    unverified={x['symbol'] for x in audits if x['volume_confirmation_eligible'] is not True}
    for item in indicators:
        if item.symbol in unverified and ('volume' in item.name or item.name in {'vwap','obv'}):
            item.quality='unverified_for_volume_confirmation'
    return indicators
