"""直前情報ページ (owpc/pc/race/beforeinfo) のパーサー。

展示タイム・チルト・調整重量・進入コース（判明していれば）と、
水面気象情報（天候・気温・風速・水温・波高）を取得する。

風向はサイト上でアイコン画像（is-windN, N=1-16）のみで表現されており、
方角を示す文言は公開されていないため、アイコン番号をそのまま参考値として保持する。
"""
from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from bs4.element import Tag

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from kyotei.constants import VENUES
from kyotei.models.entities import BeforeInfo, ExhibitionEntry, WeatherInfo
from kyotei.scraper._text import safe_float, safe_int, zenkaku_to_int


def _parse_exhibition_entries(soup: BeautifulSoup) -> list[ExhibitionEntry]:
    entries: list[ExhibitionEntry] = []
    for tbody in soup.find_all("tbody", class_=lambda c: c and "is-fs12" in c):
        rows = tbody.find_all("tr", recursive=False)
        if len(rows) < 3:
            continue

        row1 = rows[0].find_all("td", recursive=False)
        if len(row1) < 8:
            continue
        lane = zenkaku_to_int(row1[0].get_text())
        weight = safe_float(row1[3].get_text())
        exhibition_time = safe_float(row1[4].get_text())
        tilt = safe_float(row1[5].get_text())

        row2 = rows[1].find_all("td", recursive=False)
        entry_course_text = row2[1].get_text(strip=True) if len(row2) > 1 else ""
        entry_course = safe_int(entry_course_text) or None

        row3 = rows[2].find_all("td", recursive=False)
        adjust_weight = safe_float(row3[0].get_text()) if row3 else 0.0

        entries.append(
            ExhibitionEntry(
                lane=lane,
                weight=weight,
                exhibition_time=exhibition_time,
                tilt=tilt,
                adjust_weight=adjust_weight,
                entry_course=entry_course,
            )
        )

    entries.sort(key=lambda e: e.lane)
    return entries


def _parse_weather(soup: BeautifulSoup) -> WeatherInfo | None:
    block = soup.select_one(".weather1")
    if block is None:
        return None

    title = block.select_one(".weather1_title")
    measured_at = title.get_text(strip=True) if title else ""

    weather_text = ""
    temperature = wind_speed = water_temperature = wave_height = 0.0
    wind_direction_code: int | None = None

    weather_unit = block.select_one(".weather1_bodyUnit.is-weather .weather1_bodyUnitLabelTitle")
    if weather_unit:
        weather_text = weather_unit.get_text(strip=True)

    temp_unit = block.select_one(".weather1_bodyUnit.is-direction .weather1_bodyUnitLabelData")
    if temp_unit:
        temperature = safe_float(temp_unit.get_text())

    wind_unit = block.select_one(".weather1_bodyUnit.is-wind .weather1_bodyUnitLabelData")
    if wind_unit:
        wind_speed = safe_float(wind_unit.get_text())

    wind_dir_img = block.select_one(".weather1_bodyUnit.is-windDirection .weather1_bodyUnitImage")
    if wind_dir_img:
        classes = wind_dir_img.get("class", [])
        for cls in classes:
            match = re.match(r"is-wind(\d+)$", cls)
            if match:
                wind_direction_code = int(match.group(1))
                break

    water_unit = block.select_one(
        ".weather1_bodyUnit.is-waterTemperature .weather1_bodyUnitLabelData"
    )
    if water_unit:
        water_temperature = safe_float(water_unit.get_text())

    wave_unit = block.select_one(".weather1_bodyUnit.is-wave .weather1_bodyUnitLabelData")
    if wave_unit:
        wave_height = safe_float(wave_unit.get_text())

    return WeatherInfo(
        measured_at=measured_at,
        weather=weather_text,
        temperature=temperature,
        wind_speed=wind_speed,
        wind_direction_code=wind_direction_code,
        water_temperature=water_temperature,
        wave_height=wave_height,
    )


def parse_beforeinfo_html(
    html: str, venue_code: str, date: str, race_number: int
) -> BeforeInfo:
    soup = BeautifulSoup(html, "lxml")

    exhibitions = _parse_exhibition_entries(soup)
    weather = _parse_weather(soup)

    return BeforeInfo(
        venue_code=venue_code,
        venue_name=VENUES.get(venue_code, venue_code),
        date=date,
        race_number=race_number,
        exhibitions=exhibitions,
        weather=weather,
    )
