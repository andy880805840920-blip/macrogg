"""
全站唯一的「現在」與「今天」。

為什麼需要這個檔案
------------------
產出是在 GitHub Actions 的機器上跑的，而那台機器的時鐘是 **UTC**。
直接用 `datetime.now()` 的話，畫面上的「更新於」印出來的是 UTC 時間，
但**沒有標**——台灣讀者看到 `更新於 2026-08-11 14:46` 會理解成下午兩點多，
實際上那是台北時間晚上 22:46。而且 OPERATIONS.md 寫的是「每天晚上 21:45
更新」，排程跑完畫面卻顯示 `13:46`，兩個數字對不起來，
自己過幾個月回來看也會困惑。

比時間戳更麻煩的是**日期**。系統有好幾處拿「今天」做算術：

  · 「N 天前發布」——距上一次資料發布幾天
  · 「距下次發布還有 N 天」的倒數
  · 資料停止更新的判定（月頻超過 75 天沒動就示警）
  · 近 120 天的發債申報視窗

台北時間比 UTC 早 8 小時，所以**台北的 00:00–08:00 之間，UTC 還停在昨天**。
排程是 13:45 UTC 不會踩到，但 push 觸發（改程式或改 config）隨時可能發生：
台北時間凌晨兩點推一版上去，UTC 那邊還是前一天，倒數與「N 天前」會整個差一天。
畫面上看不出錯，只是數字默默少一天。

所以「現在」只能有一個來源，而且必須是**讀者所在的時區**。

為什麼寫死 +8 而不是 zoneinfo("Asia/Taipei")
--------------------------------------------
台灣自 1979 年起沒有夏令時間，UTC+8 是常數，寫死不會錯。
而 `zoneinfo` 要讀作業系統的 tzdata——精簡容器裡常常沒有這包，
一旦缺了就是執行期爆炸。用固定偏移量沒有外部相依，行為完全可預測。
"""

from __future__ import annotations

import datetime as dt

# 台北時間。台灣沒有夏令時間，所以這是常數。
TAIPEI = dt.timezone(dt.timedelta(hours=8), "台北")

# 畫面上標註時區用的後綴。時間戳不標時區等於沒說，
# 因為產出的機器（UTC）跟讀者（UTC+8）差了 8 小時。
TZ_LABEL = "（台北）"


def now() -> dt.datetime:
    """帶時區的現在（台北）。**不要用 datetime.now()**，那是機器的時鐘。"""
    return dt.datetime.now(dt.timezone.utc).astimezone(TAIPEI)


def today() -> dt.date:
    """台北的今天。所有「距今幾天」的算術都要用這個。"""
    return now().date()


def stamp() -> str:
    """畫面用的時間戳，已含時區標註：`2026-08-11 22:46（台北）`。"""
    return now().strftime("%Y-%m-%d %H:%M") + TZ_LABEL


# ---------------------------------------------------------------------------
# 紐約與倫敦時間（首頁「最後更新」用）
#
# 這兩個時區**有夏令時間**，不能像台北一樣寫死偏移。但也不用 zoneinfo
# （精簡容器常缺 tzdata，缺了就是執行期爆炸）——改用規則自己算：
#   美國：3 月第二個週日 02:00 當地（＝07:00 UTC）起 EDT（−4），
#         11 月第一個週日 02:00 當地（＝06:00 UTC）回 EST（−5）
#   英國：3 月最後一個週日 01:00 UTC 起 BST（+1），
#         10 月最後一個週日 01:00 UTC 回 GMT（0）
# 這兩條規則分別由 2005 年美國能源政策法與歐盟指令固定，是常數不是資料。
# ---------------------------------------------------------------------------
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """某月第 n 個星期 X（weekday：一＝0…日＝6）。"""
    first = dt.date(year, month, 1)
    off = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=off + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    last = (dt.date(year, 12, 31) if month == 12
            else dt.date(year, month + 1, 1) - dt.timedelta(days=1))
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def ny_offset(t_utc: dt.datetime) -> int:
    """紐約對 UTC 的偏移（−4 夏令／−5 冬令）。輸入須為 UTC aware。"""
    y = t_utc.year
    start = dt.datetime(y, 3, _nth_weekday(y, 3, 6, 2).day, 7,
                        tzinfo=dt.timezone.utc)
    end = dt.datetime(y, 11, _nth_weekday(y, 11, 6, 1).day, 6,
                      tzinfo=dt.timezone.utc)
    return -4 if start <= t_utc < end else -5


def london_offset(t_utc: dt.datetime) -> int:
    """倫敦對 UTC 的偏移（+1 夏令／0 冬令）。輸入須為 UTC aware。"""
    y = t_utc.year
    start = dt.datetime(y, 3, _last_weekday(y, 3, 6).day, 1,
                        tzinfo=dt.timezone.utc)
    end = dt.datetime(y, 10, _last_weekday(y, 10, 6).day, 1,
                      tzinfo=dt.timezone.utc)
    return 1 if start <= t_utc < end else 0


def world_stamp(t_utc: dt.datetime | None = None) -> str:
    """
    三地時間戳：`2026-08-22 01:44（台北）　·　08-21 13:44（紐約）　·
    08-21 18:44（倫敦）`。

    紐約／倫敦的日期跟台北不同天時（台北清晨對美國是前一天下午）
    才標月-日，同一天只標時分——三組完整日期排在一起反而難掃。
    `t_utc` 參數是給測試用的（固定時刻驗算夏令切換）。
    """
    t = t_utc or now().astimezone(dt.timezone.utc)
    tpe = t.astimezone(TAIPEI)
    parts = [tpe.strftime("%Y-%m-%d %H:%M") + TZ_LABEL]
    for label, off in (("紐約", ny_offset(t)), ("倫敦", london_offset(t))):
        loc = t + dt.timedelta(hours=off)
        fmt = "%H:%M" if loc.date() == tpe.date() else "%m-%d %H:%M"
        parts.append(loc.strftime(fmt) + f"（{label}）")
    return "　·　".join(parts)


def iso() -> str:
    """機器讀的時間戳，含 UTC 偏移：`2026-08-11T22:46:03+08:00`。

    latest.json 與執行紀錄用這個——帶偏移量的 ISO 字串不需要額外約定
    就能還原成絕對時間，日後要跟別的資料源對時也不會出錯。
    """
    return now().isoformat(timespec="seconds")
