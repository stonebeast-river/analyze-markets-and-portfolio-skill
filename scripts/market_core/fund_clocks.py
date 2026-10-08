"""Reviewed fund valuation/publication calendars, distinct from exchange quote clocks."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from .conventions import parse_time
from .task_health import cash_calendar,completed_cash_session


def nav_currentness(product,valuation_date,as_of):
    contract=product.get('nav_calendar_contract') or {}
    if not contract.get('verified'):return {'status':'unknown','reason':'unverified_fund_calendar'}
    market=contract.get('valuation_market');calendar=cash_calendar(market)
    latest=completed_cash_session(market,as_of)
    if calendar is None or latest is None:return {'status':'unknown','reason':'calendar_out_of_coverage'}
    if contract.get('publication_rule')!='next_calendar_day_end':
        return {'status':'unknown','reason':'unsupported_publication_rule'}
    now=parse_time(as_of).astimezone(ZoneInfo(calendar['timezone']));day=datetime.fromisoformat(latest).date()
    closed=set(calendar['closed_dates']);required=None
    while day.isoformat()>=calendar['coverage_start']:
        if day.weekday()<5 and day.isoformat() not in closed:
            deadline=datetime.combine(day+timedelta(days=1),datetime.max.time(),tzinfo=now.tzinfo)
            if now>deadline:required=day.isoformat();break
        day-=timedelta(days=1)
    if required is None:return {'status':'unknown','reason':'prior_publication_deadline_out_of_coverage'}
    if valuation_date>latest:return {'status':'unavailable','reason':'valuation_after_last_completed_session'}
    return {'status':'current_publication_window' if valuation_date>=required else 'stale',
            'minimum_expected_valuation_date':required,'last_completed_valuation_session':latest,
            'publication_rule':contract['publication_rule'],'normal_case_only':True,
            'source':contract.get('source')}
