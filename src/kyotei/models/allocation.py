"""予算を買い目候補に配分する。

推定確率に比例して、舟券の最低購入単位（100円）刻みで割り振る。
実際の購入・投票は行わない。あくまで金額配分の目安を計算するだけ。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

BET_UNIT = 100


class _HasProbabilityAndLabel(Protocol):
    """TicketCandidate(combos.py)・GenreCandidate(genres.py)のどちらも満たす最小要件。"""

    probability: float
    label: str


@dataclass
class BudgetAllocation:
    candidate: Any  # TicketCandidate または GenreCandidate
    amount: int  # 円（100円単位）

    @property
    def expected_return(self) -> float | None:
        """候補にoddsが付与されていれば（GenreCandidate等）、当たった場合の払戻目安。"""
        odds = getattr(self.candidate, "odds", None)
        if odds is None:
            return None
        return self.amount * odds


def allocate_budget(
    candidates: list[_HasProbabilityAndLabel], budget: int, unit: int = BET_UNIT
) -> list[BudgetAllocation]:
    """推定確率に比例して予算を配分する（100円単位、端数は確率上位から配分）。"""
    if not candidates or budget < unit:
        return []

    total_weight = sum(max(c.probability, 0.0) for c in candidates)
    if total_weight <= 0:
        weights = [1 / len(candidates)] * len(candidates)
    else:
        weights = [max(c.probability, 0.0) / total_weight for c in candidates]

    max_units = budget // unit
    raw_units = [budget * w / unit for w in weights]
    units = [int(u) for u in raw_units]  # 切り捨て

    allocated_units = sum(units)
    leftover_units = max_units - allocated_units

    # 端数(切り捨てで浮いた分)を、確率が高い順に1単位ずつ配る
    order = sorted(range(len(candidates)), key=lambda i: candidates[i].probability, reverse=True)
    i = 0
    while leftover_units > 0 and order:
        units[order[i % len(order)]] += 1
        leftover_units -= 1
        i += 1

    return [
        BudgetAllocation(candidate=c, amount=u * unit)
        for c, u in zip(candidates, units)
        if u > 0
    ]
