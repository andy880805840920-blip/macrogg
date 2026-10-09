"""Regression coverage for Google redirects, blocked originals and source binding."""
from pathlib import Path
import sys,unittest,datetime as dt,json,html
from email.utils import format_datetime
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis import news_sources as ns,focus_today as ft
TITLE='Fed minutes show some officials want to prepare for market stress'
TITLES={"fed":"Fed officials discuss inflation and interest rates", "long":"US Treasury yields rise after Treasury auction", "funding":"SOFR rises as bank reserves fall in US repo market", "oil":"Oil prices rise as Iran conflict threatens oil supply", "equity":"Wall Street stocks rise led by Nasdaq", "semi":"Nvidia announces new semiconductor chips", "twf":"台指期夜盤上漲，外資加碼台股", "election":"US midterm elections shift Senate race", "gold":"Gold prices rise as bullion demand grows", "fx":"New Taiwan dollar strengthens against US dollar"}
class SourceTests(unittest.TestCase):
 def setUp(self):
  ns._resolved.clear();self.now=dt.datetime.now(dt.timezone.utc)
  self.google='https://news.google.com/rss/articles/CBMi'+'a'*60
  self.original={'title':TITLE,'link':self.google,'source':'Reuters','at':(self.now-dt.timedelta(hours=1)).isoformat()}
  self.alt={**self.original,'link':'https://finance.yahoo.com/news/fed-minutes-story.html','source':'Yahoo Finance','at':(self.now-dt.timedelta(hours=2)).isoformat()}
 def decoder(self,urls):return [{'success':True,'decoded_url':'https://www.reuters.com/business/fed-minutes-story/'} for u in urls]
 def resolver(self,rows,**kw):return ns.resolve_records(rows,_decoder=self.decoder,**kw)
 def test_batch_decodes_once_and_preserves_original_metadata(self):
  calls=[]
  def decode(urls):calls.append(urls);return self.decoder(urls)
  first=ns.resolve_records([self.original,self.original],now=self.now,_decoder=decode)
  second=ns.resolve_records([self.original],now=self.now,_decoder=decode)
  self.assertEqual(len(calls),1);self.assertEqual(calls[0],[self.google])
  for a in first+second:
   self.assertEqual(a['original_link'],self.google);self.assertEqual(a['source'],'Reuters');self.assertEqual(a['at'],self.original['at'])
   self.assertIn('reuters.com',a['link'])
 def test_future_old_and_unknown_dates_are_never_decoded(self):
  rows=[{**self.original,'at':(self.now-dt.timedelta(hours=25)).isoformat()},{**self.original,'at':(self.now+dt.timedelta(minutes=1)).isoformat()},{**self.original,'at':''}]
  with patch.object(ns,'_decode') as decode:
   self.assertEqual(ns.resolve_records(rows,now=self.now),rows);decode.assert_not_called()
 def test_failed_decoder_does_not_poison_next_run(self):
  self.assertEqual(ns.resolve_records([self.original],now=self.now,_decoder=lambda u:[{'success':False}])[0]['link'],self.google)
  self.assertIn('reuters.com',ns.resolve_records([self.original],now=self.now,_decoder=self.decoder)[0]['link'])
 def test_non_article_google_link_cannot_take_body_slot(self):
  self.assertFalse(ft._can_read_news('https://news.google.com/rss/articles/fake'))
  self.assertTrue(ft._can_read_news(self.google))
 def test_private_or_invalid_decoded_url_is_not_used(self):
  for target in ['http://127.0.0.1/private','javascript:alert(1)','https://news.google.com/','https://user:password@example.com/']:
   with self.subTest(target=target):
    ns._resolved.clear();out=ns.resolve_records([self.original],now=self.now,_decoder=lambda u:[{'success':True,'decoded_url':target}])
    self.assertEqual(out[0]['link'],self.google)
 def test_blocked_original_uses_public_syndication_and_actual_reference(self):
  calls=[]
  def fetch(url):calls.append(url);return '' if 'reuters.com' in url else 'Federal Reserve officials suggested strengthening tools to prepare for Treasury market stress.'
  out=ns.read_article(self.original,fetch,now=self.now,_resolver=self.resolver,_find=lambda *a,**k:[self.alt])
  self.assertEqual(out['link'],self.alt['link']);self.assertEqual(out['source'],'Yahoo Finance');self.assertEqual(out['at'],self.alt['at'])
  self.assertEqual(out['original_source'],'Reuters');self.assertEqual(out['original_link'],self.google)
  self.assertIn('market stress',out['body']);self.assertEqual(len(calls),2)
 def test_timeout_also_recovers_and_good_original_does_not_search(self):
  def fetch(url):
   if 'reuters.com' in url:raise TimeoutError()
   return 'Federal Reserve officials prepared for Treasury market stress.'
  self.assertTrue(ns.read_article(self.original,fetch,now=self.now,_resolver=self.resolver,_find=lambda *a,**k:[self.alt])['body'])
  with patch.object(ns,'find_same_article') as finder:
   self.assertEqual(ns.read_article(self.original,lambda u:'Complete reporting.',now=self.now,_resolver=self.resolver)['body'],'Complete reporting.')
   finder.assert_not_called()
 def test_decoder_failure_can_recover_a_direct_public_copy(self):
  def identity(rows,**kw):return rows
  out=ns.read_article(self.original,lambda u:'A full published report.',now=self.now,_resolver=identity,_find=lambda *a,**k:[self.alt])
  self.assertEqual(out['link'],self.alt['link']);self.assertTrue(out['body'])
 def test_different_story_or_expired_copy_cannot_replace_article(self):
  wrong={**self.alt,'title':'Fed officials say Treasury market is already broken'}
  stale={**self.alt,'at':(self.now-dt.timedelta(hours=25)).isoformat()}
  out=ns.read_article(self.original,lambda u:'',now=self.now,_resolver=self.resolver,_find=lambda *a,**k:[wrong,stale])
  self.assertEqual(out['body'],'');self.assertIn('reuters.com',out['link'])
  self.assertFalse(ns.same_article(self.original,{**self.alt,'title':TITLE.replace('want','do not want')}))
  self.assertFalse(ns.same_article({'title':'Treasury auction sells 39 billion in debt'},{'title':'Treasury auction sells 89 billion in debt'}))
 def test_syndication_queries_share_exact_title_and_verify_24_hours(self):
  good={**self.alt,'title':TITLE+' - Yahoo Finance'};old={**good,'at':(self.now-dt.timedelta(hours=30)).isoformat(),'link':'https://old.example/story'}
  wrong={**good,'title':'Fed inflation report','link':'https://other.example/story'}
  xml='<rss><channel>'+''.join('<item><title>'+html.escape(a['title'])+'</title><link>'+a['link']+'</link><source>'+a['source']+'</source><pubDate>'+format_datetime(dt.datetime.fromisoformat(a['at']))+'</pubDate></item>' for a in [good,old,wrong])+'</channel></rss>'
  class Response:
   content=xml.encode()
   def raise_for_status(self):pass
  calls=[]
  def get(url):calls.append(url);return Response()
  out=ns.find_same_article(self.original,now=self.now,_get=get)
  self.assertEqual(len(out),1);self.assertEqual(out[0]['link'],good['link']);self.assertEqual(len(calls),4)
  self.assertTrue(any('finance.yahoo.com' in u for u in calls));self.assertTrue(any('economictimes' in u for u in calls))
 def test_all_ten_topics_read_resolved_article_and_bind_reference(self):
  specs=ft.topic_specs({})
  for s in specs:s['search']=[]
  rows=[dict(title=title,link=self.google+tid,source='Reuters',at=self.original['at']) for tid,title in TITLES.items()]
  target={a['link']:'https://www.reuters.com/'+tid for tid,a in zip(TITLES,rows)}
  def prepare(records,**kw):return ns.resolve_records(records,_decoder=lambda urls:[{'success':True,'decoded_url':target[u]} for u in urls],**kw)
  def body(url):return TITLES[url.rsplit('/',1)[-1]]+'. The reporting describes market reactions and the background of this event.'
  with patch.object(ft,'_prepare_news_links',side_effect=prepare),patch.object(ft,'fetch_article_text',side_effect=body):
   got=ft.gather_topic_material(specs,rows,now=self.now,_fetch=lambda *a,**k:[])
  self.assertEqual(set(got),set(TITLES))
  for tid,m in got.items():
   self.assertTrue(m['arts']);self.assertEqual(m['arts'][0]['link'],m['links'][0]['link']);self.assertNotIn('news.google.com',m['links'][0]['link'])
 def test_readable_fifth_candidate_is_not_lost_after_four_failed_articles(self):
  spec=next(s for s in ft.topic_specs({}) if s['id']=='funding');spec['search']=[]
  pool=[dict(title='US repo SOFR bank reserves funding stress money markets report '+str(i),link='https://bad.example/'+str(i),source='Reuters',at=(self.now-dt.timedelta(minutes=i)).isoformat()) for i in range(4)]
  report={**self.original,'link':'https://www.reuters.com/actual-funding-story'};pool.append(report)
  body='Federal Reserve meeting minutes described plans and tools for Treasury market stress.'
  got=ft.gather_topic_material([spec],pool,now=self.now,_fetch=lambda *a,**k:[],_body=lambda url:body if url==report['link'] else '')
  self.assertTrue(got['funding']['arts']);self.assertEqual(got['funding']['links'][0]['link'],report['link'])
 def test_crypto_price_news_cannot_crowd_out_funding_reporting(self):
  from src.analysis import news_policy as policy
  wrong={'title':'Bitcoin falls as US Treasury yields and oil rise','body':'Fed market stress and rising yields pressure cryptocurrencies.'}
  self.assertFalse(policy.topic_allowed('funding',wrong))
  valid={'title':'US repo SOFR funding stress weighs on Bitcoin','body':'The US repo market faced funding pressure.'}
  self.assertTrue(policy.topic_allowed('funding',valid))
 def test_main_recovery_reads_public_copy_and_keeps_its_provenance(self):
  body='Federal Reserve meeting minutes said a few participants recommended preparing for Treasury market stress and strengthening communications and tools.'
  text='Fed 會議紀要顯示，少數與會者建議提前準備美債市場壓力，強化溝通與工具，以應對可能出現的市場失靈。'
  proof={}
  with patch.object(ns,'_decode',side_effect=self.decoder),patch.object(ns,'find_same_article',return_value=[self.alt]),patch.object(ft,'fetch_article_text',side_effect=lambda u:body if 'yahoo.com' in u else ''),patch.object(ft,'_generate_items',return_value=(text,'')):
   out=ft._main_recovery([],[],[self.original],scope_topics=['Fed','美債'],cap=250,env={},provenance=proof)
  self.assertEqual(out[0],text);self.assertEqual(out[1],'model-content');self.assertEqual(proof['sources']['a1']['link'],self.alt['link'])

if __name__=='__main__':unittest.main()
