"""Prioritize primary documents for reading, never infer an economic verdict from titles."""
import re


GOVERNANCE_REVIEW_TERMS=('留置','被立案','立案调查','处罚决定','重大诉讼','退市风险','重大风险提示','业绩预亏')


def select_material_documents(rows,*,limit=12):
    if type(limit)!=int or not 1<=limit<=40:raise ValueError('Bounded material-document limit required')
    unique={r.value['announcement_id']:r for r in rows};selected={};reasons={}
    def add(row,reason):
        key=row.value['announcement_id'];selected[key]=row;reasons.setdefault(key,[]).append(reason)
    full_reports=[r for r in unique.values() if not any(x in r.value['title'] for x in ('摘要','英文','提示性公告'))]
    for name,pattern in [('annual_report',r'年年度报告(?:$|[（(])'),
                         ('interim_report',r'(?:年半年度报告|年中期报告)(?:$|[（(])'),
                         ('quarter_report',r'(?:年第?[一二三四1234]季度报告)(?:$|[（(])')]:
        eligible=[r for r in full_reports if re.search(pattern,re.sub(r'\s+','',r.value['title']))]
        if eligible:add(max(eligible,key=lambda r:(r.as_of,r.value['announcement_id'])),name)
    for row in unique.values():
        if any(term in row.value['title'] for term in GOVERNANCE_REVIEW_TERMS):add(row,'governance_or_risk_content_requires_review')
    for term in ('重大事项','业绩预告','业绩快报','资产减值','重大合同','重大资产','更正','修订','会计政策变更',
                 '回购股份实施结果','权益分派实施','商标许可协议','业绩说明会'):
        eligible=[r for r in unique.values() if term in r.value['title']]
        if eligible:add(max(eligible,key=lambda r:(r.as_of,r.value['announcement_id'])),term)
    priority={'governance_or_risk_content_requires_review':0,'annual_report':1,'interim_report':1,'quarter_report':1}
    ordered=sorted(selected.values(),key=lambda r:(min(priority.get(x,2) for x in reasons[r.value['announcement_id']]),
                    -int(r.as_of[:10].replace('-','')),r.value['announcement_id']))
    return ordered[:limit],{'selected_reasons':reasons,'selected_documents':len(ordered[:limit]),
        'remaining_prioritized_documents':[{'announcement_id':r.value['announcement_id'],'title':r.value['title'],
            'publication_date':r.as_of,'document_url':r.value['document_url']} for r in ordered[limit:]],
        'all_material_contents_reviewed':False,'scope':'bounded title triage for original-content research, not risk/catalyst confirmation'}
