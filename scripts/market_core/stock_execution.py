"""Delayed long-only paper execution with T+1, lots, costs and dated cash entitlements."""
import math
from .stock_technicals import technical_series

def paper_stock_strategy(bars,*,initial_cash=1000000.0,lot_size=100,holding_bars=20,
                         side_cost_fraction=0.001,slippage_fraction=0.001,dividends=None,dividend_tax_fraction=0.0,warmup_bars=None):
    if initial_cash<=0 or type(lot_size)!=int or lot_size<1 or type(holding_bars)!=int or holding_bars<2:
        raise ValueError('Cash/lot/holding parameters invalid')
    if not 0<=side_cost_fraction<.1 or not 0<=slippage_fraction<.1 or not 0<=dividend_tax_fraction<=1:
        raise ValueError('Cost/tax scenario parameters invalid')
    warmup=warmup_bars or [];full_rows=technical_series([*warmup,*bars]);offset=len(warmup);rows=full_rows[offset:];events=dividends or []
    if any(not all(event.get(k) is not None for k in ('record_date','payment_date','cash_per_share_CNY'))
           or event['cash_per_share_CNY']<0 or event['payment_date']<event['record_date'] for event in events):
        raise ValueError('Dated dividend entitlement invalid')
    dates=[b.timestamp[:10] for b in bars]
    if len(set(dates))!=len(dates):raise ValueError('Paper execution needs unique daily sessions')
    cash=float(initial_cash);qty=0;bought=None;pending=None;signals=[];fills=[];equity=[];entitlements={};paid=set();unfilled=[]
    def liquid(i):
        bar=bars[i]
        return bar.volume is not None and bar.volume>0 and bar.high>bar.low
    def buy(i,reason):
        nonlocal cash,qty,bought
        price=bars[i].open*(1+slippage_fraction);per_lot=price*lot_size*(1+side_cost_fraction)
        if price>bars[i].high:return False
        lots=int(cash//per_lot)
        if lots<=0:return False
        shares=lots*lot_size;fee=shares*price*side_cost_fraction;cash-=shares*price+fee;qty=shares;bought=i
        fills.append({'side':'buy','date':dates[i],'price':price,'quantity':shares,'fee':fee,'reason':reason});return True
    def sell(i,reason):
        nonlocal cash,qty,bought
        price=bars[i].open*(1-slippage_fraction);fee=qty*price*side_cost_fraction
        if price<bars[i].low:return False
        fills.append({'side':'sell','date':dates[i],'price':price,'quantity':qty,'fee':fee,'reason':reason})
        cash+=qty*price-fee;qty=0;bought=None;return True
    for i,row in enumerate(rows):
        if pending:
            if liquid(i) and (pending['side']=='buy' or bought is not None and i>bought):
                filled=buy(i,pending['reason']) if pending['side']=='buy' else sell(i,pending['reason'])
                if filled:pending=None
                elif pending['side']=='buy':unfilled.append({'date':dates[i],'side':'buy','reason':'cash_or_slippage_range'});pending=None
            elif pending['side']=='buy':
                unfilled.append({'date':dates[i],'side':'buy','reason':'not_tradable_next_open'});pending=None
        # Entitlement is established on record-date close; payment can follow after sale.
        for n,event in enumerate(events):
            if dates[i]==event['record_date']:entitlements[n]=qty*event['cash_per_share_CNY']*(1-dividend_tax_fraction)
            if dates[i]>=event['payment_date'] and n in entitlements and n not in paid:
                cash+=entitlements[n];paid.add(n)
        equity.append({'date':dates[i],'cash':cash,'shares':qty,'close':row['close'],
                       'equity':cash+qty*row['close']+sum(v for n,v in entitlements.items() if n not in paid and dates[i]>=events[n].get('ex_date',events[n]['payment_date']))})
        absolute_index=offset+i
        if absolute_index<60 or pending:continue
        previous=full_rows[max(0,absolute_index-20):absolute_index]
        if not previous:continue
        resistance=max(x['high'] for x in previous);support=min(x['low'] for x in previous)
        if qty and (row['close']<support or i-bought>=holding_bars):
            reason='support_lost' if row['close']<support else 'holding_period'
            pending={'side':'sell','reason':reason};signals.append({'date':dates[i],'side':'sell','reason':reason,'execution':'next_available_open'})
        elif not qty and row['close']>resistance and row['ema20']>row['ema60'] and row['volume_ratio5'] is not None and row['volume_ratio5']>=1.2:
            pending={'side':'buy','reason':'prior20_breakout_with_volume'};signals.append({'date':dates[i],'side':'buy','execution':'next_available_open'})
    # Same-period passive comparator with the same entry costs, lots and cash entitlements.
    first=next((i for i in range(len(bars)) if liquid(i) and bars[i].open*(1+slippage_fraction)<=bars[i].high),None);base_curve=[];base_cash=float(initial_cash);base_qty=0;base_entitlements={};base_paid=set()
    if first is not None:
        price=bars[first].open*(1+slippage_fraction);base_qty=int(base_cash//(price*lot_size*(1+side_cost_fraction)))*lot_size
        base_cash-=base_qty*price*(1+side_cost_fraction)
    for i,bar in enumerate(bars):
        held=base_qty if first is not None and i>=first else 0
        for n,event in enumerate(events):
            if dates[i]==event['record_date']:base_entitlements[n]=held*event['cash_per_share_CNY']*(1-dividend_tax_fraction)
            if dates[i]>=event['payment_date'] and n in base_entitlements and n not in base_paid:base_cash+=base_entitlements[n];base_paid.add(n)
        base_curve.append({'date':dates[i],'equity':(base_cash if i>=first else initial_cash) if first is not None else initial_cash})
        if held:base_curve[-1]['equity']+=held*bar.close
        base_curve[-1]['equity']+=sum(v for n,v in base_entitlements.items() if n not in base_paid and dates[i]>=events[n].get('ex_date',events[n]['payment_date']))
    def summary(curve):
        peak=initial_cash;drawdown=0
        for row in curve:peak=max(peak,row['equity']);drawdown=min(drawdown,row['equity']/peak-1)
        final=curve[-1]['equity'] if curve else initial_cash
        return {'ending_equity_mark_to_market':final,'return':final/initial_cash-1,'max_drawdown':drawdown}
    return {'strategy':'fixed_prior20_breakout_volume1.2_ema20above60_v1','parameters':{
        'initial_simulation_cash_CNY':initial_cash,'lot_size':lot_size,'holding_daily_bars':holding_bars,
        'side_cost_fraction':side_cost_fraction,'slippage_fraction':slippage_fraction,'dividend_tax_scenario_fraction':dividend_tax_fraction},
        'period_start':dates[0] if dates else None,'period_end':dates[-1] if dates else None,
        'warmup_daily_bars':len(warmup),'fills_count':len(fills),'completed_round_trips':sum(r['side']=='sell' for r in fills),
        'strategy_result':summary(equity),'passive_same_stock':summary(base_curve),'signals':signals,'fills':fills,
        'equity_curve':equity,'passive_curve':base_curve,'dividend_events':events,'unfilled_orders':unfilled,
        'unfilled_pending_order':pending,'open_inventory_shares':qty,
        'scope':'Paper scenario; T+1/lots/delay/costs and supplied entitlements. Liquidity uses daily-volume/range proxy, not verified queue fills.',
        'historically_robust_strategy_verified':False,'personal_portfolio_used':False,
        'zero_fills_is_cash_holding_not_predictive_advantage':not fills,
        'costs_are_configured_scenarios_not_broker_or_tax_rate_certification':True}
