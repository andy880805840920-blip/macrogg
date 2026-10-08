import sys, json, pathlib, datetime as dt, unittest
from unittest.mock import patch
import yaml
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.analysis import focus_today as ft
from src.pages import home

class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.cfg=yaml.safe_load((ROOT/'config/focus.yaml').read_text(encoding='utf-8'))
        self.specs=ft.topic_specs(self.cfg)
        for s in self.specs: s['search']=[]
        self.now=dt.datetime(2026,10,8,2,tzinfo=dt.timezone.utc)
        titles={'fed':'Fed officials discuss inflation and interest rates',
            'long':'US Treasury yields rise after Treasury auction',
            'funding':'SOFR rises as bank reserves fall in repo market',
            'oil':'Oil prices rise as Iran conflict threatens oil supply',
            'equity':'Wall Street stocks rise led by Nasdaq',
            'semi':'NVIDIA announces new semiconductor chips',
            'twf':'台指期夜盤上漲，外資加碼台股',
            'election':'US midterm elections shift Senate race',
            'gold':'Gold prices rise as bullion demand grows',
            'fx':'New Taiwan dollar strengthens against US dollar'}
        self.pool=[{'title':v,'link':'https://example.com/'+k,'source':'Reuters',
                    'summary':'','at':self.now.isoformat()} for k,v in titles.items()]

    def material(self,pool=None,body=None,specs=None):
        return ft.gather_topic_material(specs or self.specs,self.pool if pool is None else pool,
            global_exclude=self.cfg.get('exclude_keywords'),now=self.now,
            _fetch=lambda *a,**k:[],_body=body or (lambda u:''))

    def test_all_ten_topics_survive_body_failure(self):
        mat=self.material()
        self.assertEqual(set(mat),{s['id'] for s in self.specs})
        for tid,m in mat.items():
            self.assertFalse(m['arts'])
            self.assertTrue(m['briefs'])
            self.assertEqual(m['links'][0]['link'],'https://example.com/'+tid)

    def test_failed_body_exception_also_keeps_public_brief(self):
        def fail(u): raise TimeoutError('private diagnostic')
        self.assertEqual(set(self.material(body=fail)),{s['id'] for s in self.specs})

    def test_etf_body_is_rejected_without_fallback(self):
        mat=self.material(body=lambda u:'台指期分析與ETF申購指南' if u.endswith('/twf') else '')
        self.assertNotIn('twf',mat)
        self.assertIn('fx',mat)

    def test_summary_can_match_keyword_but_context_is_still_required(self):
        specs=ft.topic_specs({'topics':[{'id':'funding','label':'資金市場',
            'keywords':['SOFR'],'chips':['sofr'],'search':[]}]})
        pool=[{'title':'Overnight borrowing becomes more expensive','summary':'SOFR rises.',
               'link':'https://example.com/summary','source':'Reuters','at':self.now.isoformat()}]
        self.assertIn('funding',self.material(pool=pool,specs=specs))
        pool=[{'title':'India inflation slows','summary':'US Treasury yields rise.',
               'link':'https://example.com/india','source':'Reuters'}]
        self.assertNotIn('long',self.material(pool=pool))

    def test_existing_fx_taiwan_and_equity_rules_remain(self):
        bad=[
            {'title':'台指期ETF配息與申購','link':'https://example.com/etf'},
            {'title':'Indian rupee rises against dollar','link':'https://example.com/inr'},
            {'title':'日股在AI與半導體股帶動下收高','link':'https://example.com/japan'},
            {'title':'NVIDIA芯片價格上升','link':'https://example.com/no-taiwan'}]
        mat=self.material(pool=bad)
        self.assertFalse(set(mat)&{'twf','fx','equity'})

    def test_omitted_topic_is_retried_independently(self):
        good='黃金價格上漲，報導指出市場對避險需求的變化影響金價表現，投資人仍持續關注美元與利率走勢。'
        mat=self.material()
        mat={k:mat[k] for k in ['gold','fx']}
        for m in mat.values():m['briefs'][0]['summary']=good
        calls=[]
        def ai(src,system,env=None):
            calls.append(src)
            return ('gold｜'+good if len(calls)==1 else 'fx｜'+good),''
        with patch.object(ft,'_call_ai',side_effect=ai):
            got=ft.summarize_topics(mat,{},'')
        self.assertEqual(set(got),{'gold','fx'})
        self.assertEqual(len(calls),2)
        self.assertNotIn('=== gold',calls[1])
        self.assertIn('=== fx',calls[1])

    def test_model_failure_preserves_all_topics_and_retries_next_run(self):
        mat=self.material()
        st={}
        with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('', 'unavailable')):
            result=ft.build_topics(self.cfg,self.pool,'',[],st,now=self.now)
        self.assertEqual(len(result['items']),10)
        self.assertEqual({i['text_source'] for i in result['items']},{'headlines'})
        self.assertEqual(st['topics']['hash'],'')
        for i in result['items']:
            self.assertTrue(i['text'].startswith('Reuters：'))
            self.assertNotIn('unavailable',i['text'])

    def test_explicit_repeat_skip_does_not_fallback(self):
        mat={'gold':self.material()['gold']}
        with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('gold｜略','')):
            result=ft.build_topics(self.cfg,self.pool,'相同事件',[],{},now=self.now)
        self.assertEqual(result['items'],[])

    def test_skipped_topic_is_rechecked_before_it_disappears(self):
        good='黃金價格上漲，報導指出市場對避險需求的變化影響金價表現，投資人仍持續關注美元與利率走勢。'
        mat={'gold':self.material()['gold']}
        mat['gold']['briefs'][0]['summary']=good
        skipped=set()
        with patch.object(ft,'_call_ai',side_effect=[('gold｜略',''),('gold｜'+good,'')]):
            result=ft.summarize_topics(mat,{},'',skipped=skipped)
        self.assertEqual(result,{'gold':good})
        self.assertFalse(skipped)

    def test_minimum_reaches_headline_prompt_and_retry(self):
        long='美國公債殖利率上升，市場重新評估通膨與利率前景。'*10
        seen=[]
        def ai(src,system,env=None):
            seen.append((src,system))
            return ('美國公債殖利率上升。' if len(seen)==1 else long),''
        with patch.object(ft,'_call_ai',side_effect=ai):
            text,kind=ft.summarize([{'title':'美國公債殖利率上升','summary':long,'source':'Reuters'}],
                caps=[250],mins=[200])
        self.assertEqual(kind,'model')
        self.assertGreaterEqual(ft.cjk_len(text),200)
        self.assertEqual(len(seen),2)
        self.assertIn('200–250',seen[0][1])
        self.assertIn('要 200–250',seen[1][0])

    def test_build_generates_topics_even_when_main_summary_fails(self):
        import tempfile
        def feed(*args,**kwargs):
            if kwargs.get('raw_out') is not None:
                kwargs['raw_out'].extend(self.pool)
            return self.pool
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ft,'fetch_feed_headlines',side_effect=feed), \
             patch.object(ft,'fetch_article_text',return_value=''), \
             patch.object(ft,'fedwatch_path',return_value=None), \
             patch.object(ft,'fetch_atlanta_fedwatch',return_value=None), \
             patch.object(ft,'build_catalog',return_value=[]), \
             patch.object(ft,'_call_ai',return_value=('','unavailable')), \
             patch.object(ft,'build_topics',return_value={'items':[], 'map':{}}) as topics:
            result=ft.build({},False,self.cfg,pathlib.Path(tmp)/'focus.json',env={})
        self.assertEqual(result['text_source'],'headlines')
        self.assertEqual(topics.call_count,1)
        self.assertEqual(topics.call_args.args[2],'')
        self.assertEqual(topics.call_args.args[3],[])

    def test_home_shows_topics_even_without_main_summary(self):
        mat=self.material()
        with patch.object(ft,'gather_topic_material',return_value=mat),patch.object(ft,'_call_ai',return_value=('', 'unavailable')):
            result=ft.build_topics(self.cfg,self.pool,'',[],{},now=self.now)
        cat=[{'id':s['chips'][0],'label':s['label'],'on':i<2,'value':'—','delta':''}
             for i,s in enumerate(self.specs)]
        html=home._focus_strip({'topics':result['items'],'topic_map':result['map'],
            'chips':[c for c in cat if c['id']!='pm_house'],'text':'','text_source':'headlines','links':[]})
        self.assertEqual(html.count('class="fs-text fs-topic'),10)
        self.assertNotIn('今日無新聞',html)
        self.assertNotIn(' disabled',html)
        self.assertIn('&lt;',home._focus_strip({'topics':[{'id':'gold','label':'黃金','text':'<來源標題>','links':[]}],'text':''}))
        config=json.loads(__import__('re').search(r'var FS_CONFIG=(\{.*?\});',html).group(1))
        self.assertEqual(config['topicOptions'].count('<option'),10)

if __name__=='__main__':
    unittest.main()

