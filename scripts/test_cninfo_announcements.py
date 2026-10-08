import unittest,tempfile,json
from pathlib import Path
from datetime import datetime,timezone
from market_core.providers.cninfo_announcements import CninfoAnnouncementsProvider

class Client:
    archive=None;last_response_receipt=None
    def __init__(self,pages):self.pages=pages;self.calls=[]
    def get_text(self,url):return 'var stockCode="600519";var orgId="gssh0600519";',url
    def post_form_json(self,url,form,**kwargs):self.calls.append(form);return self.pages[int(form['pageNum'])-1],url
    def source_receipts(self):return []
    def bind_rows(self,rows,receipts=None):return rows

def row(aid):
    return {'secCode':'600519','secName':'贵州茅台','orgId':'gssh0600519','announcementId':str(aid),
        'announcementTime':int(datetime(2026,8,14,16,tzinfo=timezone.utc).timestamp()*1000),
        'announcementTitle':'测试公告','adjunctUrl':f'finalpage/2026-08-15/{aid}.PDF'}

class CninfoTests(unittest.TestCase):
    def run_catalogue(self,pages,max_pages=10):
        c=Client(pages)
        with tempfile.TemporaryDirectory() as tmp:
            rows,audit=CninfoAnnouncementsProvider(tmp,c).fetch_catalogue('sh600519',start_date='2026-01-01',end_date='2026-10-06',max_pages=max_pages)
        return rows,audit,c
    def test_complete_pages_keep_date_precision_and_do_not_verify_headline_effect(self):
        pages=[{'totalAnnouncement':32,'announcements':[row(i) for i in range(30)]},
               {'totalAnnouncement':32,'announcements':[row(i) for i in (30,31)]}]
        rows,audit,c=self.run_catalogue(pages)
        self.assertEqual(len(rows),32);self.assertEqual(audit.value['status'],'complete_catalogue_window')
        self.assertEqual(rows[0].publication,'2026-08-15');self.assertFalse(rows[0].value['economic_effect_verified'])
        self.assertFalse(rows[0].value['original_publication_time_known']);self.assertEqual(c.calls[1]['pageNum'],'2')
    def test_wrong_issuer_or_missing_page_is_partial_without_bad_rows(self):
        bad=row(30);bad['secCode']='000858'
        pages=[{'totalAnnouncement':31,'announcements':[row(i) for i in range(30)]},{'totalAnnouncement':31,'announcements':[bad]}]
        rows,audit,c=self.run_catalogue(pages)
        self.assertEqual(len(rows),30);self.assertEqual(audit.value['status'],'partial_catalogue_window')
        self.assertIn('Cross-issuer',audit.value['error'])
        rows,audit,c=self.run_catalogue([pages[0]],max_pages=1)
        self.assertEqual(audit.value['status'],'partial_catalogue_window');self.assertEqual(audit.value['received_pages'],1)
    def test_duplicate_ids_and_offsite_documents_cannot_pass_catalogue_scope(self):
        pages=[{'totalAnnouncement':2,'announcements':[row(1),row(1)]}]
        rows,audit,_=self.run_catalogue(pages);self.assertEqual(rows,[]);self.assertIn('duplicate',audit.value['error'])
        bad=row(1);bad['adjunctUrl']='https://unregistered.test/1.PDF'
        rows,audit,_=self.run_catalogue([{'totalAnnouncement':1,'announcements':[bad]}]);self.assertEqual(rows,[])
        self.assertIn('Unregistered',audit.value['error'])

if __name__=='__main__':unittest.main()
