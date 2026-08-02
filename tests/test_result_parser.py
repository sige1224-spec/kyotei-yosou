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


def test_parses_payouts():
    result = _load_result()
    trifecta = result.payouts_for("3連単")
    assert len(trifecta) == 1
    assert trifecta[0].combination == "3-4-5"
    assert trifecta[0].amount == 10770
    assert trifecta[0].popularity == 42

    trio = result.payouts_for("3連複")
    assert trio[0].combination == "3=4=5"
    assert trio[0].amount == 1430

    exacta = result.payouts_for("2連単")
    assert exacta[0].combination == "3-4"
    assert exacta[0].amount == 3780

    wide = result.payouts_for("拡連複")
    assert len(wide) == 3
    assert {p.combination for p in wide} == {"3=4", "3=5", "4=5"}

    win = result.payouts_for("単勝")
    assert len(win) == 1
    assert win[0].combination == "3"
    assert win[0].amount == 1590
    assert win[0].popularity is None
