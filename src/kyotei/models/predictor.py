"""統計・ルールベースの競艇予想ロジック。

機械学習モデルではなく、公表されている統計的傾向（コース別1着率、
選手・モーター・ボートの勝率/連対率など）を重み付き合成して
レーンごとのスコアを算出する簡易モデル。

直前情報（展示タイム・進入コース）が取得できた場合はそれも加味する。
天候・水面気象情報は影響が状況依存で不確実性が高いため、スコアには
組み込まず、利用者が参考情報として別途確認できるようCLI等で表示するに留める。

あくまで統計的な参考情報であり、的中を保証するものではない。
将来的に結果データが蓄積されたら、この重みや式自体を実データに基づく
モデル（scikit-learn等）に置き換えていく想定。

## 重みの検証について（2026-08-02実施）

`scripts/tune_weights.py` を使い、2026-07-28〜07-30の全24競艇場・480レース分
（backtest-day で収集、`data/cache/` のキャッシュのみでネットワーク不要に再評価）で
以下を検証した。

- **展示タイム重みのablation**: exhibition_time を 0 / 0.5倍 / 2倍 に変えても
  単勝的中率(top1)はほぼ変化なし（39.4%で同一、2倍時のみ2件改善・2件悪化で相殺）。
  → このデータ量・重み範囲では展示タイムの寄与は統計的に有意とは言えなかった。
  値を大きく動かす根拠がないため、控えめな既定値のまま維持している。
- **ランダムサーチ（300パターン）**: 上位候補は軒並み course（コース別1着率の寄与）を
  0.55→0.35〜0.40程度に下げ、local_win_rate（当地勝率）をほぼ0まで下げる方向で
  一致していた。単独の最良候補をそのまま採用すると480レースへの過学習リスクが高いため、
  上位候補群の傾向を参考にした控えめな調整のみ反映（course 0.55→0.45、
  national_win_rate 0.20→0.24、local_win_rate 0.10→0.04、boat_2nd_rate 0.04→0.02）。
  同じ480レースで再評価すると top1 39.4%→40.4%、top2 61.5%→62.1%、
  top3 75.6%→78.8%（改善11件/悪化6件）。
- サンプル数・期間ともまだ限定的（3日分・480レース）。backtest-dayでデータを
  継続的に蓄積し、傾向が変わらないか定期的に再検証すること。
"""
from __future__ import annotations

from dataclasses import dataclass

from kyotei.constants import COURSE_WIN_RATE
from kyotei.models.entities import (
    BeforeInfo,
    ExhibitionEntry,
    LanePrediction,
    RaceCard,
    RacerEntry,
    RacePrediction,
)


@dataclass
class PredictorWeights:
    """各要素の重み。合計値に絶対的な意味はなく、相対比のみが結果に影響する。"""

    # 2026-08-02、480レース分のbacktestデータによるオフライン検証（本ファイル冒頭の
    # docstring参照）を踏まえた値。course/local_win_rate/boat_2nd_rateは検証前の
    # 初期値（0.55/0.10/0.04）から控えめに調整済み。
    course: float = 0.45  # コース別（枠番別）1着率の寄与度
    national_win_rate: float = 0.24  # 全国勝率
    local_win_rate: float = 0.04  # 当地勝率
    motor_2nd_rate: float = 0.08  # モーター2連率
    boat_2nd_rate: float = 0.02  # ボート2連率
    start_timing: float = 0.02  # 平均ST（早いほど有利）
    flying_penalty: float = 0.01  # F（フライング）歴によるリスク減点
    # 展示タイムは0.1秒差でも意味を持つ実測値だが、ablation検証では的中率への
    # 有意な影響は確認できなかった（docstring参照）。動かす根拠がないため据え置き。
    exhibition_time: float = 0.03


DEFAULT_WEIGHTS = PredictorWeights()


def _racer_raw_strength(
    entry: RacerEntry, weights: PredictorWeights, exhibition: ExhibitionEntry | None
) -> float:
    # 当地成績が未蓄積（0.00）の場合は全国勝率で代替する。
    local_win = entry.local_win_rate if entry.local_win_rate > 0 else entry.national_win_rate

    score = 0.0
    score += weights.national_win_rate * entry.national_win_rate * 10  # 0-8点台 -> 0-80台に拡大
    score += weights.local_win_rate * local_win * 10
    score += weights.motor_2nd_rate * entry.motor_2nd_rate
    score += weights.boat_2nd_rate * entry.boat_2nd_rate
    score -= weights.start_timing * entry.avg_start_timing * 100
    score -= weights.flying_penalty * entry.flying_count * 20

    if exhibition is not None and exhibition.exhibition_time > 0:
        score -= weights.exhibition_time * exhibition.exhibition_time * 100

    return score


def _normalize_to_shares(values: dict[int, float]) -> dict[int, float]:
    """負値を含みうる素点を、合計100の非負シェアに変換する。"""
    min_value = min(values.values())
    shifted = {k: v - min_value + 1e-6 for k, v in values.items()}  # 全て正値化
    total = sum(shifted.values())
    return {k: v / total * 100 for k, v in shifted.items()}


def predict_race(
    race: RaceCard,
    before_info: BeforeInfo | None = None,
    weights: PredictorWeights = DEFAULT_WEIGHTS,
) -> RacePrediction:
    """出走表（と、あれば直前情報）から各レーンのスコア・推定勝率を算出する。"""
    if len(race.entries) != 6:
        raise ValueError(f"出走6艇のデータが必要です（{len(race.entries)}件しかありません）")

    exhibitions: dict[int, ExhibitionEntry] = {}
    if before_info is not None:
        exhibitions = {e.lane: e for e in before_info.exhibitions}

    raw_strength = {
        e.lane: _racer_raw_strength(e, weights, exhibitions.get(e.lane)) for e in race.entries
    }
    racer_shares = _normalize_to_shares(raw_strength)  # 合計100の相対シェア

    combined_scores: dict[int, float] = {}
    for entry in race.entries:
        exhibition = exhibitions.get(entry.lane)
        # 進入コースが判明していればそちらを、未確定ならレーン(枠番)をコース扱いにする。
        effective_course = (
            exhibition.entry_course
            if exhibition is not None and exhibition.entry_course is not None
            else entry.lane
        )
        course_component = COURSE_WIN_RATE.get(effective_course, 100 / 6)
        racer_component = racer_shares[entry.lane]
        combined = (
            weights.course * course_component
            + (1 - weights.course) * racer_component
        )
        combined_scores[entry.lane] = combined

    total = sum(combined_scores.values())
    predictions = []
    for entry in race.entries:
        win_probability = combined_scores[entry.lane] / total
        predictions.append(
            LanePrediction(
                lane=entry.lane,
                racer_name=entry.name,
                score=combined_scores[entry.lane],
                win_probability=win_probability,
            )
        )

    return RacePrediction(race=race, predictions=predictions)
