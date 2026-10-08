"""Regression cases from the second news review; no live feeds or models required."""
import sys,json,tempfile,pathlib,datetime as dt,unittest
from email.utils import format_datetime
from unittest.mock import patch
from urllib.parse import unquote
import yaml
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis import focus_today as ft,news_policy as np,news_checks as checks
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

    def test_bond_summary_supplies_us_context(self):
        self.assertIn('long',self.gather('long',[self.story('Bond yields rise after auction','US Treasury yields rose after weak demand at a Treasury auction.')]))
    def test_fx_summary_supplies_twd_usd_context(self):
        self.assertIn('fx',self.gather('fx',[self.story('匯市交投清淡，出口商增加拋匯','台幣兌美元升值，出口商增加美元賣單。')]))
    def test_foreign_bond_lead_stays_out(self):
        self.assertNotIn('long',self.gather('long',[self.story('India bond yields fall','US Treasury yields also rose.')]))
    def test_foreign_investors_in_us_bonds_are_not_local_foreign_bonds(self):
        self.assertIn('long',self.gather('long',[self.story('Japanese investors buy US Treasury bonds')]))
        self.assertTrue(np.main_allowed({'title':'Japanese investors buy US Treasury bonds'}))
        self.assertNotIn('long',self.gather('long',[self.story('Indian bond yields fall','US Treasury yields also rose.')]))

    def test_taiwan_mention_does_not_hide_semiconductor_news(self):
        self.assertIn('semi',self.gather('semi',[self.story('台股收高，TSMC宣布擴大AI晶片產能')]))
    def test_foreign_market_lead_is_not_us_equity(self):
        self.assertNotIn('equity',self.gather('equity',[self.story('日股在AI與半導體股帶動下收高')]))
    def test_us_equity_can_discuss_foreign_context(self):
        self.assertIn('equity',self.gather('equity',[self.story('Wall Street stocks rise while Japan stocks fall')]))
    def test_india_rate_decision_does_not_become_fed_news(self):
        self.assertNotIn('fed',self.gather('fed',[self.story('India central bank signals rate cuts as inflation falls','Officials compared their decision with the Fed.')]))
    def test_plural_rate_hikes_and_official_speeches(self):
        self.assertIn('fed',self.gather('fed',[self.story('US interest rate hikes may continue')]))
        a=self.story('Speech by Governor Waller')
        a.update(link='https://www.federalreserve.gov/newsevents/speech/waller.htm',source='Federal Reserve')
        self.assertIn('fed',self.gather('fed',[a]))
        self.assertTrue(ft._phrase_hit('台指期','臺指期午盤上漲'))

    def test_other_country_rate_cut_without_fed_is_rejected(self):
        self.assertNotIn('fed',self.gather('fed',[self.story('Pakistan central bank signals rate cuts')]))
    def test_us_rate_outlook_is_allowed(self):
        self.assertIn('fed',self.gather('fed',[self.story('US interest rate cuts may slow as inflation persists')]))
    def test_rupee_lead_not_rescued_by_dxy_summary(self):
        self.assertNotIn('fx',self.gather('fx',[self.story('Indian rupee rises against dollar','The DXY dollar index moved lower.')]))
    def test_etf_exclusion_stays_strict_for_taiwan(self):
        self.assertNotIn('twf',self.gather('twf',[self.story('台指期反彈','本篇介紹ETF配息及申購。')]))

    def test_opposite_bond_moves_are_distinct(self):
        a='US Treasury yields rise after weak auction'
        b='US Treasury yields fall after strong auction'
        self.assertIn('long',self.gather('long',[self.story(b)],main=[a]))
    def test_different_fed_subjects_are_distinct(self):
        a='Fed officials see inflation easing and discuss rates'
        b='Fed officials see bank reserves easing and discuss rates'
        self.assertIn('fed',self.gather('fed',[self.story(b)],main=[a]))
    def test_different_numeric_values_are_not_deduplicated(self):
        a=self.story('US Treasury 10-year auction draws strong demand',key='x')
        b=self.story('US Treasury 30-year auction draws strong demand',key='y')
        self.assertFalse(checks.same_event(a,b))
    def test_known_duplicate_source_suffix_is_removed(self):
        self.assertTrue(checks.same_event('Fed holds rates - Reuters','Fed holds rates - Bloomberg'))
    def test_normal_hyphen_and_unknown_suffix_are_preserved(self):
        self.assertEqual(checks.clean_title('Gold rises after rate-cut signals'),'Gold rises after rate-cut signals')
        self.assertEqual(checks.clean_title('US Treasury 10-year auction'),'US Treasury 10-year auction')
        self.assertEqual(checks.clean_title('Gold rises - a new record'),'Gold rises - a new record')

    def test_numeric_substrings_cannot_pass(self):
        self.assertFalse(ft._digits_ok('通膨升至3%','通膨為8.3%，2026年。'))
        self.assertFalse(ft._digits_ok('通膨升至2%','2026年報告'))
    def test_equivalent_basis_points_and_percentage_points(self):
        self.assertTrue(ft._digits_ok('降息0.25個百分點','Fed rate cut 25 basis points'))
        self.assertTrue(ft._digits_ok('降息25bp','Fed rate cut 0.25 percentage points'))
        self.assertFalse(ft._digits_ok('降息0.5個百分點','Fed rate cut 25 basis points'))
    def test_decimal_formatting_and_thousands(self):
        self.assertTrue(ft._digits_ok('殖利率5.0%','Yield is 5%'))
        self.assertTrue(ft._digits_ok('新增120000人','120,000 people joined'))
    def test_clear_currency_and_people_conversions(self):
        self.assertTrue(ft._digits_ok('投資10億美元','Investment is $1 billion'))
        self.assertTrue(ft._digits_ok('新增7.1萬人','71,000 jobs added'))
        self.assertFalse(ft._digits_ok('投資10億元','Investment is $1 billion'))
    def test_shared_range_units_and_oil_inventory_conversions(self):
        self.assertTrue(ft._digits_ok('利率區間5.25%至5.5%','Rates are 5.25-5.50%'))
        self.assertTrue(ft._digits_ok('庫存318萬桶','Inventory changed by 3.18 million barrels'))
        self.assertTrue(ft._digits_ok('發債12億美元','Bond offering $1.2bn'))
        self.assertFalse(ft._digits_ok('庫存318萬人','Inventory changed by 3.18 million barrels'))

    def test_signed_values_are_not_equivalent_to_opposite_values(self):
        self.assertTrue(ft._digits_ok('變化-5bp','Change -5 bp'))
        self.assertFalse(ft._digits_ok('變化5bp','Change -5 bp'))
        self.assertTrue(ft._digits_ok('淨流量-10億美元','Net flow -$1bn'))
        self.assertFalse(ft._digits_ok('淨流量10億美元','Net flow -$1bn'))

    def test_normal_technical_and_policy_language_is_not_meta(self):
        self.assertFalse(ft._meta_hits('NVIDIA推出新模型，可用關鍵字搜尋影片。',self.cfg['meta_markers']))
        self.assertFalse(ft._meta_hits('Fed表示目前數據不足以支持降息。',self.cfg['meta_markers']))
        self.assertTrue(ft._meta_hits('提供的材料不足以生成新聞摘要。',self.cfg['meta_markers']))

    def test_old_news_is_never_used_even_when_recent_news_missing(self):
        old=self.story('Gold prices rise',age=50,key='old')
        new=self.story('Gold prices fall',age=2,key='new')
        mat=self.gather('gold',[old,new])
        self.assertEqual([x['link'] for x in mat['gold']['links']],['https://example.com/new'])
        mat=self.gather('gold',[old])
        self.assertNotIn('gold',mat)
        self.assertNotIn('gold',self.gather('gold',[self.story('Gold prices rise',age=80)]))
    def test_search_window_is_capped_at_one_day(self):
        url=unquote(ft._topic_url({'q':'gold prices','lang':'en'},72))
        self.assertIn('when:1d',url)
        self.assertNotIn('when:3d',url)
        self.assertNotIn('when:2d',url)
    def test_identical_headline_keeps_latest_report_not_first_feed(self):
        old=self.story('Gold prices rise',age=50,key='old')
        new=self.story('Gold prices rise',age=1,key='new')
        mat=self.gather('gold',[old,new])
        self.assertEqual(mat['gold']['links'][0]['link'],new['link'])
        self.assertFalse(mat['gold']['older'])

    def test_google_fallback_preserves_public_summary(self):
        stamp=format_datetime(self.now)
        rss=f'<rss><channel><item><title>Fed holds rates - Reuters</title><link>https://example.com</link><source>Reuters</source><pubDate>{stamp}</pubDate><description>The Federal Reserve held rates and discussed the inflation outlook.</description></item></channel></rss>'
        class Response:
            content=rss.encode()
            def raise_for_status(self):pass
        rows=ft.fetch_headlines(['Fed'],_get=lambda u:Response())
        self.assertIn('inflation outlook',rows[0]['summary'])

    def test_source_preference_is_not_exclusive(self):
        self.by['gold']['search']=[{'q':'gold prices (site:reuters.com OR site:bloomberg.com)','lang':'en'}]
        calls=[]
        def fetch(feeds,*a,**k):
            url=unquote(feeds[0]['url']);calls.append(url)
            return [] if 'site:' in url else [self.story('Gold prices rise - Financial Times')]
        mat=self.gather('gold',[],fetch=fetch)
        self.assertIn('gold',mat)
        self.assertEqual(len(calls),2)

    def test_topic_summary_update_invalidates_cache(self):
        mat=self.gather('gold',[self.story('Gold prices rise')])
        st={};text='黃金價格上漲，市場避險需求推升金價，報導指出美元與利率走勢仍是投資人評估黃金表現的重要因素。'
        with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('gold｜'+text,'')) as ai:
            ft.build_topics(self.cfg,[],'',[],st,now=self.now)
            ft.build_topics(self.cfg,[],'',[],st,now=self.now)
            self.assertEqual(ai.call_count,1)
            mat['gold']['briefs'][0]['summary']='Gold rose on renewed demand.'
            ft.build_topics(self.cfg,[],'',[],st,now=self.now)
            self.assertEqual(ai.call_count,2)
    def test_topic_body_update_invalidates_cache(self):
        mat=self.gather('gold',[self.story('Gold prices rise')])
        mat['gold']['arts']=[{'title':'Gold prices rise','body':'first report','source':'Reuters','link':'https://example.com/a'}]
        st={}
        with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('gold｜黃金價格上漲。','')) as ai:
            ft.build_topics(self.cfg,[],'',[],st,now=self.now)
            before=ai.call_count
            mat['gold']['arts'][0]['body']='updated report'
            ft.build_topics(self.cfg,[],'',[],st,now=self.now)
            self.assertGreater(ai.call_count,before)
    def test_old_news_is_not_generated(self):
        mat=self.gather('gold',[self.story('Gold prices rise',age=50)])
        with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('','unavailable')):
            result=ft.build_topics(self.cfg,[],'',[],{},now=self.now)
        self.assertEqual(result['items'],[])

    def test_sources_metadata_is_hidden_and_only_valid_ids_retained(self):
        provenance={}
        replies='【主軸】\nFed宣布維持利率。\n【補充】\n【主軸來源】a1,a999'
        with patch.object(ft,'_call_ai',return_value=(replies,'')):
            text,src=ft.summarize([self.story('Fed holds rates'),self.story('Gold prices rise',key='b')],
                caps=[250],mins=[0],provenance=provenance)
        self.assertEqual(provenance['main_ids'],['a1'])
        self.assertNotIn('主軸來源',text)
        self.assertNotIn('a999',text)
    def test_unavailable_citation_keeps_reference_material_without_faking_usage(self):
        provenance={}
        with patch.object(ft,'_call_ai',return_value=('Fed宣布維持利率。','')):
            ft.summarize([self.story('Fed holds rates')],caps=[250],mins=[0],provenance=provenance)
        self.assertEqual(provenance['main_ids'],[])
        self.assertEqual(len(provenance['sources']),1)

    def test_main_body_updates_and_unused_candidates_do_not_exclude_topics(self):
        story=self.story('Fed holds rates');body={'text':'聯準會表示通膨風險仍在。'*10}
        cfg={**self.cfg,'main_min':0,'supp_items':0}
        def feed(*args,**kwargs):
            if kwargs.get('raw_out') is not None:kwargs['raw_out'].append(story)
            return [story]
        def ai(*args,**kwargs):return '【主軸】\nFed宣布維持利率。\n【補充】',''
        with tempfile.TemporaryDirectory() as tmp,patch.multiple(ft,
            fetch_feed_headlines=feed,fetch_article_text=lambda u:body['text'],
            fedwatch_path=lambda *a,**k:None,fetch_atlanta_fedwatch=lambda *a,**k:None,
            build_catalog=lambda *a,**k:[]),patch.object(ft,'_call_ai',side_effect=ai) as model,\
            patch.object(ft,'build_topics',return_value={'items':[],'map':{}}) as topics:
            path=pathlib.Path(tmp)/'focus.json'
            first=ft.build({},False,cfg,path,env={})
            self.assertEqual(topics.call_args.args[3],[])
            self.assertEqual(len(first['links']),1)
            count=model.call_count
            second=ft.build({},False,cfg,path,env={})
            self.assertEqual(second['text_source'],'cache')
            self.assertEqual(model.call_count,count)
            body['text']='聯準會表示就業與通膨需要持續觀察。'*10
            third=ft.build({},False,cfg,path,env={})
            self.assertNotEqual(third['text_source'],'cache')
            self.assertGreater(model.call_count,count)

    def test_reference_dates_render_in_taiwan_time(self):
        html=home._focus_strip({'text':'新聞摘要','layout':'main','links':[{'title':'Fed report','link':'https://example.com','source':'Reuters','at':'2026-10-06T23:00:00+00:00'}]})
        self.assertIn('2026-10-07 報導',html)
        self.assertIn('參考報導',html)
        self.assertNotIn('主軸來源',html)

if __name__=='__main__':unittest.main()

