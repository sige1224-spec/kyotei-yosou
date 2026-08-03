from pathlib import Path

from kyotei.scraper.racelist import parse_racelist_html
from kyotei.models.predictor import predict_race

FIXTURE = Path(__file__).parent / "fixtures" / "racelist_01_20260802_1.html"


def _load_card():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_racelist_html(html, venue_code="01", date="20260802", race_number=1)


def test_win_probabilities_sum_to_one():
    card = _load_card()
    result = predict_race(card)
    total = sum(p.win_probability for p in result.predictions)
    assert abs(total - 1.0) < 1e-9


def test_all_six_lanes_present_and_ranked():
    card = _load_card()
    result = predict_race(card)
    ranked = result.as_rank_list()
    assert {p.lane for p in ranked} == {1, 2, 3, 4, 5, 6}
    # スコア降順に並んでいること
    scores = [p.win_probability for p in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rationale_generated_for_every_lane():
    card = _load_card()
    result = predict_race(card)
    for p in result.predictions:
        assert p.rationale_summary
        assert len(p.rationale_factors) >= 1
        # コース要素は必ず先頭に含まれる
        assert p.rationale_factors[0].label == "コース取り"
        # 推定勝率と6艇中の順位への言及が要約文に含まれる
        assert "推定勝率" in p.rationale_summary
        assert "%" in p.rationale_summary


def test_rationale_course_favorable_for_lane1_default_course():
    card = _load_card()
    result = predict_race(card)
    lane1 = next(p for p in result.predictions if p.lane == 1)
    course_factor = lane1.rationale_factors[0]
    assert course_factor.favorable is True  # 進入コース未確定時は1号艇=1コースで最有利


def test_recent_form_weight_zero_by_default_does_not_change_prediction():
    from kyotei.models.entities import RecentForm
    from kyotei.models.predictor import predict_race as predict

    card = _load_card()
    baseline = predict(card)
    with_forms = predict(
        card,
        recent_forms={
            e.racer_id: RecentForm(racer_id=e.racer_id, meetings=[]) for e in card.entries
        },
    )
    for a, b in zip(baseline.predictions, with_forms.predictions):
        assert abs(a.win_probability - b.win_probability) < 1e-12
