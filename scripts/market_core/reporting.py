"""Export a locked research view and a separate optional private product appendix."""
import hashlib
import json
from pathlib import Path

from .lineage import canonical
from .portfolio_overlay import read_portfolio_mapping
from .workflow import read_prepared, verify_research


def text(value):
    if value is None:
        return 'unknown'
    if isinstance(value, dict):
        return '; '.join(f'{key}: {text(item)}' for key, item in value.items())
    if isinstance(value, list):
        return '; '.join(text(item) for item in value) or 'unknown'
    return str(value)


def table(headers, rows):
    def cell(value):
        return text(value).replace('|', '\\|').replace('\r', ' ').replace('\n', '<br>')
    return '\n'.join(['| ' + ' | '.join(map(cell, headers)) + ' |',
                       '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                      ['| ' + ' | '.join(map(cell, row)) + ' |' for row in rows])


def sealed_json(root, name):
    value = json.loads((root / (name + '.json')).read_text(encoding='utf-8'))
    seal = json.loads((root / (name + '-seal.json')).read_text(encoding='utf-8'))
    if hashlib.sha256(canonical(value)).hexdigest() != seal['sha256']:
        raise ValueError('Changed sealed artifact: ' + name)
    return value, seal['sha256']


def market_report(inputs, locked):
    view = locked['view']
    summary = view['market_summary']
    judgment = summary.get('judgment', text(summary)) if isinstance(summary, dict) else text(summary)
    parts = ['# 市场研究记录', f"市场证据截止：{inputs['cutoff']}。研究模式：{inputs['profile']}。",
             judgment, f"**Exposure stance: {view.get('exposure_stance', 'not supplied')}**",
             f"判断信心：{text(view.get('confidence', 'not supplied'))}。", '## 研究覆盖',
             table(['市场', '已取得的证据与缺口'], view.get('coverage', {}).items())
             if isinstance(view.get('coverage'), dict) else text(view.get('coverage')),
             '## 行业相对价格窗口',
             '下表比较行业代理与各自宽基。回报为价格回报；窗口为共同基准观察期，未核为含分红总回报。']
    sectors = [fact for fact in inputs['evidence_register'].values()
               if fact['record'].get('measurement') == 'sector_price_windows']
    rows = []
    for fact in sectors:
        record = fact['record']
        windows = {item['periods']: item for item in record.get('windows', [])}
        returns = [f"{windows[n]['relative_return_percentage_points']:+.2f}"
                   if n in windows and windows[n].get('relative_return_percentage_points') is not None
                   else 'unknown' for n in (1, 5, 20, 60)]
        dates = [item.get('end') for item in windows.values() if item.get('end')]
        rows.append([record.get('sector_identity'), record.get('benchmark_identity'),
                     max(dates) if dates else 'unknown', *returns,
                     record.get('currency'), record.get('price_basis'),
                     f"{record.get('sector_provider')} / {record.get('benchmark_provider')}",
                     fact.get('source_url') or 'unknown'])
    parts.append(table(['行业代理', '基准', '窗口末日', '1期相对百分点', '5期', '20期', '60期',
                        '币种', '价格口径', '来源', '来源链接'], rows) if rows else '未取得可核验行业窗口。')
    targets=inputs.get('tactical_input_coverage',{}).get('target_identities',[])
    if targets:
        tactical_rows=[]
        for identity in targets:
            facts=[(key,fact['record']) for key,fact in inputs['evidence_register'].items() if fact['identity']==identity]
            quotes=[(key,row) for key,row in facts if 'last' in row and 'input_provider' not in row]
            quote_id,quote=quotes[-1] if quotes else ('unknown',{})
            metrics={(row['interval'],row['name']):(key,row['value']) for key,row in facts if 'input_provider' in row}
            minute_intervals=sorted({interval for interval,name in metrics if interval not in {'snapshot','1d','1w','1mo'}})
            interval=minute_intervals[0] if minute_intervals else 'unknown'
            def metric(name,period):
                key,value=metrics.get((period,name),('unknown',None))
                return f'{text(value)} ({key})'
            flows=[(key,row) for key,row in facts if row.get('dataset')=='transaction_aggregate_summary']
            flow_id,flow=flows[-1] if flows else ('unknown',{})
            tactical_rows.append([identity,quote.get('as_of'),f"{text(quote.get('last'))} {text(quote.get('currency'))} ({quote_id})",
                quote.get('turnover_pct'),metric('volume_ratio_vendor','snapshot'),
                metric('order_book_imbalance_5','snapshot'),metric('outer_inner_volume_ratio','snapshot'),
                interval,metric('macd_histogram',interval),metric('rsi',interval),
                f"{text(flow.get('value',{}).get('net_amount'))} CNY ({flow_id}); {text(flow.get('as_of'))}"])
        parts.extend(['## 盘中研究证据',
            '以下是各来源最后可用时点的记录。分钟指标使用完整冻结前缀；成交聚合净额保留供应商方向分类。盘口、量比和成交聚合不等同于机构行为。',
            table(['对象','报价时间','价格与证据','换手%','供应商量比','五档不平衡','外内盘比','分钟周期','MACD柱','RSI','供应商聚合净额与时间'],tactical_rows)])
    parts.extend(['## 原观点复核', table(['观点ID', '状态', '原截止', '本次截止', '确认', '失效'],
        [[item.get(key) for key in ('thesis_id', 'status', 'original_cutoff', 'review_cutoff',
                                    'confirmation', 'invalidation')]
         for item in view.get('prior_view_reviews', [])])
        if view.get('prior_view_reviews') else '本次为基线，尚无旧观点复核。', '## 核心判断与反证'])
    for thesis in view['theses']:
        parts.extend([f"### {thesis.get('thesis_id', 'unassigned')}", text(thesis.get('thesis')),
            f"状态：{text(thesis.get('status'))}。期限：{text(thesis.get('horizon'))}。基准：{text(thesis.get('benchmark'))}。",
            f"反例：{text(thesis.get('countercase'))}", f"确认：{text(thesis.get('confirmation'))}",
            f"失效：{text(thesis.get('invalidation'))}", f"证据：{text(thesis.get('evidence_ids'))}"])
    parts.extend(['## 候选调查', table(['方向', '类型', '状态', '信心', '核心缺口', '反例', '期限',
                                     '确认', '失效', '替代', '等待理由', '证据'],
        [[item.get(key) for key in ('exposure', 'opportunity_type', 'status', 'confidence',
          'core_missing', 'countercase', 'horizon', 'confirmation', 'invalidation', 'alternative',
          'waiting_case', 'evidence_ids')] for item in view['opportunities']]), '## 方案比较',
        table(['选择', '资格', '理由', '缺口', '等待代价'],
              [[item.get(key) for key in ('choice', 'eligible', 'reason', 'missing', 'waiting_cost')]
               for item in view['alternatives'] if isinstance(item, dict)]),
        '## 等待与下一次复核', text(view['waiting_case']), '## 判断所引用的来源'])
    ids = sorted({key for item in view['theses'] + view['opportunities'] for key in item.get('evidence_ids', [])})
    parts.append(table(['证据ID', '对象', '种类', '观察时间', '来源'],
        [[key, inputs['evidence_register'][key]['identity'], inputs['evidence_register'][key]['kind'],
          inputs['evidence_register'][key]['as_of'], inputs['evidence_register'][key].get('source_url') or 'unknown']
         for key in ids]))
    return '\n\n'.join(parts) + '\n'


def portfolio_report(dossier, mapping):
    parts = ['# 私人产品与持仓附录',
        f"市场证据截止：{dossier['market_cutoff']}。产品证据截止：{dossier['product_evidence_cutoff']}。",
        '本附录在独立市场观点封印后生成。原始记录没有份额及当前市值，当前权重、重叠比例和收益贡献尚不能计算。',
        table(['产品代码', '已核名称', '份额', '币种', '底层参考', '目标ETF', '产品资料状态', '影响选择的缺口'],
            [[row.get(key) for key in ('code', 'name', 'share_class', 'currency', 'underlying_identity',
                                       'target_etf', 'product_readiness', 'contract_missing')]
             for row in mapping['positions']]), '## 产品合同证据']
    for item in dossier['products']:
        records = [row for row in item['evidence']['observations'] if row['dataset'] == 'fund_product']
        product = records[-1]['value'] if records else {}
        document_urls = {row['value']['sha256']: row['value'].get('source_url', row.get('source_url'))
                         for row in item.get('documents', [])}
        parts.extend([f"### {item['code']}",
            f"费用及计费基数：{text(product.get('fee_terms'))}",
            f"正常申赎与公布条款：{text(product.get('dealing_rules'))}",
            f"已取得的限购公告：{text(product.get('dated_subscription_limit'))}",
            f"当前申购状态：{text(product.get('subscription_status'))}。",
            '已取公告与正常条款仍需结合后续公告、开放日历及实际平台规则判断当日能否办理。',
            table(['原文来源', '公布日期', 'PDF SHA256'],
                  [[document_urls.get(doc.get('sha256')), doc.get('publication_date'), doc.get('sha256')]
                   for doc in product.get('source_documents', [])]),
            table(['已核字段', '原文来源', '证据页'],
                  [[field, source.get('source_url'), source.get('page_evidence', {}).get('pages',
                      source.get('page_evidence', {}).get('page', 'unknown'))]
                   for field, source in product.get('field_sources', {}).items()])])
    parts.extend(['## 组合层面的可用结论',
        f"同一已核底层分组：{text(mapping['same_underlying_groups'])}。",
        '跨指数成分重叠、地域和汇率敞口比例需取得对应时点的成分及持仓权重。',
        '当前记录支持产品身份与合同映射；尚不足以计算集中度，或确认已达到组合复核阈值。'])
    return '\n\n'.join(parts) + '\n'


def export_report(directory, output, *, include_portfolio=False):
    root, inputs, input_seal = read_prepared(directory)
    verified = verify_research(root)
    if verified['status'] not in {'ok', 'partial'}:
        raise ValueError('Research calculations failed verification')
    locked, market_sha = sealed_json(root, 'market-view')
    if locked['input_sha256'] != input_seal['sha256']:
        raise ValueError('Market view belongs to another research input')
    artifacts = {'market-report.md': market_report(inputs, locked)}
    provenance = {'schema_version': 1, 'market_cutoff': inputs['cutoff'], 'profile': inputs['profile'],
                  'research_input_sha256': input_seal['sha256'], 'market_view_sha256': market_sha,
                  'calculations_verified': verified['status'], 'portfolio_in_market_report': False}
    if include_portfolio:
        dossier, dossier_sha = sealed_json(root, 'product-dossier')
        if dossier['market_view_sha256'] != market_sha:
            raise ValueError('Product dossier belongs to another market view')
        mapping = json.loads((root / 'portfolio-mapping.private.json').read_text(encoding='utf-8'))
        if canonical(mapping) != canonical(read_portfolio_mapping(root)):
            raise ValueError('Portfolio mapping differs from its authoritative projection')
        artifacts['portfolio-appendix.private.md'] = portfolio_report(dossier, mapping)
        provenance.update(product_evidence_cutoff=dossier['product_evidence_cutoff'],
                          product_dossier_sha256=dossier_sha, quantitative_weights_verified=False)
    target = Path(output).resolve()
    if target.exists():
        raise ValueError('Export path already exists; use a new directory')
    # Validate all inputs before producing any files. No live database or network.
    target.mkdir(parents=True)
    for name, body in artifacts.items():
        (target / name).write_text(body, encoding='utf-8')
    provenance['artifacts'] = {name: hashlib.sha256((target / name).read_bytes()).hexdigest()
                               for name in artifacts}
    (target / 'report-provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'output': str(target), 'artifacts': list(artifacts) + ['report-provenance.json'],
            'market_view_unchanged': True, 'private_amounts_printed': False}
