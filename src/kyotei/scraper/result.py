"""レース結果ページ (owpc/pc/race/raceresult) のパーサー。

学習データ収集や、ルールベース予想の答え合わせに使う。
"""
from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from kyotei.constants import VENUES

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
from kyotei.models.entities import Payout, RaceResult, RaceResultEntry
from kyotei.scraper._text import normalize_name, safe_int, zenkaku_to_int

_zenkaku_to_int = zenkaku_to_int
_parse_name = normalize_name


def _find_payout_table(soup: BeautifulSoup):
    for table in soup.select("table.is-w495"):
        header_text = table.get_text()
        if "勝式" in header_text and "払戻金" in header_text:
            return table
    return None


def _parse_payouts(soup: BeautifulSoup) -> list[Payout]:
    table = _find_payout_table(soup)
    if table is None:
        return []

    payouts: list[Payout] = []
    for tbody in table.find_all("tbody"):
        rows = tbody.find_all("tr", recursive=False)
        bet_type = ""
        for i, row in enumerate(rows):
            cells = row.find_all("td", recursive=False)
            if i == 0:
                if not cells:
                    continue
                bet_type = cells[0].get_text(strip=True)
                combo_cell, payout_cell, popularity_cell = cells[1], cells[2], cells[3]
            else:
                if len(cells) < 3:
                    continue
                combo_cell, payout_cell, popularity_cell = cells[0], cells[1], cells[2]

            combo_text = combo_cell.get_text(strip=True)
            if not combo_text:
                continue  # 空の予備行（表のセル数を揃えるための余白）

            payout_text = payout_cell.get_text(strip=True)
            amount_match = re.search(r"[\d,]+", payout_text)
            if not amount_match:
                continue
            amount = int(amount_match.group().replace(",", ""))

            popularity_text = popularity_cell.get_text(strip=True)
            popularity = safe_int(popularity_text) if popularity_text.strip() else None

            payouts.append(
                Payout(
                    bet_type=bet_type,
                    combination=combo_text,
                    amount=amount,
                    popularity=popularity,
                )
            )

    return payouts


def parse_raceresult_html(
    html: str, venue_code: str, date: str, race_number: int
) -> RaceResult:
    soup = BeautifulSoup(html, "lxml")

    result_table = soup.select_one("table.is-w495")
    if result_table is None:
        raise ValueError(
            "結果データが見つかりませんでした。レース中止や開催なしの可能性があります。"
        )

    entries: list[RaceResultEntry] = []
    for tbody in result_table.find_all("tbody"):
        row = tbody.find("tr")
        if row is None:
            continue
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        rank = _zenkaku_to_int(cells[0].get_text())
        lane = _zenkaku_to_int(cells[1].get_text())

        spans = cells[2].find_all("span")
        racer_id = _zenkaku_to_int(spans[0].get_text()) if spans else 0
        name = _parse_name(spans[1].get_text(strip=True)) if len(spans) > 1 else ""

        race_time = cells[3].get_text(strip=True)

        entries.append(
            RaceResultEntry(
                rank=rank, lane=lane, racer_id=racer_id, name=name, race_time=race_time
            )
        )

    payouts = _parse_payouts(soup)

    return RaceResult(
        venue_code=venue_code,
        venue_name=VENUES.get(venue_code, venue_code),
        date=date,
        race_number=race_number,
        entries=entries,
        payouts=payouts,
    )
