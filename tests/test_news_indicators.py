"""New quotes, direction labels, companies and stricter news-topic boundaries."""
import sys,pathlib,json
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import yaml
from src.analysis import focus_today as ft,news_policy as policy
from src.pages import home
cfg=yaml.safe_load((ROOT/'config/focus.yaml').read_text(encoding='utf-8'))
specs=ft.topic_specs(cfg);by={s['id']:s for s in specs};mapping=ft.chip_topic_map(specs)
assert len(specs)==10 and mapping['gold']=='gold' and mapping['twd']==mapping['dxy']=='fx'
assert mapping['live_dgs10']==mapping['live_dgs30']=='long'
assert ft.pick_topics(['twd','dxy','gold','dgs10'],mapping,list(by))==['fx','gold']
assert policy.english_names('輝達與台積電、微軟、谷歌、谷歌母公司和黃仁勳')=='NVIDIA與TSMC、Microsoft、Google、Alphabet和Jensen Huang'
assert policy.english_names('蘋果價格上漲')=='蘋果價格上漲'
assert policy.english_names('蘋果 iPhone 新品')=='Apple iPhone 新品'
assert policy.english_names('Nvidia 和 NVIDIA')=='NVIDIA 和 NVIDIA'
assert policy.topic_excluded('twf',{'title':'台指期夜盤反彈','summary':'主要介紹 etfs 配息'},by['twf']['exclude'])
assert policy.topic_excluded('twf',{'title':'台股外資回補','body':'本篇談指數型基金的申購'},by['twf']['exclude'])
assert not policy.topic_allowed('twf',{'title':'NVIDIA AI revenue rises'})
assert policy.topic_allowed('twf',{'title':'台指期因 AI 股走強而上漲'})
assert policy.topic_allowed('oil',{'title':'美伊衝突升級','summary':'原油出口與油輪運輸受阻'})
assert not policy.topic_allowed('oil',{'title':'美伊外交談判','summary':'討論使館人員安排'})
assert policy.topic_allowed('fx',{'title':'台幣因外資匯入而升值'})
assert policy.topic_allowed('fx',{'title':'Dollar weakens after US payrolls report'})
assert not policy.topic_allowed('fx',{'title':'Indian rupee gains against dollar'})
assert not policy.topic_allowed('long',{'title':'India 10-year government yield falls'})
assert policy.topic_allowed('long',{'title':'US Treasury yields rise before auction'})
# FRED fallback keeps its own source/date and correct TWD direction/precision.
liq={'DEXTAUS':[{'date':'2026-10-01','value':31.98},{'date':'2026-10-02','value':32.01}]}
chip=ft._level_chip('twd',ft.QUOTE_SPECS['twd'],liq,True)
assert chip['value']=='32.010 元' and chip['delta']=='貶0.030' and chip['source']=='FRED'
u=home._unify_chip(chip);assert 'FRED' in u['date'] and '紐約中午' in u['tip']
liq['DEXTAUS'][-1]['value']=31.96
assert ft._level_chip('twd',ft.QUOTE_SPECS['twd'],liq,True)['delta']=='升0.020'
gold=ft._level_chip('gold',ft.QUOTE_SPECS['gold'],{},False,_pre={'value':4051.25,'prev':4000,'date':'2026-10-06'})
assert gold['value']=='4051.25 美元／盎司' and gold['delta']=='+51.25' and '期貨' in home._unify_chip(gold)['tip']
dxy=ft._level_chip('dxy',ft.QUOTE_SPECS['dxy'],{},False,_pre={'value':101.23,'prev':101.01,'date':'2026-10-06'})
assert dxy['value']=='101.23' and dxy['delta']=='+0.22'
# Full-body ETF rejection also removes its displayed source link.
pool=[{'title':'台指期反彈，外資回補','link':'https://example.com/twf','source':'Reuters','summary':''}]
material=ft.gather_topic_material([by['twf']],pool,_fetch=lambda *a,**k:[],_body=lambda u:'台指期文章，但內容主要談 etfs 配息。')
assert 'twf' not in material
news={'text':'輝達由黃仁勳領導','links':[{'title':'台積電投資','link':'https://example.com'}],'topics':[{'text':'微軟發債','links':[]}]};policy.display_news(news)
assert news['text']=='NVIDIA由Jensen Huang領導' and news['links'][0]['link']=='https://example.com'
print('PASS: ten topic mappings; gold/DXY/TWD formats and fallback sources; English companies; ETF title/summary/body rejection; Taiwan/US FX and energy-related conflict boundaries.')

# A failed parallel fetch is not retried sequentially for every missing quote.
assert ft._level_chip('gold',ft.QUOTE_SPECS['gold'],{},False,_pre=None,_get=lambda u:(_ for _ in ()).throw(AssertionError('duplicate request')))['value']=='—'
# Intraday TWD retains the live quote when FRED only has the same date's noon fixing.
same=ft._level_chip('twd',ft.QUOTE_SPECS['twd'],liq,False,_pre={'value':32.015,'prev':32.005,'date':'2026-10-02'})
assert same['source']=='Yahoo' and same['value']=='32.015 元'

assert not policy.topic_allowed('fx',{'title':'Singapore dollar strengthens against US dollar'})
assert not policy.topic_allowed('fx',{'title':'Euro gains as dollar slides'})
assert policy.topic_allowed('fx',{'title':'US dollar weakens against euro after payrolls'})
