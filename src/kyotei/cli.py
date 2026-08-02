"""競艇予想CLI。

使い方:
    kyotei predict --venue 桐生 --date 20260802 --race 1
    kyotei predict --venue 01 --date 20260802 --race 1 --no-cache
    kyotei backtest --venue 桐生 --date 20260731 --race 1
    kyotei backtest-day --date 20260731 --venues 桐生,唐津
    kyotei backtest-day --date 20260731 --venues all
    kyotei stats
    kyotei stats --venue 桐生 --from 20260701 --to 20260731

全24競艇場で同じテンプレートのページを使用しているため、--venue には
場名（例: 桐生）または2桁の場コード（例: 01）のどちらも指定できる。
"""
from __future__ import annotations

import argparse
import sys

from kyotei.backtest import parse_race_range, run_day_backtest, run_single_backtest
from kyotei.constants import VENUES, racer_profile_url, venue_code
from kyotei.models.combos import exacta_candidates, trifecta_candidates
from kyotei.models.entities import BeforeInfo, RacePrediction
from kyotei.models.predictor import predict_race
from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.storage import BacktestOutcome, BacktestStore


def _format_prediction(prediction: RacePrediction, before_info: BeforeInfo | None) -> str:
    race = prediction.race
    lines = [
        f"{race.venue_name}（{race.venue_code}） {race.date} {race.race_number}R 予想",
        "※ 統計的な参考情報であり、的中・回収を保証するものではありません。舟券の購入判断はご自身で。",
        "",
        "[推定勝率]",
        f"{'枠':<3}{'選手名':<12}{'推定勝率':>10}",
    ]
    for p in prediction.as_rank_list():
        lines.append(f"{p.lane:<3}{p.racer_name:<12}{p.win_probability * 100:>9.1f}%")

    lines.append("")
    lines.append("[選手情報]")
    lines.append(
        f"{'枠':<3}{'級別':<5}{'全国勝率':>9}{'当地勝率':>9}"
        f"{'モーター2連率':>13}{'ボート2連率':>12}{'F数':>5}{'平均ST':>8}"
    )
    for e in sorted(race.entries, key=lambda x: x.lane):
        flying_flag = f"{e.flying_count}" + ("!" if e.flying_count > 0 else "")
        lines.append(
            f"{e.lane:<3}{e.racer_class:<5}{e.national_win_rate:>8.2f}%{e.local_win_rate:>8.2f}%"
            f"{e.motor_2nd_rate:>12.1f}%{e.boat_2nd_rate:>11.1f}%{flying_flag:>5}{e.avg_start_timing:>8.2f}"
        )

    lines.append("")
    lines.append("[選手プロフィール（BOATRACE公式サイト）]")
    for e in sorted(race.entries, key=lambda x: x.lane):
        lines.append(f"{e.lane}  {e.name}: {racer_profile_url(e.racer_id)}")

    lines.append("")
    lines.append("[買い目候補（3連単 上位6点、推定勝率からのHarville近似）]")
    for t in trifecta_candidates(prediction.predictions, top_n=6):
        lines.append(f"{t.label:<10}{t.probability * 100:>6.1f}%")
    lines.append("")
    lines.append("[買い目候補（2連単 上位3点）]")
    for t in exacta_candidates(prediction.predictions, top_n=3):
        lines.append(f"{t.label:<10}{t.probability * 100:>6.1f}%")

    if before_info is not None:
        lines.append("")
        if before_info.exhibitions:
            lines.append("[直前情報]")
            lines.append(f"{'枠':<3}{'展示T':>7}{'進入':>6}{'調整体重':>9}")
            for e in sorted(before_info.exhibitions, key=lambda x: x.lane):
                course = e.entry_course if e.entry_course is not None else "-"
                lines.append(
                    f"{e.lane:<3}{e.exhibition_time:>7.2f}{str(course):>6}{e.adjust_weight:>9.1f}"
                )
        if before_info.weather is not None:
            w = before_info.weather
            lines.append("")
            lines.append(
                f"[気象情報]（{w.measured_at}）: {w.weather} 気温{w.temperature}℃ "
                f"風速{w.wind_speed}m 水温{w.water_temperature}℃ 波高{w.wave_height}cm"
            )
    else:
        lines.append("")
        lines.append("（直前情報は未取得または未公開のため、出走表データのみで予想しています）")

    return "\n".join(lines)


