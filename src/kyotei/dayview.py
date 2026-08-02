"""同一開催日・同一会場の他レース結果をまとめて取得する補助関数。

「この会場、今日ここまでのレース結果」を表示する用途。未実施・データなしの
レースは静かにスキップする（開催前・進行中はまだ結果ページが存在しないため）。
"""
from __future__ import annotations

from kyotei.models.entities import RaceResult
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.result import parse_raceresult_html


def fetch_day_results(
    client: BoatraceClient, venue_code: str, date: str, race_numbers: list[int]
) -> list[RaceResult]:
    """指定したレース番号群の結果を取得する。未実施・データなしはスキップする。"""
    results: list[RaceResult] = []
    for race_number in race_numbers:
        try:
            html = client.get_raceresult_html(venue_code, date, race_number)
            result = parse_raceresult_html(html, venue_code, date, race_number)
        except Exception:
            continue
        if result.entries:
            results.append(result)
    return results
