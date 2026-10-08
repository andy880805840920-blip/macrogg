"""Regression checks for the real byline/English-title supplement failures."""
from pathlib import Path
import sys,unittest,datetime as dt
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis import focus_today as ft,news_checks as nc

class CopyTests(unittest.TestCase):
 def setUp(self):
  self.now=dt.datetime.now(dt.timezone.utc)
  self.t_title='台指期夜盤一度失守49K、TSMC ADR走低'
  self.t_summary='[FTNN新聞網]記者吳峻光／綜合報導適逢雙十國慶連假，台股明（9）日休市一天。'
  self.t_body='將 Yahoo 設為首選來源，在 Google 上查看更多我們的精彩報導\n'+self.t_summary+'\n台指期夜盤報49180點，跌177點，盤中最低報48788點，一度失守49K。\n更多FTNN新聞網報導：台指期上周突破50200點。'
  self.s_title="Chip stocks retreat despite Samsung's record profit guidance: AlphaCheck"
  self.s_body="Good morning. The major averages retreated for a second day with chip stocks falling.\nBrent crude rose toward $105 amid US-Iran tensions.\nNvidia and AMD were set to decline from record highs.\nSamsung reported record profit guidance, but it did little to lift the chip sector, with peers Micron and SK Hynix trading lower.\nClick here for the latest stock market news"
  self.s_good='Samsung 的獲利展望創紀錄，仍未帶動半導體類股走強；Micron 和 SK Hynix 走低，NVIDIA 與 AMD 也從高點回落。'
 def material(self,tid,body=True):
  is_t=tid=='twf';h={'title':self.t_title if is_t else self.s_title,'link':'https://example.test/'+tid,'source':'Yahoo奇摩新聞' if is_t else 'Yahoo Finance','at':self.now.isoformat()}
  a={**h,'summary':self.t_summary if is_t else '','body':self.t_body if is_t else self.s_body}
  return {'arts':[a] if body else [],'briefs':[] if body else [a], 'links':[h]}
 def test_copy_removes_byline_but_preserves_reported_content(self):
  self.assertEqual(nc.clean_news_copy(self.t_summary),'適逢雙十國慶連假，台股明（9）日休市一天。')
  text=nc.clean_news_copy(self.t_body)
  for word in ['FTNN','記者','首選來源','50200']:self.assertNotIn(word,text)
  self.assertIn('49180',text);self.assertIn('48788',text)
 def test_chinese_source_fallback_uses_futures_body_not_holiday_lead(self):
  text=ft._topic_public_text(self.material('twf'),'twf')
  for word in ['49180','177','48788']:self.assertIn(word,text)
  for word in ['FTNN','記者','休市','50200']:self.assertNotIn(word,text)
  self.assertTrue(text.endswith('。'))
 def test_english_title_cannot_masquerade_as_chinese_summary(self):
  text=ft._topic_public_text(self.material('semi'),'semi')
  self.assertNotIn(self.s_title,text);self.assertIn('中文摘要暫時無法取得',text)
  self.assertIn('Yahoo Finance',text)
 def test_english_and_byline_outputs_fail_every_attempt(self):
  for tid,text in [('semi',self.s_title+'.'),('twf',self.t_summary)]:
   with patch.object(ft,'_call_ai',return_value=(tid+'｜'+text,'')):
    self.assertEqual(ft.summarize_topics({tid:self.material(tid)},{},''),{})
 def test_single_retry_uses_one_relevant_event_and_can_recover_chinese(self):
  with patch.object(ft,'_call_ai',side_effect=[('semi｜'+self.s_title+'.',''),('semi｜'+self.s_title+'.',''),('semi｜'+self.s_good,'')]) as ai:
   out=ft.summarize_topics({'semi':self.material('semi')},{'semi':'AI 與半導體'},'')
  self.assertEqual(out['semi'],self.s_good)
  prompt=ai.call_args_list[-1].args[0]
  self.assertIn('Samsung reported',prompt);self.assertNotIn('Brent crude rose',prompt);self.assertNotIn('Click here',prompt)
 def test_cutting_a_long_sentence_cannot_publish_an_unfinished_line(self):
  text='半導體股走低，'+('市場持續觀察晶片產業動向與公司獲利展望，'*12)+'市場變化仍受矚目。'
  with patch.object(ft,'_call_ai',return_value=('semi｜'+text,'')):
   self.assertEqual(ft.summarize_topics({'semi':self.material('semi')},{},''),{})
 def test_pipeline_keeps_links_and_falls_back_to_actual_futures_data(self):
  mat={t:self.material(t) for t in ('twf','semi')};state={}
  with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('','沒有 AI 金鑰')) as ai:
   out=ft.build_topics({},[],'',[],state,now=self.now)
  rows={r['id']:r for r in out['items']}
  self.assertIn('49180',rows['twf']['text']);self.assertNotIn('記者',rows['twf']['text'])
  self.assertNotIn(self.s_title,rows['semi']['text'])
  self.assertEqual(rows['semi']['links'][0]['title'],self.s_title)
  self.assertEqual(state['topics']['hash'],'');self.assertEqual(ai.call_count,1)
 def test_valid_output_is_not_affected(self):
  self.assertEqual(nc.topic_copy_problem(self.s_good),'')
  self.assertEqual(nc.clean_news_copy('聯準會官員指出通膨仍偏高，利率決策將取決於後續數據。'),'聯準會官員指出通膨仍偏高，利率決策將取決於後續數據。')

if __name__=='__main__':unittest.main()
