"""推定勝率から買い目候補（着順の組み合わせ）を算出する。

各レーンの推定1着確率(win_probability)から、Harvilleの公式（Harville, 1973、
競馬の着順確率推定で提案された手法）を使って2着・3着までの組み合わせ確率を
近似する。「1着になった艇を除いた残りの艇で、残り確率を按分して2着以降を
決める」という単純化されたモデルで、実際のレース展開の相関（例: ある艇が
1着を取る展開だと別の艇が不利になる、など）までは表現できない。

あくまで推定勝率から機械的に導いた参考情報であり、的中や回収を保証するものではない。
舟券の購入・投票自体は本アプリの対象外（表示のみ）。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

from kyotei.models.entities import LanePrediction


@dataclass
class TicketCandidate:
    bet_type: str  # "3連単" / "2連単" / "3連複"
    lanes: tuple[int, ...]  # 3連単/2連単は着順どおり、3連複は昇順
    probability: float

    @property
    def label(self) -> str:
        sep = "=" if self.bet_type == "3連複" else "-"
        return sep.join(str(lane) for lane in self.lanes)


def _harville_ordered_probabilities(
    win_probs: dict[int, float], size: int
) -> list[tuple[tuple[int, ...], float]]:
    """Harvilleの公式で、指定着順数(size)ぶんの全順列とその確率を返す。"""
    lanes = list(win_probs.keys())
    results: list[tuple[tuple[int, ...], float]] = []
    for order in permutations(lanes, size):
        prob = 1.0
        remaining = 1.0
        valid = True
        for lane in order:
            if remaining <= 1e-9:
                valid = False
                break
            prob *= win_probs[lane] / remaining
            remaining -= win_probs[lane]
        if valid:
            results.append((order, prob))
    return results


def trifecta_candidates(
    predictions: list[LanePrediction], top_n: int = 6
) -> list[TicketCandidate]:
    """3連単（1-2-3着を着順どおり）の上位候補。"""
    win_probs = {p.lane: p.win_probability for p in predictions}
    ordered = _harville_ordered_probabilities(win_probs, 3)
    ordered.sort(key=lambda item: item[1], reverse=True)
    return [
        TicketCandidate(bet_type="3連単", lanes=order, probability=prob)
        for order, prob in ordered[:top_n]
    ]


def exacta_candidates(
    predictions: list[LanePrediction], top_n: int = 6
) -> list[TicketCandidate]:
    """2連単（1-2着を着順どおり）の上位候補。"""
    win_probs = {p.lane: p.win_probability for p in predictions}
    ordered = _harville_ordered_probabilities(win_probs, 2)
    ordered.sort(key=lambda item: item[1], reverse=True)
    return [
        TicketCandidate(bet_type="2連単", lanes=order, probability=prob)
        for order, prob in ordered[:top_n]
    ]


def trio_candidates(
    predictions: list[LanePrediction], top_n: int = 6
) -> list[TicketCandidate]:
    """3連複（1-2-3着の組み合わせ、順不同）の上位候補。"""
    win_probs = {p.lane: p.win_probability for p in predictions}
    ordered = _harville_ordered_probabilities(win_probs, 3)
    combo_probs: dict[tuple[int, ...], float] = {}
    for order, prob in ordered:
        key = tuple(sorted(order))
        combo_probs[key] = combo_probs.get(key, 0.0) + prob
    ranked = sorted(combo_probs.items(), key=lambda item: item[1], reverse=True)
    return [
        TicketCandidate(bet_type="3連複", lanes=combo, probability=prob)
        for combo, prob in ranked[:top_n]
    ]
