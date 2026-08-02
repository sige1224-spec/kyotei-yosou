"""レースデータのエンティティ定義。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RacerEntry:
    """出走表1選手分のデータ。"""

    lane: int  # 枠番 (1-6)
    racer_id: int  # 登録番号
    racer_class: str  # 級別 (A1/A2/B1/B2)
    name: str
    branch: str  # 支部
    hometown: str  # 出身地
    age: int
    weight: float
    flying_count: int  # F数
    late_count: int  # L数
    avg_start_timing: float  # 平均ST
    national_win_rate: float  # 全国勝率
    national_2nd_rate: float  # 全国2連率
    national_3rd_rate: float  # 全国3連率
    local_win_rate: float  # 当地勝率
    local_2nd_rate: float  # 当地2連率
    local_3rd_rate: float  # 当地3連率
    motor_number: int
    motor_2nd_rate: float  # モーター2連率
    motor_3rd_rate: float  # モーター3連率
    boat_number: int
    boat_2nd_rate: float  # ボート2連率
    boat_3rd_rate: float  # ボート3連率


@dataclass
class RaceCard:
    """1レース分の出走表。"""

    venue_code: str
    venue_name: str
    date: str  # YYYYMMDD
    race_number: int
    entries: list[RacerEntry] = field(default_factory=list)

    def entry(self, lane: int) -> RacerEntry:
        for e in self.entries:
            if e.lane == lane:
                return e
        raise KeyError(f"枠番 {lane} が見つかりません")


@dataclass
class ExhibitionEntry:
    """直前情報1艇分のデータ。"""

    lane: int  # 枠番（艇番）
    weight: float  # 体重(kg)
    exhibition_time: float  # 展示タイム
    tilt: float  # チルト角度
    adjust_weight: float  # 調整重量(kg)
    entry_course: int | None  # 進入コース（未確定/変更なしの場合はNone。その場合はlaneを使う）


@dataclass
class WeatherInfo:
    """レース直前の水面気象情報。"""

    measured_at: str  # 例: "15:32現在"
    weather: str  # 天候（晴/曇/雨など）
    temperature: float  # 気温(℃)
    wind_speed: float  # 風速(m)
    wind_direction_code: int | None  # サイトのアイコン番号（1-16）。方角の公式な文言は非公開のため参考値
    water_temperature: float  # 水温(℃)
    wave_height: float  # 波高(cm)


@dataclass
class BeforeInfo:
    """直前情報ページ (beforeinfo) 全体。"""

    venue_code: str
    venue_name: str
    date: str
    race_number: int
    exhibitions: list[ExhibitionEntry] = field(default_factory=list)
    weather: WeatherInfo | None = None

    def exhibition(self, lane: int) -> ExhibitionEntry | None:
        for e in self.exhibitions:
            if e.lane == lane:
                return e
        return None


@dataclass
class RaceResultEntry:
    """レース結果1着分のデータ（学習データ収集・答え合わせ用）。"""

    rank: int  # 着順 (1-6, 出走取消等は0)
    lane: int
    racer_id: int
    name: str
    race_time: str  # 例: "1'51\"9"


@dataclass
class RaceResult:
    venue_code: str
    venue_name: str
    date: str
    race_number: int
    entries: list[RaceResultEntry] = field(default_factory=list)

    def winner_lane(self) -> int | None:
        for e in self.entries:
            if e.rank == 1:
                return e.lane
        return None


@dataclass
class LanePrediction:
    """レーン単位の予想スコア。"""

    lane: int
    racer_name: str
    score: float
    win_probability: float  # 正規化後の推定1着確率 (0-1)


@dataclass
class RacePrediction:
    race: RaceCard
    predictions: list[LanePrediction]  # win_probability 降順

    def as_rank_list(self) -> list[LanePrediction]:
        return sorted(self.predictions, key=lambda p: p.win_probability, reverse=True)
