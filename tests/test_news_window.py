import datetime as dt
import pathlib,sys,unittest,tempfile,json
from unittest.mock import patch
from email.utils import format_datetime
from urllib.parse import unquote
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from src.analysis import focus_today as ft

class WindowTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime.now(dt.timezone.utc)
        self.spec=next(s for s in ft.topic_specs({}) if s['id']=='gold')
        self.spec['search']=[]
    def story(self,age):
        return {'title':'Gold prices rise','source':'Reuters','link':'https://example.com/gold',
                'at':(self.now-dt.timedelta(hours=age)).isoformat()}
    def test_window_boundary_and_invalid_dates(self):
        for age,want in [(0,True),(24,True),(24+1/3600,False),(25,False),(50,False),(-1,False)]:
            with self.subTest(age=age):self.assertEqual(ft._within_news_window(self.story(age),self.now),want)
        self.assertFalse(ft._within_news_window({'at':'bad'},self.now))
        self.assertFalse(ft._within_news_window({},self.now))
    def test_no_topic_fallback_to_old_or_undated_reports(self):
        for h in [self.story(25),self.story(50),self.story(-1),{**self.story(1),'at':''}]:
            with self.subTest(h=h):
                self.assertEqual(ft.gather_topic_material([self.spec],[h],now=self.now,
                    _fetch=lambda *a,**k:[],_body=lambda u:''),{})
    def test_recent_topic_survives_body_failure(self):
        got=ft.gather_topic_material([self.spec],[self.story(23)],now=self.now,
            _fetch=lambda *a,**k:[],_body=lambda u:'')
        self.assertEqual(got['gold']['links'][0]['at'],self.story(23)['at'])
    def test_broader_source_search_also_stays_within_24_hours(self):
        self.spec['search']=[{'q':'gold prices (site:reuters.com OR site:bloomberg.com)','lang':'en'}]
        calls=[]
        def fetch(feeds,*args,**kw):
            calls.append((unquote(feeds[0]['url']),kw['hours']))
            return [] if 'site:' in calls[-1][0] else [self.story(25)]
        got=ft.gather_topic_material([self.spec],[],now=self.now,_fetch=fetch,_body=lambda u:'')
        self.assertEqual(got,{})
        self.assertEqual(len(calls),3)
        self.assertTrue(all(hours==24 for u,hours in calls))
        self.assertTrue(all('when:1d' in u for u,hours in calls if 'news.google.com' in u))
    def rss_get(self,urls):
        records=[self.story(age) for age in [1,25,-1]]
        xml='<rss><channel>'+''.join('<item><title>'+h['title']+str(i)+'</title><link>'+h['link']+str(i)+'</link><pubDate>'+format_datetime(dt.datetime.fromisoformat(h['at']))+'</pubDate><source>Reuters</source></item>' for i,h in enumerate(records))+'</channel></rss>'
        class Response:
            content=xml.encode()
            def raise_for_status(self):pass
        def get(url):
            urls.append(unquote(url))
            return Response()
        return get
    def test_google_rss_caps_requested_window_and_rejects_future(self):
        urls=[]
        rows=ft.fetch_headlines(['gold'],hours=72,_get=self.rss_get(urls))
        self.assertEqual(len(rows),1)
        self.assertTrue(all('when:1d' in u for u in urls))
    def test_feed_and_raw_pool_both_only_recent(self):
        urls=[];raw=[]
        rows=ft.fetch_feed_headlines([{'url':ft._topic_url({'q':'gold','lang':'en'},72),'all':True}],[],
            hours=72,_get=self.rss_get(urls),raw_out=raw)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(raw),1)
        self.assertTrue(all('when:1d' in u for u in urls))

    def test_main_and_google_do_not_reuse_expired_cached_news(self):
        story=self.story(25);story['title']='Fed holds interest rates'
        cfg={'enabled':True,'keywords':['Fed'],'topics':[]}
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'focus.json'
            path.write_text(json.dumps({'text':'過期新聞','hash':'old-version',
                'at':self.now.isoformat(),'links':[story]}),encoding='utf-8')
            with patch.object(ft,'fetch_feed_headlines',return_value=[story]) as feed, \
                 patch.object(ft,'fetch_headlines',return_value=[story]) as google, \
                 patch.object(ft,'fedwatch_path',return_value=None), \
                 patch.object(ft,'fetch_atlanta_fedwatch',return_value=None), \
                 patch.object(ft,'build_catalog',return_value=[]), \
                 patch.object(ft,'build_topics',return_value={'items':[],'map':{}}), \
                 patch.object(ft,'_call_ai') as ai:
                result=ft.build({},False,cfg,path,env={})
            self.assertEqual(result['text'],'')
            self.assertEqual(result['links'],[])
            self.assertEqual(feed.call_args.kwargs['hours'],24)
            self.assertEqual(google.call_args.kwargs['hours'],24)
            ai.assert_not_called()
    def test_main_second_body_pass_rejects_older_candidate(self):
        recent=self.story(1);recent['title']='Fed holds interest rates'
        old={**self.story(25),'title':'Fed cuts interest rates','link':'https://example.com/old'}
        calls=[]
        def feed(*args,**kwargs):
            calls.append(kwargs['hours'])
            if kwargs.get('raw_out') is not None:kwargs['raw_out'].extend([recent,old])
            return [recent,old]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ft,'fetch_feed_headlines',side_effect=feed), \
             patch.object(ft,'fetch_article_text',return_value='') as body, \
             patch.object(ft,'fedwatch_path',return_value=None), \
             patch.object(ft,'fetch_atlanta_fedwatch',return_value=None), \
             patch.object(ft,'build_catalog',return_value=[]), \
             patch.object(ft,'build_topics',return_value={'items':[],'map':{}}), \
             patch.object(ft,'_call_ai',return_value=('','unavailable')):
            ft.build({},False,{'enabled':True,'keywords':['Fed']},
                pathlib.Path(tmp)/'focus.json',env={})
        self.assertGreaterEqual(len(calls),2)
        self.assertTrue(all(hours==24 for hours in calls))
        self.assertNotIn(old['link'],[c.args[0] for c in body.call_args_list])

if __name__=='__main__':unittest.main()
