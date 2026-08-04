"""競艇予想CLI。

使い方:
    kyotei predict --venue 桐生 --date 20260802 --race 1
    kyotei predict --venue 01 --date 20260802 --race 1 --no-cache
    kyotei predict --venue 桐生 --date 20260802 --race 5 --budget 1000
    kyotei backtest --venue 桐生 --date 20260731 --race 1
    kyotei backtest-day --date 20260731 --venues 桐生,唐津
    kyotei backtest-day --date 20260731 --venues all
    kyotei scan --date 20260802 --venues all --races 1-12 --genre 大穴 --top 10
    kyotei stats
    kyotei stats --venue 桐生 --from 20260701 --to 20260731
    kyotei patterns
    kyotei favorite add-racer 4300 --label 加藤綾
    kyotei favorite add-venue 桐生
    kyotei favorite list
    kyotei favorite today --date 20260802
    kyotei today --date 20260802
    kyotei predict-all --date 20260803 --venues all --races 1-12

全24競艇場で同じテンプレートのページを使用しているため、--venue には
場名（例: 桐生）または2桁の場コード（例: 01）のどちらも指定できる。
"""
from __future__ import annotations

import argparse
import sys

from kyotei.backtest import parse_race_range, run_day_backtest, run_single_backtest
from kyotei.constants import VENUES, racer_profile_url, raceresult_url, venue_code
from kyotei.dayview import fetch_day_results
from kyotei.models.allocation import allocate_budget
from kyotei.models.combos import exacta_candidates, trifecta_candidates
from kyotei.models.entities import BeforeInfo, RacePrediction, RecentForm, TrifectaOdds
from kyotei.models.genres import (
    GENRE_CHUANA,
    GENRE_HONMEI,
    GENRE_OOANA,
    LONGSHOT_ODDS_MIN,
    MID_ODDS_MIN,
    categorize_trifecta,
)
from kyotei.favoritesview import today_favorite_races
from kyotei.models.predictor import predict_race
from kyotei.models.scan import scan_races, top_candidates
from kyotei.predictionlog import compare_logged_predictions
from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.odds import parse_odds3t_html
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.scraper.racerform import parse_racer_back3_html
from kyotei.storage import (
    FAVORITE_RACER,
    FAVORITE_VENUE,
    BacktestOutcome,
    BacktestStore,
    FavoriteStore,
    OddsSnapshotStore,
    PredictionLogStore,
)


def _fetch_recent_form(client: BoatraceClient, racer_id: int) -> RecentForm | None:
    try:
        html = client.get_racer_back3_html(racer_id)
        return parse_racer_back3_html(html, racer_id)
    except Exception:
        return None


