"""Public intraday requests use bounded recent ranges rather than daily-year budgets."""
from .conventions import interval_name
from .conventions import parse_time
from datetime import timedelta
from dataclasses import replace
import re


def public_history_request(interval,outputsize):
    if type(outputsize)!=int or not 1<=outputsize<=5000:raise ValueError('Use a positive bounded output-size budget')
    native=interval_name(interval)
    if native in {'1m','2m','5m','15m','30m','60m','90m','1h'}:
        return native,2
    return native,max(450,outputsize*2)


def completed_public_intraday(rows,interval,cutoff):
    match=re.fullmatch(r'(\d+)(m|h)',interval)
    if not match:return rows
    seconds=int(match[1])*(60 if match[2]=='m' else 3600)
    end=parse_time(cutoff);result=[]
    for row in rows:
        closes=parse_time(row.timestamp)+timedelta(seconds=seconds)
        if closes>end:continue
        result.append(replace(row,session='completed_provider_intraday_bar',
            raw={**row.raw,'locally_checked_interval_end_utc':closes.isoformat(),
                 'local_completion_cutoff_utc':end.isoformat(),'intraday_clock_check_is_local':True}))
    return result
