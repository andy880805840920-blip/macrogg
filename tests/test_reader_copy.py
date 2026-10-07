"""Reader-facing warnings keep dates and sources while hiding operational failures."""
from pathlib import Path
from html.parser import HTMLParser
from dataclasses import replace
import sys,re,yaml
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src import build,fixtures,fixtures_rates
from src.pages import rates,labor,fomc,election
class Visible(HTMLParser):
 def __init__(self):super().__init__();self.skip=0;self.parts=[]
 def handle_starttag(self,t,a):
  if t in ('script','style'):self.skip+=1
 def handle_endtag(self,t):
  if t in ('script','style'):self.skip-=1
 def handle_data(self,s):
  if not self.skip:self.parts.append(s)
def text(html):
 p=Visible();p.feed(html);return ' '.join(p.parts)
for p in (ROOT/'output').rglob('*.html'):
 body=text(p.read_text(encoding='utf-8'))
 for phrase in ['config/rates.yaml','SEC_USER_AGENT','User-Agent','--offline','每天 3 次建置','每次執行結果一致','機械比對','固定規則產生','不是 AI','全部是確定性規則','先前的「客觀訊號分數」','使用者要求','你的提示詞']:
  assert phrase not in body,(str(p),phrase)
assert '資料來源' in text((ROOT/'output/rates/index.html').read_text(encoding='utf-8'))
cfg=yaml.safe_load((ROOT/'config/rates.yaml').read_text(encoding='utf-8'))
ctx=build.build_rates_context(cfg,fixtures_rates.build(),[],True)
for count in (0,1):
 ctx['hyperscalers']=replace(ctx['hyperscalers'],verified=False,n_from_sec=count)
 body=text(rates.rates_body(ctx))
 assert ('本區資料尚未更新' if count==0 else '部分公司資料尚未更新') in body
 assert '期別' in body and '未取自 SEC' in body
 assert 'config/rates.yaml' not in body and 'SEC_USER_AGENT' not in body
cfg=yaml.safe_load((ROOT/'config/indicators.yaml').read_text(encoding='utf-8'))
labels={x['id']:x.get('label',x['id']) for g in cfg.values() if isinstance(g,list) for x in g if isinstance(x,dict) and 'id' in x}
ctx=build.build_labor_context(cfg,fixtures.build(),fixtures.build_vintages(),labels,{},[('PAYEMS','HTTP 403 token=secret-demo')],True)
body=text(labor.labor_body(ctx))
assert '非農就業總數：資料暫缺' in body and 'secret-demo' not in body and 'HTTP 403' not in body
assert '期貨資料暫缺' in text(fomc._market_html({}))
assert '資料暫缺' in text(election._chamber2('參議院',None))
print('PASS: all rendered pages omit operational copy; full/partial stale data warnings retain source and period; raw fetch errors are hidden and missing indicators use readable names.')
