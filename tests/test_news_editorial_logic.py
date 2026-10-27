"""Regression cases from the second news review; no live feeds or models required."""
import sys,json,tempfile,pathlib,datetime as dt,unittest
from email.utils import format_datetime
from unittest.mock import patch
from urllib.parse import unquote
import yaml
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis import focus_today as ft
from src.pages import home

class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.cfg=yaml.safe_load((ROOT/'config/focus.yaml').read_text(encoding='utf-8'))
        self.specs=ft.topic_specs(self.cfg)
        for s in self.specs:s['search']=[]
        self.by={s['id']:s for s in self.specs}
        self.now=dt.datetime.now(dt.timezone.utc)
    def story(self,title,summary='',age=1,key='a'):
        return {'title':title,'summary':summary,'source':'Reuters',
                'link':'https://example.com/'+key,'at':(self.now-dt.timedelta(hours=age)).isoformat()}
    def gather(self,tid,stories,main=(),fetch=None):
        return ft.gather_topic_material([self.by[tid]],stories,main_titles=main,
            global_exclude=self.cfg['exclude_keywords'],now=self.now,
            _fetch=fetch or (lambda *a,**k:[]),_body=lambda u:'')

    def test_foreign_bond_lead_stays_out(self):
        self.assertNotIn('long',self.gather('long',[self.story('India bond yields fall','US Treasury yields also rose.')]))

    def test_foreign_market_lead_is_not_us_equity(self):
        self.assertNotIn('equity',self.gather('equity',[self.story('日股在AI與半導體股帶動下收高')]))
    def test_india_rate_decision_does_not_become_fed_news(self):
        self.assertNotIn('fed',self.gather('fed',[self.story('India central bank signals rate cuts as inflation falls','Officials compared their decision with the Fed.')]))

    def test_other_country_rate_cut_without_fed_is_rejected(self):
        self.assertNotIn('fed',self.gather('fed',[self.story('Pakistan central bank signals rate cuts')]))
    def test_rupee_lead_not_rescued_by_dxy_summary(self):
        self.assertNotIn('fx',self.gather('fx',[self.story('Indian rupee rises against dollar','The DXY dollar index moved lower.')]))
    def test_etf_exclusion_stays_strict_for_taiwan(self):
        self.assertNotIn('twf',self.gather('twf',[self.story('台指期反彈','本篇介紹ETF配息及申購。')]))








    def test_old_news_is_not_generated(self):
        mat=self.gather('gold',[self.story('Gold prices rise',age=50)])
        with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('','unavailable')):
            result=ft.build_topics(self.cfg,[],'',[],{},now=self.now)
        self.assertEqual(result['items'],[])



    def test_reference_dates_render_in_taiwan_time(self):
        html=home._focus_strip({'text':'新聞摘要','layout':'main','links':[{'title':'Fed report','link':'https://example.com','source':'Reuters','at':'2026-10-06T23:00:00+00:00'}]})
        self.assertIn('2026-10-07 報導',html)
        self.assertIn('參考報導',html)
        self.assertNotIn('主軸來源',html)

if __name__=='__main__':unittest.main()

