import unittest
import json,tempfile
from pathlib import Path
from market_core.ledger_review import evaluate_condition,review_ledger
from market_core.store import MarketStore
from market_core.workflow import prepare_research


class LedgerReviewTests(unittest.TestCase):
    def fixture(self,*,stamp='2026-10-02',eligible=True):
        return {'E-fixture':{'identity':'XLK','as_of':stamp,'eligible':eligible,
                'record':{'name':'return_5period','timestamp':stamp,'interval':'1d','input_provider':'yahoo_public_chart',
                          'price_basis':'provider_split_adjusted_close','unit':'ratio','currency':'USD','value':0.06}}}
    def rule(self):
        return {'kind':'indicator','identity':'XLK','metric':'return_5period','provider':'yahoo_public_chart',
                'interval':'1d','price_basis':'provider_split_adjusted_close','unit':'ratio','currency':'USD',
                'operator':'gt','threshold':0.05,'market_calendar':'US_CASH'}

    def test_daily_completion_time_is_after_cutoff_even_with_same_calendar_date(self):
        result=evaluate_condition(self.rule(),self.fixture(),baseline_cutoff='2026-10-02T13:00:00+00:00')
        self.assertIs(result['result'],True)
        self.assertEqual(result['observation_complete_at'],'2026-10-02T16:00:00-04:00')

    def test_old_observation_is_not_new_confirmation(self):
        result=evaluate_condition(self.rule(),self.fixture(),baseline_cutoff='2026-10-05T12:00:00+00:00')
        self.assertIsNone(result['result'])
        self.assertEqual(result['reason'],'no_post_baseline_observation')

    def test_ineligible_or_currency_mismatched_fact_cannot_confirm(self):
        self.assertIsNone(evaluate_condition(self.rule(),self.fixture(eligible=False),baseline_cutoff='2026-09-01T00:00:00+00:00')['result'])
        rule=self.rule();rule['currency']='CNY'
        self.assertIsNone(evaluate_condition(rule,self.fixture(),baseline_cutoff='2026-09-01T00:00:00+00:00')['result'])

    def test_empty_and_manual_conditions_are_unknown_not_true(self):
        self.assertIsNone(evaluate_condition({'all_of':[]},{},baseline_cutoff='2026-09-01')['result'])
        self.assertIsNone(evaluate_condition('profit outlook improves',{},baseline_cutoff='2026-09-01')['result'])

    def test_unknown_child_does_not_become_false_in_all_condition(self):
        condition={'all_of':[self.rule(),{'kind':'primary_event'}]}
        self.assertIsNone(evaluate_condition(condition,self.fixture(),baseline_cutoff='2026-09-01T00:00:00+00:00')['result'])

    def test_invalidated_view_is_not_reclassified_as_expired(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=MarketStore(root/'fixture.sqlite3');run=root/'run'
            prepare_research(store,run,profile='allocation')
            original={'thesis_id':'fixture','created_at':'2026-06-01T10:00:00+00:00','cutoff':'2026-06-01T09:00:00+00:00',
                      'thesis':'fixture original','horizon':{'review_deadline':'2026-09-30T23:59:59+00:00'},
                      'confirmation':'manual evidence','invalidation':'manual counterevidence','status':'active'}
            prior={**original,'created_at':'2026-09-15T10:00:00+00:00','status':'invalidated'}
            ledger=root/'ledger.jsonl';ledger.write_text(json.dumps(original)+'\n'+json.dumps(prior)+'\n',encoding='utf-8')
            result=review_ledger(ledger,run)
            self.assertEqual(result['reviews'][0]['status'],'invalidated')


if __name__=='__main__':unittest.main(verbosity=2)
