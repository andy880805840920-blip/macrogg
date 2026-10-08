import datetime as dt,json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from src.analysis import focus_today as ft

class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime.now(dt.timezone.utc)
        self.specs=[s for s in ft.topic_specs({}) if s['id'] in ('gold','fx')]
        self.gold='黃金價格回落，報導指出美元走強影響金價表現，市場同時關注各國央行持續購金與黃金交易市場的發展。'
        self.fx='美元走強，新台幣貶破31.8元，報導指出聯準會升息循環尚未結束，台幣交易仍受到美元走勢影響。'
    def story(self,tid,direct=False,age=1):
        title={'gold':'Gold prices fall','fx':'美元走強 新台幣貶破31.8元'}[tid]
        return {'title':title,'source':'Reuters' if not direct else '自由財經',
            'summary':({'gold':self.gold,'fx':self.fx}[tid] if direct else ''),
            'at':(self.now-dt.timedelta(hours=age)).isoformat(),
            'link':('https://ec.ltn.com.tw/article/'+tid if direct else 'https://news.google.com/rss/articles/'+tid)}
    def material(self):
        return {tid:{'arts':[],'briefs':[self.story(tid,True)],'links':[self.story(tid,True)]}
                for tid in ('gold','fx')}
    def gather(self,public,body=lambda u:'',pool=None):
        calls=[]
        def fetch(feeds,*args,**kwargs):
            calls.append((feeds,kwargs))
            return public if ft.TOPIC_PUBLIC_FEEDS[0] in feeds[0]['url'] else []
        result=ft.gather_topic_material(self.specs,[self.story('gold'),self.story('fx')] if pool is None else pool,
            now=self.now,_fetch=fetch,_body=body)
        return result,calls
    def test_public_finance_feed_is_shared_and_keeps_original_article(self):
        public=[self.story('gold',True),self.story('fx',True)]
        got,calls=self.gather(public,body=lambda u:self.gold if u.endswith('gold') else self.fx)
        rss=[c for c in calls if ft.TOPIC_PUBLIC_FEEDS[0] in c[0][0]['url']]
        self.assertEqual(len(rss),1)
        self.assertEqual(rss[0][1]['hours'],24)
        for tid in ('gold','fx'):
            self.assertTrue(got[tid]['arts'])
            self.assertEqual(got[tid]['links'][0]['link'],self.story(tid,True)['link'])
            self.assertEqual(got[tid]['arts'][0]['summary'],self.story(tid,True)['summary'])
            self.assertFalse(any(h['link'].startswith('https://news.google.com') for h in got[tid]['briefs']))
    def test_publisher_summary_survives_body_failure(self):
        got,_=self.gather([self.story('gold',True),self.story('fx',True)])
        for tid in ('gold','fx'):
            self.assertEqual(ft._topic_public_text(got[tid]),'自由財經：'+self.story(tid,True)['summary'])
    def test_public_feed_still_rejects_old_and_future_news(self):
        public=[self.story('gold',True,25),self.story('fx',True,-1)]
        got,_=self.gather(public)
        self.assertTrue(all(not m['arts'] for m in got.values()))
        self.assertTrue(all(not h['link'].startswith('https://ec.ltn') for m in got.values() for h in m['links']))
    def test_public_feed_cannot_bypass_etf_filter(self):
        bad={**self.story('gold',True),'title':'黃金ETF配息策略','summary':'黃金ETF申購指南'}
        got,_=self.gather([bad])
        self.assertTrue(all('ETF' not in x['title'] for x in got['gold']['links']))
    def test_public_feeds_are_shared_once_even_with_existing_articles(self):
        _,calls=self.gather([],pool=[self.story('gold',True),self.story('fx',True)])
        self.assertEqual(sum(ft.TOPIC_PUBLIC_FEEDS[0] in c[0][0]['url'] for c in calls),1)
    def test_public_summary_is_not_described_as_title_only(self):
        block=ft._topic_block('gold','黃金',self.material()['gold'])
        self.assertIn('標題與出版社摘要',block)
        self.assertNotIn('（只有標題）',block)
    def test_json_response_format_is_accepted(self):
        text=json.dumps({'gold':self.gold,'fx':self.fx},ensure_ascii=False)
        self.assertEqual(ft._parse_topic_lines(text),{'gold':self.gold,'fx':self.fx})
        self.assertEqual(ft._parse_topic_lines('```json\n'+text+'\n```')['gold'],self.gold)
    def test_bad_json_value_is_not_accepted(self):
        self.assertEqual(ft._parse_topic_lines('{"gold": {"text": "x"}, "fx": 1}'),{})
    def test_failed_gold_is_retried_alone_without_rewriting_good_fx(self):
        responses=[('fx｜'+self.fx,''),('gold｜提供的材料不足以生成摘要。',''),('gold｜'+self.gold,'')]
        with patch.object(ft,'_call_ai',side_effect=responses) as ai:
            got=ft.summarize_topics(self.material(),{},'')
        self.assertEqual(got,{'fx':self.fx,'gold':self.gold})
        self.assertEqual(ai.call_count,3)
        self.assertNotIn('=== fx',ai.call_args_list[2].args[0])
    def test_batch_error_can_recover_single_topic(self):
        with patch.object(ft,'_call_ai',side_effect=[('','temporary failure'),('gold｜'+self.gold,'')]):
            got=ft.summarize_topics({'gold':self.material()['gold']},{},'')
        self.assertEqual(got,{'gold':self.gold})
    def test_isolated_retry_still_checks_numbers(self):
        wrong=self.fx.replace('31.8','35.9')
        with patch.object(ft,'_call_ai',return_value=('fx｜'+wrong,'')) as ai:
            got=ft.summarize_topics({'fx':self.material()['fx']},{},'')
        self.assertEqual(got,{})
        self.assertEqual(ai.call_count,3)
    def test_isolated_retry_still_rejects_prompt_wording(self):
        with patch.object(ft,'_call_ai',return_value=('gold｜提供的材料中相關資訊有限。','')):
            got=ft.summarize_topics({'gold':self.material()['gold']},{},'')
        self.assertEqual(got,{})
    def test_model_skip_is_recovered_before_source_fallback(self):
        skipped=set()
        with patch.object(ft,'_call_ai',return_value=('gold｜略','')) as ai:
            got=ft.summarize_topics({'gold':self.material()['gold']},{},'',skipped=skipped)
        self.assertEqual(got,{})
        self.assertEqual(ai.call_count,3)
        self.assertEqual(skipped,set())
    def test_fallback_can_use_summary_from_successful_article(self):
        m=self.material()['gold'];m['arts']=m['briefs'];m['briefs']=[]
        self.assertEqual(ft._topic_public_text(m),'自由財經：'+self.gold)
    def test_title_only_reports_keep_references_but_are_not_summaries(self):
        m={'arts':[],'briefs':[],'links':[{'title':'美元走強，新台幣貶破31.8元','source':'自由財經','link':'https://x/1'},
            {'title':'午盤新台幣兌美元報31.872元','source':'經濟日報','link':'https://x/2'}]}
        result=ft._topic_public_text(m)
        self.assertNotIn('31.8',result);self.assertNotIn('31.872',result)
        self.assertIn('中文摘要暫時無法取得',result)
        self.assertEqual(len(m['links']),2)

    def test_publisher_excerpt_omits_byline_and_truncated_sentence(self):
        m=self.material()['gold']
        m['briefs'][0]['summary']='〔財經頻道／綜合報導〕黃金價格下跌，美元走強影響市場表現，專家表示仍需留意利率變化。黃金現貨觸...…'
        result=ft._topic_public_text(m)
        self.assertEqual(result,'自由財經：黃金價格下跌，美元走強影響市場表現，專家表示仍需留意利率變化。')
    def test_missing_ai_credentials_do_not_retry_each_topic(self):
        with patch.object(ft,'_call_ai',return_value=('','沒有 AI 金鑰')) as ai:
            self.assertEqual(ft.summarize_topics(self.material(),{},''),{})
        self.assertEqual(ai.call_count,1)
    def test_broader_search_material_is_not_lost_during_public_enrichment(self):
        spec={**self.specs[0],'search':[{'q':'gold prices (site:reuters.com OR site:bloomberg.com)','lang':'en'}]}
        def fetch(feeds,*args,**kwargs):
            from urllib.parse import unquote
            url=unquote(feeds[0]['url'])
            if ft.TOPIC_PUBLIC_FEEDS[0] in url or 'site:' in url:return []
            return [self.story('gold')]
        result=ft.gather_topic_material([spec],[],now=self.now,_fetch=fetch,_body=lambda u:'')
        self.assertEqual(result['gold']['links'][0]['link'],self.story('gold')['link'])
    def test_single_topic_skip_does_not_erase_qualified_material(self):
        skipped=set()
        with patch.object(ft,'_call_ai',side_effect=[('','temporary failure'),('gold｜略','')]):
            result=ft.summarize_topics({'gold':self.material()['gold']},{},'',skipped=skipped)
        self.assertEqual(result,{})
        self.assertEqual(skipped,set())

    def test_english_month_is_a_valid_numeric_date(self):
        self.assertTrue(ft._digits_ok('中國央行9月增加黃金持有量','China central bank adds gold in September'))
        self.assertFalse(ft._digits_ok('中國央行8月增加黃金持有量','China central bank adds gold in September'))
    def test_written_week_duration_is_not_an_invented_number(self):
        self.assertTrue(ft._digits_ok('黃金跌至9週低點','Gold near Nine-Week Low'))
        self.assertFalse(ft._digits_ok('黃金跌至8週低點','Gold near Nine-Week Low'))
    def test_chinese_written_duration_is_not_an_invented_number(self):
        self.assertTrue(ft._digits_ok('黃金跌至2個月低點','黃金跌至兩個月低點'))
        self.assertFalse(ft._digits_ok('黃金跌至3個月低點','黃金跌至兩個月低點'))
    def test_twd_cents_conversion_is_checked(self):
        self.assertTrue(ft._digits_ok('新台幣貶值0.077元','新台幣貶值7.7分'))
        self.assertFalse(ft._digits_ok('新台幣貶值0.077美元','新台幣貶值7.7分'))
        self.assertFalse(ft._digits_ok('新台幣貶值0.078元','新台幣貶值7.7分'))
    def test_minutes_and_scores_are_not_money(self):
        self.assertFalse(ft._digits_ok('金額0.07元','等待7分鐘'))
        self.assertFalse(ft._digits_ok('金額0.07元','新台幣市場評分7分數據'))
    def test_lowercase_may_does_not_create_a_date(self):
        self.assertFalse(ft._digits_ok('5月可能升息','Fed may raise rates'))
        self.assertFalse(ft._digits_ok('5月可能升息','May raise rates'))
        self.assertTrue(ft._digits_ok('5月可能升息','Fed could raise rates in May'))

if __name__=='__main__':unittest.main()
