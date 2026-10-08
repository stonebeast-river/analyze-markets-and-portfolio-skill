"""Current-vintage CSI index PE-TTM history, kept separate from executable entry levels."""
import math
from datetime import date,timedelta
from urllib.parse import urlencode
from ..http import HttpClient,DataSourceError
from ..models import Observation


class CsiValuationProvider:
    name='csi_official_index_valuation'
    def __init__(self,client=None):self.client=client or HttpClient(timeout=15,retries=0,user_agent='Mozilla/5.0')

    def fetch_evidence(self,index_code,*,end_date,years=10):
        if len(index_code)!=6 or not index_code.isalnum() or type(years)!=int or not 1<=years<=20:
            raise ValueError('Publisher index code and bounded lookback required')
        end=date.fromisoformat(end_date);start=end-timedelta(days=365*years)
        url='https://www.csindex.com.cn/csindex-home/perf/index-perf?'+urlencode({'indexCode':index_code,'startDate':start.strftime('%Y%m%d'),'endDate':end.strftime('%Y%m%d')})
        result,source=self.client.get_json(url)
        if str(result.get('code'))!='200' or result.get('success') is False or not isinstance(result.get('data'),list) or not result['data']:
            raise DataSourceError('CSI valuation response shape/rows unavailable')
        records=[];seen=set()
        for row in result['data']:
            if row.get('indexCode')!=index_code:raise DataSourceError('CSI returned a different index identity')
            raw_date=str(row.get('tradeDate',''));day=date(int(raw_date[:4]),int(raw_date[4:6]),int(raw_date[6:8]))
            if not start<=day<=end or day in seen:raise DataSourceError('CSI valuation dates duplicate or outside requested window')
            seen.add(day);pe=row.get('peg')
            if pe is not None and (type(pe) not in (int,float) or not math.isfinite(pe)):
                raise DataSourceError('CSI PE-TTM field not finite numeric')
            records.append({**row,'date':day.isoformat()})
        records.sort(key=lambda r:r['date']);latest=records[-1];current=latest.get('peg');ranks=[]
        calendar_anomalies=[{'date':r['date'],'PE_TTM':r.get('peg')} for r in records if date.fromisoformat(r['date']).weekday()>=5]
        if type(current) in (int,float) and current>0:
            for window in (1,3,5,10):
                if window>years:continue
                cutoff=(date.fromisoformat(latest['date'])-timedelta(days=365*window)).isoformat()
                values=[r['peg'] for r in records if r['date']>=cutoff and type(r.get('peg')) in (int,float) and r['peg']>0]
                if len(values)<60:continue
                sorted_values=sorted(values)
                weekdays=[r['peg'] for r in records if r['date']>=cutoff and date.fromisoformat(r['date']).weekday()<5 and type(r.get('peg')) in (int,float) and r['peg']>0]
                ranks.append({'lookback_365_day_years':window,'valid_rows':len(values),'empirical_fraction_at_or_below_latest':sum(x<=current for x in values)/len(values),
                    'weekday_only_fraction_sensitivity':sum(x<=current for x in weekdays)/len(weekdays) if weekdays else None,
                    'PE20_observation_parameter':sorted_values[int((len(values)-1)*.2)],
                    'PE10_observation_parameter':sorted_values[int((len(values)-1)*.1)],'proven_optimal_entry_threshold':False})
        value={'publisher_index_code':index_code,'latest_source_date':latest['date'],'latest_reported_fields':latest,
            'PE_TTM':current,'source_field':'peg','field_meaning':'PE TTM / rolling price earnings, not price-earnings-growth ratio',
            'field_mapping_basis':'observed CSI official index valuation UI downloaded2026-10-02; raw field retained',
            'historical_vintage_availability_verified':False,'current_vintage_history':records,'percentiles':ranks,
            'date_audit':{'nonweekday_source_rows':calendar_anomalies,'full_historical_exchange_calendar_verified':False,
                'percentile_main_basis':'reported positive observations; weekday-only sensitivity separate, not full-calendar certification'},
            'automatic_buy_level_supported':False,'scope':'current downloaded valuation history and transparent observation parameters'}
        return self.client.bind_rows([Observation(self.name,'index_valuation','CSI:'+index_code,latest['date'],value,
            unit='PE_TTM_ratio_and_empirical_fractions',currency='CNY',source_url=source,quality='primary_index_current_vintage')])
