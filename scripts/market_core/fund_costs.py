"""Compare forward A/C costs from reviewed terms without re-charging historical NAV."""
import math,calendar
from datetime import date,timedelta


def subscription_cost(amount,tiers,*,rate_override=None):
    if not isinstance(amount,(int,float)) or isinstance(amount,bool) or not math.isfinite(amount) or amount<=0:
        raise ValueError('Positive finite comparison cash required')
    if rate_override is not None:
        if not 0<=rate_override<1:raise ValueError('Subscription scenario rate invalid')
        return {'net_investment':amount/(1+rate_override),'fee':amount-amount/(1+rate_override),
                'applied_fraction':rate_override,'basis':'external_charge_on_gross_application_amount','override_is_scenario':True}
    matched=[t for t in tiers if amount>=t['min_amount'] and (t.get('max_amount_exclusive') is None or amount<t['max_amount_exclusive'])]
    if len(matched)!=1:raise ValueError('Subscription tiers missing or overlapping for comparison amount')
    tier=matched[0]
    if 'fixed_CNY' in tier:
        fee=tier['fixed_CNY'];net=amount-fee
        if not 0<=fee<amount:raise ValueError('Fixed subscription fee invalid')
        return {'net_investment':net,'fee':fee,'applied_fraction':None,'fixed_CNY':fee,'basis':'fixed_charge','override_is_scenario':False}
    rate=tier['fraction']
    if not 0<=rate<1:raise ValueError('Subscription tier rate invalid')
    return {'net_investment':amount/(1+rate),'fee':amount-amount/(1+rate),'applied_fraction':rate,
            'basis':'external_charge_on_gross_application_amount','override_is_scenario':False}


def redemption_rate(terms,holding_fee_age_days,*,one_year_tier_reached=None):
    if type(holding_fee_age_days)!=int or holding_fee_age_days<0:raise ValueError('Actual fee-age days required')
    if one_year_tier_reached is True and holding_fee_age_days<365:raise ValueError('One-year tier conflicts with fee-age days')
    if holding_fee_age_days<7:return terms['under_7_day_fraction']
    if terms['type']=='seven_day_only':return terms['at_least_7_day_fraction']
    if terms['type']!='seven_day_and_one_year':raise ValueError('Unsupported reviewed redemption structure')
    if one_year_tier_reached is True:return terms['at_least_one_year_fraction']
    if one_year_tier_reached is False or holding_fee_age_days<365:return terms['seven_days_to_one_year_fraction']
    return None


def forward_share_cost_comparison(contract,*,comparison_cash=10000,holding_fee_age_days=90,start_date=None,
                                  A_subscription_rate_scenario=None,one_year_tier_reached=None):
    if not contract.get('verified_against_current_source_bytes'):raise ValueError('Reviewed current fee contract required')
    if contract.get('sales_service_charge_base')!='previous_calendar_day_full_share_class_NAV':
        raise ValueError('This comparison requires the reviewed full-NAV sales-service base')
    if contract.get('common_portfolio_and_ongoing_terms_identical') is not True:raise ValueError('A/C underlying and common terms must be matched')
    if type(holding_fee_age_days)!=int or holding_fee_age_days<0:raise ValueError('Fee-age days must be a nonnegative integer')
    start=date.fromisoformat(start_date) if start_date else None
    classes=[]
    for share in ('A','C'):
        terms=contract['classes'][share];rate=terms['sales_service_annual_fraction']
        if not 0<=rate<1:raise ValueError('Sales-service rate invalid')
        service_factor=1.0
        for i in range(holding_fee_age_days):
            day=start+timedelta(days=i) if start else None
            denominator=366 if day and calendar.isleap(day.year) else 365
            service_factor*=1-rate/denominator
        upfront=subscription_cost(comparison_cash,terms['subscription_tiers'],rate_override=A_subscription_rate_scenario if share=='A' else None)
        redeem=redemption_rate(terms['redemption'],holding_fee_age_days,one_year_tier_reached=one_year_tier_reached)
        cash_before_redemption=upfront['net_investment']*service_factor
        remaining=cash_before_redemption*(1-redeem) if redeem is not None else None
        classes.append({'code':terms['code'],'share_class':share,'subscription':upfront,'sales_service_factor':service_factor,
            'redemption_fraction':redeem,'ending_comparison_cash':remaining,
            'relative_cost_fraction':1-remaining/comparison_cash if remaining is not None else None})
    comparable=all(x['ending_comparison_cash'] is not None for x in classes)
    winner=max(classes,key=lambda x:x['ending_comparison_cash'])['code'] if comparable else None
    return {'comparison_cash_CNY':comparison_cash,'holding_fee_age_days':holding_fee_age_days,
        'classes':classes,'lower_relative_cost_code':winner,'source':contract['source'],
        'basis':'same pre-class-fee flat NAV scenario; matched common fees cancel approximately; no predicted market return',
        'fee_age_start_is_not_assumed_application_date':True,'historical_NAV_fees_charged_again':False,
        'day_count': 'actual calendar year days' if start else '365-day scenario without specified actual start date',
        'one_year_tier_flag_supplied':one_year_tier_reached is not None,
        'platform_A_rate_verified':False,'platform_purchase_availability_verified':False,
        'rounding_and_real_confirmation_NAV_simulated':False,'personal_portfolio_used':False}
