from pathlib import Path

from kyotei.scraper.racelist import parse_racelist_html
from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.models.predictor import predict_race

RACELIST_FIXTURE = Path(__file__).parent / "fixtures" / "racelist_01_20260802_1.html"
BEFOREINFO_FIXTURE = Path(__file__).parent / "fixtures" / "beforeinfo_01_20260802_1.html"


def test_prediction_with_before_info_still_sums_to_one():
    race = parse_racelist_html(
        RACELIST_FIXTURE.read_text(encoding="utf-8"), "01", "20260802", 1
    )
    before_info = parse_beforeinfo_html(
        BEFOREINFO_FIXTURE.read_text(encoding="utf-8"), "01", "20260802", 1
    )
    result = predict_race(race, before_info=before_info)
    total = sum(p.win_probability for p in result.predictions)
    assert abs(total - 1.0) < 1e-9
    assert {p.lane for p in result.predictions} == {1, 2, 3, 4, 5, 6}