def _format_prediction(
    client: BoatraceClient,
    prediction: RacePrediction,
    before_info: BeforeInfo | None,
    odds_list: list[TrifectaOdds] | None,
    budget: int | None,
    recent_forms: dict[int, RecentForm | None] | None = None,
    odds_history: list[dict] | None = None,
    favorite_racer_ids: set[int] | None = None,
) -> str:
    race = prediction.race
    favorite_racer_ids = favorite_racer_ids or set()
    grade_label = f"[{race.grade}] " if race.grade and race.grade != "一般" else ""
    lines = [
        f"{grade_label}{race.venue_name}（{race.venue_code}） {race.date} {race.race_number}R 予想",
        "※ 統計的な参考情報であり、的中・回収を保証するものではありません。舟券の購入判断はご自身で。",
        "",
        "[推定勝率]",
        f"{'枠':<3}{'選手名':<12}{'推定勝率':>10}",
    ]
    for p in prediction.as_rank_list():
        star = "★" if race.entry(p.lane).racer_id in favorite_racer_ids else ""
        lines.append(f"{p.lane:<3}{p.racer_name + star:<12}{p.win_probability * 100:>9.1f}%")

    lines.append("")
    lines.append("[予想根拠]")
    for p in prediction.as_rank_list():
        lines.append(f"{p.lane}  {p.racer_name}: {p.rationale_summary}")

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

    if recent_forms is not None:
        lines.append("")
        lines.append("[直近成績（過去3節、参考情報。予想スコアには未反映）]")
        for e in sorted(race.entries, key=lambda x: x.lane):
            form = recent_forms.get(e.racer_id)
            if form is None or not form.meetings:
                lines.append(f"{e.lane}  {e.name}: データなし")
                continue
            avg = form.average_finish()
            top3 = form.top3_rate()
            avg_text = f"平均着順{avg:.1f}" if avg is not None else "平均着順-"
            top3_text = f"3着内率{top3:.0f}%" if top3 is not None else "3着内率-"
            latest = form.meetings[0]
            sequence = "".join(latest.raw_labels)
            lines.append(
                f"{e.lane}  {e.name}: {avg_text} {top3_text}"
                f"（直近節 {latest.venue_name} {sequence}）"
            )

    lines.append("")
    lines.append("[買い目候補（3連単）]")
    if odds_list is None:
        lines.append("（オッズ未取得のため「本命」のみ表示。中穴・大穴の判定にはオッズが必要）")
    genres = categorize_trifecta(prediction.predictions, odds_list, top_n=5)
    genre_notes = {
        GENRE_HONMEI: "的中重視・推定確率が高い順",
        GENRE_CHUANA: f"そこそこ的中も狙えるオッズ帯（目安{MID_ODDS_MIN:.0f}〜{LONGSHOT_ODDS_MIN:.0f}倍）",
        GENRE_OOANA: "高配当狙い。期待値(推定確率×オッズ)が高い順",
    }
    budget_target_genre: list = []
    for genre in (GENRE_HONMEI, GENRE_CHUANA, GENRE_OOANA):
        candidates = genres[genre]
        if not candidates:
            continue
        lines.append(f"● {genre}（{genre_notes[genre]}）")
        for c in candidates:
            odds_text = f" オッズ{c.odds:.1f}倍" if c.odds is not None else ""
            ev_text = f" 期待値{c.expected_value:.2f}" if c.expected_value is not None else ""
            lines.append(f"  {c.label:<10}確率{c.probability * 100:>5.1f}%{odds_text}{ev_text}")
        if genre == GENRE_HONMEI:
            budget_target_genre = candidates

    lines.append("")
    lines.append("[買い目候補（2連単 上位3点）]")
    for t in exacta_candidates(prediction.predictions, top_n=3):
        lines.append(f"{t.label:<10}{t.probability * 100:>6.1f}%")

    if budget is not None and budget_target_genre:
        lines.append("")
        lines.append(f"[予算配分（本命 {len(budget_target_genre)}点、予算{budget}円）]")
        allocations = allocate_budget(budget_target_genre, budget)
        if not allocations:
            lines.append(f"（予算{budget}円では100円単位の配分ができません）")
        else:
            total = 0
            for a in allocations:
                lines.append(f"  {a.candidate.label:<10}{a.amount:>6}円")
                total += a.amount
            lines.append(f"  合計: {total}円（予算との差額 {budget - total}円は未配分）")

    if odds_history:
        by_combo: dict[str, list[dict]] = {}
        for h in odds_history:
            by_combo.setdefault(h["combo"], []).append(h)
        if any(len(v) >= 2 for v in by_combo.values()):
            lines.append("")
            lines.append("[オッズの推移（本命上位3点、このレースをこのアプリで見るたびに記録）]")
            for combo, points in by_combo.items():
                series = " → ".join(f"{p['odds']:.1f}倍" for p in points)
                lines.append(f"  {combo:<10}{series}")

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

    if race.race_number > 1:
        lines.append("")
        lines.append(f"[本日ここまでの結果（{race.venue_name}）]")
        earlier = fetch_day_results(client, race.venue_code, race.date, list(range(1, race.race_number)))
        if not earlier:
            lines.append("（まだ確定した結果はありません）")
        for r in earlier:
            top3 = sorted((e for e in r.entries if 1 <= e.rank <= 3), key=lambda e: e.rank)
            top3_text = " ".join(f"{e.rank}着{e.lane}号艇" for e in top3)
            lines.append(f"  {r.race_number}R: {top3_text}")
            lines.append(f"    詳細: {raceresult_url(race.venue_code, race.date, r.race_number)}")

    return "\n".join(lines)


