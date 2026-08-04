"""予想の答え合わせ・的中率・回収率を蓄積するローカルSQLiteストア。

`kyotei backtest` / `kyotei backtest-day` で過去のレースについて
「その時点の出走表データで予想したら実際の結果と比べてどうだったか」を
継続的に記録し、`kyotei stats` で的中率・回収率を確認できるようにする。

回収率は、実際にレース結果ページに掲載されている払戻金（100円購入時の金額）を
そのまま使って算出する試算値。舟券を実際に購入したわけではなく、あくまで
「毎レース同じ買い方をしていたら」という仮定に基づくシミュレーションであり、
将来の回収を保証するものではない。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from kyotei.models.combos import trifecta_candidates
from kyotei.models.entities import RacePrediction, RaceResult, WeatherInfo

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
    tansho_payout INTEGER NOT NULL DEFAULT 0,
    trifecta_top1_hit INTEGER NOT NULL DEFAULT 0,
    trifecta_top1_payout INTEGER NOT NULL DEFAULT 0,
    weather TEXT,
    temperature REAL,
    wind_speed REAL,
    wind_direction_code INTEGER,
    water_temperature REAL,
    wave_height REAL,
    UNIQUE(venue_code, date, race_number)
);
"""

# 既存DBに後から追加したカラム。古いDBファイルにはALTER TABLEで補う。
_MIGRATION_COLUMNS = [
    ("tansho_payout", "INTEGER NOT NULL DEFAULT 0"),
    ("trifecta_top1_hit", "INTEGER NOT NULL DEFAULT 0"),
    ("trifecta_top1_payout", "INTEGER NOT NULL DEFAULT 0"),
    # 天候データ（2026-08-03追加）。過去に記録した行はNULLのまま
    # （backtestを再実行すればキャッシュ済みレースでも遡って記録される）。
    ("weather", "TEXT"),
    ("temperature", "REAL"),
    ("wind_speed", "REAL"),
    ("wind_direction_code", "INTEGER"),
    ("water_temperature", "REAL"),
    ("wave_height", "REAL"),
]


