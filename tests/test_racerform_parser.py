from pathlib import Path

from kyotei.scraper.racerform import parse_racer_back3_html

FIXTURE = Path(__file__).parent / "fixtures" / "back3_4300.html"


def test_parse_racer_back3_html():
    html = FIXTURE.read_text(encoding="utf-8")
    form = parse_racer_back3_html(html, racer_id=4300)

    assert form.racer_id == 4300
    assert len(form.meetings) == 3

    latest = form.meetings[0]
    assert latest.venue_name == "浜名湖"
    assert latest.period == "2026/07/10 ～ 2026/07/15"
    assert latest.finishes == [1, 4, 2, 5, 5, 6, 1, 6, 5]
    assert latest.raw_labels == ["１", "４", "２", "５", "５", "６", "１", "６", "５"]

    all_finishes = form.all_finishes()
    assert len(all_finishes) == 9 + 9 + 9
    assert form.average_finish() is not None
    assert form.top3_rate() is not None


def test_recent_form_handles_no_data():
    from kyotei.models.entities import RecentForm

    form = RecentForm(racer_id=1)
    assert form.all_finishes() == []
    assert form.average_finish() is None
    assert form.top3_rate() is None