def _fetch_before_info(
    client: BoatraceClient, code: str, date: str, race_number: int
) -> BeforeInfo | None:
    try:
        html = client.get_beforeinfo_html(code, date, race_number)
        return parse_beforeinfo_html(html, code, date, race_number)
    except Exception:
        return None


def _fetch_odds(
    client: BoatraceClient, code: str, date: str, race_number: int
) -> list[TrifectaOdds] | None:
    try:
        html = client.get_odds3t_html(code, date, race_number)
        odds_list = parse_odds3t_html(html, code, date, race_number)
        return odds_list or None
    except Exception:
        return None


def cmd_predict(args: argparse.Namespace) -> int:
    code = venue_code(args.venue)
    client = BoatraceClient(use_cache=not args.no_cache)
    html = client.get_racelist_html(code, args.date, args.race)
    race = parse_racelist_html(html, code, args.date, args.race)
    before_info = _fetch_before_info(client, code, args.date, args.race)
    odds_list = _fetch_odds(client, code, args.date, args.race)
    prediction = predict_race(race, before_info=before_info)
    recent_forms = None
    if not args.no_recent_form:
        recent_forms = {
            e.racer_id: _fetch_recent_form(client, e.racer_id) for e in race.entries
        }

    PredictionLogStore().log(prediction)

    odds_snapshots = OddsSnapshotStore()
    if odds_list:
        odds_map = {o.lanes: o.odds for o in odds_list}
        top3 = trifecta_candidates(prediction.predictions, top_n=3)
        entries = [(t.label, odds_map[t.lanes]) for t in top3 if t.lanes in odds_map]
        odds_snapshots.record(code, args.date, args.race, entries)
    odds_history = odds_snapshots.history(code, args.date, args.race)

    favorite_racer_ids = {
        int(f["key"]) for f in FavoriteStore().list(kind=FAVORITE_RACER)
    }

    print(
        _format_prediction(
            client,
            prediction,
            before_info,
            odds_list,
            args.budget,
            recent_forms,
            odds_history,
            favorite_racer_ids,
        )
    )
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


