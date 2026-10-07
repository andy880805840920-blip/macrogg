"""Directional pricing must follow data, distinguish policy, and handle missing data."""
import sys,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.analysis import longend as le
from src.pages import longend as page
up=[{"gap_bp":v,"mom_bp":m} for v,m in zip([74,29,42,13],[60,55,46,35])]
v=le.future_view(up,{"r0":3.875,"market_end":4.14,"year":2026})
assert "均高於" in v["headline"] and "全部上修" in v["recent"]
assert "偏升" in v["policy"]["title"] and v["policy"]["change"]=="+27bp"
v=le.future_view([{"gap_bp":-50,"mom_bp":-20}],{"r0":4,"market_end":3})
assert "均低於" in v["headline"] and "全部下修" in v["recent"] and "偏降" in v["policy"]["title"]
assert "分歧" in le.future_view([{"gap_bp":20,"mom_bp":30},{"gap_bp":-20,"mom_bp":-30}],None)["headline"]
v=le.future_view([],None);assert "不足" in v["headline"] and v["policy"] is None
assert "大致持平" in le.future_view([{"gap_bp":0,"mom_bp":0}],{"r0":4,"market_end":4.01})["policy"]["title"]
cd={"d":["2026-10-02","2026-10-05"],"y2":[4.83,4.84],"y10":[5.28,5.31],"y30":[5.63,5.66],"be":[2.4,2.41],"real":[2.88,2.90],"tp":[0.7,None],"y3m":[4.19,4.22],"oil":[70,71]}
r=le.window_analysis(cd,*cd["d"]);v=le.window_view(r)
assert len(v["panels"])==3 and "實質利率" in v["panels"][1]["verdict"]
assert r["drivers"]["tp_dates"]==["2026-10-02","2026-10-02"]
cd["real"][-1]=2.93
assert "尚未吻合" in le.window_view(le.window_analysis(cd,*cd["d"]))["panels"][1]["verdict"]
cd["real"][-1]=None;cd["y3m"][-1]=None
v=le.window_view(le.window_analysis(cd,*cd["d"]));assert "資料不足" in v["panels"][1]["verdict"] and "資料不足" in v["panels"][2]["verdict"]
# Missing one tenor on the latest day: forward and spot must share an actual date.
series={k:[{"date":"2026-10-02","value":v},{"date":"2026-10-05","value":v+.1}] for k,v in [("DGS1",4),("DGS2",4.5),("DGS5",4.7),("DGS10",5),("DGS20",5.2),("DGS30",5.3)]}
series["DGS1"][-1]["value"]=None
f=le.forwards(series);assert f[0]["date"]=="2026-10-02" and abs(f[0]["fwd"]-le._fwd(4,1,4.5,2))<1e-9
series["DGS1"]=[{"date":"2026-09-01","value":4}]
assert all(x["key"]!="1y1y" for x in le.forwards(series)), "stale aligned data must not be presented as current"
flat={"d":["2026-10-02","2026-10-05"],"y2":[4,4],"y10":[5,5],"y30":[6,6],"be":[2,2],"real":[3,3],"y3m":[4,4]}
assert "大致持平" in le.window_view(le.window_analysis(flat,*flat["d"]))["panels"][1]["verdict"]
flat["be"]=[2,2.1];flat["real"]=[3,2.9]
assert "抵銷" in le.window_view(le.window_analysis(flat,*flat["d"]))["panels"][1]["verdict"]
print("PASS: higher/lower/mixed/flat/missing outlook; policy distinction; aligned forward dates; decomposition guards")
