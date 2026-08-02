from pathlib import Path

from kyotei.models.genres import GENRE_OOANA
from kyotei.models.scan import scan_races, top_candidates

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeClient:
    """レース1(場コード01)だけデータがあり、他はデータなし扱いのフェイククライアント。"""

    def get_racelist_html(self, venue_code: str, date: str, race_number: int) -> str:
        if race_number == 1:
            return (FIXTURES / "racelist_01_20260802_1.html").read_text(encoding="utf-8")
        raise ValueError("出走表が見つかりませんでした（テスト用: 開催なし）")

    def get_beforeinfo_html(self, venue_code: str, date: str, race_number: int) -> str:
        return (FIXTURES / "beforeinfo_01_20260802_1.html").read_text(encoding="utf-8")

    def get_odds3t_html(self, venue_code: str, date: str, race_number: int) -> str:
        return (FIXTURES / "odds3t_01_20260802_1.html").read_text(encoding="utf-8")


def test_scan_races_skips_races_without_racelist():
    results = list(scan_races(_FakeClient(), ["01"], "20260802", [1, 2]))

    assert len(results) == 2
    code, race_number, prediction, genres, error = results[0]
    assert race_number == 1
    assert error is None
    assert prediction is not None
    assert genres is not None
    assert len(prediction.predictions) == 6

    code, race_number, prediction, genres, error = results[1]
    assert race_number == 2
    assert error is not None
    assert prediction is None
    assert genres is None


def test_top_candidates_returns_ooana_sorted_by_expected_value():
    results = top_candidates(
        _FakeClient(), ["01"], "20260802", [1, 2], genre=GENRE_OOANA, top_n=5
    )

    assert all(r.venue_code == "01" and r.race_number == 1 for r in results)
    evs = [r.candidate.expected_value for r in results]
    assert evs == sorted(evs, reverse=True)