@dataclass
class BacktestOutcome:
    """1レース分の答え合わせ結果。

    top1_hit: 予想1位のレーンが実際に1着だったか
    top2_hit: 実際の1着が予想上位2レーン以内に入っていたか
    top3_hit: 実際の1着が予想上位3レーン以内に入っていたか
    tansho_payout: 予想1位のレーンに単勝100円を賭けていた場合の払戻金（円、外れなら0）
    trifecta_top1_hit: 3連単の最有力候補（Harville近似1位）が的中したか
    trifecta_top1_payout: その3連単候補に100円を賭けていた場合の払戻金（円、外れなら0）
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
    tansho_payout: int = 0
    trifecta_top1_hit: bool = False
    trifecta_top1_payout: int = 0
    # 天候（backtest実行時にbefore_infoの気象情報が取得できていれば記録。取得できなければNone）。
    # スコアには反映していない予想ロジックとは独立の記録で、荒天と的中率の相関分析に使う。
    weather: str | None = None
    temperature: float | None = None
    wind_speed: float | None = None
    wind_direction_code: int | None = None
    water_temperature: float | None = None
    wave_height: float | None = None


def evaluate_prediction(
    prediction: RacePrediction, result: RaceResult, weather: WeatherInfo | None = None
) -> BacktestOutcome:
    """予想結果と実際のレース結果（着順・払戻金）を突き合わせる。

    weatherを渡すと、そのレース直前の気象情報もBacktestOutcomeに記録する
    （予想ロジックには使わず、後から`stats_by_weather`等で相関分析するための記録用）。
    """
    ranked = prediction.as_rank_list()
    predicted_ranking = [p.lane for p in ranked]
    win_probabilities = {p.lane: p.win_probability for p in ranked}

    actual_sorted = sorted((e for e in result.entries if e.rank > 0), key=lambda e: e.rank)
    actual_ranking = [e.lane for e in actual_sorted]
    actual_winner_lane = result.winner_lane()

    top1_hit = actual_winner_lane is not None and predicted_ranking[:1] == [actual_winner_lane]
    top2_hit = actual_winner_lane is not None and actual_winner_lane in predicted_ranking[:2]
    top3_hit = actual_winner_lane is not None and actual_winner_lane in predicted_ranking[:3]

    tansho_payout = 0
    if predicted_ranking:
        top_lane = str(predicted_ranking[0])
        for payout in result.payouts_for("単勝"):
            if payout.combination == top_lane:
                tansho_payout = payout.amount
                break

    trifecta_top1_hit = False
    trifecta_top1_payout = 0
    top_trifecta = trifecta_candidates(ranked, top_n=1)
    if top_trifecta:
        predicted_label = top_trifecta[0].label
        for payout in result.payouts_for("3連単"):
            if payout.combination == predicted_label:
                trifecta_top1_hit = True
                trifecta_top1_payout = payout.amount
                break

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
        tansho_payout=tansho_payout,
        trifecta_top1_hit=trifecta_top1_hit,
        trifecta_top1_payout=trifecta_top1_payout,
        weather=weather.weather if weather is not None else None,
        temperature=weather.temperature if weather is not None else None,
        wind_speed=weather.wind_speed if weather is not None else None,
        wind_direction_code=weather.wind_direction_code if weather is not None else None,
        water_temperature=weather.water_temperature if weather is not None else None,
        wave_height=weather.wave_height if weather is not None else None,
    )


class BacktestStore:
    """`data/kyotei.db` に答え合わせ結果を永続化するリポジトリ。"""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(_SCHEMA)
            existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(backtests)")}
            for column, coltype in _MIGRATION_COLUMNS:
                if column not in existing_columns:
                    conn.execute(f"ALTER TABLE backtests ADD COLUMN {column} {coltype}")
            conn.commit()

    def save(self, outcome: BacktestOutcome) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO backtests (
                    venue_code, venue_name, date, race_number, evaluated_at,
                    predicted_ranking, win_probabilities, actual_ranking,
                    actual_winner_lane, top1_hit, top2_hit, top3_hit,
                    tansho_payout, trifecta_top1_hit, trifecta_top1_payout,
                    weather, temperature, wind_speed, wind_direction_code,
                    water_temperature, wave_height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(venue_code, date, race_number) DO UPDATE SET
                    evaluated_at=excluded.evaluated_at,
                    predicted_ranking=excluded.predicted_ranking,
                    win_probabilities=excluded.win_probabilities,
                    actual_ranking=excluded.actual_ranking,
                    actual_winner_lane=excluded.actual_winner_lane,
                    top1_hit=excluded.top1_hit,
                    top2_hit=excluded.top2_hit,
                    top3_hit=excluded.top3_hit,
                    tansho_payout=excluded.tansho_payout,
                    trifecta_top1_hit=excluded.trifecta_top1_hit,
                    trifecta_top1_payout=excluded.trifecta_top1_payout,
                    weather=excluded.weather,
                    temperature=excluded.temperature,
                    wind_speed=excluded.wind_speed,
                    wind_direction_code=excluded.wind_direction_code,
                    water_temperature=excluded.water_temperature,
                    wave_height=excluded.wave_height
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
                    outcome.tansho_payout,
                    int(outcome.trifecta_top1_hit),
                    outcome.trifecta_top1_payout,
                    outcome.weather,
                    outcome.temperature,
                    outcome.wind_speed,
                    outcome.wind_direction_code,
                    outcome.water_temperature,
                    outcome.wave_height,
                ),
            )
            conn.commit()

    def stats(
        self,
        venue_code: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        query = (
            "SELECT top1_hit, top2_hit, top3_hit, tansho_payout, "
            "trifecta_top1_hit, trifecta_top1_payout FROM backtests WHERE 1=1"
        )
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
            return {
                "count": 0,
                "top1_rate": 0.0,
                "top2_rate": 0.0,
                "top3_rate": 0.0,
                "tansho_roi": 0.0,
                "trifecta_top1_rate": 0.0,
                "trifecta_roi": 0.0,
            }

        top1 = sum(r[0] for r in rows)
        top2 = sum(r[1] for r in rows)
        top3 = sum(r[2] for r in rows)
        tansho_total = sum(r[3] for r in rows)
        trifecta_hit = sum(r[4] for r in rows)
        trifecta_total = sum(r[5] for r in rows)
        stake = count * 100
        return {
            "count": count,
            "top1_rate": top1 / count,
            "top2_rate": top2 / count,
            "top3_rate": top3 / count,
            # 回収率は100%＝収支トントン。1.0を超えていれば黒字、下回れば赤字。
            "tansho_roi": tansho_total / stake,
            "trifecta_top1_rate": trifecta_hit / count,
            "trifecta_roi": trifecta_total / stake,
        }

    def daily_stats(self, venue_code: str | None = None) -> list[dict]:
        """日付ごとの的中率・回収率推移（ダッシュボードのグラフ表示用）。"""
        query = (
            "SELECT date, "
            "SUM(top1_hit) AS top1, SUM(top2_hit) AS top2, SUM(top3_hit) AS top3, "
            "SUM(tansho_payout) AS tansho_total, SUM(trifecta_top1_payout) AS trifecta_total, "
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
                "top1_rate": r[1] / r[6],
                "top2_rate": r[2] / r[6],
                "top3_rate": r[3] / r[6],
                "tansho_roi": r[4] / (r[6] * 100),
                "trifecta_roi": r[5] / (r[6] * 100),
                "count": r[6],
            }
            for r in rows
        ]

    def monthly_stats(
        self,
        venue_code: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """月ごと（YYYYMM）の的中率・回収率推移（ダッシュボードのグラフ表示用）。

        dateはYYYYMMDD形式の文字列で保存しているため、先頭6文字（YYYYMM）で
        グルーピングする。daily_statsと違い月単位でまとめる分、日々の振れ幅が
        均され、長期トレンドや季節性を見るのに向く。
        """
        query = (
            "SELECT substr(date, 1, 6) AS month, "
            "SUM(top1_hit) AS top1, SUM(top2_hit) AS top2, SUM(top3_hit) AS top3, "
            "SUM(tansho_payout) AS tansho_total, SUM(trifecta_top1_payout) AS trifecta_total, "
            "COUNT(*) AS count "
            "FROM backtests WHERE 1=1"
        )
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
        query += " GROUP BY month ORDER BY month ASC"

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "month": r[0],
                "top1_rate": r[1] / r[6],
                "top2_rate": r[2] / r[6],
                "top3_rate": r[3] / r[6],
                "tansho_roi": r[4] / (r[6] * 100),
                "trifecta_roi": r[5] / (r[6] * 100),
                "count": r[6],
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

    def stats_by_venue(
        self, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        """場ごとの的中率・回収率（どの場で予想精度が良い/悪いかを見る「勝ちパターン分析」用）。"""
        query = (
            "SELECT venue_code, venue_name, "
            "SUM(top1_hit) AS top1, SUM(top2_hit) AS top2, SUM(top3_hit) AS top3, "
            "SUM(tansho_payout) AS tansho_total, SUM(trifecta_top1_payout) AS trifecta_total, "
            "COUNT(*) AS count "
            "FROM backtests WHERE 1=1"
        )
        params: list[str] = []
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        query += " GROUP BY venue_code, venue_name ORDER BY count DESC"

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "venue_code": r[0],
                "venue_name": r[1],
                "count": r[7],
                "top1_rate": r[2] / r[7],
                "top2_rate": r[3] / r[7],
                "top3_rate": r[4] / r[7],
                "tansho_roi": r[5] / (r[7] * 100),
                "trifecta_roi": r[6] / (r[7] * 100),
            }
            for r in rows
        ]

    def stats_by_confidence(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        buckets: list[tuple[float, float, str]] | None = None,
    ) -> list[dict]:
        """予想1位レーンの推定勝率帯ごとに、実際の的中率・回収率を集計する。

        モデルが「自信を持っている」（推定勝率が高い）レースほど実際に当たって
        いるかを確認するための「勝ちパターン分析」。推定勝率とヒット率がおおむね
        比例していれば、モデルの確率の付け方自体は大きく歪んでいないと判断できる。
        """
        buckets = buckets or [
            (0.0, 0.30, "30%未満"),
            (0.30, 0.40, "30〜40%"),
            (0.40, 0.50, "40〜50%"),
            (0.50, 1.01, "50%以上"),
        ]
        query = (
            "SELECT predicted_ranking, win_probabilities, top1_hit, tansho_payout "
            "FROM backtests WHERE 1=1"
        )
        params: list[str] = []
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()

        agg = {label: {"count": 0, "top1": 0, "payout": 0} for _, _, label in buckets}
        for predicted_ranking_json, win_probabilities_json, top1_hit, payout in rows:
            predicted_ranking = json.loads(predicted_ranking_json)
            win_probabilities = json.loads(win_probabilities_json)
            if not predicted_ranking:
                continue
            prob = win_probabilities.get(str(predicted_ranking[0]))
            if prob is None:
                continue
            for lo, hi, label in buckets:
                if lo <= prob < hi:
                    agg[label]["count"] += 1
                    agg[label]["top1"] += top1_hit
                    agg[label]["payout"] += payout
                    break

        result = []
        for _lo, _hi, label in buckets:
            a = agg[label]
            count = a["count"]
            result.append(
                {
                    "bucket": label,
                    "count": count,
                    "top1_rate": (a["top1"] / count) if count else 0.0,
                    "tansho_roi": (a["payout"] / (count * 100)) if count else 0.0,
                }
            )
        return result

    def stats_by_weather(
        self, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        """天候（晴/曇/雨など）ごとの的中率・回収率。天候データが未記録の行は除外する。

        天候はbacktest実行時にbefore_infoが取得できたレースのみ記録される
        （2026-08-03以前に記録した行はNULLのまま。backtestを再実行すればキャッシュ済み
        レースでも遡って記録される）。
        """
        query = (
            "SELECT weather, SUM(top1_hit) AS top1, SUM(top2_hit) AS top2, SUM(top3_hit) AS top3, "
            "SUM(tansho_payout) AS tansho_total, SUM(trifecta_top1_payout) AS trifecta_total, "
            "COUNT(*) AS count "
            "FROM backtests WHERE weather IS NOT NULL AND weather != ''"
        )
        params: list[str] = []
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        query += " GROUP BY weather ORDER BY count DESC"

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "weather": r[0],
                "count": r[6],
                "top1_rate": r[1] / r[6],
                "top2_rate": r[2] / r[6],
                "top3_rate": r[3] / r[6],
                "tansho_roi": r[4] / (r[6] * 100),
                "trifecta_roi": r[5] / (r[6] * 100),
            }
            for r in rows
        ]

    def _stats_by_numeric_bucket(
        self,
        column: str,
        buckets: list[tuple[float, float, str]],
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict]:
        query = f"SELECT {column}, top1_hit, tansho_payout FROM backtests WHERE {column} IS NOT NULL"
        params: list[str] = []
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)

        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()

        agg = {label: {"count": 0, "top1": 0, "payout": 0} for _, _, label in buckets}
        for value, top1_hit, payout in rows:
            for lo, hi, label in buckets:
                if lo <= value < hi:
                    agg[label]["count"] += 1
                    agg[label]["top1"] += top1_hit
                    agg[label]["payout"] += payout
                    break

        result = []
        for _lo, _hi, label in buckets:
            a = agg[label]
            count = a["count"]
            result.append(
                {
                    "bucket": label,
                    "count": count,
                    "top1_rate": (a["top1"] / count) if count else 0.0,
                    "tansho_roi": (a["payout"] / (count * 100)) if count else 0.0,
                }
            )
        return result

    def stats_by_wind_speed(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        buckets: list[tuple[float, float, str]] | None = None,
    ) -> list[dict]:
        """風速帯ごとの実際の的中率・回収率（風が強いと荒れやすいかの目安）。"""
        buckets = buckets or [
            (0.0, 3.0, "3m未満"),
            (3.0, 6.0, "3〜6m"),
            (6.0, 999.0, "6m以上"),
        ]
        return self._stats_by_numeric_bucket("wind_speed", buckets, date_from, date_to)

    def stats_by_wave_height(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        buckets: list[tuple[float, float, str]] | None = None,
    ) -> list[dict]:
        """波高帯ごとの実際の的中率・回収率。"""
        buckets = buckets or [
            (0.0, 1.0, "1cm未満"),
            (1.0, 3.0, "1〜3cm"),
            (3.0, 999.0, "3cm以上"),
        ]
        return self._stats_by_numeric_bucket("wave_height", buckets, date_from, date_to)


_FAVORITES_SCHEMA = """
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(kind, key)
);
"""

FAVORITE_RACER = "racer"
FAVORITE_VENUE = "venue"


class FavoriteStore:
    """お気に入り選手・お気に入り競艇場を `data/kyotei.db` に永続化するリポジトリ。"""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(_FAVORITES_SCHEMA)
            conn.commit()

    def add(self, kind: str, key: str, label: str) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO favorites (kind, key, label, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(kind, key) DO UPDATE SET label=excluded.label",
                (kind, key, label, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    def remove(self, kind: str, key: str) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("DELETE FROM favorites WHERE kind = ? AND key = ?", (kind, key))
            conn.commit()

    def list(self, kind: str | None = None) -> list[dict]:
        query = "SELECT kind, key, label, created_at FROM favorites WHERE 1=1"
        params: list[str] = []
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY created_at DESC"
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(query, params).fetchall()
        return [{"kind": r[0], "key": r[1], "label": r[2], "created_at": r[3]} for r in rows]

    def is_favorite(self, kind: str, key: str) -> bool:
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM favorites WHERE kind = ? AND key = ?", (kind, str(key))
            ).fetchone()
        return row is not None


_ODDS_SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_code TEXT NOT NULL,
    date TEXT NOT NULL,
    race_number INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    combo TEXT NOT NULL,
    odds REAL NOT NULL
);
"""