def _fetch_before_info(
    client: BoatraceClient, code: str, date: str, race_number: int
) -> BeforeInfo | None:
    try:
        html = client.get_beforeinfo_html(code, date, race_number)
        return parse_beforeinfo_html(html, code, date, race_number)
    except Exception:
        return None


def cmd_predict(args: argparse.Namespace) -> int:
    code = venue_code(args.venue)
    client = BoatraceClient(use_cache=not args.no_cache)
    html = client.get_racelist_html(code, args.date, args.race)
    race = parse_racelist_html(html, code, args.date, args.race)
    before_info = _fetch_before_info(client, code, args.date, args.race)
    prediction = predict_race(race, before_info=before_info)
    print(_format_prediction(prediction, before_info))
    return 0


def cmd_venues(_args: argparse.Namespace) -> int:
    for code, name in VENUES.items():
        print(f"{code}: {name}")
    return 0


def _format_outcome(outcome: BacktestOutcome) -> str:
    hit_mark = "◎的中" if outcome.top1_hit else "✕"
    trifecta_mark = "◎的中" if outcome.trifecta_top1_hit else "✕"
    return (
        f"{outcome.venue_name} {outcome.date} {outcome.race_number}R: "
        f"予想1位={outcome.predicted_ranking[0]}号艇 / "
        f"実際1着={outcome.actual_winner_lane}号艇 {hit_mark} "
        f"(上位2着以内={'○' if outcome.top2_hit else '✕'}, "
        f"上位3着以内={'○' if outcome.top3_hit else '✕'}, "
        f"単勝払戻={outcome.tansho_payout}円, "
        f"3連単本命{trifecta_mark}払戻={outcome.trifecta_top1_payout}円)"
    )


def cmd_backtest(args: argparse.Namespace) -> int:
    code = venue_code(args.venue)
    client = BoatraceClient(use_cache=not args.no_cache)
    store = BacktestStore()
    outcome = run_single_backtest(client, store, code, args.date, args.race)
    print(_format_outcome(outcome))
    return 0


