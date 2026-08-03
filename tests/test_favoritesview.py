from pathlib import Path

from kyotei.favoritesview import today_favorite_races
from kyotei.storage import FAVORITE_RACER, FAVORITE_VENUE, FavoriteStore

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeClient:
    """場コード01のレース1だけデータがあり、他は開催なし扱いのフェイククライアント。"""

    def get_racelist_html(self, venue_code: str, date: str, race_number: int) -> str:
        if venue_code == "01" and race_number == 1:
            return (FIXTURES / "racelist_01_20260802_1.html").read_text(encoding="utf-8")
        raise ValueError("出走表が見つかりませんでした（テスト用: 開催なし）")


def test_today_favorite_races_only_targets_favorite_venues(tmp_path):
    store = FavoriteStore(db_path=tmp_path / "test.db")
    store.add(FAVORITE_VENUE, "01", "桐生")

    matches = today_favorite_races(_FakeClient(), "20260802", [1, 2], favorite_store=store)

    assert len(matches) == 1
    assert matches[0].venue_code == "01"
    assert matches[0].race_number == 1
    assert len(matches[0].prediction.predictions) == 6
    assert matches[0].favorite_racer_lanes == []


def test_today_favorite_races_flags_favorite_racer_lane(tmp_path):
    store = FavoriteStore(db_path=tmp_path / "test.db")
    store.add(FAVORITE_VENUE, "01", "桐生")
    # racelist_01_20260802_1.html の1号艇の選手(登録番号5184)をお気に入り登録
    store.add(FAVORITE_RACER, "5184", "テスト選手")

    matches = today_favorite_races(_FakeClient(), "20260802", [1], favorite_store=store)

    assert len(matches) == 1
    assert matches[0].favorite_racer_lanes == [1]


def test_today_favorite_races_empty_when_no_favorite_venues(tmp_path):
    store = FavoriteStore(db_path=tmp_path / "test.db")
    matches = today_favorite_races(_FakeClient(), "20260802", [1], favorite_store=store)
    assert matches == []
