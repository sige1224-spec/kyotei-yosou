from pathlib import Path

from kyotei.scraper.result import parse_raceresult_html

FIXTURE = Path(__file__).parent / "fixtures" / "raceresult_01_20260731_1.html"


def _load_result():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_raceresult_html(html, venue_code="01", date="20260731", race_number=1)


def test_parses_six_results_ranked():
    result = _load_result()
    assert len(result.entries) == 6
    assert [e.rank for e in result.entries] == [1, 2, 3, 4, 5, 6]


def test_winner_lane_is_three():
    result = _load_result()
    assert result.winner_lane() == 3
    winner = result.entries[0]
    assert winner.racer_id == 3509
    assert winner.name == "池 千夏"
