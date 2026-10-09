import datetime as dt,pathlib,sys,unittest,json
from unittest.mock import patch
import yaml
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from src.analysis import focus_today as ft,news_policy as np

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
    def test_funding_finds_market_stress_coverage(self):
        rows=[self.story('Fed minutes show some officials want to prepare for market stress')]
        self.assertIn('funding',self.material('funding',rows))
    def test_funding_money_markets_and_treasury_bills(self):
        for title in ['US money markets face funding pressure','Fed prepares for dollar liquidity stress',
                      'US Treasury bills draw money market funds','SOFR rises as repo rates increase']:
            with self.subTest(title=title):self.assertIn('funding',self.material('funding',[self.story(title)]))
    def test_funding_rejects_foreign_repo_and_company_fundraising(self):
        for title in ['Hedge funds warn Bank of England repo reforms could backfire',
                      'India bank reserves rise after RBI policy decision',
                      'Rupee falls against US dollar after RBI repo rate hike','Startup completes new funding round']:
            with self.subTest(title=title):self.assertNotIn('funding',self.material('funding',[self.story(title)]))
    def test_listing_page_is_not_a_news_report(self):
        for title in ['Stocks - Bloomberg','Markets','U.S. T-Bill Futures - Settlements - CME Group']:
            with self.subTest(title=title):self.assertFalse(np.news_item_allowed(self.story(title)))
    def test_stock_market_topic_is_not_wall_street_employment(self):
        title='AI Crowds Out Fresh Grads at Wall Street Tech Hubs in India'
        self.assertNotIn('equity',self.material('equity',[self.story(title)]))
    def test_stock_market_keeps_real_us_index_coverage(self):
        for title in ['S&P 500 falls as Treasury yields rise','Wall Street ends lower as rates rise',
                      'US stocks rise while Japan stocks decline','美股四大指數收黑，道瓊回落']:
            with self.subTest(title=title):self.assertIn('equity',self.material('equity',[self.story(title)]))
    def test_taiwan_futures_day_night_and_stock_context(self):
        for title in ['台指期日盤收低，外資減碼','台指期夜盤下跌，台股高檔震盪','加權指數回落，外資賣超台股']:
            with self.subTest(title=title):self.assertIn('twf',self.material('twf',[self.story(title)]))
    def test_taiwan_futures_still_excludes_etf_in_body(self):
        mat=self.material('twf',[self.story('台指期夜盤下跌')],body=lambda u:'台指期行情與ETF配息申購策略')
        self.assertNotIn('twf',mat)
    def test_election_keeps_us_race_poll_and_campaign(self):
        for title in ['Trump faces Senate race as US midterms approach','Republicans seek House majority in election',
                      '美國期中選舉民調：民主黨力拚參議院','Conservative group seeks approval for AI robocalls ahead of US midterms']:
            with self.subTest(title=title):self.assertIn('election',self.material('election',[self.story(title)]))
    def test_election_excludes_foreign_races_and_non_election_laws(self):
        for title in ['Japan Senate election polls shift','India elections draw US attention','US Congress passes spending bill']:
            with self.subTest(title=title):self.assertNotIn('election',self.material('election',[self.story(title)]))
    def test_us_dollar_prices_are_not_fx_coverage(self):
        for title in ['International graduate faces $70000 visa fee','從500美元跳7萬美元，留美工作門檻升高']:
            with self.subTest(title=title):self.assertNotIn('fx',self.material('fx',[self.story(title)]))
    def test_real_twd_and_dollar_index_coverage_survives(self):
        for title in ['New Taiwan dollar strengthens against US dollar','DXY rises ahead of Fed decision',
                      '美元走強，新台幣貶破31.8元']:
            with self.subTest(title=title):self.assertIn('fx',self.material('fx',[self.story(title)]))
    def test_public_rss_is_available_to_all_ten_topics(self):
        titles={'fed':'Fed officials discuss inflation','long':'US Treasury yields rise after auction',
                'funding':'SOFR rises as US repo market tightens','oil':'Oil prices rise as Iran threatens oil supply',
                'equity':'Wall Street stocks fall as Nasdaq declines','semi':'NVIDIA expands semiconductor output',
                'twf':'台指期夜盤下跌，外資減碼台股','election':'US midterm election polls shift Senate race',
                'gold':'Gold prices decline','fx':'New Taiwan dollar falls against US dollar'}
        public=[self.story(title,summary='報導說明市場最新變化，並整理事件背景與來源已交代的重要細節，供讀者了解相關市場動態。',
                           link='https://example.com/'+tid) for tid,title in titles.items()]
        calls=[]
        def fetch(feeds,*a,**kw):calls.append((feeds,kw));return public
        specs=[{**s,'search':[]} for s in ft.topic_specs(self.cfg)]
        mat=ft.gather_topic_material(specs,[],now=self.now,_fetch=fetch,_body=lambda u:'')
        self.assertEqual(set(mat),set(titles))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]['hours'],24)
    def test_model_omission_skip_and_failure_do_not_hide_four_topics(self):
        titles={'funding':'Fed prepares for market stress','equity':'Wall Street stocks fall',
                'twf':'台指期夜盤下跌，外資減碼台股','election':'US midterm election polls shift Senate race'}
        specs=[self.spec(t) for t in titles]
        rows=[self.story(title,summary='報導說明最新事件與市場背景，並提供來源已交代的重要細節，讓讀者了解本次變化。',
                         link='https://example.com/'+t) for t,title in titles.items()]
        mat=ft.gather_topic_material(specs,rows,now=self.now,_fetch=lambda *a,**k:[],_body=lambda u:'')
        with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('funding｜略\nequity｜略\ntwf｜略\nelection｜略','')):
            result=ft.build_topics(self.cfg,rows,'',[],{},now=self.now)
        self.assertEqual({i['id'] for i in result['items']},set(titles))
        self.assertTrue(all(len(i['text'])>20 for i in result['items']))
    def test_true_same_event_is_filtered_before_ai(self):
        story=self.story('US midterm election polls shift Senate race')
        mat=ft.gather_topic_material([self.spec('election')],[story],main_titles=[story['title']],now=self.now,
              _fetch=lambda *a,**k:[],_body=lambda u:'')
        self.assertEqual(mat,{})
    def test_new_sources_cannot_supply_stale_news(self):
        story=self.story('Fed prepares for money market stress',age=25)
        mat=ft.gather_topic_material([self.spec('funding')],[],now=self.now,_fetch=lambda *a,**k:[story],_body=lambda u:'')
        self.assertEqual(mat,{})
    def test_config_and_default_searches_both_cover_missing_topics(self):
        for cfg in [self.cfg,{}]:
            topics={t['id']:t for t in ft.topic_specs(cfg)}
            for tid in ['funding','equity','twf','election']:
                self.assertGreaterEqual(len(topics[tid]['search']),2)
            self.assertIn('market stress',topics['funding']['keywords'])
    def test_topic_search_uses_alternative_keywords_instead_of_requiring_every_term(self):
        for cfg in [self.cfg,{}]:
            topics={t['id']:t for t in ft.topic_specs(cfg)}
            for tid in ['funding','equity','twf','election']:
                self.assertTrue(any(' OR ' in q['q'] for q in topics[tid]['search']))
    def test_taiwan_company_names_are_english(self):
        self.assertEqual(np.english_names('緯創、緯穎、廣達、鴻海'), 'Wistron、Wiwynn、Quanta、Foxconn')

    def test_fx_rejects_cash_conversion_in_foreign_war_news(self):
        h=self.story('伊朗祕密撥款2億美元，助真主黨救濟黎巴嫩難民',
                     summary='援助款約2億美元，換算新台幣約63億元，協助難民安置。')
        self.assertNotIn('fx',self.material('fx',[h]))
    def test_fx_keeps_publisher_lead_with_actual_exchange_rate_subject(self):
        h=self.story('央行說明外資最新動向',summary='外資匯出讓台幣貶值，美元兌新台幣匯率走高。')
        self.assertIn('fx',self.material('fx',[h]))
    def test_taiwan_futures_keeps_company_dividend_market_effect(self):
        h=self.story('台指期受TSMC股息影響下跌，市場留意夜盤')
        self.assertIn('twf',self.material('twf',[h]))
    def test_gold_rejects_local_daily_quotes_but_keeps_global_bullion_report(self):
        local=self.story('India Gold price today: Gold rises, according to FXStreet data')
        self.assertFalse(np.news_item_allowed(local))
        self.assertNotIn('gold',self.material('gold',[local]))
        global_report=self.story('Gold remains below $4150 as hawkish Fed and firm USD cap gains')
        self.assertIn('gold',self.material('gold',[global_report]))
    def test_gold_and_oil_searches_include_local_readable_sources(self):
        for cfg in [self.cfg,{}]:
            topics={t['id']:t for t in ft.topic_specs(cfg)}
            for tid in ['gold','oil']:
                self.assertTrue(any(q['lang']=='zh' for q in topics[tid]['search']))
    def test_article_reader_excludes_navigation_recommendations_ads_and_captions(self):
        report='這是市場報導的真正內文，包含本期事件背景與市場變化，不能混入網站導覽或廣告。'
        page=('<nav><p>導覽訊息與其他市場消息都不屬於本篇真正報導的內文。</p></nav>'
              '<article><p>市場相關照片（記者王小明攝），照片來源說明不應當作報導。</p>'
              '<p>'+report+'</p><div class="related"><p>推薦文章中的市場數據與事件不應混進當篇報導內容。</p></div>'
              '<div class="ad-container"><p>金融廣告優惠活動，開戶享有特別費率，請立即申請。</p></div></article>'
              '<footer><p>網站訂閱與版權公告，這段不能用來摘要當篇新聞內容。</p></footer>')
        self.assertEqual(ft._article_paragraphs(page),[report])
    def test_rss_uses_actual_instants_for_sorting_and_duplicate_dates(self):
        from email.utils import format_datetime
        newer=self.now-dt.timedelta(hours=1)
        older=(self.now-dt.timedelta(hours=2)).astimezone(dt.timezone(dt.timedelta(hours=8)))
        data=[('Gold rises',newer),('Gold falls',older),('Gold rises',older)]
        xml='<rss><channel>'+''.join('<item><title>'+t+'</title><link>https://example.com/a</link><pubDate>'+format_datetime(d)+'</pubDate><source>Reuters</source></item>' for t,d in data)+'</channel></rss>'
        class Response:
            content=xml.encode()
            def raise_for_status(self):pass
        for rows in [ft.fetch_headlines(['gold'],_get=lambda u:Response()),
                     ft.fetch_feed_headlines([{'url':'https://example.com/rss','all':True}],[],_get=lambda u:Response())]:
            self.assertEqual([h['title'] for h in rows],['Gold rises','Gold falls'])
            self.assertEqual(dt.datetime.fromisoformat(rows[0]['at']).replace(microsecond=0),newer.replace(microsecond=0))
    def test_main_uses_readable_public_article_content_before_headlines(self):
        import tempfile
        story=self.story('Fed officials discuss inflation',summary='聯準會官員說明通膨及利率政策。')
        body='聯準會官員說明通膨及利率政策，報導整理會議討論與市場動態。'*8
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ft,'fetch_feed_headlines',return_value=[story]) as feeds, \
             patch.object(ft,'fetch_article_text',return_value=body), \
             patch.object(ft,'fedwatch_path',return_value=None), \
             patch.object(ft,'fetch_atlanta_fedwatch',return_value=None), \
             patch.object(ft,'build_catalog',return_value=[]), \
             patch.object(ft,'build_topics',return_value={'items':[],'map':{}}), \
             patch.object(ft,'summarize_content',return_value=('主軸摘要','model-content')) as content, \
             patch.object(ft,'summarize') as headline:
            result=ft.build({},False,{'enabled':True,'keywords':['Fed'],'feeds':['https://example.com/rss']},
                            pathlib.Path(tmp)/'focus.json',env={})
        self.assertEqual(result['text_source'],'model-content')
        self.assertEqual(content.call_args.args[0][0]['body'],body)
        headline.assert_not_called()
        self.assertTrue(set(ft.PUBLIC_NEWS_FEEDS).issubset({x if isinstance(x,str) else x["url"] for x in feeds.call_args_list[0].args[0]}))

    def test_foreign_fx_headline_does_not_become_main_by_mentioning_dollar_and_oil(self):
        h=self.story('British Pound slips due to stable US Dollar, rising oil prices')
        self.assertFalse(np.main_allowed(h))
        self.assertTrue(np.main_allowed(self.story('Japanese yen rises as US Dollar retreats')))
    def test_foreign_currency_report_does_not_become_treasury_news(self):
        h=self.story('British Pound slips due to stable US Dollar, rising oil prices',
                     summary='US Treasury yields rose while the British Pound weakened.')
        self.assertNotIn('long',self.material('long',[h]))
    def test_foreign_currency_report_does_not_become_oil_news(self):
        h=self.story('Canadian Dollar weakens despite higher oil prices',summary='Oil prices rose as shipping was disrupted.')
        self.assertNotIn('oil',self.material('oil',[h]))
        h=self.story('Oil prices rise as US Dollar retreats')
        self.assertIn('oil',self.material('oil',[h]))
    def test_tokenised_fund_product_launch_is_not_us_funding_conditions(self):
        h=self.story('DigiFT launches tokenised access to US Treasury money market fund')
        self.assertNotIn('funding',self.material('funding',[h]))

if __name__=='__main__':unittest.main()
