"""全24競艇場の共通定数。"""
from __future__ import annotations

# jcd（場コード）-> 場名。BOATRACE公式サイトのURLパラメータ jcd に対応。
VENUES: dict[str, str] = {
    "01": "桐生",
    "02": "戸田",
    "03": "江戸川",
    "04": "平和島",
    "05": "多摩川",
    "06": "浜名湖",
    "07": "蒲郡",
    "08": "常滑",
    "09": "津",
    "10": "三国",
    "11": "びわこ",
    "12": "住之江",
    "13": "尼崎",
    "14": "鳴門",
    "15": "丸亀",
    "16": "児島",
    "17": "宮島",
    "18": "徳山",
    "19": "下関",
    "20": "若松",
    "21": "芦屋",
    "22": "福岡",
    "23": "唐津",
    "24": "大村",
}

VENUE_NAME_TO_CODE: dict[str, str] = {name: code for code, name in VENUES.items()}

# 全国集計に基づくコース別(枠番別)1着率の目安（%）。
# 出典: BOATRACEオフィシャルの公表統計に基づく概算値。場・時期により変動するため、
# 将来的には実データから算出した値に差し替える想定（暫定の事前確率として使用）。
COURSE_WIN_RATE: dict[int, float] = {
    1: 55.0,
    2: 14.0,
    3: 12.0,
    4: 10.0,
    5: 6.0,
    6: 3.0,
}


BOATRACE_BASE_URL = "https://www.boatrace.jp"
RACER_PROFILE_PATH = "/owpc/pc/data/racersearch/profile"


def racer_profile_url(racer_id: int) -> str:
    """選手登録番号(toban)から、BOATRACE公式サイトの選手プロフィールページURLを返す。"""
    return f"{BOATRACE_BASE_URL}{RACER_PROFILE_PATH}?toban={racer_id}"


def raceresult_url(venue_code: str, date: str, race_number: int) -> str:
    """BOATRACE公式サイトの結果ページURLを返す。"""
    return (
        f"{BOATRACE_BASE_URL}/owpc/pc/race/raceresult"
        f"?rno={race_number}&jcd={venue_code}&hd={date}"
    )


def venue_code(name_or_code: str) -> str:
    """場名または場コードを受け取り、2桁の場コード文字列を返す。"""
    if name_or_code in VENUES:
        return name_or_code
    if name_or_code in VENUE_NAME_TO_CODE:
        return VENUE_NAME_TO_CODE[name_or_code]
    normalized = name_or_code.zfill(2)
    if normalized in VENUES:
        return normalized
    raise ValueError(f"未知の競艇場です: {name_or_code}")
