from kyotei.models.allocation import BET_UNIT, allocate_budget
from kyotei.models.combos import TicketCandidate


def _candidates():
    return [
        TicketCandidate(bet_type="3連単", lanes=(1, 2, 3), probability=0.4),
        TicketCandidate(bet_type="3連単", lanes=(2, 1, 3), probability=0.3),
        TicketCandidate(bet_type="3連単", lanes=(1, 3, 2), probability=0.2),
        TicketCandidate(bet_type="3連単", lanes=(3, 1, 2), probability=0.1),
    ]


def test_allocation_uses_full_budget_in_100yen_units():
    allocations = allocate_budget(_candidates(), budget=1000)
    total = sum(a.amount for a in allocations)
    assert total == 1000
    assert all(a.amount % BET_UNIT == 0 for a in allocations)


def test_higher_probability_gets_more_or_equal_amount():
    allocations = allocate_budget(_candidates(), budget=1000)
    by_lanes = {a.candidate.lanes: a.amount for a in allocations}
    assert by_lanes[(1, 2, 3)] >= by_lanes[(2, 1, 3)] >= by_lanes[(1, 3, 2)] >= by_lanes[(3, 1, 2)]


def test_budget_below_unit_returns_empty():
    assert allocate_budget(_candidates(), budget=50) == []


def test_empty_candidates_returns_empty():
    assert allocate_budget([], budget=1000) == []


def test_small_budget_still_fully_allocated():
    allocations = allocate_budget(_candidates(), budget=300)
    total = sum(a.amount for a in allocations)
    assert total == 300
