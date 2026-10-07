"""Treasury daily feed/fallback alignment, without network or API keys."""
from pathlib import Path
import copy
import datetime as dt
import json
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import treasury_yields as ty
from src.analysis import longend as le
from src.analysis import focus_today as ft
from src.pages import home

TODAY = dt.date(2026, 10, 7)
def entry(day, values=None, missing=None):
    values = values or {sid: 4 + i / 10 for i, sid in enumerate(ty.FIELDS)}
    cells = ''.join(f'<d:{field}>{values[sid]}</d:{field}>' for sid, field in ty.FIELDS.items() if sid != missing)
    return '<entry><m:properties><d:NEW_DATE>' + day + 'T00:00:00</d:NEW_DATE>' + cells + '</m:properties></entry>'
def xml(*rows):
    return ('<feed xmlns:m="urn:meta" xmlns:d="urn:data">'+''.join(rows)+'</feed>').encode()
class Response:
    def __init__(self, content): self.content = content
    def raise_for_status(self): pass
def fred(days=('2026-10-02', '2026-10-05')):
    return {sid: [{'date': d, 'value': 7 + i / 10} for d in days] for i, sid in enumerate(ty.FIELDS)}
def timeout(*a, **kw): raise TimeoutError('offline')

real = {'DGS3MO': 4.21, 'DGS1': 4.46, 'DGS2': 4.79, 'DGS5': 5.03,
        'DGS7': 5.15, 'DGS10': 5.27, 'DGS20': 5.68, 'DGS30': 5.64}
payload = xml(entry('2026-10-05'), entry('2026-10-06', real),
              entry('2026-10-07', missing='DGS2'), entry('2026-10-08'),
              entry('2026-10-04'), entry('invalid'))
parsed = ty.parse_xml(payload, TODAY)
assert [x['date'] for x in parsed] == ['2026-10-05', '2026-10-06']
assert parsed[-1]['values'] == real, 'Percent values must not be scaled like Yahoo'
for invalid in ('NaN', 'inf', '99', None):
    invalid_values = dict(real, DGS2=invalid)
    assert not ty.parse_xml(xml(entry('2026-10-06', invalid_values)), TODAY)

with tempfile.TemporaryDirectory() as tmp:
    cache = Path(tmp)/'treasury.json'
    requests=[]
    def get(url, **kw):
        requests.append((url,kw))
        return Response(payload if url.endswith('2026') else xml(entry('2025-12-31')))
    s = fred(); s['T10YIE']=[{'date':'2026-10-05','value':2.4}]
    before_be=copy.deepcopy(s['T10YIE'])
    result=ty.merge(s,cache,_get=get,today=TODAY)
    assert result['date']=='2026-10-06' and result['source']=='Treasury'
    assert len(requests)==2 and all(x[1]['timeout']==ty.TIMEOUT for x in requests)
    assert {x[0].split('=')[-1] for x in requests} == {'2025','2026'}
    for sid in ty.FIELDS:
        assert s[sid][-1]=={'date':'2026-10-06','value':real[sid],'source':'Treasury'}
        assert s[sid][1]['date']=='2026-10-02' and s[sid][1]['source']=='FRED', 'Older history retained'
    assert s['T10YIE']==before_be, 'Other FRED indicators must retain their publication dates'
    original=copy.deepcopy(s)
    fallback=fred()
    ty.merge(fallback,cache,_get=timeout,today=TODAY)
    assert fallback['DGS2'][-1]==s['DGS2'][-1], 'Cache must survive a feed outage'
    assert json.loads(cache.read_text())['days'][-1]['date']=='2026-10-06'
    # FRED may already have a complete newer day while the feed/cache is behind.
    newer=fred(('2026-10-05','2026-10-07'))
    ty.merge(newer,cache,_get=timeout,today=TODAY)
    assert all(newer[k][-1]['date']=='2026-10-07' and newer[k][-1]['source']=='FRED' for k in ty.FIELDS)
    # FRED itself may update only some maturities: truncate the partial new day.
    partial=fred()
    for sid in ('DGS10','DGS30'):
        partial[sid].append({'date':'2026-10-07','value':5.5})
    ty.merge(partial,None,_get=timeout,today=TODAY)
    assert {partial[k][-1]['date'] for k in ty.FIELDS} == {'2026-10-05'}
    cache.write_text('{"version":1,"days":[{"date":"2026-10-06","values":{"DGS2":4.79}}]}')
    plain=fred(); ty.merge(plain,cache,_get=timeout,today=TODAY)
    assert plain['DGS2'][-1]['source']=='FRED', 'Malformed cache must not invent a curve'
    plain['DGS10'].append({'date':'2026-10-07','value':5.7,'live':True})
    ty.merge(plain,None,_get=timeout,today=TODAY)
    assert not any(row.get('live') for row in plain['DGS10'])
    years=[]
    ty.merge({},None,_get=lambda url,**kw:(years.append(url) or Response(xml())),today=dt.date(2027,1,1))
    assert {x.split('=')[-1] for x in years}=={'2026','2027'}
    chips={c['id']:c for c in ft.build_catalog(original,{},[],offline=True)}
    for cid,sid in [('dgs2','DGS2'),('dgs10','DGS10'),('dgs30','DGS30')]:
        assert chips[cid]['value']==f'{real[sid]:.2f}%' and chips[cid]['iso']=='2026-10-06'
        display=home._unify_chip(chips[cid]); assert display['date']=='財政部 10/06'
    assert not chips['live_dgs10']['on'] and chips['live_dgs10']['value']=='—'
    snaps=le.curve_snapshots(original)
    assert snaps[0]['date']=='2026-10-06' and len(snaps[0]['points'])==8
    gap=copy.deepcopy(original)
    gap['DGS2']=[x for x in gap['DGS2'] if x['date']!='2026-10-06']
    assert le.curve_snapshots(gap)[0]['date']=='2026-10-05', 'Snapshots must use one shared day'
    cd=le.curve_data(original,'2026-10-01')
    window=le.window_analysis(cd,'2026-10-02','2026-10-06')
    assert window['end']=='2026-10-06' and window['drivers']['be'] is None, 'Do not shift lagging breakeven into latest day'
# Verify the scheduled build merges Treasury before writing SQLite snapshots.
from unittest.mock import patch
import run as runner
from src import fred as fred_module
from src.store import Store
from src.analysis import rates as rates_analysis
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    with patch.object(runner, 'ROOT', root), patch.object(runner, 'SAVE_FIXTURES', False), \
         patch.object(fred_module, 'FredClient') as client, \
         patch.object(fred_module, 'fetch_all', return_value=fred()), \
         patch.object(ty.requests, 'get', side_effect=lambda url,**kw: Response(payload)):
        client.return_value.failed = []
        gathered, _, failed = runner.gather_fred(False, list(ty.FIELDS), 'rates')
    assert not failed and gathered['DGS2'][-1]['value'] == 4.79
    db = Store(root/'data/rates.db')
    assert db.series('DGS10')[-1] == {'date':'2026-10-06','value':5.27}
    db.close()
    assert (root/'state/treasury_yields.json').exists()
    gathered['DFII10']=[{'date':'2026-10-05','value':2.9}]
    gathered['T10YIE']=[{'date':'2026-10-05','value':2.4}]
    assert not rates_analysis.curve_state(gathered).decomposition
    assert le.curve_drivers(gathered)['wow']['be'] is None

print('PASS: Treasury parsing, actual values, atomic dates, cache/FRED fallback, old history, year boundary, source labels, no intraday contamination, aligned snapshots and missing decomposition.')
