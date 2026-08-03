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
    RationaleFactor,
    RecentForm,
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
    # 選手の直近成績（過去3節、3着内率）の寄与度。既定値0で無効
    # （2026-08-02追加。backtestでの効果検証を未実施のため、安易に重みへ組み込むと
    # 過学習のリスクがある。`scripts/tune_weights.py --with-recent-form` で
    # オフライン検証してから値を動かすこと）。
    recent_form_weight: float = 0.0


DEFAULT_WEIGHTS = PredictorWeights()


def _racer_raw_strength(
    entry: RacerEntry,
    weights: PredictorWeights,
    exhibition: ExhibitionEntry | None,
    recent_form: RecentForm | None = None,
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

    if (
        weights.recent_form_weight != 0
        and recent_form is not None
        and recent_form.top3_rate() is not None
    ):
        score += weights.recent_form_weight * recent_form.top3_rate()

    return score


def _normalize_to_shares(values: dict[int, float]) -> dict[int, float]:
    """負値を含みうる素点を、合計100の非負シェアに変換する。"""
    min_value = min(values.values())
    shifted = {k: v - min_value + 1e-6 for k, v in values.items()}  # 全て正値化
    total = sum(shifted.values())
    return {k: v / total * 100 for k, v in shifted.items()}


def _rank_map(values: dict[int, float], ascending: bool = False) -> dict[int, int]:
    """値の大小から1位〜n位の順位を返す（デフォルトは値が大きいほど1位）。"""
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=not ascending)
    return {lane: i + 1 for i, (lane, _) in enumerate(ordered)}


