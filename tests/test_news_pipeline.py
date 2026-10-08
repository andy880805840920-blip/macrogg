"""Shared topic recovery, reference binding and real main-text extraction."""
from pathlib import Path
import sys,unittest,datetime as dt,json
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis import focus_today as ft, news_article

TITLES={"fed":"Fed officials discuss inflation and interest rates", "long":"US Treasury yields rise after Treasury auction", "funding":"SOFR rises as bank reserves fall in US repo market", "oil":"Oil prices rise as Iran conflict threatens oil supply", "equity":"Wall Street stocks rise led by Nasdaq", "semi":"Nvidia announces new semiconductor chips", "twf":"台指期夜盤上漲，外資加碼台股", "election":"US midterm elections shift Senate race", "gold":"Gold prices rise as bullion demand grows", "fx":"New Taiwan dollar strengthens against US dollar"}

class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.now=dt.datetime.now(dt.timezone.utc);self.specs=ft.topic_specs({})
  for s in self.specs:s['search']=[]
 def story(self,tid,i):
  return dict(title=TITLES[tid]+f" report {i}",link=f"https://example.test/{tid}/{i}",source="Reuters",at=(self.now-dt.timedelta(minutes=i)).isoformat(),summary="")
 def test_all_ten_topics_replace_failed_bodies_and_bind_sources(self):
  for spec in self.specs:
   tid=spec['id'];pool=[self.story(tid,i) for i in range(4)];calls=[]
   def body(url):
    calls.append(url)
    return "" if url.endswith(('/0','/1')) else TITLES[tid]+". The report describes market reactions and the reasons for this change."
   got=ft.gather_topic_material([spec],pool,_fetch=lambda *a,**k:[],_body=body,now=self.now)
   with self.subTest(topic=tid):
    self.assertIn(tid,got);self.assertEqual(len(got[tid]['arts']),2)
    self.assertEqual(len(calls),4)
    self.assertEqual({a['link'] for a in got[tid]['arts']},{a['link'] for a in got[tid]['links']})
 def test_body_rejection_also_triggers_replacement(self):
  spec=next(s for s in self.specs if s['id']=='twf');pool=[self.story('twf',i) for i in range(4)]
  def body(url):
   return '台指期走高，ETF 配息與申購指南。' if url.endswith(('/0','/1')) else '台指期夜盤上漲，外資加碼台股，市場交易反映當晚美股走勢。'
  got=ft.gather_topic_material([spec],pool,_fetch=lambda *a,**k:[],_body=body,now=self.now)['twf']
  self.assertTrue(got['arts']);self.assertTrue(all('ETF' not in a['body'] for a in got['arts']))
  self.assertTrue(all(not a['link'].endswith(('/0','/1')) for a in got['links']))
 def test_same_url_shared_between_topics_is_downloaded_once(self):
  specs=[s for s in self.specs if s['id'] in ('equity','semi')];story=self.story('semi',0)
  story['title']='Wall Street chip stocks retreat as Nvidia semiconductor shares fall';calls=[]
  def body(url):calls.append(url);return story['title']+'. Nvidia shares declined as investors assessed semiconductor earnings.'
  got=ft.gather_topic_material(specs,[story],_fetch=lambda *a,**k:[],_body=body,now=self.now)
  self.assertEqual(set(got),{'equity','semi'});self.assertEqual(calls,[story['link']])
 def test_title_only_is_not_sent_to_ai_for_any_topic(self):
  for spec in self.specs:
   tid=spec['id'];h=self.story(tid,0);m={'arts':[],'briefs':[h], 'links':[h]}
   with patch.object(ft,'_call_ai') as ai,self.subTest(topic=tid):
    self.assertEqual(ft.summarize_topics({tid:m},{tid:spec['label']},''),{})
    ai.assert_not_called()
    self.assertIn('中文摘要暫時無法取得',ft._topic_public_text(m,tid))
    self.assertNotIn(h['title'],ft._topic_public_text(m,tid))
 def test_same_quality_guard_rejects_byline_english_and_made_up_number(self):
  source='台指期夜盤上漲，市場成交增加。';m={'arts':[dict(title='夜盤觀察',body=source)],'briefs':[],'links':[]}
  for tid in TITLES:
   for text in ['[FTNN新聞網]記者王小明／綜合報導台指期夜盤上漲。','Chip stocks fall despite strong earnings.','台指期夜盤上漲五百點，成交達999999口，市場持續觀察後續變化。']:
    with self.subTest(topic=tid,text=text):self.assertTrue(ft._topic_summary_problem(text,source,m))
 def test_body_extractor_keeps_article_but_not_recommended_story(self):
  article='The Federal Reserve held interest rates steady. Policymakers said inflation remained elevated and explained that they would evaluate incoming employment and price data before deciding the next policy step.'
  page='<html><head><title>Policy report</title></head><body><nav>Home Markets</nav><article><h1>Policy report</h1><p>'+article+'</p></article><aside><p>Gold rises to 999999 in an unrelated recommended story.</p></aside><footer>Subscribe for more</footer></body></html>'
  text=' '.join(news_article.extract_paragraphs(page,fallback=ft._legacy_article_paragraphs))
  self.assertIn('employment and price data',text);self.assertNotIn('999999',text);self.assertNotIn('Subscribe',text)
 def test_short_yahoo_article_cannot_absorb_related_news(self):
  lead='國際油價上漲，美國公債殖利率徘徊高點，市場評估通膨前景。'*5
  unrelated='台股 ETF 申購與配息策略，網紅預測指數突破新高。'*30
  page='<html><body><div class="caas-body"><p>'+lead+'</p></div><section><p>'+unrelated+'</p></section></body></html>'
  text=' '.join(news_article.extract_paragraphs(page,fallback=ft._legacy_article_paragraphs))
  self.assertIn('公債殖利率',text);self.assertNotIn('ETF',text);self.assertNotIn('網紅',text)
 def test_wire_service_datelines_are_metadata_not_reporting(self):
  from src.analysis import news_checks as nc
  text='（中央社紐約2026年10月8日綜合外電報導）國際油價上漲，美債殖利率徘徊高點，市場評估通膨前景。'
  self.assertTrue(nc.topic_copy_problem(text))
  self.assertEqual(nc.clean_news_copy(text),'國際油價上漲，美債殖利率徘徊高點，市場評估通膨前景。')
  self.assertEqual(nc.clean_news_copy('（中央社記者王小明台北8日電）台指期上漲，市場持續觀察交易動向。'),'台指期上漲，市場持續觀察交易動向。')
 def test_extractor_failure_uses_scoped_reader(self):
  with patch.dict(sys.modules,{'trafilatura':None}):
   rows=news_article.extract_paragraphs('<article><p>台指期夜盤上漲，市場交易反映當晚美股走勢，外資買賣動向也是觀察重點。</p></article>',fallback=ft._legacy_article_paragraphs)
  self.assertEqual(len(rows),1);self.assertIn('台指期',rows[0])

if __name__=='__main__':unittest.main()
