"""News scope and English name rules; includes offline scheduled-build paths."""
from pathlib import Path
import copy,sys,tempfile,datetime as dt,json
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import yaml
from src.analysis import news_policy as np, focus_today as ft
from src.pages import home

cfg=yaml.safe_load((Path(__file__).resolve().parents[1]/'config/focus.yaml').read_text(encoding='utf-8'))
assert cfg['keywords']==np.MAIN_TOPICS
assert not cfg['keywords_secondary']
for bad in ['India CPI cools as RBI signals a rate cut', '印度央行降息，GDP成長上修',
            'Indian bond yields drop after Federal Reserve remarks',
            '印度債市受Fed降息預期激勵', 'India inflation eases as oil prices fall',
            '印度GDP上修，但黃金價格上漲', 'Australia unemployment rises',
            'India rupee declines against US dollar', 'Friday rain forecast improves',
            'Fedora coat sales increase', 'A chair designed for your office', 'Golden retriever wins award']:
 assert not np.main_allowed({'title':bad}),bad
for good in ['Fed signals rate cuts after U.S. CPI', 'U.S. GDP growth lifts Treasury yields',
             'Powell says inflation risks remain', '鮑威爾表示通膨風險仍在',
             'Scott Bessent announces Treasury auction', 'BOJ considers raising rates after Japan CPI',
             '日本央行植田和男談升息與日圓', 'Yen climbs after BOJ decision',
             'AI capital spending drives Nvidia bond issuance', '輝達宣布AI資本支出計畫',
             'Nvidia invests in semiconductor production in India',
             'Oil prices rise as Iran conflict intensifies', '中東戰爭推升油價與黃金',
             'Russia-Ukraine war raises energy concerns', '川普宣布對印度加徵關稅',
             'US Treasury yields rise as foreign investors sell', 'Gold climbs on weaker dollar']:
 assert np.main_allowed({'title':good}),good
assert not np.main_allowed({'title':'CPI falls sharply','summary':'India inflation was reported by RBI this morning.'})
assert np.main_allowed({'title':'Fed reviews inflation','summary':'Officials also mentioned developments in India.'})
assert np.main_allowed({'title':'Speech by Governor','link':'https://www.federalreserve.gov/newsevents/speech/example.htm'})
for word,bad in [('AI','chair'),('Fed','federalism'),('gold','golden')]:
 assert not ft._kw_hit(word,bad)
assert ft._kw_hit('AI','AI資本支出') and ft._kw_hit('NVIDIA','Nvidia raises capital')
assert np.english_names('川普與鮑威爾會面，貝森特及華許出席。')=='Donald Trump與Jerome Powell會面，Scott Bessent及Kevin Warsh出席。'
assert np.english_names('Trump（川普）與鮑威爾（Jerome Powell）')=='Trump與Jerome Powell'
assert np.english_names('黃仁勳與植田和男')=='Jensen Huang與Kazuo Ueda'
assert np.english_names('英文 Donald Trump；通膨與美國財政部。')=='英文 Donald Trump；通膨與美國財政部。'
# Model obeys the editorial rules; deterministic normalization is the backup.
seen=[]
def model(src,system,env=None):
 seen.append((src,system));return '【主軸】\n川普與鮑威爾談Fed通膨政策。\n【補充】\n黃仁勳說明AI資本支出。',''
with patch.object(ft,'_call_ai',side_effect=model):
 text,src=ft.summarize_content([{'title':'Fed與AI','body':'川普、鮑威爾與黃仁勳談Fed通膨政策和AI資本支出。','source':'Reuters'}], np.MAIN_TOPICS,caps=[250,80,80],scope_topics=np.MAIN_TOPICS)
 assert all(a not in text for a in ['川普','鮑威爾','黃仁勳'])
 assert '一律使用英文' in seen[0][1] and '印度' in seen[0][1]
# Out-of-scope model output must be retried, then omitted, never cached as a main.
with patch.object(ft,'_call_ai',return_value=('【主軸】\n印度央行降息，印度CPI回落。','')) as ai:
 text,why=ft.summarize([{'title':'Fed討論CPI','source':'Reuters'}],caps=[250,80,80],scope_topics=np.MAIN_TOPICS)
 assert not text and '範圍' in why and ai.call_count==2
# Exercise feed mode, Google fallback, expanded second-pass content and old cache.
now=dt.datetime.now(dt.timezone.utc).isoformat()
def h(title,index):return {'title':title,'link':f'https://example.test/{index}','source':'Reuters','at':now,'summary':''}
india=h('India CPI falls as RBI cuts rates','india')
us=h('Fed與川普討論CPI','us')
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp)/'focus.json'
 path.write_text(json.dumps({'hash':'old','text':'印度央行降息。','at':now,'text_source':'model-content'}),encoding='utf-8')
 with patch.multiple(ft, fetch_yahoo_yield=lambda *a,**k:None,
                     fedwatch_from_futures=lambda *a,**k:None,
                     fetch_atlanta_fedwatch=lambda *a,**k:None,
                     fetch_fedwatch=lambda *a,**k:None,
                     build_catalog=lambda *a,**k:[],
                     build_topics=lambda *a,**k:{'items':[],'map':{}},
                     fetch_article_text=lambda url:'川普和鮑威爾討論Fed通膨政策。'*8):
  for mode in ['feed','google']:
   seen.clear()
   with patch.object(ft,'fetch_feed_headlines',return_value=[india,us] if mode=='feed' else [india]), \
        patch.object(ft,'fetch_headlines',return_value=[india,us]), \
        patch.object(ft,'_call_ai',side_effect=model):
    result=ft.build({},False,dict(cfg,topics=[]),path,env={})
   assert '印度' not in result['text'] and 'Donald Trump' in result['text']
   assert result['links'][0]['title']=='Fed與Donald Trump討論CPI'
   assert all('India CPI' not in source for source,_ in seen)
   assert 'example.test/india' not in json.dumps(result['links'])
   assert result['text_source']!='cache', 'Mode differs, stale main must not survive'
  saved=json.loads(path.read_text(encoding='utf-8'))
  assert '印度' not in saved['text'] and '川普' not in saved['text']
  with patch.object(ft,'fetch_feed_headlines',return_value=[india]),patch.object(ft,'fetch_headlines',return_value=[india]),patch.object(ft,'_call_ai') as ai:
   result=ft.build({},False,dict(cfg,topics=[]),path,env={})
  assert not result['text'] and not result['links'] and not ai.called, 'No eligible news must not broaden the scope'
original={'text':'川普談通膨。','links':[{'title':'鮑威爾演講','link':'https://example.test/a'}],
          'topics':[{'id':'fed','label':'聯準會','text':'植田和男談BOJ','links':[{'title':'黃仁勳談AI','link':'https://example.test/b'}]}]}
np.display_news(original)
assert original['links'][0]['link']=='https://example.test/a'
assert 'Jerome Powell' in original['links'][0]['title'] and 'Jensen Huang' in original['topics'][0]['links'][0]['title']
assert 'Donald Trump' in home._focus_strip(dict(original,generated='2026-10-07',text_source='model-content'))
print('PASS: approved bilingual topics, Indian/foreign macro exclusion, whole-word matching, English people names, model scope retry, feed/Google/second-pass filtering, cache invalidation and fallback headlines.')