def cmd_scan(args: argparse.Namespace) -> int:
    if args.favorites_only:
        codes = [venue_code(f["key"]) for f in FavoriteStore().list(kind=FAVORITE_VENUE)]
        if not codes:
            print("お気に入り登録された競艇場がありません（`kyotei favorite add-venue` で登録してください）。")
            return 0
    elif args.venues is None:
        print("エラー: --venues か --favorites-only のどちらかを指定してください。", file=sys.stderr)
        return 1
    elif args.venues.strip().lower() == "all":
        codes = list(VENUES.keys())
    else:
        codes = [venue_code(v.strip()) for v in args.venues.split(",") if v.strip()]

    races = parse_race_range(args.races)
    client = BoatraceClient(use_cache=not args.no_cache)

    print(f"[{args.genre}スキャン] {args.date} 対象{len(codes)}場×{len(races)}レース")
    print("※ 統計的な参考情報であり、的中・回収を保証するものではありません。")
    print()
    results = top_candidates(
        client, codes, args.date, races, genre=args.genre, top_n=args.top
    )
    if not results:
        print("該当する候補が見つかりませんでした（オッズ未発表のレースが多い可能性があります）。")
        return 0
    for r in results:
        c = r.candidate
        odds_text = f" オッズ{c.odds:.1f}倍" if c.odds is not None else ""
        ev_text = f" 期待値{c.expected_value:.2f}" if c.expected_value is not None else ""
        print(
            f"{r.venue_name} {r.race_number}R  {c.label:<10}確率{c.probability * 100:>5.1f}%"
            f"{odds_text}{ev_text}"
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


def cmd_patterns(args: argparse.Namespace) -> int:
    store = BacktestStore()
    by_venue = store.stats_by_venue(date_from=args.date_from, date_to=args.date_to)
    if not by_venue:
        print("該当するbacktestデータがありません。先に `kyotei backtest` / `kyotei backtest-day` を実行してください。")
        return 0

    print("[場ごとの的中率・回収率（勝ちパターン分析）]")
    for r in sorted(by_venue, key=lambda x: x["top1_rate"], reverse=True):
        print(
            f"{r['venue_name']:<6} 件数{r['count']:>4}件  "
            f"単勝的中率{r['top1_rate'] * 100:>5.1f}%  "
            f"単勝回収率{r['tansho_roi'] * 100:>6.1f}%  "
            f"3連単回収率{r['trifecta_roi'] * 100:>6.1f}%"
        )

    by_grade = store.stats_by_grade(date_from=args.date_from, date_to=args.date_to)
    if by_grade:
        print()
        print("[グレードごとの的中率・回収率]")
        for r in by_grade:
            print(
                f"{r['grade']:<4} 件数{r['count']:>4}件  "
                f"単勝的中率{r['top1_rate'] * 100:>5.1f}%  "
                f"単勝回収率{r['tansho_roi'] * 100:>6.1f}%  "
                f"3連単回収率{r['trifecta_roi'] * 100:>6.1f}%"
            )
    else:
        print()
        print(
            "（グレードデータがまだ記録されていません。2026-08-04以降にbacktestを実行したレース分から"
            "記録されます。既存のキャッシュ済みレースも `kyotei backtest`/`kyotei backtest-day` を"
            "再実行すれば遡って記録できます）"
        )

    monthly = store.monthly_stats(date_from=args.date_from, date_to=args.date_to)
    if monthly:
        print()
        print("[月ごとの的中率・回収率]")
        for r in monthly:
            month_label = f"{r['month'][:4]}-{r['month'][4:6]}"
            print(
                f"{month_label} 件数{r['count']:>4}件  "
                f"単勝的中率{r['top1_rate'] * 100:>5.1f}%  "
                f"単勝回収率{r['tansho_roi'] * 100:>6.1f}%  "
                f"3連単回収率{r['trifecta_roi'] * 100:>6.1f}%"
            )

    print()
    print("[推定勝率帯ごとの実際の的中率（モデルの自信度は信頼できるか）]")
    by_confidence = store.stats_by_confidence(date_from=args.date_from, date_to=args.date_to)
    for r in by_confidence:
        if r["count"] == 0:
            continue
        print(
            f"予想1位の推定勝率 {r['bucket']:<8} 件数{r['count']:>4}件  "
            f"実際の的中率{r['top1_rate'] * 100:>5.1f}%  単勝回収率{r['tansho_roi'] * 100:>6.1f}%"
        )
    print("※ 推定勝率帯が上がるほど実際の的中率も上がっていれば、モデルの確率の付け方は妥当と判断できる目安。")

    by_weather = store.stats_by_weather(date_from=args.date_from, date_to=args.date_to)
    by_wind = [r for r in store.stats_by_wind_speed(date_from=args.date_from, date_to=args.date_to) if r["count"] > 0]
    by_wave = [r for r in store.stats_by_wave_height(date_from=args.date_from, date_to=args.date_to) if r["count"] > 0]
    if by_weather or by_wind or by_wave:
        print()
        print("[天候ごとの的中率・回収率]")
        print("※ 予想スコアには天候を反映していない。荒天時に的中率が下がる傾向があるかの参考情報。")
        for r in by_weather:
            print(
                f"天候={r['weather']:<4} 件数{r['count']:>4}件  "
                f"単勝的中率{r['top1_rate'] * 100:>5.1f}%  単勝回収率{r['tansho_roi'] * 100:>6.1f}%"
            )
        for r in by_wind:
            print(
                f"風速 {r['bucket']:<6} 件数{r['count']:>4}件  "
                f"実際の的中率{r['top1_rate'] * 100:>5.1f}%  単勝回収率{r['tansho_roi'] * 100:>6.1f}%"
            )
        for r in by_wave:
            print(
                f"波高 {r['bucket']:<6} 件数{r['count']:>4}件  "
                f"実際の的中率{r['top1_rate'] * 100:>5.1f}%  単勝回収率{r['tansho_roi'] * 100:>6.1f}%"
            )
    else:
        print()
        print(
            "（天候データがまだ記録されていません。2026-08-03以降にbacktestを実行したレース分から"
            "記録されます。既存のキャッシュ済みレースも `kyotei backtest`/`kyotei backtest-day` を"
            "再実行すれば遡って記録できます）"
        )
    return 0


def cmd_favorite_add_racer(args: argparse.Namespace) -> int:
    label = args.label or f"選手{args.racer_id}"
    FavoriteStore().add(FAVORITE_RACER, str(args.racer_id), label)
    print(f"お気に入り選手に追加しました: {label}（登録番号{args.racer_id}）")
    return 0


def cmd_favorite_add_venue(args: argparse.Namespace) -> int:
    code = venue_code(args.venue)
    FavoriteStore().add(FAVORITE_VENUE, code, VENUES.get(code, code))
    print(f"お気に入り競艇場に追加しました: {VENUES.get(code, code)}")
    return 0


def cmd_favorite_remove_racer(args: argparse.Namespace) -> int:
    FavoriteStore().remove(FAVORITE_RACER, str(args.racer_id))
    print(f"お気に入り選手から削除しました: 登録番号{args.racer_id}")
    return 0


def cmd_favorite_remove_venue(args: argparse.Namespace) -> int:
    code = venue_code(args.venue)
    FavoriteStore().remove(FAVORITE_VENUE, code)
    print(f"お気に入り競艇場から削除しました: {VENUES.get(code, code)}")
    return 0


def cmd_favorite_list(_args: argparse.Namespace) -> int:
    store = FavoriteStore()
    racers = store.list(kind=FAVORITE_RACER)
    venues = store.list(kind=FAVORITE_VENUE)
    print("[お気に入り選手]")
    if not racers:
        print("（登録なし）")
    for f in racers:
        print(f"  {f['label']}（登録番号{f['key']}）: {racer_profile_url(int(f['key']))}")
    print()
    print("[お気に入り競艇場]")
    if not venues:
        print("（登録なし）")
    for f in venues:
        print(f"  {f['label']}")
    return 0


def cmd_favorite_today(args: argparse.Namespace) -> int:
    client = BoatraceClient(use_cache=not args.no_cache)
    races = parse_race_range(args.races)
    matches = today_favorite_races(client, args.date, races)
    if not matches:
        print(
            "お気に入り競艇場での開催が見つかりませんでした"
            "（お気に入り競艇場が未登録か、その日は開催がない可能性があります）。"
        )
        return 0
    for m in matches:
        top = m.prediction.as_rank_list()[0]
        star_text = ""
        if m.favorite_racer_lanes:
            lanes_text = "・".join(f"{lane}号艇" for lane in m.favorite_racer_lanes)
            star_text = f"  ★お気に入り選手: {lanes_text}"
        print(
            f"{m.venue_name} {m.race_number}R: "
            f"予想1位={top.lane}号艇 {top.racer_name}（{top.win_probability * 100:.1f}%）{star_text}"
        )
    return 0


def cmd_today(args: argparse.Namespace) -> int:
    client = BoatraceClient(use_cache=not args.no_cache)
    log_store = PredictionLogStore()
    rows = list(compare_logged_predictions(client, log_store, args.date))
    if not rows:
        print(f"{args.date} 分の予想ログがありません（`kyotei predict` で予想を見るとログされます）。")
        return 0

    resolved = [r for r in rows if r["status"] == "resolved"]
    unresolved = [r for r in rows if r["status"] != "resolved"]

    print(f"[{args.date} に見た予想の振り返り]")
    for r in resolved:
        mark = "◎的中" if r["top1_hit"] else "✕"
        prob_text = (
            f"（推定勝率{r['predicted_top_probability'] * 100:.1f}%）"
            if r["predicted_top_probability"] is not None
            else ""
        )
        print(
            f"{r['venue_name']} {r['race_number']}R: "
            f"予想1位={r['predicted_top_lane']}号艇{prob_text} / "
            f"実際1着={r['actual_winner_lane']}号艇 {mark}"
        )
    if resolved:
        hit = sum(1 for r in resolved if r["top1_hit"])
        print(f"\n確定分 的中率: {hit}/{len(resolved)}件 ({hit / len(resolved) * 100:.1f}%)")
    if unresolved:
        print(f"\n未確定（開催前・進行中）: {len(unresolved)}件")
        for r in unresolved:
            print(f"  {r['venue_name']} {r['race_number']}R")
    return 0


def cmd_predict_all(args: argparse.Namespace) -> int:
    """指定日の複数レースをまとめて予想し、予想ログに記録する（`kyotei today`で後日振り返れる）。

    直前情報・オッズ・選手の直近成績は前日以前だとまだ公開されていないことが多く、
    その場合は出走表データのみでの予想になる（`predict_race`はbefore_infoがNoneでも動作する）。
    """
    if args.venues.strip().lower() == "all":
        codes = list(VENUES.keys())
    else:
        codes = [venue_code(v.strip()) for v in args.venues.split(",") if v.strip()]

    races = parse_race_range(args.races)
    client = BoatraceClient(use_cache=not args.no_cache)
    log_store = PredictionLogStore()

    print(f"[{args.date} 全レース予想] 対象{len(codes)}場×{len(races)}レース")
    ran = skipped = 0
    for code, race_number, prediction, _genres, error in scan_races(client, codes, args.date, races):
        if error is not None or prediction is None:
            skipped += 1
            continue
        log_store.log(prediction)
        ran += 1
        top = prediction.as_rank_list()[0]
        print(
            f"{VENUES.get(code, code)} {race_number}R: "
            f"予想1位={top.lane}号艇 {top.racer_name}（{top.win_probability * 100:.1f}%）"
        )

    print(f"\n実行: {ran}件 / スキップ: {skipped}件（予想ログに記録。`kyotei today --date {args.date}` で後日振り返れます）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kyotei", description="競艇予想CLI（全24競艇場対応）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    predict_parser = subparsers.add_parser("predict", help="指定レースの予想を表示する")
    predict_parser.add_argument("--venue", required=True, help="競艇場名 または 場コード（例: 桐生, 01）")
    predict_parser.add_argument("--date", required=True, help="開催日 YYYYMMDD（例: 20260802）")
    predict_parser.add_argument("--race", required=True, type=int, help="レース番号 1-12")
    predict_parser.add_argument(
        "--budget", type=int, default=None, help="予算（円）。指定すると本命の買い目に配分する"
    )
    predict_parser.add_argument(
        "--no-cache", action="store_true", help="ローカルキャッシュを使わず毎回取得する"
    )
    predict_parser.add_argument(
        "--no-recent-form",
        action="store_true",
        help="選手の直近成績（過去3節）取得をスキップする（6選手分で追加リクエストが発生するため）",
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

    scan_parser = subparsers.add_parser(
        "scan", help="複数場・複数レースを横断して狙い目の買い目候補を探す"
    )
    scan_parser.add_argument("--date", required=True, help="開催日 YYYYMMDD")
    scan_parser.add_argument(
        "--venues",
        default=None,
        help="場名/場コードのカンマ区切り（例: 桐生,唐津）。全24場対象なら 'all' を指定。"
        "--favorites-only と併用不可",
    )
    scan_parser.add_argument(
        "--favorites-only",
        action="store_true",
        help="お気に入り登録した競艇場のみを対象にする（`kyotei favorite add-venue` で登録）",
    )
    scan_parser.add_argument(
        "--races", default="1-12", help="レース番号（例: 1-12 や 1,3,5）。デフォルト全レース"
    )
    scan_parser.add_argument(
        "--genre",
        default=GENRE_OOANA,
        choices=[GENRE_HONMEI, GENRE_CHUANA, GENRE_OOANA],
        help="対象ジャンル（デフォルト: 大穴）",
    )
    scan_parser.add_argument("--top", type=int, default=10, help="表示件数（デフォルト10件）")
    scan_parser.add_argument("--no-cache", action="store_true")
    scan_parser.set_defaults(func=cmd_scan)

    stats_parser = subparsers.add_parser("stats", help="蓄積したbacktest結果の的中率を表示する")
    stats_parser.add_argument("--venue", default=None, help="場名/場コードで絞り込み（省略可）")
    stats_parser.add_argument("--from", dest="date_from", default=None, help="開始日 YYYYMMDD")
    stats_parser.add_argument("--to", dest="date_to", default=None, help="終了日 YYYYMMDD")
    stats_parser.set_defaults(func=cmd_stats)

    patterns_parser = subparsers.add_parser(
        "patterns", help="場ごと・自信度ごとの的中率を集計し、勝ちパターンを分析する"
    )
    patterns_parser.add_argument("--from", dest="date_from", default=None, help="開始日 YYYYMMDD")
    patterns_parser.add_argument("--to", dest="date_to", default=None, help="終了日 YYYYMMDD")
    patterns_parser.set_defaults(func=cmd_patterns)

    favorite_parser = subparsers.add_parser("favorite", help="お気に入り選手・競艇場を管理する")
    favorite_subparsers = favorite_parser.add_subparsers(dest="favorite_command", required=True)

    fav_add_racer = favorite_subparsers.add_parser("add-racer", help="お気に入り選手を追加する")
    fav_add_racer.add_argument("racer_id", type=int, help="選手登録番号")
    fav_add_racer.add_argument("--label", default=None, help="表示名（省略時は「選手{番号}」）")
    fav_add_racer.set_defaults(func=cmd_favorite_add_racer)

    fav_add_venue = favorite_subparsers.add_parser("add-venue", help="お気に入り競艇場を追加する")
    fav_add_venue.add_argument("venue", help="競艇場名 または 場コード")
    fav_add_venue.set_defaults(func=cmd_favorite_add_venue)

    fav_remove_racer = favorite_subparsers.add_parser("remove-racer", help="お気に入り選手を削除する")
    fav_remove_racer.add_argument("racer_id", type=int, help="選手登録番号")
    fav_remove_racer.set_defaults(func=cmd_favorite_remove_racer)

    fav_remove_venue = favorite_subparsers.add_parser("remove-venue", help="お気に入り競艇場を削除する")
    fav_remove_venue.add_argument("venue", help="競艇場名 または 場コード")
    fav_remove_venue.set_defaults(func=cmd_favorite_remove_venue)

    fav_list = favorite_subparsers.add_parser("list", help="お気に入り一覧を表示する")
    fav_list.set_defaults(func=cmd_favorite_list)

    fav_today = favorite_subparsers.add_parser(
        "today", help="お気に入り競艇場の今日の開催・お気に入り選手の出走有無をまとめて表示する"
    )
    fav_today.add_argument("--date", required=True, help="対象日 YYYYMMDD")
    fav_today.add_argument(
        "--races", default="1-12", help="レース番号（例: 1-12 や 1,3,5）。デフォルト全レース"
    )
    fav_today.add_argument("--no-cache", action="store_true")
    fav_today.set_defaults(func=cmd_favorite_today)

    today_parser = subparsers.add_parser(
        "today", help="`predict`で実際に見た予想を、確定結果と突き合わせて振り返る"
    )
    today_parser.add_argument("--date", required=True, help="対象日 YYYYMMDD")
    today_parser.add_argument("--no-cache", action="store_true")
    today_parser.set_defaults(func=cmd_today)

    predict_all_parser = subparsers.add_parser(
        "predict-all",
        help="指定日の複数レースをまとめて予想し、予想ログに記録する（`kyotei today`で後日振り返り可能）",
    )
    predict_all_parser.add_argument("--date", required=True, help="対象日 YYYYMMDD")
    predict_all_parser.add_argument(
        "--venues", default="all", help="場名/場コードのカンマ区切り。デフォルト'all'（全24場）"
    )
    predict_all_parser.add_argument(
        "--races", default="1-12", help="レース番号（例: 1-12 や 1,3,5）。デフォルト全レース"
    )
    predict_all_parser.add_argument("--no-cache", action="store_true")
    predict_all_parser.set_defaults(func=cmd_predict_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Windowsのコンソール（cp932等）では◎/○/✕のような記号文字がエンコードできず
    # UnicodeEncodeErrorでクラッシュすることがある（タスクスケジューラ経由の非対話実行時に
    # 顕在化しやすい）。コンソールの文字コードに関わらず出力できるよう、標準出力・標準エラーを
    # UTF-8に強制する（表示できない文字は環境依存のフォールバック表示に留め、クラッシュさせない）。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # CLIの最終防衛ライン。原因をそのまま利用者に見せる。
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
