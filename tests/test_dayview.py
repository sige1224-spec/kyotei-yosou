from pathlib import Path

from kyotei.dayview import fetch_day_results

FIXTURE = Path(__file__).parent / "fixtures" / "raceresult_01_20260731_1.html"


class _FakeClient:
    """ネットワークにアクセスせず、race_number=1だけ結果を返すフェイク。"""

    def get_raceresult_html(self, venue_code: str, date: str, race_number: int) -> str:
        if race_number == 1:
            return FIXTURE.read_text(encoding="utf-8")
        raise ValueError("結果データが見つかりませんでした（テスト用: 未実施レース）")


def test_fetch_day_results_skips_missing_races():
    results = fetch_day_results(_FakeClient(), "01", "20260731", [1, 2, 3])

    assert len(results) == 1
    assert results[0].race_number == 1
    assert results[0].winner_lane() == 3
