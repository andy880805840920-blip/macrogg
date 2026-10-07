"""Full data dates and missing-value isolation in shared chart inspection."""
import sys, pathlib, json
from html.parser import HTMLParser
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import charts
class Inspector(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.points=[]; self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if "data-points" in a:self.points=json.loads(a["data-points"])
a=[{"date": f"2026-{1+i//28:02}-{1+i%28:02}","value":4+i/1000} for i in range(200)]
b=[r for r in a if r["date"] != a[72]["date"]]
h=charts.compact_lines([{"label":"2 年","color":"#123","points":a},{"label":"10 年","color":"#456","points":b}],unit="%",months=12)
pts=Inspector(h).points
assert len(pts)==200, "daily points must not be sampled"
assert pts[72]["date"]==a[72]["date"]
assert pts[72]["values"][1]["text"]=="當日無資料", "no same-month substitution"
assert pts[72]["values"][1]["y"] is None
# Date only present in the second series is still selectable.
c=a+[{"date":"2026-08-09","value":5.2}]
pts=Inspector(charts.compact_lines([{"label":"A","color":"#123","points":a},{"label":"B","color":"#456","points":c}])).points
assert pts[-1]["date"]=="2026-08-09" and pts[-1]["values"][0]["text"]=="當日無資料"
pts=Inspector(charts.line_chart(a,unit="%",digits=2)).points
assert len(pts)==200 and pts[0]["x"]==0 and pts[-1]["x"]==100
pts=Inspector(charts.cat_lines([{"label":"現在","color":"#123","points":[("2 年",4),("10 年",5)]}])).points
assert [p["date"] for p in pts]==["2 年","10 年"]
pts=Inspector(charts.stacked_shares([{"label":"A","color":"#123","points":[{"date":"2026-01-01","value":30},{"date":"2026-02-01","value":40}]},{"label":"B","color":"#456","points":[{"date":"2026-01-01","value":70},{"date":"2026-02-01","value":60}]}])).points
assert pts[1]["values"][0]["text"]=="40.0%" and pts[1]["values"][1]["text"]=="60.0%"
print("PASS: all daily dates; union dates; no cross-date substitution; legacy line/category/area inspection")
