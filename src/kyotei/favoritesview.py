"""お気に入り競艇場・お気に入り選手をもとに、今日確認すべきレースをまとめる。

全24場を毎回横断してお気に入り選手を探すと公式サイトへのリクエスト数が
大きくなりすぎるため、対象は「お気に入り競艇場」で開催中のレースに絞る
（お気に入り選手がその中に出走していれば合わせて示す）。より幅広く選手の
出走予定を追いたい場合は、選手プロフィールページ（お気に入り選手一覧の
リンク先）で確認する想定。
"""
from __future__ import annotations

from dataclasses import dataclass

from kyotei.constants import VENUES, venue_code
from kyotei.models.entities import RacePrediction
from kyotei.models.predictor import DEFAULT_WEIGHTS, PredictorWeights, predict_race
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.storage import FAVORITE_RACER, FAVORITE_VENUE, FavoriteStore


@dataclass
class FavoriteRaceMatch:
    venue_code: str
    venue_name: str
    race_number: int
    prediction: RacePrediction
    favorite_racer_lanes: list[int]  # このレースに出走しているお気に入り選手のレーン


def today_favorite_races(
    client: BoatraceClient,
    date: str,
    race_numbers: list[int] | None = None,
    weights: PredictorWeights = DEFAULT_WEIGHTS,
    favorite_store: FavoriteStore | None = None,
) -> list[FavoriteRaceMatch]:
    """お気に入り競艇場で開催中のレースを対象に、お気に入り選手の出走有無も含めてまとめる。"""
    race_numbers = race_numbers or list(range(1, 13))
    favorite_store = favorite_store or FavoriteStore()
    favorite_venue_codes = [venue_code(f["key"]) for f in favorite_store.list(kind=FAVORITE_VENUE)]
    favorite_racer_ids = {int(f["key"]) for f in favorite_store.list(kind=FAVORITE_RACER)}

    matches: list[FavoriteRaceMatch] = []
    for code in favorite_venue_codes:
        for race_number in race_numbers:
            try:
                html = client.get_racelist_html(code, date, race_number)
                race = parse_racelist_html(html, code, date, race_number)
            except Exception:
                continue
            prediction = predict_race(race, weights=weights)
            favorite_lanes = [e.lane for e in race.entries if e.racer_id in favorite_racer_ids]
            matches.append(
                FavoriteRaceMatch(
                    venue_code=code,
                    venue_name=VENUES.get(code, code),
                    race_number=race_number,
                    prediction=prediction,
                    favorite_racer_lanes=favorite_lanes,
                )
            )
    return matches