class OddsSnapshotStore:
    """3連単オッズを取得するたびに記録し、直前までのオッズの推移を追えるようにする。

    バックグラウンドでの定期取得は行わない（サーバー常駐の仕組みがないため）。
    利用者がそのレースを予想画面で複数回開いたタイミングでのみ記録が増える、
    間隔が不定期な「その場しのぎ」の記録である点に注意。
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(_ODDS_SNAPSHOT_SCHEMA)
            conn.commit()

    def record(
        self, venue_code: str, date: str, race_number: int, entries: list[tuple[str, float]]
    ) -> None:
        if not entries:
            return
        captured_at = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executemany(
                "INSERT INTO odds_snapshots "
                "(venue_code, date, race_number, captured_at, combo, odds) VALUES (?, ?, ?, ?, ?, ?)",
                [(venue_code, date, race_number, captured_at, label, odds) for label, odds in entries],
            )
            conn.commit()

    def history(self, venue_code: str, date: str, race_number: int) -> list[dict]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT captured_at, combo, odds FROM odds_snapshots "
                "WHERE venue_code = ? AND date = ? AND race_number = ? "
                "ORDER BY captured_at",
                (venue_code, date, race_number),
            ).fetchall()
        return [{"captured_at": r[0], "combo": r[1], "odds": r[2]} for r in rows]


_PREDICTION_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_code TEXT NOT NULL,
    venue_name TEXT NOT NULL,
    date TEXT NOT NULL,
    race_number INTEGER NOT NULL,
    logged_at TEXT NOT NULL,
    predicted_ranking TEXT NOT NULL,
    win_probabilities TEXT NOT NULL,
    UNIQUE(venue_code, date, race_number)
);
"""


