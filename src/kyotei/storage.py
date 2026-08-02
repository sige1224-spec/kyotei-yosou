"""予想の答え合わせ・的中率検証結果を蓄積するローカルSQLiteストア。

`kyotei backtest` / `kyotei backtest-day` で過去のレースについて
「その時点の出走表データで予想したら実際の結果と比べてどうだったか」を
継続的に記録し、`kyotei stats` で的中率を確認できるようにする。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from kyotei.models.entities import RacePrediction, RaceResult

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "kyotei.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_code TEXT NOT NULL,
    venue_name TEXT NOT NULL,
    date TEXT NOT NULL,
    race_number INTEGER NOT NULL,
    evaluated_at TEXT NOT NULL,
    predicted_ranking TEXT NOT NULL,
    win_probabilities TEXT NOT NULL,
    actual_ranking TEXT NOT NULL,
    actual_winner_lane INTEGER,
    top1_hit INTEGER NOT NULL,
    top2_hit INTEGER NOT NULL,
    top3_hit INTEGER NOT NULL,
    UNIQUE(venue_code, date, race_number)
);
"""


@dataclass
class BacktestOutcome:
    """1レース分の答え合わせ結果。

    top1_hit: 予想1位のレーンが実際に1着だったか
    top2_hit: 実際の1着が予想上位2レーン以内に入っていたか
    top3_hit: 実際の1着が予想上位3レーン以内に入っていたか
    """

    venue_code: str
    venue_name: str
    date: str
    race_number: int
    predicted_ranking: list[int]
    win_probabilities: dict[int, float]
    actual_ranking: list[int]
    actual_winner_lane: int | None
    top1_hit: bool
    top2_hit: bool
    top3_hit: bool


def evaluate_prediction(prediction: RacePrediction, result: RaceResult) -> BacktestOutcome:
    """予想結果と実際のレース結果を突き合わせる。"""
    ranked = prediction.as_rank_list()
    predicted_ranking = [p.lane for p in ranked]
    win_probabilities = {p.lane: p.win_probability for p in ranked}

    actual_sorted = sorted((e for e in result.entries if e.rank > 0), key=lambda e: e.rank)
    actual_ranking = [e.lane for e in actual_sorted]
    actual_winner_lane = result.winner_lane()

    top1_hit = actual_winner_lane is not None and predicted_ranking[:1] == [actual_winner_lane]
    top2_hit = actual_winner_lane is not None and actual_winner_lane in predicted_ranking[:2]
    top3_hit = actual_winner_lane is not None and actual_winner_lane in predicted_ranking[:3]

    return BacktestOutcome(
        venue_code=prediction.race.venue_code,
        venue_name=prediction.race.venue_name,
        date=prediction.race.date,
        race_number=prediction.race.race_number,
        predicted_ranking=predicted_ranking,
        win_probabilities=win_probabilities,
        actual_ranking=actual_ranking,
        actual_winner_lane=actual_winner_lane,
        top1_hit=bool(top1_hit),
        top2_hit=bool(top2_hit),
        top3_hit=bool(top3_hit),
    )


class BacktestStore:
    """`data/kyotei.db` に答え合わせ結果を永続化するリポジトリ。"""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def save(self, outcome: BacktestOutcome) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO backtests (
                    venue_code, venue_name, date, race_number, evaluated_at,
                    predicted_ranking, win_probabilities, actual_ranking,
                    actual_winner_lane, top1_hit, top2_hit, top3_hit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(venue_code, date, race_number) DO UPDATE SET
                    evaluated_at=excluded.evaluated_at,
                    predicted_ranking=excluded.predicted_ranking,
                    win_probabilities=excluded.win_probabilities,
                    actual_ranking=excluded.actual_ranking,
                    actual_winner_lane=excluded.actual_winner_lane,
                    top1_hit=excluded.top1_hit,
                    top2_hit=excluded.top2_hit,
                    top3_hit=excluded.top3_hit
                """,
                (
                    outcome.venue_code,
                    outcome.venue_name,
                    outcome.date,
                    outcome.race_number,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(outcome.predicted_ranking),
                    json.dumps(outcome.win_probabilities),
                    json.dumps(outcome.actual_ranking),
                    outcome.actual_winner_lane,
                    int(outcome.top1_hit),
                    int(outcome.top2_hit),
                    int(outcome.top3_hit),
                ),
            )
            conn.commit()

    def stats(
        self,
        venue_code: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        query = "SELECT top1_hit, top2_hit, top3_hit FROM backtests WHERE 1=1"
        params: list[str] = []
        if venue_code:
            query += " AND venue_code = ?"
            params.append(venue_code)
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()

        count = len(rows)
        if count == 0:
            return {"count": 0, "top1_rate": 0.0, "top2_rate": 0.0, "top3_rate": 0.0}

        top1 = sum(r[0] for r in rows)
        top2 = sum(r[1] for r in rows)
        top3 = sum(r[2] for r in rows)
        return {
            "count": count,
            "top1_rate": top1 / count,
            "top2_rate": top2 / count,
            "top3_rate": top3 / count,
        }

    def daily_stats(self, venue_code: str | None = None) -> list[dict]:
        """日付ごとの的中率推移（ダッシュボードのグラフ表示用）。"""
        query = (
            "SELECT date, "
            "SUM(top1_hit) AS top1, SUM(top2_hit) AS top2, SUM(top3_hit) AS top3, "
            "COUNT(*) AS count "
            "FROM backtests WHERE 1=1"
        )
        params: list[str] = []
        if venue_code:
            query += " AND venue_code = ?"
            params.append(venue_code)
        query += " GROUP BY date ORDER BY date ASC"

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "date": r[0],
                "top1_rate": r[1] / r[4],
                "top2_rate": r[2] / r[4],
                "top3_rate": r[3] / r[4],
                "count": r[4],
            }
            for r in rows
        ]

    def recent(self, limit: int = 20) -> list[dict]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM backtests ORDER BY date DESC, race_number DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
