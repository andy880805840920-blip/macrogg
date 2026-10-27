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
    def test_bad_json_value_is_not_accepted(self):
        self.assertEqual(ft._parse_topic_lines('{"gold": {"text": "x"}, "fx": 1}'),{})


    def test_english_month_is_a_valid_numeric_date(self):
        self.assertTrue(ft._digits_ok('中國央行9月增加黃金持有量','China central bank adds gold in September'))
        self.assertFalse(ft._digits_ok('中國央行8月增加黃金持有量','China central bank adds gold in September'))
    def test_minutes_and_scores_are_not_money(self):
        self.assertFalse(ft._digits_ok('金額0.07元','等待7分鐘'))
        self.assertFalse(ft._digits_ok('金額0.07元','新台幣市場評分7分數據'))

if __name__=='__main__':unittest.main()
