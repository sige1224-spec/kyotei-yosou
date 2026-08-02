from kyotei.models.combos import exacta_candidates, trifecta_candidates, trio_candidates
from kyotei.models.entities import LanePrediction


def _uniform_predictions() -> list[LanePrediction]:
    return [
        LanePrediction(lane=lane, racer_name=f"racer{lane}", score=1.0, win_probability=1 / 6)
        for lane in range(1, 7)
    ]


def _skewed_predictions() -> list[LanePrediction]:
    # 1号艇が圧倒的に強い想定
    probs = {1: 0.5, 2: 0.15, 3: 0.15, 4: 0.1, 5: 0.06, 6: 0.04}
    return [
        LanePrediction(lane=lane, racer_name=f"racer{lane}", score=p, win_probability=p)
        for lane, p in probs.items()
    ]


def test_trifecta_probabilities_sum_to_one_for_all_120_combos():
    preds = _uniform_predictions()
    all_combos = trifecta_candidates(preds, top_n=120)
    assert len(all_combos) == 120
    total = sum(c.probability for c in all_combos)
    assert abs(total - 1.0) < 1e-9
    # 均等勝率なら全組み合わせが均等確率になるはず
    assert abs(all_combos[0].probability - 1 / 120) < 1e-9


def test_trifecta_top_pick_follows_win_probability_order():
    preds = _skewed_predictions()
    top = trifecta_candidates(preds, top_n=1)[0]
    assert top.lanes[0] == 1  # 圧倒的本命が1着候補の先頭
    assert top.label == "1-2-3" or top.label.startswith("1-")


def test_exacta_probabilities_sum_to_one():
    preds = _uniform_predictions()
    all_combos = exacta_candidates(preds, top_n=30)
    assert len(all_combos) == 30
    total = sum(c.probability for c in all_combos)
    assert abs(total - 1.0) < 1e-9


def test_trio_probabilities_sum_to_one_and_dedupes_orderings():
    preds = _uniform_predictions()
    all_combos = trio_candidates(preds, top_n=20)
    assert len(all_combos) == 20
    # 6艇から3艇選ぶ組み合わせは20通りのみ（順序をまとめている）
    labels = {c.label for c in all_combos}
    assert len(labels) == 20
    total_all = sum(c.probability for c in trio_candidates(preds, top_n=20))
    assert abs(total_all - 1.0) < 1e-9
