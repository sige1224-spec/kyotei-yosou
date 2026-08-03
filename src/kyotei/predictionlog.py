"""その日実際に見た予想（`kyotei predict` / Webの予想画面）を、後から確定結果と
突き合わせて振り返るための補助関数。

`backtest`系は「過去レースを出走表データの時点で改めて予想し直す」検証用の仕組みだが、
こちらは「その時ユーザーが実際に目にした予想」をそのまま記録し、結果が出た後に
answer合わせする点が異なる（同じ日のうちに答え合わせしたい、という用途）。

結果が確定したレースは`BacktestStore`（`data/kyotei.db`の`backtests`テーブル）にも
記録する。これにより`kyotei predict-all`＋`kyotei today`だけの運用でも、`kyotei stats`/
`kyotei patterns`・Webの「検証ダッシュボード」（日次の的中率・回収率の推移グラフ、
直近の結果一覧）に自動で反映される。改めて`backtest`/`backtest-day`を回さなくても、
毎日の的中率・回収率が積み上がっていく。
"""
from __future__ import annotations

import json
from collections.abc import Iterator

from kyotei.models.entities import LanePrediction, RaceCard, RacePrediction
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.result import parse_raceresult_html
from kyotei.storage import BacktestStore, PredictionLogStore, evaluate_prediction


def compare_logged_predictions(
    client: BoatraceClient,
    log_store: PredictionLogStore,
    date: str,
    backtest_store: BacktestStore | None = None,
) -> Iterator[dict]:
    """指定日にログされた予想を、確定済みなら結果と突き合わせて1件ずつ返す。

    結果がまだ確定していないレース（未実施・進行中）は status="unresolved" で返す。
    確定したレースはbacktest_store（省略時はdata/kyotei.dbの既定インスタンス）にも
    答え合わせ結果を保存する。
    """
    backtest_store = backtest_store or BacktestStore()
    for entry in log_store.for_date(date):
        predicted_ranking = json.loads(entry["predicted_ranking"])
        win_probabilities = json.loads(entry["win_probabilities"])
        base = {
            "venue_code": entry["venue_code"],
            "venue_name": entry["venue_name"],
            "date": entry["date"],
            "race_number": entry["race_number"],
            "logged_at": entry["logged_at"],
            "predicted_top_lane": predicted_ranking[0] if predicted_ranking else None,
            "predicted_top_probability": (
                win_probabilities.get(str(predicted_ranking[0])) if predicted_ranking else None
            ),
        }
        try:
            html = client.get_raceresult_html(entry["venue_code"], entry["date"], entry["race_number"])
            result = parse_raceresult_html(html, entry["venue_code"], entry["date"], entry["race_number"])
        except Exception:
            yield {**base, "status": "unresolved", "actual_winner_lane": None, "top1_hit": None}
            continue

        winner = result.winner_lane()
        if winner is None:
            yield {**base, "status": "unresolved", "actual_winner_lane": None, "top1_hit": None}
            continue

        if predicted_ranking:
            race = RaceCard(
                venue_code=entry["venue_code"],
                venue_name=entry["venue_name"],
                date=entry["date"],
                race_number=entry["race_number"],
                entries=[],
            )
            lane_predictions = [
                LanePrediction(
                    lane=lane,
                    racer_name="",
                    score=0.0,
                    win_probability=win_probabilities.get(str(lane), 0.0),
                )
                for lane in predicted_ranking
            ]
            outcome = evaluate_prediction(RacePrediction(race=race, predictions=lane_predictions), result)
            backtest_store.save(outcome)

        yield {
            **base,
            "status": "resolved",
            "actual_winner_lane": winner,
            "top1_hit": base["predicted_top_lane"] == winner,
        }
