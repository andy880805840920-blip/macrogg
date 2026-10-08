"""Source-grounded minutes comparison and integration checks, without network."""
from pathlib import Path
import sys,tempfile,json,hashlib
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis import fomc_extra as fx
from src import build,fixtures_fomc
from src.pages import fomc

def row(text,level='普遍',rank=0,topic='其他'):
 return {'text':text,'level':level,'rank':rank,'topic':topic}
rows=[
 row('Participants generally expected inflation to decline under appropriate monetary policy.',topic='政策路徑'),
 row('All participants supported raising the target range for the federal funds rate.','全體'),
 row('Most participants assessed that another increase in the target range would likely be appropriate by year end.','多數',2),
 row('Participants noted that inflation remained elevated and they had not seen sufficient progress on lowering inflation.'),
 row('Participants judged that inflation expectations remained at levels consistent with the inflation objective.'),
 row('Participants judged that labor market conditions were stable and close to maximum employment.'),
 row('Several participants noted that dynamism in the labor market was unusually low, with low rates of hiring and layoffs and elevated long-term unemployment.','數位',4),
 row('Participants also discussed developments related to financial conditions.'),
 row('Several participants noted that credit appeared broadly available.','數位',4),
 row('A few participants noted housing financial conditions did not appear supportive with mortgage rates elevated.','少數',6)]
rv=fx.minutes_review(rows)
assert [x['topic'] for x in rv]==['政策路徑','通膨','就業','金融情勢']
assert rv[0]['main']['text']==rows[1]['text'] and rv[0]['other'][0]['text']==rows[2]['text']
assert rv[1]['main']['text']==rows[3]['text']
assert rv[2]['other'][0]['text']==rows[6]['text']
assert rv[3]['main']['text']==rows[8]['text'] and rv[3]['other'][0]['text']==rows[9]['text']
assert all('also discussed developments' not in r['text'] for i in rv for r in [i['main'],*i['other']])
assert rows[1]['topic']=='其他','review must not mutate detailed quotes'
for level,rank in [('全體',0),('多數',2),('數位',4),('少數',6)]:
 assert fx.minutes_count(row(level+' participants',level,rank))==level
assert fx.minutes_count(row('Participants judged inflation elevated.'))=='未明示人數'
assert fx.minutes_count(row('One participant saw labor risks.','一位',8))=='1 人'
assert fx.minutes_count(row('Two participants saw labor risks.','兩位',7))=='2 人'
assert fx.minutes_count(row('A couple of participants saw labor risks.','兩位',7))=='兩位'
assert fx.minutes_fallback('All participants supported lowering the target range.')=='支持本次會議降息。'
assert fx.minutes_fallback('Participants said conditions were stable, but not near maximum employment.')==''
assert fx.minutes_fallback('Unknown economic judgment.')==''
assert fx.minutes_fallback('All participants did not support raising the target range.')==''
item={'kind':'minutes_overview','text':'All participants supported raising the target range by 1/4 percentage point.'}
for bad in ['12人支持升息。','十二人支持升息。','十二位支持升息。','1人支持升息。','明年利率將為5%。','x'*151]:assert not fx._check(item,bad),bad
assert fx._check(item,'全體與會者支持本次升息。')
assert fx._check({'kind':'minutes_extract','text':'One participant saw risks.'},'1人指出風險。')
assert fx._check({'kind':'minutes_extract','text':'Two participants saw risks.'},'兩位與會者指出風險。')
ex=fixtures_fomc.extras();ex['minutes']={'meeting':'2026-09-16','released':'2026-10-07','url':'https://www.federalreserve.gov/example','rows':rows}
with tempfile.TemporaryDirectory() as tmp:
 calls=[]
 def notes(payload,cache,offline):
  calls.append((payload,cache))
  if 'minutes_overview' in payload:return {'minutes_overview':'全體支持本次升息，多數認為年底前可能再升息；通膨降溫進展有限，就業大致穩定。企業信貸仍充裕，房貸利率偏高則限制房市。'}
  return {}
 with patch.object(fx,'ai_notes',side_effect=notes):
  ctx=build.build_fomc_context(fixtures_fomc.build(),{'lower':3.75,'upper':4},[],True,extras=ex,ai_cache=Path(tmp)/'fomc_ai.json')
 assert calls[0][1]!=calls[1][1] and calls[1][1].name=='fomc_minutes_review_ai.json'
 mn=ctx['minutes'];assert len(mn['review'])==4 and mn['overview']
 html=fomc._minutes_html(ctx)
 assert '<table class="mn-table">' in html and '本次紀要重點' in html and 'AI 中文綜述' in html
 assert '<details class="mn-evidence">' in html and '<details class="mn-evidence" open' not in html
 assert all(r['text'] in html for _,rs in mn['groups'] for r in rs)
 assert rows[2]['text'] in html and rows[9]['text'] in html
 assert '未必互相對立' in html and '與會者也不等於投票委員' in html
 mn['overview']='';fallback=fomc._minutes_html(ctx)
 assert '支持本次會議升息' in fallback and '年底前可能適合再升息' in fallback
 assert 'AI 中文綜述' not in fallback
 assert '暫時無法取得' in fomc._minutes_html({})
print('PASS: source selection, current/future distinction, exact counts, numeric safeguards, retained quotes, fallback and build integration')
