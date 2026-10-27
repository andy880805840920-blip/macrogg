import datetime as dt,pathlib,sys,unittest,json
from unittest.mock import patch
import yaml
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from src.analysis import focus_today as ft

class AllNewsTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime.now(dt.timezone.utc)
        self.cfg=yaml.safe_load((pathlib.Path(__file__).resolve().parents[1]/'config/focus.yaml').read_text(encoding='utf-8'))
    def story(self,title,summary='',age=1,link='https://example.com/report'):
        return {'title':title,'summary':summary,'source':'Reuters','link':link,
                'at':(self.now-dt.timedelta(hours=age)).isoformat()}
    def spec(self,tid):
        s=next(x for x in ft.topic_specs(self.cfg) if x['id']==tid)
        return {**s,'search':[]}
    def material(self,tid,rows,body=lambda u:''):
        return ft.gather_topic_material([self.spec(tid)],rows,now=self.now,_fetch=lambda *a,**k:[],_body=body)
    def test_funding_rejects_foreign_repo_and_company_fundraising(self):
        for title in ['Hedge funds warn Bank of England repo reforms could backfire',
                      'India bank reserves rise after RBI policy decision',
                      'Rupee falls against US dollar after RBI repo rate hike','Startup completes new funding round']:
            with self.subTest(title=title):self.assertNotIn('funding',self.material('funding',[self.story(title)]))
    def test_stock_market_topic_is_not_wall_street_employment(self):
        title='AI Crowds Out Fresh Grads at Wall Street Tech Hubs in India'
        self.assertNotIn('equity',self.material('equity',[self.story(title)]))
    def test_election_excludes_foreign_races_and_non_election_laws(self):
        for title in ['Japan Senate election polls shift','India elections draw US attention','US Congress passes spending bill']:
            with self.subTest(title=title):self.assertNotIn('election',self.material('election',[self.story(title)]))
    def test_us_dollar_prices_are_not_fx_coverage(self):
        for title in ['International graduate faces $70000 visa fee','從500美元跳7萬美元，留美工作門檻升高']:
            with self.subTest(title=title):self.assertNotIn('fx',self.material('fx',[self.story(title)]))
    def test_true_same_event_is_filtered_before_ai(self):
        story=self.story('US midterm election polls shift Senate race')
        mat=ft.gather_topic_material([self.spec('election')],[story],main_titles=[story['title']],now=self.now,
              _fetch=lambda *a,**k:[],_body=lambda u:'')
        self.assertEqual(mat,{})
    def test_new_sources_cannot_supply_stale_news(self):
        story=self.story('Fed prepares for money market stress',age=25)
        mat=ft.gather_topic_material([self.spec('funding')],[],now=self.now,_fetch=lambda *a,**k:[story],_body=lambda u:'')
        self.assertEqual(mat,{})
    def test_topic_search_uses_alternative_keywords_instead_of_requiring_every_term(self):
        for cfg in [self.cfg,{}]:
            topics={t['id']:t for t in ft.topic_specs(cfg)}
            for tid in ['funding','equity','twf','election']:
                self.assertTrue(any(' OR ' in q['q'] for q in topics[tid]['search']))

    def test_fx_rejects_cash_conversion_in_foreign_war_news(self):
        h=self.story('伊朗祕密撥款2億美元，助真主黨救濟黎巴嫩難民',
                     summary='援助款約2億美元，換算新台幣約63億元，協助難民安置。')
        self.assertNotIn('fx',self.material('fx',[h]))
    def test_gold_and_oil_searches_include_local_readable_sources(self):
        for cfg in [self.cfg,{}]:
            topics={t['id']:t for t in ft.topic_specs(cfg)}
            for tid in ['gold','oil']:
                self.assertTrue(any(q['lang']=='zh' for q in topics[tid]['search']))

    def test_foreign_currency_report_does_not_become_treasury_news(self):
        h=self.story('British Pound slips due to stable US Dollar, rising oil prices',
                     summary='US Treasury yields rose while the British Pound weakened.')
        self.assertNotIn('long',self.material('long',[h]))
    def test_tokenised_fund_product_launch_is_not_us_funding_conditions(self):
        h=self.story('DigiFT launches tokenised access to US Treasury money market fund')
        self.assertNotIn('funding',self.material('funding',[h]))

if __name__=='__main__':unittest.main()
