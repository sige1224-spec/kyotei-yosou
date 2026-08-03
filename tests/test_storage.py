from pathlib import Path

from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.scraper.result import parse_raceresult_html
from kyotei.models.predictor import predict_race
from kyotei.storage import (
    FAVORITE_RACER,
    FAVORITE_VENUE,
    BacktestStore,
    FavoriteStore,
    OddsSnapshotStore,
    PredictionLogStore,
    evaluate_prediction,
)

RACELIST_FIXTURE = Path(__file__).parent / "fixtures" / "racelist_01_20260802_1.html"
RESULT_FIXTURE = Path(__file__).parent / "fixtures" / "raceresult_01_20260731_1.html"
BEFOREINFO_FIXTURE = Path(__file__).parent / "fixtures" / "beforeinfo_01_20260802_1.html"


def _make_outcome(with_weather: bool = False):
    race = parse_racelist_html(
        RACELIST_FIXTURE.read_text(encoding="utf-8"), "01", "20260802", 1
    )
    result = parse_raceresult_html(
        RESULT_FIXTURE.read_text(encoding="utf-8"), "01", "20260802", 1
    )
    prediction = predict_race(race)
    weather = None
    if with_weather:
        before_info = parse_beforeinfo_html(
            BEFOREINFO_FIXTURE.read_text(encoding="utf-8"), "01", "20260802", 1
        )
        weather = before_info.weather
    return evaluate_prediction(prediction, result, weather=weather)


def test_evaluate_prediction_matches_known_winner():
    outcome = _make_outcome()
    assert outcome.actual_winner_lane == 3
    assert outcome.actual_ranking[0] == 3
    assert outcome.top1_hit == (outcome.predicted_ranking[0] == 3)
    assert outcome.top3_hit == (3 in outcome.predicted_ranking[:3])


def test_store_save_and_stats(tmp_path):
    outcome = _make_outcome()
    store = BacktestStore(db_path=tmp_path / "test.db")
    store.save(outcome)

    stats = store.stats()
    assert stats["count"] == 1

    # 同じレースを再保存しても UPSERT で1件のまま
    store.save(outcome)
    stats_after = store.stats()
    assert stats_after["count"] == 1

    daily = store.daily_stats()
    assert len(daily) == 1
    assert daily[0]["date"] == "20260802"

    recent = store.recent()
    assert len(recent) == 1
    assert recent[0]["venue_code"] == "01"


def test_stats_by_venue(tmp_path):
    outcome = _make_outcome()
    store = BacktestStore(db_path=tmp_path / "test.db")
    store.save(outcome)

    by_venue = store.stats_by_venue()
    assert len(by_venue) == 1
    assert by_venue[0]["venue_code"] == "01"
    assert by_venue[0]["count"] == 1
    assert by_venue[0]["top1_rate"] == float(outcome.top1_hit)


def test_stats_by_confidence_buckets_by_top_pick_probability(tmp_path):
    outcome = _make_outcome()
    store = BacktestStore(db_path=tmp_path / "test.db")
    store.save(outcome)

    by_confidence = store.stats_by_confidence()
    # 4帯すべてが返り、該当するレースがある帯だけcount>0になる
    assert len(by_confidence) == 4
    assert sum(b["count"] for b in by_confidence) == 1
    non_empty = [b for b in by_confidence if b["count"] > 0]
    assert len(non_empty) == 1
    assert non_empty[0]["top1_rate"] == float(outcome.top1_hit)


def test_stats_by_venue_and_confidence_empty_when_no_data(tmp_path):
    store = BacktestStore(db_path=tmp_path / "test.db")
    assert store.stats_by_venue() == []
    by_confidence = store.stats_by_confidence()
    assert all(b["count"] == 0 for b in by_confidence)


