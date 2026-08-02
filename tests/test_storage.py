from pathlib import Path

from kyotei.scraper.racelist import parse_racelist_html
from kyotei.scraper.result import parse_raceresult_html
from kyotei.models.predictor import predict_race
from kyotei.storage import BacktestStore, evaluate_prediction

RACELIST_FIXTURE = Path(__file__).parent / "fixtures" / "racelist_01_20260802_1.html"
RESULT_FIXTURE = Path(__file__).parent / "fixtures" / "raceresult_01_20260731_1.html"


def _make_outcome():
    race = parse_racelist_html(
        RACELIST_FIXTURE.read_text(encoding="utf-8"), "01", "20260802", 1
    )
    result = parse_raceresult_html(
        RESULT_FIXTURE.read_text(encoding="utf-8"), "01", "20260802", 1
    )
    prediction = predict_race(race)
    return evaluate_prediction(prediction, result)


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
