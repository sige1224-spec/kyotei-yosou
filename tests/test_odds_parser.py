from pathlib import Path

from kyotei.scraper.odds import parse_odds3t_html

FIXTURE = Path(__file__).parent / "fixtures" / "odds3t_01_20260802_1.html"


def _load_odds():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_odds3t_html(html, venue_code="01", date="20260802", race_number=1)


def _odds_map(odds_list):
    return {o.lanes: o.odds for o in odds_list}


def test_parses_up_to_120_combinations():
    odds_list = _load_odds()
    lanes_seen = {o.lanes for o in odds_list}
    assert len(lanes_seen) == len(odds_list)  # 重複なし
    assert len(odds_list) <= 120
    assert len(odds_list) > 100  # ほぼ全通り取得できているはず


def test_known_combo_odds_values():
    odds_map = _odds_map(_load_odds())
    # HTML構造から手動で確認した値
    assert odds_map[(1, 2, 3)] == 24.1
    assert odds_map[(1, 2, 4)] == 31.2
    assert odds_map[(1, 2, 5)] == 42.9
    assert odds_map[(1, 2, 6)] == 74.9
    assert odds_map[(2, 1, 3)] == 50.8
    assert odds_map[(2, 1, 4)] == 61.9
    assert odds_map[(2, 1, 5)] == 68.3


def test_all_lane_triples_are_valid_permutations():
    odds_list = _load_odds()
    for o in odds_list:
        assert len(set(o.lanes)) == 3
        assert all(1 <= lane <= 6 for lane in o.lanes)
        assert o.odds > 0
