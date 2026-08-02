"""3連単オッズページ (owpc/pc/race/odds3t) のパーサー。

ページは「1着艇」ごとに6ブロックが横に並び、各ブロック内は2着艇→3着艇の
入れ子（2着5パターン×3着4パターン=20行）になっている。2着セルは
rowspan="4"で4行に1回しか現れないため、行を4行ひとまとまりのサイクルとして
処理し、直前に見た2着艇の値を持ち越して補完する。
"""
from __future__ import annotations

import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from kyotei.models.entities import TrifectaOdds
from kyotei.scraper._text import safe_float, zenkaku_to_int

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def _find_odds_table(soup: BeautifulSoup):
    for table in soup.select(".table1 table"):
        if table.select_one("td.oddsPoint") is not None:
            return table
    return None


def parse_odds3t_html(html: str, venue_code: str, date: str, race_number: int) -> list[TrifectaOdds]:
    """3連単オッズを全120通り（取得できた分）返す。"""
    soup = BeautifulSoup(html, "lxml")

    table = _find_odds_table(soup)
    if table is None:
        raise ValueError(
            "3連単オッズが見つかりませんでした。まだ発売前か、開催がない可能性があります。"
        )

    header_ths = table.select("thead tr")[0].find_all("th")
    # ヘッダーは [枠番, 名前(colspan2)] のペアが6ブロック分並ぶ
    first_place_lanes = [zenkaku_to_int(header_ths[i * 2].get_text()) for i in range(6)]

    rows = [tr for tbody in table.find_all("tbody") for tr in tbody.find_all("tr", recursive=False)]

    current_second: list[int | None] = [None] * 6
    odds_list: list[TrifectaOdds] = []

    for row_idx, tr in enumerate(rows):
        cells = tr.find_all("td", recursive=False)
        cycle_pos = row_idx % 4

        if cycle_pos == 0:
            for b in range(6):
                if len(cells) < b * 3 + 3:
                    continue
                second = zenkaku_to_int(cells[b * 3].get_text())
                third = zenkaku_to_int(cells[b * 3 + 1].get_text())
                odds_text = cells[b * 3 + 2].get_text(strip=True)
                current_second[b] = second
                _append_odds(odds_list, first_place_lanes[b], second, third, odds_text)
        else:
            for b in range(6):
                if len(cells) < b * 2 + 2:
                    continue
                second = current_second[b]
                if second is None:
                    continue
                third = zenkaku_to_int(cells[b * 2].get_text())
                odds_text = cells[b * 2 + 1].get_text(strip=True)
                _append_odds(odds_list, first_place_lanes[b], second, third, odds_text)

    return odds_list


def _append_odds(
    odds_list: list[TrifectaOdds], first: int, second: int, third: int, odds_text: str
) -> None:
    if not odds_text or not odds_text.strip():
        return
    odds_value = safe_float(odds_text)
    if odds_value <= 0:
        return
    odds_list.append(TrifectaOdds(lanes=(first, second, third), odds=odds_value))
