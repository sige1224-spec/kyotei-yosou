from pathlib import Path

from kyotei.scraper.racelist import parse_racelist_html

FIXTURE = Path(__file__).parent / "fixtures" / "racelist_01_20260802_1.html"


def _load_card():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_racelist_html(html, venue_code="01", date="20260802", race_number=1)


def test_parses_six_entries():
    card = _load_card()
    assert card.venue_name == "桐生"
    assert len(card.entries) == 6
    assert [e.lane for e in card.entries] == [1, 2, 3, 4, 5, 6]


def test_lane1_racer_fields():
    card = _load_card()
    racer = card.entry(1)
    assert racer.racer_id == 5184
    assert racer.racer_class == "B2"
    assert racer.name == "飯塚 響"
    assert racer.branch == "群馬"
    assert racer.hometown == "栃木"
    assert racer.age == 27
    assert racer.weight == 46.5
    assert racer.flying_count == 0
    assert racer.late_count == 0
    assert racer.avg_start_timing == 0.21
    assert racer.national_win_rate == 3.31
    assert racer.national_2nd_rate == 17.14
    assert racer.national_3rd_rate == 22.86
    assert racer.local_win_rate == 3.59
    assert racer.motor_number == 21
    assert racer.motor_2nd_rate == 32.32
    assert racer.boat_number == 16
    assert racer.boat_2nd_rate == 25.81
