from pathlib import Path

from kyotei.scraper.beforeinfo import parse_beforeinfo_html

FIXTURE = Path(__file__).parent / "fixtures" / "beforeinfo_01_20260802_1.html"


def _load_info():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_beforeinfo_html(html, venue_code="01", date="20260802", race_number=1)


def test_parses_six_exhibition_entries():
    info = _load_info()
    assert len(info.exhibitions) == 6
    assert [e.lane for e in info.exhibitions] == [1, 2, 3, 4, 5, 6]


def test_lane1_exhibition_fields():
    info = _load_info()
    e = info.exhibition(1)
    assert e.weight == 46.5
    assert e.exhibition_time == 6.63
    assert e.tilt == -0.5
    assert e.adjust_weight == 0.5
    # 開催前のためこのサンプルでは進入コースは未確定(None)
    assert e.entry_course is None


def test_weather_info():
    info = _load_info()
    assert info.weather is not None
    assert info.weather.weather == "晴"
    assert info.weather.temperature == 30.0
    assert info.weather.wind_speed == 5.0
    assert info.weather.water_temperature == 24.0
    assert info.weather.wave_height == 4.0
    assert info.weather.wind_direction_code == 10