def _favorable(rank: int, field_size: int) -> bool | None:
    """順位が上位/下位グループに入っていれば有利/不利、中位ならNone（中立）。"""
    band = max(1, -(-field_size // 3))  # ceil(field_size / 3)
    if rank <= band:
        return True
    if rank > field_size - band:
        return False
    return None


def _course_adjective(rank: int, field_size: int) -> str:
    if rank == 1:
        return "最も有利なイン"
    favorable = _favorable(rank, field_size)
    if favorable is True:
        return "有利な立場"
    if favorable is False:
        return "不利な立場"
    return "標準的な立場"


def _build_rationale(
    race: RaceCard,
    weights: PredictorWeights,
    exhibitions: dict[int, ExhibitionEntry],
    effective_courses: dict[int, int],
    course_components: dict[int, float],
    win_probabilities: dict[int, float],
) -> dict[int, tuple[str, list[RationaleFactor]]]:
    """各レーンについて「なぜこの順位・勝率になったか」を人が読める形で組み立てる。

    数値そのものではなく、6艇中の順位（相対比較）をベースに文章化する。
    _normalize_to_shares の非線形変換により各要素の寄与度を厳密に分解するのは
    ミスリーディングになりうるため、あえて厳密な内訳ではなく「この艇は他と比べて
    何が強み/弱みか」という納得感重視の説明にしている。
    """
    n = len(race.entries)

    def local_win(e: RacerEntry) -> float:
        return e.local_win_rate if e.local_win_rate > 0 else e.national_win_rate

    course_ranks = _rank_map(course_components)
    national_ranks = _rank_map({e.lane: e.national_win_rate for e in race.entries})
    local_ranks = _rank_map({e.lane: local_win(e) for e in race.entries})
    motor_ranks = _rank_map({e.lane: e.motor_2nd_rate for e in race.entries})
    boat_ranks = _rank_map({e.lane: e.boat_2nd_rate for e in race.entries})
    st_ranks = _rank_map({e.lane: e.avg_start_timing for e in race.entries}, ascending=True)
    exhibition_ranks: dict[int, int] = {}
    valid_exhibitions = {
        lane: ex.exhibition_time for lane, ex in exhibitions.items() if ex.exhibition_time > 0
    }
    if len(valid_exhibitions) >= 2:
        exhibition_ranks = _rank_map(valid_exhibitions, ascending=True)
    win_ranks = _rank_map(win_probabilities)

    # (重み, key, ラベル, 有利時の文言テンプレ, 不利時の文言テンプレ)
    weighted_specs = [
        (
            weights.national_win_rate,
            "national_win_rate",
            "全国勝率",
            lambda e, r: f"全国勝率{e.national_win_rate:.2f}（{n}艇中{r}位）が強み",
            lambda e, r: f"全国勝率{e.national_win_rate:.2f}（{n}艇中{r}位）はやや見劣り",
        ),
        (
            weights.local_win_rate,
            "local_win_rate",
            "当地勝率",
            lambda e, r: f"当地勝率{local_win(e):.2f}（{n}艇中{r}位）と当地実績十分",
            lambda e, r: f"当地勝率{local_win(e):.2f}（{n}艇中{r}位）と当地実績は物足りない",
        ),
        (
            weights.motor_2nd_rate,
            "motor_2nd_rate",
            "モーター2連率",
            lambda e, r: f"モーター2連率{e.motor_2nd_rate:.1f}%（{n}艇中{r}位）と機力面で優位",
            lambda e, r: f"モーター2連率{e.motor_2nd_rate:.1f}%（{n}艇中{r}位）とやや不利な機力",
        ),
        (
            weights.boat_2nd_rate,
            "boat_2nd_rate",
            "ボート2連率",
            lambda e, r: f"ボート2連率{e.boat_2nd_rate:.1f}%（{n}艇中{r}位）と足まわりが良い",
            lambda e, r: f"ボート2連率{e.boat_2nd_rate:.1f}%（{n}艇中{r}位）と足まわりはやや不安",
        ),
        (
            weights.start_timing,
            "start_timing",
            "平均ST",
            lambda e, r: f"平均ST{e.avg_start_timing:.2f}（{n}艇中{r}位）とスタートが速い",
            lambda e, r: f"平均ST{e.avg_start_timing:.2f}（{n}艇中{r}位）とスタートがやや遅め",
        ),
    ]

    result: dict[int, tuple[str, list[RationaleFactor]]] = {}
    for e in race.entries:
        lane = e.lane
        course = effective_courses[lane]
        c_rank = course_ranks[lane]
        course_favorable = _favorable(c_rank, n)
        factors: list[RationaleFactor] = [
            RationaleFactor(
                label="コース取り",
                detail=f"{course}コース想定（1着率目安{course_components[lane]:.1f}%、{n}艇中{c_rank}位）",
                favorable=course_favorable,
            )
        ]

        rank_map_by_key = {
            "national_win_rate": national_ranks,
            "local_win_rate": local_ranks,
            "motor_2nd_rate": motor_ranks,
            "boat_2nd_rate": boat_ranks,
            "start_timing": st_ranks,
        }
        candidate_clauses: list[tuple[float, bool, str]] = []  # (weight, favorable, clause)
        for weight, key, label, fav_tmpl, unfav_tmpl in weighted_specs:
            rank = rank_map_by_key[key][lane]
            favorable = _favorable(rank, n)
            detail = (
                f"{getattr(e, key) if key != 'local_win_rate' else local_win(e):.2f}"
                if key in ("national_win_rate", "local_win_rate")
                else f"{getattr(e, key):.1f}%" if key in ("motor_2nd_rate", "boat_2nd_rate")
                else f"{e.avg_start_timing:.2f}"
            )
            factors.append(
                RationaleFactor(label=label, detail=f"{detail}（{n}艇中{rank}位）", favorable=favorable)
            )
            if favorable is True:
                candidate_clauses.append((weight, True, fav_tmpl(e, rank)))
            elif favorable is False:
                candidate_clauses.append((weight, False, unfav_tmpl(e, rank)))

        if lane in exhibition_ranks:
            ex_rank = exhibition_ranks[lane]
            ex_time = valid_exhibitions[lane]
            ex_favorable = _favorable(ex_rank, len(valid_exhibitions))
            factors.append(
                RationaleFactor(
                    label="展示タイム",
                    detail=f"{ex_time:.2f}秒（{len(valid_exhibitions)}艇中{ex_rank}位）",
                    favorable=ex_favorable,
                )
            )
            if ex_favorable is True:
                candidate_clauses.append(
                    (weights.exhibition_time, True, f"展示タイム{ex_time:.2f}秒（{ex_rank}位）と好調")
                )
            elif ex_favorable is False:
                candidate_clauses.append(
                    (weights.exhibition_time, False, f"展示タイム{ex_time:.2f}秒（{ex_rank}位）とやや周回遅れ気味")
                )

        if e.flying_count > 0:
            factors.append(
                RationaleFactor(
                    label="フライング歴",
                    detail=f"F{e.flying_count}",
                    favorable=False,
                )
            )
            # F歴はリスクとして常に触れておきたいため重みに関わらず優先度を高めに扱う
            candidate_clauses.append((max(weights.flying_penalty, 0.05), False, f"F{e.flying_count}（フライング歴あり）でスタートに注意"))

        candidate_clauses.sort(key=lambda item: item[0], reverse=True)
        favorable_clauses = [c for w, fav, c in candidate_clauses if fav][:2]
        unfavorable_clauses = [c for w, fav, c in candidate_clauses if not fav][:1]
        highlight_clauses = favorable_clauses + unfavorable_clauses

        win_rank = win_ranks[lane]
        summary = (
            f"{course}コース想定で{_course_adjective(c_rank, n)}"
            f"（コース別1着率目安{course_components[lane]:.1f}%、{n}艇中{c_rank}位）。"
        )
        if highlight_clauses:
            summary += "、".join(highlight_clauses) + "。"
        summary += (
            f"総合的な推定勝率は{win_probabilities[lane] * 100:.1f}%で、{n}艇中{win_rank}位の評価。"
        )

        result[lane] = (summary, factors)

    return result


def predict_race(
    race: RaceCard,
    before_info: BeforeInfo | None = None,
    weights: PredictorWeights = DEFAULT_WEIGHTS,
    recent_forms: dict[int, RecentForm | None] | None = None,
) -> RacePrediction:
    """出走表（と、あれば直前情報）から各レーンのスコア・推定勝率を算出する。

    recent_forms を渡すと（racer_id -> RecentForm）、weights.recent_form_weight が
    0以外の場合にスコアへ加味する。既定では0のため通常は渡さなくても結果は変わらない。
    """
    if len(race.entries) != 6:
        raise ValueError(f"出走6艇のデータが必要です（{len(race.entries)}件しかありません）")

    exhibitions: dict[int, ExhibitionEntry] = {}
    if before_info is not None:
        exhibitions = {e.lane: e for e in before_info.exhibitions}

    recent_forms = recent_forms or {}

    raw_strength = {
        e.lane: _racer_raw_strength(
            e, weights, exhibitions.get(e.lane), recent_forms.get(e.racer_id)
        )
        for e in race.entries
    }
    racer_shares = _normalize_to_shares(raw_strength)  # 合計100の相対シェア

    combined_scores: dict[int, float] = {}
    effective_courses: dict[int, int] = {}
    course_components: dict[int, float] = {}
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
        effective_courses[entry.lane] = effective_course
        course_components[entry.lane] = course_component

    total = sum(combined_scores.values())
    win_probabilities = {lane: score / total for lane, score in combined_scores.items()}

    rationales = _build_rationale(
        race, weights, exhibitions, effective_courses, course_components, win_probabilities
    )

    predictions = []
    for entry in race.entries:
        summary, factors = rationales[entry.lane]
        predictions.append(
            LanePrediction(
                lane=entry.lane,
                racer_name=entry.name,
                score=combined_scores[entry.lane],
                win_probability=win_probabilities[entry.lane],
                rationale_summary=summary,
                rationale_factors=factors,
            )
        )

    return RacePrediction(race=race, predictions=predictions)
