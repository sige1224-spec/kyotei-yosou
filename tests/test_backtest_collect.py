from kyotei.backtest import collect_raw_race_ids


def test_collect_raw_race_ids_parses_filenames(tmp_path):
    (tmp_path / "racelist_01_20260802_1.html").write_text("x", encoding="utf-8")
    (tmp_path / "racelist_23_20260731_12.html").write_text("x", encoding="utf-8")
    (tmp_path / "raceresult_01_20260802_1.html").write_text("x", encoding="utf-8")  # 対象外
    (tmp_path / "not_a_match.html").write_text("x", encoding="utf-8")

    ids = collect_raw_race_ids(tmp_path)

    assert ("01", "20260802", 1) in ids
    assert ("23", "20260731", 12) in ids
    assert len(ids) == 2
