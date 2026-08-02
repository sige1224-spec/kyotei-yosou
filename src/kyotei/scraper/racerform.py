"""選手プロフィール「過去3節成績」ページ (owpc/pc/data/racersearch/back3) のパーサー。

直近3節（開催）ぶんの、レースごとの着順の並びを取得する。通算成績（勝率等）とは別に
「今、調子が良いか悪いか」の参考情報として使う。全国/当地勝率のような蓄積統計と違い、
直近の傾向のみを表すため、天候等と同様に予想スコアには組み込まず参考表示に留める。
"""
from __future__ import annotations

import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from kyotei.models.entities import RecentForm, RecentMeetingResult
from kyotei.scraper._text import zenkaku_to_int


def parse_racer_back3_html(html: str, racer_id: int) -> RecentForm:
    """過去3節成績HTMLをパースしてRecentFormを返す。データがなければ空のmeetingsを返す。"""
    soup = BeautifulSoup(html, "lxml")

    meetings: list[RecentMeetingResult] = []
    for table in soup.select("div.table1 table"):
        for tbody in table.find_all("tbody", recursive=False):
            tr = tbody.find("tr")
            if tr is None:
                continue
            cells = tr.find_all("td", recursive=False)
            if len(cells) < 6:
                continue

            period = cells[0].get_text(" ", strip=True)
            img = cells[1].find("img")
            venue_name = img.get("alt", "").strip() if img else ""
            title = cells[4].get_text(strip=True)

            links = cells[5].find_all("a")
            raw_labels = [a.get_text(strip=True) for a in links]
            finishes = [zenkaku_to_int(label) for label in raw_labels]

            meetings.append(
                RecentMeetingResult(
                    period=period,
                    venue_name=venue_name,
                    title=title,
                    raw_labels=raw_labels,
                    finishes=finishes,
                )
            )

    return RecentForm(racer_id=racer_id, meetings=meetings)
