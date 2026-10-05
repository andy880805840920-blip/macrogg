"""
一次性工具：把 us-atlas 的 states-albers-10m.json（已投影成 975×610 的
Albers USA，含阿拉斯加、夏威夷插圖）轉成首頁選舉地圖用的 SVG 路徑，
寫到 src/pages/us_map_data.py。地圖形狀不會變，平常不用再跑。

來源：https://cdn.jsdelivr.net/npm/us-atlas@3/states-albers-10m.json
授權：us-atlas（ISC，© Michael Bostock），底層資料是美國人口普查局的
公有領域地理資料。

用法：python tools/make_us_map.py states-albers-10m.json
"""
import json
import sys
import pathlib

TOL = 0.55          # Douglas–Peucker 容許誤差（像素）：首頁寬度看不出差別


def decode(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def dp(pts, tol):
    if len(pts) < 3:
        return pts
    # 封閉的弧（起點＝終點，島嶼與阿拉斯加常見）：起訖距離為零，直接套
    # 會把整圈都判成「在線上」刪光——先從離起點最遠的點切成兩段再各自簡化
    if len(pts) > 3 and pts[0] == pts[-1]:
        x0, y0 = pts[0]
        k = max(range(1, len(pts) - 1),
                key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
        return dp(pts[:k + 1], tol)[:-1] + dp(pts[k:], tol)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = (dx * dx + dy * dy) ** 0.5 or 1e-9
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / L
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def ring(arcs, ids):
    out = []
    for i in ids:
        a = arcs[i] if i >= 0 else arcs[~i][::-1]
        out.extend(a if not out else a[1:])
    return out


def path(arcs, geom):
    polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
    segs = []
    for poly in polys:
        for r in poly:
            pts = ring(arcs, r)
            if len(pts) < 3:
                continue
            segs.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
    return "".join(segs)


def label_pos(arcs, geom):
    """州名標籤位置：最大那一塊多邊形的面積重心。"""
    polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
    best = None
    for poly in polys:
        pts = ring(arcs, poly[0])
        a = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            cr = x0 * y1 - x1 * y0
            a += cr
            cx += (x0 + x1) * cr
            cy += (y0 + y1) * cr
        if a and (best is None or abs(a) > best[0]):
            best = (abs(a), cx / (3 * a), cy / (3 * a))
    return (round(best[1], 1), round(best[2], 1)) if best else (0, 0)


# 重心落在州外或擠到邊界的幾州，手動微調（像素）
NUDGE = {"Florida": (12, 4), "Louisiana": (-10, -2), "Michigan": (8, 14),
         "Idaho": (0, 14), "Kentucky": (6, 2), "West Virginia": (-3, 3),
         "Virginia": (8, 2), "Minnesota": (-6, 0), "Hawaii": (0, 0)}


def main(src):
    topo = json.loads(pathlib.Path(src).read_text())
    arcs = [dp(a, TOL) for a in decode(topo)]
    out, labels = {}, {}
    for g in topo["objects"]["states"]["geometries"]:
        nm = g["properties"]["name"]
        out[nm] = path(arcs, g)
        x, y = label_pos(arcs, g)
        dx, dy = NUDGE.get(nm, (0, 0))
        labels[nm] = (round(x + dx, 1), round(y + dy, 1))
    dst = pathlib.Path(__file__).resolve().parents[1] / "src" / "pages" / "us_map_data.py"
    body = ("# 自動產生（tools/make_us_map.py）：美國各州 SVG 路徑（Albers USA 投影，含阿拉斯加、夏威夷插圖）。\n"
            "# 來源 us-atlas（ISC 授權，© Michael Bostock；底層為美國人口普查局公有領域資料）。\n"
            "# 請勿手改——要重產就重跑工具。\n"
            "VIEWBOX = (-60, 0, 1035, 612)   # x 起點負值：阿拉斯加西端在 x≈−58\n"
            "PATHS = " + json.dumps(out, ensure_ascii=False, indent=0) + "\n"
            "LABELS = " + json.dumps(labels, ensure_ascii=False) + "\n")
    dst.write_text(body, encoding="utf-8")
    print(dst, len(body), "bytes", len(out), "states")


if __name__ == "__main__":
    main(sys.argv[1])
