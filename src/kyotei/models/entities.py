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
    grade: str = ""  # 開催のグレード（"一般"/"G3"/"G2"/"G1"/"SG"）。取得できない場合は空文字

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
class TrifectaOdds:
    """3連単1組番ぶんのオッズ（レース発売中の払戻倍率、随時変動する）。"""

    lanes: tuple[int, int, int]  # (1着, 2着, 3着)
    odds: float  # 倍率。100円が odds*100 円になる目安


@dataclass
class RaceResultEntry:
    """レース結果1着分のデータ（学習データ収集・答え合わせ用）。"""

    rank: int  # 着順 (1-6, 出走取消等は0)
    lane: int
    racer_id: int
    name: str
    race_time: str  # 例: "1'51\"9"


@dataclass
class Payout:
    """1組番ぶんの払戻金情報。"""

    bet_type: str  # "3連単" / "3連複" / "2連単" / "2連複" / "拡連複" / "単勝" / "複勝"
    combination: str  # 例: "3-4-5"（3連単/2連単）, "3=4=5"（3連複等）, "3"（単勝/複勝）
    amount: int  # 払戻金額(円)。100円購入した場合の払戻額
    popularity: int | None  # 人気順位（単勝・複勝は非公開のためNone）


@dataclass
class RaceResult:
    venue_code: str
    venue_name: str
    date: str
    race_number: int
    entries: list[RaceResultEntry] = field(default_factory=list)
    payouts: list[Payout] = field(default_factory=list)

    def winner_lane(self) -> int | None:
        for e in self.entries:
            if e.rank == 1:
                return e.lane
        return None

    def payouts_for(self, bet_type: str) -> list[Payout]:
        return [p for p in self.payouts if p.bet_type == bet_type]


@dataclass
class RecentMeetingResult:
    """選手の「過去3節成績」1節分のデータ（boatrace.jp選手プロフィールback3ページ）。"""

    period: str  # 例: "2026/07/10 ～ 2026/07/15"
    venue_name: str
    title: str  # 開催名
    raw_labels: list[str]  # 各レースの着順表示そのまま（"1"等の数字の他、"F"/"L"/転覆などもありうる）
    finishes: list[int]  # raw_labelsを数値化したもの。数字でない着順（F/L/転等）は0

    def numeric_finishes(self) -> list[int]:
        return [f for f in self.finishes if f > 0]


@dataclass
class RecentForm:
    """選手の直近（過去3節）成績まとめ。"""

    racer_id: int
    meetings: list[RecentMeetingResult] = field(default_factory=list)

    def all_finishes(self) -> list[int]:
        return [f for m in self.meetings for f in m.numeric_finishes()]

    def average_finish(self) -> float | None:
        finishes = self.all_finishes()
        return sum(finishes) / len(finishes) if finishes else None

    def top3_rate(self) -> float | None:
        finishes = self.all_finishes()
        if not finishes:
            return None
        return sum(1 for f in finishes if f <= 3) / len(finishes) * 100


@dataclass
class RationaleFactor:
    """予想根拠の1要素（レーン1つぶん）。"""

    label: str  # 例: "全国勝率"
    detail: str  # 例: "6.80（6艇中1位）" のような具体的な数値付き説明
    favorable: bool | None  # True=このレーンにとって有利な要素 / False=不利な要素 / None=中立（参考情報）


@dataclass
class LanePrediction:
    """レーン単位の予想スコア。"""

    lane: int
    racer_name: str
    score: float
    win_probability: float  # 正規化後の推定1着確率 (0-1)
    rationale_summary: str = ""  # 一言でまとめた予想根拠の文章
    rationale_factors: list[RationaleFactor] = field(default_factory=list)  # 重み順の要素一覧


@dataclass
class RacePrediction:
    race: RaceCard
    predictions: list[LanePrediction]  # win_probability 降順

    def as_rank_list(self) -> list[LanePrediction]:
        return sorted(self.predictions, key=lambda p: p.win_probability, reverse=True)
