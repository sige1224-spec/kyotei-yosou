from kyotei.models.combos import trifecta_candidates
from kyotei.models.entities import LanePrediction, TrifectaOdds
from kyotei.models.genres import GENRE_CHUANA, GENRE_HONMEI, GENRE_OOANA, categorize_trifecta


def _predictions() -> list[LanePrediction]:
    probs = {1: 0.5, 2: 0.15, 3: 0.15, 4: 0.1, 5: 0.06, 6: 0.04}
    return [
        LanePrediction(lane=lane, racer_name=f"racer{lane}", score=p, win_probability=p)
        for lane, p in probs.items()
    ]


def _synthetic_odds(predictions: list[LanePrediction]) -> list[TrifectaOdds]:
    # 単純化: オッズ ≒ 1/確率 * ノイズなしの理論値に少しの控除率を掛けたもの
    combos = trifecta_candidates(predictions, top_n=120)
    return [TrifectaOdds(lanes=c.lanes, odds=round(0.75 / c.probability, 1)) for c in combos]


def test_without_odds_only_honmei_is_populated():
    preds = _predictions()
    result = categorize_trifecta(preds, odds_list=None, top_n=5)
    assert len(result[GENRE_HONMEI]) == 5
    assert result[GENRE_CHUANA] == []
    assert result[GENRE_OOANA] == []


def test_honmei_is_sorted_by_probability_descending():
    preds = _predictions()
    result = categorize_trifecta(preds, odds_list=_synthetic_odds(preds), top_n=5)
    probs = [c.probability for c in result[GENRE_HONMEI]]
    assert probs == sorted(probs, reverse=True)


def test_ooana_candidates_have_higher_odds_than_honmei():
    preds = _predictions()
    odds_list = _synthetic_odds(preds)
    result = categorize_trifecta(preds, odds_list=odds_list, top_n=5)
    if result[GENRE_OOANA] and result[GENRE_HONMEI]:
        avg_ooana_odds = sum(c.odds for c in result[GENRE_OOANA]) / len(result[GENRE_OOANA])
        avg_honmei_odds = sum(c.odds for c in result[GENRE_HONMEI]) / len(result[GENRE_HONMEI])
        assert avg_ooana_odds > avg_honmei_odds


def test_ooana_sorted_by_expected_value_descending():
    preds = _predictions()
    result = categorize_trifecta(preds, odds_list=_synthetic_odds(preds), top_n=5)
    evs = [c.expected_value for c in result[GENRE_OOANA]]
    assert evs == sorted(evs, reverse=True)
