"""Behavioral checks: the requested publishers win across all news sections."""
from pathlib import Path
import sys, unittest, datetime as dt, html
from email.utils import format_datetime
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.analysis import focus_today as ft, news_publishers as np, news_sources as ns
TITLES={"fed":"Fed officials discuss inflation and interest rates", "long":"US Treasury yields rise after Treasury auction", "funding":"SOFR rises as bank reserves fall in US repo market", "oil":"Oil prices rise as Iran conflict threatens oil supply", "equity":"Wall Street stocks rise led by Nasdaq", "semi":"Nvidia announces new semiconductor chips", "twf":"台指期夜盤上漲，外資加碼台股", "election":"US midterm elections shift Senate race", "gold":"Gold prices rise as bullion demand grows", "fx":"New Taiwan dollar strengthens against US dollar"}
class PriorityTests(unittest.TestCase):
 def setUp(self): self.now=dt.datetime.now(dt.timezone.utc)
 def story(self,title,source,link,age=1):
  return dict(title=title,source=source,link=link,at=(self.now-dt.timedelta(hours=age)).isoformat(),summary='')
 def test_all_eleven_publishers_and_names_are_recognised(self):
  for p in np.PUBLISHERS:
   for name in p[3]:
    with self.subTest(name=name):self.assertEqual(np.priority({'source':name}),p[1])
   for domain in p[2]:
    self.assertEqual(np.priority({'link':'https://'+domain+'/story'}),p[1])
  self.assertEqual(np.priority({'link':'https://reuters.com.fake.example/story'}),0)
  self.assertEqual(np.priority({'source':'Other','title':'Reuters economist discusses Yahoo Finance earnings'}),0)
 def test_original_wire_priority_survives_readable_mirror(self):
  mirror={'source':'The Economic Times','original_source':'Reuters','link':'https://economictimes.indiatimes.com/story'}
  self.assertEqual(np.priority(mirror),2);self.assertEqual(np.label(mirror),'Reuters（The Economic Times轉載）')
  m={'arts':[{**mirror,'title':TITLES['fed'],'body':'Fed officials discussed inflation.'}],'briefs':[]}
  self.assertIn('Reuters（The Economic Times轉載）',ft._topic_block('fed','聯準會',m))
 def test_main_prefers_yahoo_finance_over_more_keyword_hits(self):
  other=self.story('Fed FOMC inflation CPI PCE GDP Treasury yields rise','CNBC','https://cnbc.com/a',.1)
  yahoo=self.story('Fed officials discuss rates','Yahoo Finance','https://finance.yahoo.com/a',20)
  self.assertEqual(ft.pick_fallback([other,yahoo],ft.DEFAULT_KEYWORDS,n=1,now=self.now)[0]['link'],yahoo['link'])
  second=self.story('Fed officials discuss policy','經濟日報','https://money.udn.com/a',21)
  self.assertEqual(ft.pick_fallback([other,second],ft.DEFAULT_KEYWORDS,n=1,now=self.now)[0]['link'],second['link'])
 def test_all_ten_topics_use_same_priority_and_freshness(self):
  specs=ft.topic_specs({})
  for spec in specs:
   tid=spec['id'];title=TITLES[tid]
   other=self.story(title,'Other','https://other.example/'+tid,.1)
   secondary=self.story(title,'Financial Times','https://ft.com/'+tid,2)
   yahoo=self.story(title,'Yahoo Finance','https://finance.yahoo.com/'+tid,20)
   material=ft.gather_topic_material([spec],[other,secondary,yahoo],now=self.now,_fetch=lambda *a,**k:[],_body=lambda u:title+'. Market reaction and background explain the event.')
   with self.subTest(tid=tid):self.assertEqual(material[tid]['links'][0]['link'],yahoo['link'])
   stale={**yahoo,'at':(self.now-dt.timedelta(hours=25)).isoformat()}
   material=ft.gather_topic_material([spec],[other,secondary,stale],now=self.now,_fetch=lambda *a,**k:[],_body=lambda u:title+'. Market reaction and background explain the event.')
   self.assertEqual(material[tid]['links'][0]['link'],secondary['link'])
 def test_all_topics_search_all_eleven_requested_publishers(self):
  domains=np.PRIMARY_DOMAINS+np.SECONDARY_EN+np.SECONDARY_ZH
  for spec in ft.topic_specs({}):
   searches=np.priority_searches(spec)
   self.assertEqual(len(searches),3)
   queries=' '.join(s['q'] for s in searches)
   for domain in domains:self.assertIn('site:'+domain,queries)
   for search in searches:
    self.assertIn('when%3A1d',ft._topic_url(search,24))
 def test_blocked_priority_sources_do_not_crowd_out_readable_secondary(self):
  spec=next(x for x in ft.topic_specs({}) if x['id']=='funding')
  pool=[self.story('US repo SOFR bank reserves report '+str(i),'Reuters','https://reuters.com/'+str(i)) for i in range(12)]
  secondary=self.story('Fed minutes discuss US market stress','經濟日報','https://money.udn.com/body')
  pool.append(secondary)
  got=ft.gather_topic_material([spec],pool,now=self.now,_fetch=lambda *a,**k:[],_body=lambda u:'Fed minutes described US funding pressure, market stress and bank reserve tools.' if u==secondary['link'] else '')
  self.assertEqual(got['funding']['links'][0]['link'],secondary['link'])
  self.assertTrue(got['funding']['arts'])
 def test_rss_duplicate_keeps_older_preferred_publisher(self):
  title=TITLES['fed'];rows=[self.story(title,'Other','https://other.example/a',.1),self.story(title,'Reuters','https://reuters.com/a',20)]
  xml='<rss><channel>'+''.join('<item><title>'+html.escape(a['title'])+'</title><link>'+a['link']+'</link><source>'+a['source']+'</source><pubDate>'+format_datetime(dt.datetime.fromisoformat(a['at']))+'</pubDate></item>' for a in rows)+'</channel></rss>'
  class Response:
   content=xml.encode()
   def raise_for_status(self):pass
  result=ft.fetch_feed_headlines(['https://example.com/rss'],['Fed'],_get=lambda u:Response())
  self.assertEqual(result[0]['source'],'Reuters')
 def test_same_article_public_copy_search_prefers_requested_media(self):
  original=self.story(TITLES['fed'],'Reuters','https://reuters.com/original')
  generic=self.story(TITLES['fed'],'The Economic Times','https://economictimes.indiatimes.com/a',.1)
  yahoo=self.story(TITLES['fed'],'Yahoo Finance','https://finance.yahoo.com/a',20)
  rows=[generic,yahoo]
  xml='<rss><channel>'+''.join('<item><title>'+html.escape(a['title'])+'</title><link>'+a['link']+'</link><source>'+a['source']+'</source><pubDate>'+format_datetime(dt.datetime.fromisoformat(a['at']))+'</pubDate></item>' for a in rows)+'</channel></rss>'
  class Response:
   content=xml.encode()
   def raise_for_status(self):pass
  result=ns.find_same_article(original,now=self.now,_get=lambda u:Response())
  self.assertEqual(result[0]['source'],'Yahoo Finance')
 def test_source_targeted_search_does_not_admit_unrequested_publishers(self):
  rows=[self.story(TITLES['fed'],'CNBC','https://cnbc.com/a'),self.story(TITLES['fed']+' after meeting','Yahoo! Finance Canada','https://ca.finance.yahoo.com/b')]
  xml='<rss><channel>'+''.join('<item><title>'+html.escape(a['title'])+'</title><link>'+a['link']+'</link><source>'+a['source']+'</source><pubDate>'+format_datetime(dt.datetime.fromisoformat(a['at']))+'</pubDate></item>' for a in rows)+'</channel></rss>'
  class Response:
   content=xml.encode()
   def raise_for_status(self):pass
  result=ft.fetch_feed_headlines([{'url':'https://example.com/rss','all':True,'preferred_sources':True}],[],_get=lambda u:Response())
  self.assertEqual([a['source'] for a in result],['Yahoo! Finance Canada'])
  ordinary=ft.fetch_feed_headlines([{'url':'https://example.com/rss','all':True}],[],_get=lambda u:Response())
  self.assertEqual(len(ordinary),2)  # General public sources remain available as fallback.
if __name__=='__main__': unittest.main()
