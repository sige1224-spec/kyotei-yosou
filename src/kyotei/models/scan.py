"""当日・複数会場のレースを横断して、狙い目のジャンル別買い目候補をスキャンする。

「今日、この後開催されるレースの中でどこを見るべきか」を横断的に把握する用途。
`backtest.run_day_backtest` と同様、開催のない場・レースは静かにスキップする。
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from kyotei.constants import VENUES
from kyotei.models.entities import RacePrediction
from kyotei.models.genres import GENRE_OOANA, GenreCandidate, categorize_trifecta
from kyotei.models.predictor import DEFAULT_WEIGHTS, PredictorWeights, predict_race
from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.odds import parse_odds3t_html
from kyotei.scraper.racelist import parse_racelist_html


@dataclass
class ScanCandidate:
    venue_code: str
    venue_name: str
    race_number: int
    candidate: GenreCandidate


def scan_races(
    client: BoatraceClient,
    venue_codes: list[str],
    date: str,
    race_numbers: list[int],
    weights: PredictorWeights = DEFAULT_WEIGHTS,
) -> Iterator[tuple[str, int, RacePrediction | None, dict[str, list[GenreCandidate]] | None, Exception | None]]:
    """複数場・複数レースをまとめて予想し、ジャンル分けした買い目候補を1件ずつyieldする。

    出走表が取得できないレース（開催なし・未発表）はスキップ扱いでexceptionを添えてyieldする。
    直前情報・オッズは取得できなくても予想自体は継続する（オッズなしなら本命のみ判定）。
    """
    for code in venue_codes:
        for race_number in race_numbers:
            try:
                racelist_html = client.get_racelist_html(code, date, race_number)
                race = parse_racelist_html(racelist_html, code, date, race_number)
            except Exception as exc:
                yield code, race_number, None, None, exc
                continue

            before_info = None
            try:
                before_html = client.get_beforeinfo_html(code, date, race_number)
                before_info = parse_beforeinfo_html(before_html, code, date, race_number)
            except Exception:
                before_info = None

            prediction = predict_race(race, before_info=before_info, weights=weights)

            odds_list = None
            try:
                odds_html = client.get_odds3t_html(code, date, race_number)
                odds_list = parse_odds3t_html(odds_html, code, date, race_number) or None
            except Exception:
                odds_list = None

            genres = categorize_trifecta(prediction.predictions, odds_list)
            yield code, race_number, prediction, genres, None


def top_candidates(
    client: BoatraceClient,
    venue_codes: list[str],
    date: str,
    race_numbers: list[int],
    genre: str = GENRE_OOANA,
    top_n: int = 10,
    weights: PredictorWeights = DEFAULT_WEIGHTS,
) -> list[ScanCandidate]:
    """指定ジャンルの買い目候補を全場・全レース横断で集め、上位N件を返す。

    大穴（GENRE_OOANA）は期待値（推定確率×オッズ）順、それ以外は推定確率順に並べる。
    オッズ未取得のレースは大穴・中穴の候補が出ないため、実質的にオッズ発表済みのレースのみ対象になる。
    """
    collected: list[ScanCandidate] = []
    for code, race_number, _prediction, genres, error in scan_races(
        client, venue_codes, date, race_numbers, weights=weights
    ):
        if error is not None or genres is None:
            continue
        for candidate in genres.get(genre, []):
            collected.append(
                ScanCandidate(
                    venue_code=code,
                    venue_name=VENUES.get(code, code),
                    race_number=race_number,
                    candidate=candidate,
                )
            )

    if genre == GENRE_OOANA:
        collected.sort(key=lambda sc: sc.candidate.expected_value or 0.0, reverse=True)
    else:
        collected.sort(key=lambda sc: sc.candidate.probability, reverse=True)

    return collected[:top_n]