class PredictionLogStore:
    """`kyotei predict` / Webの予想画面で実際に見た予想を記録するリポジトリ。

    同一レースを複数回見た場合は最新の予想で上書きする（同日結果比較ビュー用に
    「その日その時点で何を見ていたか」の記録が目的で、backtestとは別物）。
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(_PREDICTION_LOG_SCHEMA)
            conn.commit()

    def log(self, prediction: RacePrediction) -> None:
        ranked = prediction.as_rank_list()
        predicted_ranking = [p.lane for p in ranked]
        win_probabilities = {p.lane: p.win_probability for p in ranked}
        race = prediction.race
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO prediction_log (
                    venue_code, venue_name, date, race_number, logged_at,
                    predicted_ranking, win_probabilities
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(venue_code, date, race_number) DO UPDATE SET
                    logged_at=excluded.logged_at,
                    predicted_ranking=excluded.predicted_ranking,
                    win_probabilities=excluded.win_probabilities
                """,
                (
                    race.venue_code,
                    race.venue_name,
                    race.date,
                    race.race_number,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(predicted_ranking),
                    json.dumps(win_probabilities),
                ),
            )
            conn.commit()

    def for_date(self, date: str) -> list[dict]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM prediction_log WHERE date = ? ORDER BY race_number ASC, venue_name ASC",
                (date,),
            ).fetchall()
        return [dict(r) for r in rows]
