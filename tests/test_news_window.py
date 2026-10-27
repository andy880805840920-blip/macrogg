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
    def test_no_topic_fallback_to_old_or_undated_reports(self):
        for h in [self.story(25),self.story(50),self.story(-1),{**self.story(1),'at':''}]:
            with self.subTest(h=h):
                self.assertEqual(ft.gather_topic_material([self.spec],[h],now=self.now,
                    _fetch=lambda *a,**k:[],_body=lambda u:''),{})
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


if __name__=='__main__':unittest.main()
