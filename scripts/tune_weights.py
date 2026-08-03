"""キャッシュ済みHTML（data/cache/）だけを使い、ネットワーク不要で
PredictorWeights の妥当性を検証・探索するオフラインツール。

- ablation: 展示タイム重みを0/半分/2倍にした場合の的中率の変化を見る
- random search: 重み空間をランダムサンプリングし、的中率が改善するか探す

同じレース集合に対する「ペアごとの的中反転数」も出すことで、標本数が
少ない中でも差が意味を持ちそうかの目安にする（本格的な有意差検定ではない）。

使い方:
    python scripts/tune_weights.py
    python scripts/tune_weights.py --with-recent-form  # 直近成績weightのablationも実行（初回はネットワークアクセスあり）
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kyotei.backtest import collect_raw_race_ids
from kyotei.models.entities import RecentForm
from kyotei.models.predictor import DEFAULT_WEIGHTS, PredictorWeights, predict_race
from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.scraper.racerform import parse_racer_back3_html
from kyotei.scraper.result import parse_raceresult_html
from kyotei.storage import evaluate_prediction


def load_dataset(client: BoatraceClient) -> list[tuple]:
    dataset = []
    for code, date, race_number in collect_raw_race_ids(client.cache_dir):
        racelist_html = client.read_cache(f"racelist_{code}_{date}_{race_number}")
        result_html = client.read_cache(f"raceresult_{code}_{date}_{race_number}")
        if not racelist_html or not result_html:
            continue
        try:
            race = parse_racelist_html(racelist_html, code, date, race_number)
            result = parse_raceresult_html(result_html, code, date, race_number)
        except ValueError:
            continue  # 開催なし・出走取消などデータ欠損

        if len(race.entries) != 6:
            continue

        before_info = None
        before_html = client.read_cache(f"beforeinfo_{code}_{date}_{race_number}")
        if before_html:
            try:
                before_info = parse_beforeinfo_html(before_html, code, date, race_number)
            except Exception:
                before_info = None

        dataset.append((race, before_info, result))
    return dataset


def load_recent_forms(client: BoatraceClient, dataset: list[tuple]) -> dict[int, RecentForm]:
    """データセットに登場する全選手の直近成績（過去3節）をまとめて取得する。

    `client`の通常のレート制限・キャッシュ機構をそのまま使うため、初回のみ
    未キャッシュの選手分だけネットワークアクセスが発生する（`data/cache/back3_*.html`
    に保存されるため、2回目以降は完全にオフラインで再評価できる）。
    """
    racer_ids = {e.racer_id for race, _before, _result in dataset for e in race.entries}
    forms: dict[int, RecentForm] = {}
    for i, racer_id in enumerate(sorted(racer_ids), start=1):
        try:
            html = client.get_racer_back3_html(racer_id)
            forms[racer_id] = parse_racer_back3_html(html, racer_id)
        except Exception:
            continue
        if i % 20 == 0:
            print(f"  直近成績取得中... {i}/{len(racer_ids)}人")
    return forms


def evaluate(
    dataset: list[tuple],
    weights: PredictorWeights,
    recent_forms: dict[int, RecentForm] | None = None,
) -> dict:
    n = top1 = top2 = top3 = 0
    per_race_top1: dict[tuple[str, str, int], bool] = {}
    for race, before_info, result in dataset:
        if result.winner_lane() is None:
            continue
        race_recent_forms = (
            {e.racer_id: recent_forms[e.racer_id] for e in race.entries if e.racer_id in recent_forms}
            if recent_forms
            else None
        )
        prediction = predict_race(
            race, before_info=before_info, weights=weights, recent_forms=race_recent_forms
        )
        outcome = evaluate_prediction(prediction, result)
        n += 1
        top1 += outcome.top1_hit
        top2 += outcome.top2_hit
        top3 += outcome.top3_hit
        per_race_top1[(race.venue_code, race.date, race.race_number)] = outcome.top1_hit

    return {
        "n": n,
        "top1_rate": top1 / n if n else 0.0,
        "top2_rate": top2 / n if n else 0.0,
        "top3_rate": top3 / n if n else 0.0,
        "per_race_top1": per_race_top1,
    }


def compare_flips(base: dict, other: dict) -> tuple[int, int]:
    """base不的中→other的中の件数、base的中→other不的中の件数を返す。"""
    improved = worsened = 0
    for key, base_hit in base["per_race_top1"].items():
        other_hit = other["per_race_top1"].get(key)
        if other_hit is None:
            continue
        if not base_hit and other_hit:
            improved += 1
        elif base_hit and not other_hit:
            worsened += 1
    return improved, worsened


def format_result(label: str, result: dict, base: dict | None = None) -> str:
    line = (
        f"{label}: n={result['n']} "
        f"top1={result['top1_rate']*100:.1f}% "
        f"top2={result['top2_rate']*100:.1f}% "
        f"top3={result['top3_rate']*100:.1f}%"
    )
    if base is not None and base is not result:
        improved, worsened = compare_flips(base, result)
        line += f"  (baseline比: 改善{improved}件 / 悪化{worsened}件)"
    return line


def random_search(
    dataset: list[tuple], base_weights: PredictorWeights, n_trials: int, seed: int
) -> list[tuple[PredictorWeights, dict]]:
    rng = random.Random(seed)
    bounds = {
        "course": (0.35, 0.70),
        "national_win_rate": (0.05, 0.35),
        "local_win_rate": (0.0, 0.20),
        "motor_2nd_rate": (0.0, 0.15),
        "boat_2nd_rate": (0.0, 0.10),
        "start_timing": (0.0, 0.05),
        "flying_penalty": (0.0, 0.05),
        "exhibition_time": (0.0, 0.15),
    }
    results = []
    for _ in range(n_trials):
        kwargs = {name: rng.uniform(lo, hi) for name, (lo, hi) in bounds.items()}
        weights = PredictorWeights(**kwargs)
        result = evaluate(dataset, weights)
        results.append((weights, result))

    results.sort(key=lambda item: (item[1]["top1_rate"], item[1]["top3_rate"]), reverse=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-recent-form",
        action="store_true",
        help="選手の直近成績（過去3節）weightのablationも実行する。"
        "未キャッシュの選手分は初回のみネットワークアクセスが発生する",
    )
    args = parser.parse_args()

    client = BoatraceClient(use_cache=True)
    dataset = load_dataset(client)
    print(f"読み込んだキャッシュ済みレース件数: {len(dataset)}")
    if len(dataset) < 20:
        print("件数が少なすぎるため参考程度の結果になります。backtest系コマンドでデータを蓄積してください。")
    if not dataset:
        return

    baseline = evaluate(dataset, DEFAULT_WEIGHTS)
    print()
    print("=== ベースライン（現在のDEFAULT_WEIGHTS） ===")
    print(format_result("baseline", baseline))

    print()
    print("=== 展示タイム重み ablation ===")
    for label, factor in [("展示タイム=0(未使用)", 0.0), ("展示タイム半分", 0.5), ("展示タイム2倍", 2.0)]:
        w = replace(DEFAULT_WEIGHTS, exhibition_time=DEFAULT_WEIGHTS.exhibition_time * factor)
        result = evaluate(dataset, w)
        print(format_result(label, result, base=baseline))

    print()
    print("=== ランダムサーチ（上位5件） ===")
    top5 = random_search(dataset, DEFAULT_WEIGHTS, n_trials=300, seed=42)[:5]
    for i, (weights, result) in enumerate(top5, start=1):
        print(f"[{i}] {format_result('candidate', result, base=baseline)}")
        print(f"     weights={asdict(weights)}")

    if args.with_recent_form:
        print()
        print("=== 直近成績（過去3節）weight ablation ===")
        print("選手の直近成績を取得中（未キャッシュ分のみネットワークアクセス）...")
        recent_forms = load_recent_forms(client, dataset)
        print(f"取得できた選手数: {len(recent_forms)}")
        for label, w_value in [("0.05", 0.05), ("0.10", 0.10), ("0.20", 0.20)]:
            w = replace(DEFAULT_WEIGHTS, recent_form_weight=w_value)
            result = evaluate(dataset, w, recent_forms=recent_forms)
            print(format_result(f"recent_form_weight={label}", result, base=baseline))
        print(
            "※ このデータ量での参考結果。baseline比で明確かつ一貫した改善が見えない限り、"
            "PredictorWeights.recent_form_weightの既定値(0)は動かさないこと。"
        )


if __name__ == "__main__":
    main()
