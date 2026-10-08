import unittest
from types import SimpleNamespace
from market_core.announcement_selection import select_material_documents


def row(key,title,day):
    return SimpleNamespace(as_of=day,value={'announcement_id':key,'title':title,'document_url':'https://example.test/'+key+'.pdf'})


class AnnouncementSelectionTests(unittest.TestCase):
    def test_full_report_financials_and_older_governance_are_not_replaced_by_summaries(self):
        rows=[row('1','公司2025年年度报告','2026-04-17'),row('2','公司2025年年度报告摘要','2026-04-18'),
              row('3','公司2026年半年度报告','2026-08-31'),row('4','公司2026年第一季度报告','2026-04-22'),
              row('5','关于高级管理人员被留置的公告','2026-03-03'),row('6','解除留置的进展公告','2026-07-01'),
              row('7','重大事项公告','2026-07-18')]
        selected,meta=select_material_documents(rows)
        self.assertEqual({r.value['announcement_id'] for r in selected},{'1','3','4','5','6','7'})
        self.assertFalse(meta['all_material_contents_reviewed'])

    def test_bounded_selection_retains_remaining_document_work_instead_of_claiming_complete(self):
        rows=[row(str(i),'重大诉讼进展公告','2026-09-30') for i in range(20)]
        selected,meta=select_material_documents(rows,limit=4)
        self.assertEqual(len(selected),4);self.assertEqual(len(meta['remaining_prioritized_documents']),16)

    def test_latest_full_correction_is_not_a_new_profit_forecast(self):
        rows=[row('1','2025年年度报告','2026-04-01'),row('2','2025年年度报告（修订版）','2026-05-01'),
              row('3','关于2025年年度报告的更正公告','2026-05-01')]
        selected,meta=select_material_documents(rows)
        self.assertIn('2',{r.value['announcement_id'] for r in selected})
        self.assertIn('3',{r.value['announcement_id'] for r in selected})
        self.assertEqual(meta['scope'],'bounded title triage for original-content research, not risk/catalyst confirmation')
