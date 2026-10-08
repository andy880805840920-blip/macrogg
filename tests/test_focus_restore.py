import datetime as dt
import json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from src.analysis import focus_today as ft
from src.pages import home

class FocusRestoreTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime.now(dt.timezone.utc)
        self.body='聯準會官員討論通膨及利率政策，市場持續觀察就業與物價的最新變化。報導指出政策判斷需要更多數據，官員將留意通膨下降是否持續，以及勞動市場的需求變化。'
        self.article={'title':'Fed官員說明通膨及利率政策','source':'自由時報','link':'https://example.com/fed','at':(self.now-dt.timedelta(hours=1)).isoformat(),'body':self.body,'summary':self.body}
    def generate(self,replies,mins=None,proof=None):
        with patch.object(ft,'_call_ai',side_effect=replies) as ai:
            result=ft._generate_items('Fed通膨政策與利率維持5%，油價90美元。','測試',{},caps=[250,80,80],mins=mins or [0,0,0],scope_topics=['Fed','油價'],provenance=proof)
        return result,ai.call_count
    def test_bad_supplement_number_does_not_remove_valid_main(self):
        result,calls=self.generate([('【主軸】Fed維持5%，官員持續觀察通膨。\n【補充】油價升至999美元。','')])
        self.assertEqual(result,('Fed維持5%，官員持續觀察通膨。',''))
        self.assertEqual(calls,1)
    def test_unrelated_supplement_does_not_remove_main(self):
        result,calls=self.generate([('【主軸】Fed官員討論通膨及利率政策。\n【補充】印度央行降息。','')])
        self.assertEqual(result[0],'Fed官員討論通膨及利率政策。')
    def test_meta_supplement_does_not_remove_main(self):
        result,calls=self.generate([('【主軸】Fed官員討論通膨及利率政策。\n【補充】Fed提供的材料不足以生成新聞摘要。','')])
        self.assertEqual(result[0],'Fed官員討論通膨及利率政策。')
    def test_rewrite_service_failure_keeps_valid_first_version_and_source(self):
        proof={'sources':{'a1':self.article}}
        result,calls=self.generate([('【主軸】Fed維持5%，官員持續觀察通膨。\n【主軸來源】a1',''),('','unavailable')],mins=[200,40,40],proof=proof)
        self.assertEqual(result[0],'Fed維持5%，官員持續觀察通膨。')
        self.assertEqual(proof['main_ids'],['a1'])
        self.assertEqual(calls,2)
    def test_rewrite_wrong_number_keeps_verified_first_version(self):
        result,calls=self.generate([('【主軸】Fed維持5%，官員持續觀察通膨。',''),('【主軸】Fed利率升至99%。','')],mins=[200,40,40])
        self.assertEqual(result[0],'Fed維持5%，官員持續觀察通膨。')
        self.assertNotIn('99',result[0])
    def test_bad_main_is_never_adopted(self):
        result,calls=self.generate([('【主軸】Fed利率升至99%。','')])
        self.assertEqual(result[0],'')
        self.assertIn('沒有的數字',result[1])
    def recover(self,articles=None,raw=None,exclude=None,reply=('', 'unavailable'),proof=None):
        with patch.object(ft,'_call_ai',return_value=reply) as ai:
            result=ft._main_recovery([self.article] if articles is None else articles,[],raw or [],scope_topics=['Fed'],cap=250,env={},provenance=proof,exclude=exclude)
        return result,ai.call_count
    def test_independent_main_recovery_uses_one_article(self):
        proof={}
        result,calls=self.recover(reply=('【主軸】Fed官員討論通膨及利率政策，將持續觀察物價變化。',''),proof=proof)
        self.assertEqual(result[1],'model-content')
        self.assertEqual(result[2],[self.article])
        self.assertEqual(proof['main_ids'],['a1'])
        self.assertEqual(calls,1)
    def test_publisher_excerpt_is_readable_and_has_exact_source(self):
        proof={};result,calls=self.recover(proof=proof)
        self.assertEqual(result[1],'publisher-excerpt')
        self.assertIn(self.body,result[0])
        self.assertEqual(result[2],[self.article])
        self.assertTrue(result[0].endswith('。'))
        self.assertEqual(proof['sources']['a1']['link'],self.article['link'])
        self.assertLessEqual(ft.cjk_len(result[0]),250)
    def test_raw_pool_cannot_bypass_time_or_excludes(self):
        stale={**self.article,'at':(self.now-dt.timedelta(hours=25)).isoformat()}
        blocked={**self.article,'title':'Fed美債ETF推薦'}
        for h in [stale,blocked]:
            result,calls=self.recover(articles=[],raw=[h],exclude=['ETF'])
            self.assertEqual(result,('','',[]))
            self.assertEqual(calls,0)
    def test_english_headline_is_not_presented_as_chinese_excerpt(self):
        h={**self.article,'title':'Fed holds rates','body':'','summary':''}
        result,calls=self.recover(articles=[h])
        self.assertEqual(result,('','',[]))
    def test_build_restores_main_and_preserves_topics_even_when_ai_is_down(self):
        row={k:v for k,v in self.article.items() if k!='body'}
        def feed(*a,**kw):
            if kw.get('raw_out') is not None:kw['raw_out'].append(row)
            return [row]
        topics=[{'id':tid,'label':tid,'text':'這是來源已提供的補充新聞內容。','links':[]} for tid in ['funding','equity','twf','election']]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ft,'fetch_feed_headlines',side_effect=feed), \
             patch.object(ft,'fetch_article_text',return_value=self.body), \
             patch.object(ft,'fedwatch_path',return_value=None), \
             patch.object(ft,'fetch_atlanta_fedwatch',return_value=None), \
             patch.object(ft,'build_catalog',return_value=[]), \
             patch.object(ft,'build_topics',return_value={'items':topics,'map':{}}), \
             patch.object(ft,'_call_ai',return_value=('','unavailable')) as ai:
            path=pathlib.Path(tmp)/'focus.json'
            f=ft.build({},False,{'enabled':True,'keywords':['Fed']},path,env={})
            first_calls=ai.call_count
            f2=ft.build({},False,{'enabled':True,'keywords':['Fed']},path,env={})
        self.assertEqual(f['text_source'],'publisher-excerpt')
        self.assertEqual(f['layout'],'main')
        self.assertEqual(f['topics'],topics)
        self.assertEqual(f['links'][0]['link'],self.article['link'])
        self.assertGreater(ai.call_count,first_calls)
        html=home._focus_strip(f)
        self.assertIn('今日市場焦點',html)
        self.assertIn('今日主軸',html)
        self.assertIn('class="fs-main"',html)
        self.assertIn('新聞重點摘錄自參考報導',html)
        self.assertNotIn('焦點由 AI 綜合報導改寫',html)

if __name__=='__main__':unittest.main()
