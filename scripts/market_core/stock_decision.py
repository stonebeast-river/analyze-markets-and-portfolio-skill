"""Independent stock opinions and conditional plans, separated from forecast probabilities."""
import math

def decide_stock(context,financial_coverage,event_context,*,symbol,current=True,position_state='unknown',risk_budget_CNY=None):
    if position_state not in {'unknown','unheld','held'}:raise ValueError('Position state must come from user context or remain unknown')
    if risk_budget_CNY is not None and (isinstance(risk_budget_CNY,bool) or not isinstance(risk_budget_CNY,(int,float)) or not math.isfinite(risk_budget_CNY) or risk_budget_CNY<=0):
        raise ValueError('Risk budget must be a finite positive user-confirmed amount')
    fields=financial_coverage.get('primary_fields',[]);growth={};reasons=[];counter=[]
    for name in ('operating_revenue','net_profit_parent'):
        matches=[f for f in fields if f.get('usable') and f.get('identity')==symbol and f.get('name')==name
                 and f.get('unit')=='CNY_yuan' and f.get('period_kind')=='flow_YTD' and f.get('prior_reported_decimal')]
        if matches:
            field=max(matches,key=lambda f:f['period_end']);prior=float(field['prior_reported_decimal'])
            if prior>0:growth[name]=field['value']/prior-1
    earnings=growth.get('net_profit_parent');revenue=growth.get('operating_revenue')
    if earnings is not None:
        (reasons if earnings>0 else counter).append(f'核验归母利润对相同报告期变化 {earnings:+.2%}')
    if revenue is not None:
        (reasons if revenue>0 else counter).append(f'核验营业收入对相同报告期变化 {revenue:+.2%}')
    trend=context.get('trend');phase=context.get('price_phase');macd=context.get('macd_histogram')
    if trend=='upward_trend':reasons.append('EMA趋势向上')
    elif trend=='downward_trend':counter.append('EMA趋势向下')
    for event in event_context.get('reviewed_events',[]):
        if event.get('interpretation'):counter.append(event['interpretation'])
    catalogue=event_context.get('catalogue_window_complete',False)
    veto=any(e.get('decision_veto') is True for e in event_context.get('reviewed_events',[]))
    unresolved_risk=event_context.get('unreviewed_critical_announcements',[])
    current_breakout=(phase=='breakout' and context.get('volume_ratio_previous5') is not None and context['volume_ratio_previous5']>=1.2)
    supportive_fundamentals=earnings is not None and earnings>0 and revenue is not None and revenue>0
    positive_catalyst=bool(event_context.get('upcoming_material_catalysts'))
    if not current:
        action='refresh_required';direction='不能作为当前判断';why='已完成日线覆盖不足'
    elif veto:
        action='review_reduce' if position_state=='held' else 'avoid_new_entry';direction='风险压制';why='存在已核验的重大风险否决证据，不能由技术上涨抵消'
    elif unresolved_risk:
        action='wait_for_critical_review';direction='重要风险尚未核验';why='出现需要核对原文的重要风险线索，先完成该项证据核验'
    elif trend=='downward_trend' and earnings is not None and earnings<0:
        action='do_not_add' if position_state=='held' else 'avoid_new_entry'
        direction='偏弱，反弹确认不足';why='价格趋势和核验利润方向均不支持增加风险敞口'
    elif supportive_fundamentals and catalogue and trend=='upward_trend' and current_breakout:
        action='add_conditionally' if position_state=='held' else 'build_next_session_conditionally'
        direction='偏多';why='核验基本面与已发生的价格/量能确认同向；次日成交与风险预算仍需检查'
    elif supportive_fundamentals and catalogue and positive_catalyst and trend!='downward_trend':
        action='assess_early_entry';direction='经营与催化支持转强判断';why='早期证据可支持比较现在分批和确认后进入；由独立研究判断入场经济性，未突破不自动要求等待'
    elif trend=='upward_trend' and earnings is not None and earnings>=0 and catalogue:
        action='assess_hold_or_add' if position_state=='held' else 'assess_current_entry'
        direction='价格与已核经营数据偏支持';why='比较当前价格、回踩进入和机会成本；这个突破规则未触发，不代表其它进入路线不可行'
    else:
        action='independent_assessment_required';direction='需独立判断此规则之外的投资论点';why='当前未满足这一特定确认规则；补查会改变观点的证据后比较进入、持有、退出与等待，不把规则缺项直接当等待结论'
    qualified_buy=action in {'add_conditionally','build_next_session_conditionally'}
    plan={'basis':'fraction_of_user_designated_future_allocation_not_personal_portfolio_weight',
        'tranches':[{'fraction':.25,'condition':'次一可交易日检查入场价格、流动性与预算后'},
                    {'fraction':.25,'condition':'回踩不失效并再度确认，且原投资理由仍成立'},
                    {'fraction':.5,'condition':'后续经营/事件证据兑现，累计风险不超预算'}] if qualified_buy else [],
        'risk_budget_CNY':risk_budget_CNY,'quantity_calculated':False,
        'invalidation_reference':context.get('support_previous20'),'review_on':'next_completed_daily_session',
        'conditional_reduce':'若已有仓位且价格失效与基本面恶化持续，复核减仓；不推定现有仓位比例'}
    return {'symbol':symbol,'action':action,'directional_judgment':direction,'reason':why,'supporting_evidence':reasons,'counter_evidence':counter,
        'verified_risk_veto':veto,'unreviewed_critical_announcements':unresolved_risk,
        'fundamental_growth':growth,'current_breakout_confirmed':current_breakout,'catalogue_window_complete':catalogue,
        'position_state':position_state,'plan':plan,'trade_authorized':False,'user_buy_preference_affects_confidence':False,
        'opinion_type':'conditional_analytical_investment_opinion','statistical_probability_used':False,
        'strategy_profitability_assumed':False,'full_stock_diligence_complete':False,
        'rule_scope':'optional earnings-and-breakout confirmation setup, not a universal investment gate',
        'independent_final_judgment_required':True}