def test_favorite_store_add_remove_list(tmp_path):
    store = FavoriteStore(db_path=tmp_path / "test.db")
    assert store.list() == []
    assert not store.is_favorite(FAVORITE_RACER, "4300")

    store.add(FAVORITE_RACER, "4300", "加藤綾")
    store.add(FAVORITE_VENUE, "01", "桐生")
    assert store.is_favorite(FAVORITE_RACER, "4300")
    assert len(store.list()) == 2
    assert len(store.list(kind=FAVORITE_RACER)) == 1

    # 同じkindとkeyでの再addはlabelを更新するだけで件数は増えない
    store.add(FAVORITE_RACER, "4300", "加藤綾(更新)")
    racers = store.list(kind=FAVORITE_RACER)
    assert len(racers) == 1
    assert racers[0]["label"] == "加藤綾(更新)"

    store.remove(FAVORITE_RACER, "4300")
    assert not store.is_favorite(FAVORITE_RACER, "4300")
    assert len(store.list()) == 1


def test_odds_snapshot_store_records_and_returns_history(tmp_path):
    store = OddsSnapshotStore(db_path=tmp_path / "test.db")
    assert store.history("01", "20260802", 1) == []

    store.record("01", "20260802", 1, [("1-2-3", 5.0), ("1-3-2", 8.0)])
    store.record("01", "20260802", 1, [("1-2-3", 5.5), ("1-3-2", 7.5)])

    history = store.history("01", "20260802", 1)
    assert len(history) == 4
    combos = {h["combo"] for h in history}
    assert combos == {"1-2-3", "1-3-2"}

    # 記録なしのentriesは何も保存しない
    store.record("01", "20260802", 1, [])
    assert len(store.history("01", "20260802", 1)) == 4


def test_prediction_log_store_upserts_latest_prediction(tmp_path):
    race = parse_racelist_html(
        RACELIST_FIXTURE.read_text(encoding="utf-8"), "01", "20260802", 1
    )
    prediction = predict_race(race)
    store = PredictionLogStore(db_path=tmp_path / "test.db")

    store.log(prediction)
    entries = store.for_date("20260802")
    assert len(entries) == 1
    assert entries[0]["venue_code"] == "01"
    assert entries[0]["race_number"] == 1

    # 同じレースを再度logしても1件のまま（最新の予想で上書き）
    store.log(prediction)
    assert len(store.for_date("20260802")) == 1
    assert store.for_date("20260801") == []


def test_evaluate_prediction_records_weather_when_provided():
    outcome = _make_outcome(with_weather=True)
    assert outcome.weather == "晴"
    assert outcome.temperature == 30.0
    assert outcome.wind_speed == 5.0
    assert outcome.water_temperature == 24.0
    assert outcome.wave_height == 4.0


def test_evaluate_prediction_weather_none_when_not_provided():
    outcome = _make_outcome(with_weather=False)
    assert outcome.weather is None
    assert outcome.temperature is None


def test_store_save_persists_weather(tmp_path):
    outcome = _make_outcome(with_weather=True)
    store = BacktestStore(db_path=tmp_path / "test.db")
    store.save(outcome)

    recent = store.recent()
    assert recent[0]["weather"] == "晴"
    assert recent[0]["wind_speed"] == 5.0


def test_stats_by_weather(tmp_path):
    store = BacktestStore(db_path=tmp_path / "test.db")
    store.save(_make_outcome(with_weather=True))

    by_weather = store.stats_by_weather()
    assert len(by_weather) == 1
    assert by_weather[0]["weather"] == "晴"
    assert by_weather[0]["count"] == 1


def test_stats_by_weather_excludes_rows_without_weather(tmp_path):
    store = BacktestStore(db_path=tmp_path / "test.db")
    store.save(_make_outcome(with_weather=False))
    assert store.stats_by_weather() == []


def test_stats_by_wind_speed_and_wave_height_buckets(tmp_path):
    store = BacktestStore(db_path=tmp_path / "test.db")
    store.save(_make_outcome(with_weather=True))  # wind_speed=5.0, wave_height=4.0

    by_wind = store.stats_by_wind_speed()
    matching = [b for b in by_wind if b["bucket"] == "3〜6m"]
    assert matching and matching[0]["count"] == 1

    by_wave = store.stats_by_wave_height()
    matching_wave = [b for b in by_wave if b["bucket"] == "3cm以上"]
    assert matching_wave and matching_wave[0]["count"] == 1