def cmd_backtest_day(args: argparse.Namespace) -> int:
    if args.venues.strip().lower() == "all":
        codes = list(VENUES.keys())
    else:
        codes = [venue_code(v.strip()) for v in args.venues.split(",") if v.strip()]

    races = parse_race_range(args.races)

    client = BoatraceClient(use_cache=not args.no_cache)
    store = BacktestStore()

    ran = 0
    skipped = 0
    for code, race_number, outcome, error in run_day_backtest(
        client, store, codes, args.date, races
    ):
        if error is not None:
            print(
                f"{VENUES.get(code, code)} {args.date} {race_number}R: スキップ ({error})",
                file=sys.stderr,
            )
            skipped += 1
        else:
            print(_format_outcome(outcome))
            ran += 1

    print(f"\n実行: {ran}件 / スキップ: {skipped}件")
    stats = store.stats(date_from=args.date, date_to=args.date)
    if stats["count"] > 0:
        print(
            f"本日分 的中率: 単勝的中(1位予想が的中)={stats['top1_rate'] * 100:.1f}% "
            f"/ 上位2着以内={stats['top2_rate'] * 100:.1f}% "
            f"/ 上位3着以内={stats['top3_rate'] * 100:.1f}%"
        )
        print(
            f"本日分 回収率: 単勝(本命1点)={stats['tansho_roi'] * 100:.1f}% "
            f"/ 3連単(本命1点)={stats['trifecta_roi'] * 100:.1f}%"
        )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = BacktestStore()
    code = venue_code(args.venue) if args.venue else None
    stats = store.stats(venue_code=code, date_from=args.date_from, date_to=args.date_to)
    if stats["count"] == 0:
        print("該当するbacktestデータがありません。先に `kyotei backtest` を実行してください。")
        return 0
    print(f"対象レース数: {stats['count']}")
    print()
    print("[的中率]")
    print(f"単勝的中率（予想1位＝実際1着）: {stats['top1_rate'] * 100:.1f}%")
    print(f"予想上位2艇以内に実際の1着: {stats['top2_rate'] * 100:.1f}%")
    print(f"予想上位3艇以内に実際の1着: {stats['top3_rate'] * 100:.1f}%")
    print(f"3連単本命的中率: {stats['trifecta_top1_rate'] * 100:.1f}%")
    print()
    print("[回収率（毎レース100円ずつ本命1点賭けした場合の試算。100%＝収支トントン）]")
    print(f"単勝: {stats['tansho_roi'] * 100:.1f}%")
    print(f"3連単: {stats['trifecta_roi'] * 100:.1f}%")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kyotei", description="競艇予想CLI（全24競艇場対応）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    predict_parser = subparsers.add_parser("predict", help="指定レースの予想を表示する")
    predict_parser.add_argument("--venue", required=True, help="競艇場名 または 場コード（例: 桐生, 01）")
    predict_parser.add_argument("--date", required=True, help="開催日 YYYYMMDD（例: 20260802）")
    predict_parser.add_argument("--race", required=True, type=int, help="レース番号 1-12")
    predict_parser.add_argument(
        "--no-cache", action="store_true", help="ローカルキャッシュを使わず毎回取得する"
    )
    predict_parser.set_defaults(func=cmd_predict)

    venues_parser = subparsers.add_parser("venues", help="全24競艇場の場コード一覧を表示する")
    venues_parser.set_defaults(func=cmd_venues)

    backtest_parser = subparsers.add_parser(
        "backtest", help="過去レース1件について予想と実際の結果を答え合わせし、DBに記録する"
    )
    backtest_parser.add_argument("--venue", required=True, help="競艇場名 または 場コード")
    backtest_parser.add_argument("--date", required=True, help="開催日 YYYYMMDD")
    backtest_parser.add_argument("--race", required=True, type=int, help="レース番号 1-12")
    backtest_parser.add_argument("--no-cache", action="store_true")
    backtest_parser.set_defaults(func=cmd_backtest)

    backtest_day_parser = subparsers.add_parser(
        "backtest-day", help="指定日の複数レースをまとめて答え合わせし、DBに記録する"
    )
    backtest_day_parser.add_argument("--date", required=True, help="開催日 YYYYMMDD")
    backtest_day_parser.add_argument(
        "--venues",
        required=True,
        help="場名/場コードのカンマ区切り（例: 桐生,唐津）。全24場対象なら 'all' を指定",
    )
    backtest_day_parser.add_argument(
        "--races", default="1-12", help="レース番号（例: 1-12 や 1,3,5）。デフォルト全レース"
    )
    backtest_day_parser.add_argument("--no-cache", action="store_true")
    backtest_day_parser.set_defaults(func=cmd_backtest_day)

    stats_parser = subparsers.add_parser("stats", help="蓄積したbacktest結果の的中率を表示する")
    stats_parser.add_argument("--venue", default=None, help="場名/場コードで絞り込み（省略可）")
    stats_parser.add_argument("--from", dest="date_from", default=None, help="開始日 YYYYMMDD")
    stats_parser.add_argument("--to", dest="date_to", default=None, help="終了日 YYYYMMDD")
    stats_parser.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # CLIの最終防衛ライン。原因をそのまま利用者に見せる。
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
