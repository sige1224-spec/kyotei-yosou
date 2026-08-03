from pathlib import Path

from kyotei.models.predictor import predict_race
from kyotei.predictionlog import compare_logged_predictions
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.storage import BacktestStore, PredictionLogStore

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeClient:
    """20260731の1Rだけ結果が確定している想定のフェイククライアント。"""

    def get_raceresult_html(self, venue_code: str, date: str, race_number: int) -> str:
        if date == "20260731" and race_number == 1:
            return (FIXTURES / "raceresult_01_20260731_1.html").read_text(encoding="utf-8")
        raise ValueError("結果が見つかりませんでした（テスト用: 未確定扱い）")


def _log_prediction(store: PredictionLogStore, date: str, race_number: int = 1):
    race = parse_racelist_html(
        (FIXTURES / "racelist_01_20260802_1.html").read_text(encoding="utf-8"),
        "01",
        date,
        race_number,
    )
    prediction = predict_race(race)
    store.log(prediction)
    return prediction


def test_compare_logged_predictions_resolves_finished_race(tmp_path):
    store = PredictionLogStore(db_path=tmp_path / "test.db")
    backtest_store = BacktestStore(db_path=tmp_path / "test.db")
    prediction = _log_prediction(store, "20260731")

    rows = list(
        compare_logged_predictions(_FakeClient(), store, "20260731", backtest_store=backtest_store)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "resolved"
    assert row["actual_winner_lane"] == 3
    predicted_top = prediction.as_rank_list()[0].lane
    assert row["predicted_top_lane"] == predicted_top
    assert row["top1_hit"] == (predicted_top == 3)


def test_compare_logged_predictions_persists_to_backtest_store(tmp_path):
    """予想ログ経由のレビューも、後からkyotei stats/patterns/検証ダッシュボードで
    参照できるようbacktestsテーブルに保存される。"""
    store = PredictionLogStore(db_path=tmp_path / "test.db")
    backtest_store = BacktestStore(db_path=tmp_path / "test.db")
    _log_prediction(store, "20260731")

    list(compare_logged_predictions(_FakeClient(), store, "20260731", backtest_store=backtest_store))

    stats = backtest_store.stats()
    assert stats["count"] == 1

    recent = backtest_store.recent()
    assert recent[0]["venue_code"] == "01"
    assert recent[0]["race_number"] == 1
    assert recent[0]["actual_winner_lane"] == 3


def test_compare_logged_predictions_unresolved_when_no_result(tmp_path):
    store = PredictionLogStore(db_path=tmp_path / "test.db")
    backtest_store = BacktestStore(db_path=tmp_path / "test.db")
    _log_prediction(store, "20260801")

    rows = list(
        compare_logged_predictions(_FakeClient(), store, "20260801", backtest_store=backtest_store)
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "unresolved"
    assert rows[0]["actual_winner_lane"] is None
    assert rows[0]["top1_hit"] is None
    assert backtest_store.stats()["count"] == 0  # 未確定分はbacktestsに保存されない


def test_compare_logged_predictions_empty_for_date_with_no_logs(tmp_path):
    store = PredictionLogStore(db_path=tmp_path / "test.db")
    backtest_store = BacktestStore(db_path=tmp_path / "test.db")
    rows = list(
        compare_logged_predictions(_FakeClient(), store, "20260101", backtest_store=backtest_store)
    )
    assert rows == []
