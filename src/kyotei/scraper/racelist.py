"""出走表ページ (owpc/pc/race/racelist) のパーサー。

全24競艇場で共通のテンプレートを使用しているため、場コードによらず
同じロジックでパース可能。
"""
from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from bs4.element import Tag

# boatrace.jpはXHTML宣言(<?xml ...?>)付きでHTMLを返すため、lxmlパーサーが
# 誤ってXML文書と判定して警告を出す。実際にはHTMLとして問題なく解析できるため抑制する。
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from kyotei.constants import VENUES
from kyotei.models.entities import RaceCard, RacerEntry
from kyotei.scraper._text import normalize_name, safe_float, safe_int, zenkaku_to_int

_zenkaku_to_int = zenkaku_to_int
_safe_float = safe_float
_safe_int = safe_int


def _parse_reg_and_class(div: Tag) -> tuple[int, str]:
    parts = [p.strip() for p in div.get_text("/", strip=True).split("/") if p.strip()]
    reg_no = _safe_int(parts[0]) if parts else 0
    racer_class = parts[1] if len(parts) > 1 else ""
    return reg_no, racer_class


def _parse_name(div: Tag) -> str:
    return normalize_name(div.get_text(" ", strip=True))


def _parse_branch_profile(div: Tag) -> tuple[str, str, int, float]:
    lines = list(div.stripped_strings)
    branch, hometown = "", ""
    age, weight = 0, 0.0
    if lines:
        branch_parts = lines[0].split("/")
        branch = branch_parts[0].strip() if branch_parts else ""
        hometown = branch_parts[1].strip() if len(branch_parts) > 1 else ""
    if len(lines) > 1:
        age_match = re.search(r"(\d+)\s*歳", lines[1])
        weight_match = re.search(r"([\d.]+)\s*kg", lines[1])
        age = int(age_match.group(1)) if age_match else 0
        weight = float(weight_match.group(1)) if weight_match else 0.0
    return branch, hometown, age, weight


def _parse_f_l_st(cell: Tag) -> tuple[int, int, float]:
    values = list(cell.stripped_strings)
    f_count = l_count = 0
    st = 0.0
    for v in values:
        if v.upper().startswith("F"):
            f_count = _safe_int(v)
        elif v.upper().startswith("L"):
            l_count = _safe_int(v)
        else:
            st = _safe_float(v)
    return f_count, l_count, st


def _parse_rate_triplet(cell: Tag) -> tuple[float, float, float]:
    values = list(cell.stripped_strings)
    values += ["0", "0", "0"]
    return _safe_float(values[0]), _safe_float(values[1]), _safe_float(values[2])


def _parse_equipment(cell: Tag) -> tuple[int, float, float]:
    values = list(cell.stripped_strings)
    values += ["0", "0", "0"]
    return _safe_int(values[0]), _safe_float(values[1]), _safe_float(values[2])


_GRADE_LABELS = {"SG": "SG", "G1": "G1", "G2": "G2", "G3": "G3", "normal": "一般"}


def _parse_grade(soup: BeautifulSoup) -> str:
    """開催のグレードを取得する。

    見出しdiv（`heading2_title`）のクラス名に `is-G3b` のようにグレードが
    埋め込まれている（末尾の`b`等は見出しのレイアウト差異を表す接尾辞で
    グレードとは無関係）。判定できない場合は空文字を返す。
    """
    title_div = soup.find("div", class_="heading2_title")
    if title_div is None:
        return ""
    for cls in title_div.get("class") or []:
        match = re.match(r"is-(SG|G1|G2|G3|normal)", cls)
        if match:
            return _GRADE_LABELS[match.group(1)]
    return ""


def parse_racelist_html(
    html: str, venue_code: str, date: str, race_number: int
) -> RaceCard:
    """出走表HTMLをパースしてRaceCardを返す。"""
    soup = BeautifulSoup(html, "lxml")

    racer_blocks = [
        tbody
        for tbody in soup.find_all("tbody")
        if tbody.get("class") and any("is-fs12" in c for c in tbody.get("class"))
    ]
    if not racer_blocks:
        raise ValueError(
            "出走表データが見つかりませんでした。"
            "ページ構造が変更されたか、開催がない日付の可能性があります。"
        )

    entries: list[RacerEntry] = []
    for tbody in racer_blocks:
        first_row = tbody.find("tr")
        if first_row is None:
            continue
        cells = first_row.find_all("td", recursive=False)
        if len(cells) < 9:
            continue

        lane = _zenkaku_to_int(cells[0].get_text())

        info_divs = cells[2].find_all("div", recursive=False)
        reg_no, racer_class = _parse_reg_and_class(info_divs[0])
        name = _parse_name(info_divs[1]) if len(info_divs) > 1 else ""
        branch, hometown, age, weight = (
            _parse_branch_profile(info_divs[2]) if len(info_divs) > 2 else ("", "", 0, 0.0)
        )

        f_count, l_count, avg_st = _parse_f_l_st(cells[3])
        nat_win, nat_2nd, nat_3rd = _parse_rate_triplet(cells[4])
        loc_win, loc_2nd, loc_3rd = _parse_rate_triplet(cells[5])
        motor_no, motor_2nd, motor_3rd = _parse_equipment(cells[6])
        boat_no, boat_2nd, boat_3rd = _parse_equipment(cells[7])

        entries.append(
            RacerEntry(
                lane=lane,
                racer_id=reg_no,
                racer_class=racer_class,
                name=name,
                branch=branch,
                hometown=hometown,
                age=age,
                weight=weight,
                flying_count=f_count,
                late_count=l_count,
                avg_start_timing=avg_st,
                national_win_rate=nat_win,
                national_2nd_rate=nat_2nd,
                national_3rd_rate=nat_3rd,
                local_win_rate=loc_win,
                local_2nd_rate=loc_2nd,
                local_3rd_rate=loc_3rd,
                motor_number=motor_no,
                motor_2nd_rate=motor_2nd,
                motor_3rd_rate=motor_3rd,
                boat_number=boat_no,
                boat_2nd_rate=boat_2nd,
                boat_3rd_rate=boat_3rd,
            )
        )

    entries.sort(key=lambda e: e.lane)

    return RaceCard(
        venue_code=venue_code,
        venue_name=VENUES.get(venue_code, venue_code),
        date=date,
        race_number=race_number,
        entries=entries,
        grade=_parse_grade(soup),
    )
