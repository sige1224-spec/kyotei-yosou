"""backtest実行ロジック（CLI・Webダッシュボード共通）。

1レース分の答え合わせと、複数レースをまとめて回すループ処理を提供する。
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from kyotei.models.predictor import DEFAULT_WEIGHTS, PredictorWeights, predict_race
from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.scraper.result import parse_raceresult_html
from kyotei.storage import BacktestOutcome, BacktestStore, evaluate_prediction


def run_single_backtest(
    client: BoatraceClient,
    store: BacktestStore,
    code: str,
    date: str,
    race_number: int,
    weights: PredictorWeights = DEFAULT_WEIGHTS,
    use_before_info: bool = True,
) -> BacktestOutcome:
    """1レース分、出走表(+可能なら直前情報)データで予想→実結果と突き合わせ→DB保存、まで行う。"""
    racelist_html = client.get_racelist_html(code, date, race_number)
    race = parse_racelist_html(racelist_html, code, date, race_number)
    result_html = client.get_raceresult_html(code, date, race_number)
    result = parse_raceresult_html(result_html, code, date, race_number)

    before_info = None
    if use_before_info:
        try:
            before_html = client.get_beforeinfo_html(code, date, race_number)
            before_info = parse_beforeinfo_html(before_html, code, date, race_number)
        except Exception:
            before_info = None

    prediction = predict_race(race, before_info=before_info, weights=weights)
    outcome = evaluate_prediction(prediction, result)
    store.save(outcome)
    return outcome


def parse_race_range(text: str) -> list[int]:
    """"1-12" や "1,3,5" 形式の文字列をレース番号のリストに変換する。"""
    races: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            races.extend(range(int(start), int(end) + 1))
        else:
            races.append(int(part))
    return races


def run_day_backtest(
    client: BoatraceClient,
    store: BacktestStore,
    codes: list[str],
    date: str,
    races: list[int],
) -> Iterator[tuple[str, int, BacktestOutcome | None, Exception | None]]:
    """複数場・複数レースをまとめて答え合わせする。1件ずつ結果をyieldする。

    開催のない場・レースはエラーになるため、呼び出し側でスキップとして扱う想定。
    """
    for code in codes:
        for race_number in races:
            try:
                outcome = run_single_backtest(client, store, code, date, race_number)
                yield code, race_number, outcome, None
            except Exception as exc:  # 開催なし・ネットワークエラー等はスキップして続行
                yield code, race_number, None, exc


def collect_raw_race_ids(cache_dir: Path | str) -> list[tuple[str, str, int]]:
    """data/cache/ に保存済みのracelist HTMLから (venue_code, date, race_number) 一覧を得る。

    オフラインでの重みチューニング（scripts/tune_weights.py）で、再ネットワーク
    アクセスなしに手元のキャッシュ済みレースを列挙するために使う。
    """
    cache_dir = Path(cache_dir)
    ids: list[tuple[str, str, int]] = []
    for path in sorted(cache_dir.glob("racelist_*.html")):
        # racelist_{code}_{date}_{race_number}.html
        stem = path.stem
        parts = stem.split("_")
        if len(parts) != 4:
            continue
        _, code, date, race_number = parts
        ids.append((code, date, int(race_number)))
    return ids
