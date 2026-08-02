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
