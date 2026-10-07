"""Weekly change units, calendar anchoring, holidays, missing dates and JS parity."""
import sys,pathlib,datetime as dt,json,subprocess,shutil,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis.curve_weekly import weekly_spreads
from src.pages.curve_weekly import WEEKLY_CORE_JS,weekly_chart
from src.pages import longend as page
from src.analysis import longend as le

start=dt.date(2026,8,10);dates=[];a=[];b=[]
for i in range(58):
 d=start+dt.timedelta(days=i)
 if d.weekday()<5 and d.isoformat()!='2026-09-07':
  dates.append(d.isoformat());a.append(4+i*.001);b.append(5+i*.002)
cd={'d':dates,'y2':a,'y30':b,'y10':[4.5]*len(dates),'y3m':[4]*len(dates)}
r=weekly_spreads(cd,cutoff='2026-10-06')
assert len(r['rows'])==6 and r['rows'][-1]['target']=='2026-10-06'
assert abs(r['rows'][-1]['change']-.7)<1e-8
assert r['rows'][0]['target']=='2026-09-01' and r['rows'][0]['from']=='2026-08-25'
weekend=weekly_spreads(cd,cutoff='2026-10-04');assert weekend['rows'][-1]['to']=='2026-10-02' and weekend['rows'][-1]['from']=='2026-09-25'
holiday=weekly_spreads(cd,cutoff='2026-09-07');assert holiday['rows'][-1]['to']=='2026-09-04'
# Use the same actual day for both yields; a missing 30Y falls back as a pair.
missing={**cd,'y30':list(b)};missing['y30'][-1]=None
m=weekly_spreads(missing,cutoff=dates[-1]);assert m['rows'][-1]['to']==dates[-2]
short={k:v[-3:] for k,v in cd.items()};assert all(r['change'] is None for r in weekly_spreads(short,cutoff='2026-10-06')['rows'])
stale=weekly_spreads(cd,cutoff='2026-11-20');assert stale['rows'][-1]['change'] is None
future=weekly_spreads(cd,cutoff='2026-10-02');assert all((r['to'] or '')<='2026-10-02' for r in future['rows'])
custom=weekly_spreads(cd,start='2026-09-15',end='2026-10-06',cutoff='2026-10-06');assert len(custom['rows'])==4
try:weekly_spreads(cd,start='2026-10-06',end='2026-09-15',cutoff='2026-10-06');assert False
except ValueError:pass
cases=[(c,s,e,cut) for c in [cd,missing,short] for s,e,cut in [(None,'2026-10-06','2026-10-06'),(None,'2026-10-04','2026-10-04'),('2026-09-15','2026-10-06','2026-10-06'),(None,'2026-09-07','2026-09-07')]]
node=shutil.which('node')
assert node,'Node is required to check the browser calculation.'
with tempfile.TemporaryDirectory() as td:
 p=pathlib.Path(td)/'weekly.js';p.write_text(WEEKLY_CORE_JS+'\nconst cases='+json.dumps(cases)+';console.log(JSON.stringify(cases.map(c=>cwWeekly(...c))));',encoding='utf-8')
 results=json.loads(subprocess.run([node,str(p)],capture_output=True,text=True,encoding='utf-8',check=True).stdout)
assert results==[weekly_spreads(c,start=s,end=e,cutoff=cut) for c,s,e,cut in cases]
html=weekly_chart(cd,cutoff='2026-10-06');assert html.split('<script',1)[0].count('class="ww-bar"')==6 and '2026-08-25' in html
h=page.curve({'le':{'cw':cd,'cw_year':2026,'yield_chart':'HISTORY_YIELDS','curve_chart':'CURVE_SNAPSHOTS','spreads':[{'key':'30-2','value':100,'chart':'HISTORY_SPREADS'}]}})
assert h.count('class="cw-panel cw-fold"')==3 and 'future-section" open' not in h
assert 'HISTORY_YIELDS' in h and 'HISTORY_SPREADS' in h and 'CURVE_SNAPSHOTS' in h
assert '利差型態補充' in h and '接下來看什麼' in h and '方法與限制' in h
assert '30 年 − 10 年' in h and '30 年 − 2 年' in h
print('PASS: six rolling weekly bp changes; weekend/holiday/common dates; missing/stale/future data; custom range; 12 Python/JS parity cases; original content preserved.')

