"""買い目候補を「本命」「中穴」「大穴」にジャンル分けする。

推定勝率（Harville近似の組み合わせ確率）と、boatrace.jpのオッズページから
取得した実際のオッズを組み合わせて分類する。オッズは発売開始後・レース直前まで
随時変動するため、取得タイミングによって結果は変わりうる。

- 本命（的中重視）: 推定確率が高い順
- 中穴: 推定確率がそこそこ高く、オッズもそれなりに付いている（妙味がある）もの
- 大穴（高配当狙い）: オッズが高い候補の中で、期待値（推定確率×オッズ）が
  高いものを優先。期待値1.0を超えると「このモデル上は買い得」という目安になるが、
  モデル自体の誤差もあるため過信は禁物。

いずれも参考情報であり、的中や回収を保証するものではない。特に大穴genreは
市場のオッズとモデルの推定確率が大きく乖離している候補ほど期待値が高く出やすく、
それは「本当に妙味がある」のではなく「モデルがその組み合わせを過大評価している」
だけの可能性もある。大穴genreについては現状backtestでの回収率検証を行っておらず、
精度は未検証（本命・3連単全体の回収率検証は`storage.py`参照）。
"""
from __future__ import annotations

from dataclasses import dataclass

from kyotei.models.combos import trifecta_candidates
from kyotei.models.entities import LanePrediction, TrifectaOdds

# オッズによる区分の閾値（倍）。中穴と大穴の境目は好みが分かれるため、
# 必要に応じてチューニング可能なようにモジュール定数として切り出している。
MID_ODDS_MIN = 7.0
LONGSHOT_ODDS_MIN = 30.0

GENRE_HONMEI = "本命"
GENRE_CHUANA = "中穴"
GENRE_OOANA = "大穴"


@dataclass
class GenreCandidate:
    genre: str
    lanes: tuple[int, ...]
    label: str
    probability: float
    odds: float | None
    expected_value: float | None  # probability * odds。1.0超で「モデル上は妙味あり」の目安


def categorize_trifecta(
    predictions: list[LanePrediction],
    odds_list: list[TrifectaOdds] | None,
    top_n: int = 5,
) -> dict[str, list[GenreCandidate]]:
    """3連単の全候補を本命/中穴/大穴に分類する。

    odds_listがNone（オッズ未取得）の場合は本命のみ返す。
    """
    all_combos = trifecta_candidates(predictions, top_n=120)
    odds_map = {o.lanes: o.odds for o in odds_list} if odds_list else {}

    def make(candidate, genre: str) -> GenreCandidate:
        odds = odds_map.get(candidate.lanes)
        ev = candidate.probability * odds if odds is not None else None
        return GenreCandidate(
            genre=genre,
            lanes=candidate.lanes,
            label=candidate.label,
            probability=candidate.probability,
            odds=odds,
            expected_value=ev,
        )

    honmei = [
        make(c, GENRE_HONMEI)
        for c in sorted(all_combos, key=lambda c: c.probability, reverse=True)[:top_n]
    ]

    result = {GENRE_HONMEI: honmei, GENRE_CHUANA: [], GENRE_OOANA: []}

    if not odds_map:
        return result

    mid_pool = [
        c for c in all_combos if MID_ODDS_MIN <= odds_map.get(c.lanes, 0) < LONGSHOT_ODDS_MIN
    ]
    result[GENRE_CHUANA] = [
        make(c, GENRE_CHUANA)
        for c in sorted(mid_pool, key=lambda c: c.probability, reverse=True)[:top_n]
    ]

    long_pool = [c for c in all_combos if odds_map.get(c.lanes, 0) >= LONGSHOT_ODDS_MIN]
    result[GENRE_OOANA] = [
        make(c, GENRE_OOANA)
        for c in sorted(
            long_pool,
            key=lambda c: c.probability * odds_map.get(c.lanes, 0),
            reverse=True,
        )[:top_n]
    ]

    return result
