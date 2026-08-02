"""レース結果ページ (owpc/pc/race/raceresult) のパーサー。

学習データ収集や、ルールベース予想の答え合わせに使う。
"""
from __future__ import annotations

import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from kyotei.constants import VENUES

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
from kyotei.models.entities import RaceResult, RaceResultEntry
from kyotei.scraper._text import normalize_name, zenkaku_to_int

_zenkaku_to_int = zenkaku_to_int
_parse_name = normalize_name


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

    return RaceResult(
        venue_code=venue_code,
        venue_name=VENUES.get(venue_code, venue_code),
        date=date,
        race_number=race_number,
        entries=entries,
    )
