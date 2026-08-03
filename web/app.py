"""競艇予想Webダッシュボード（Streamlit）。

起動方法:
    streamlit run web/app.py

全24競艇場に対応した「レース予想」ページと、backtestで蓄積した
的中率を確認する「検証ダッシュボード」ページの2画面構成。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Streamlit Cloud等、`kyotei`パッケージがpipインストールされていない環境でも
# 確実にimportできるよう、src/を明示的にsys.pathへ追加する（-e .のインストールが
# 環境によっては反映されないことがあるための保険）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import altair as alt
import pandas as pd
import streamlit as st

from kyotei.backtest import parse_race_range, run_day_backtest
from kyotei.constants import VENUES, racer_profile_url, raceresult_url, venue_code
from kyotei.dayview import fetch_day_results
from kyotei.models.allocation import allocate_budget
from kyotei.models.combos import exacta_candidates, trifecta_candidates
from kyotei.models.genres import (
    GENRE_CHUANA,
    GENRE_HONMEI,
    GENRE_OOANA,
    LONGSHOT_ODDS_MIN,
    MID_ODDS_MIN,
    categorize_trifecta,
)
from kyotei.models.predictor import predict_race
from kyotei.models.scan import scan_races
from kyotei.predictionlog import compare_logged_predictions
from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.odds import parse_odds3t_html
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.scraper.racerform import parse_racer_back3_html
from kyotei.storage import (
    FAVORITE_RACER,
    FAVORITE_VENUE,
    BacktestStore,
    FavoriteStore,
    OddsSnapshotStore,
    PredictionLogStore,
)

# 検証済みカテゴリカルパレット（dataviz skill 参照）。固定順序で使い、循環させない。
CATEGORICAL_PALETTE = [
    "#2a78d6",  # 1: blue
    "#eb6834",  # 2: orange
    "#1baf7a",  # 3: aqua
    "#eda100",  # 4: yellow
    "#e87ba4",  # 5: magenta
    "#008300",  # 6: green
    "#4a3aa7",  # 7: violet
    "#e34948",  # 8: red
]
LANE_COLORS = CATEGORICAL_PALETTE[:6]
INK_SECONDARY = "#52514e"

st.set_page_config(page_title="競艇予想ダッシュボード", layout="wide")


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_prediction(code: str, date_str: str, race_number: int, use_cache: bool):
    client = BoatraceClient(use_cache=use_cache)
    html = client.get_racelist_html(code, date_str, race_number)
    race = parse_racelist_html(html, code, date_str, race_number)
    try:
        before_html = client.get_beforeinfo_html(code, date_str, race_number)
        before_info = parse_beforeinfo_html(before_html, code, date_str, race_number)
    except Exception:
        before_info = None
    try:
        odds_html = client.get_odds3t_html(code, date_str, race_number)
        odds_list = parse_odds3t_html(odds_html, code, date_str, race_number) or None
    except Exception:
        odds_list = None
    prediction = predict_race(race, before_info=before_info)

    PredictionLogStore().log(prediction)
    if odds_list:
        odds_map = {o.lanes: o.odds for o in odds_list}
        top3 = trifecta_candidates(prediction.predictions, top_n=3)
        entries = [(t.label, odds_map[t.lanes]) for t in top3 if t.lanes in odds_map]
        OddsSnapshotStore().record(code, date_str, race_number, entries)

    return before_info, odds_list, prediction


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_recent_forms(racer_ids: tuple[int, ...], use_cache: bool):
    client = BoatraceClient(use_cache=use_cache)
    forms = {}
    for racer_id in racer_ids:
        try:
            html = client.get_racer_back3_html(racer_id)
            forms[racer_id] = parse_racer_back3_html(html, racer_id)
        except Exception:
            forms[racer_id] = None
    return forms


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_earlier_results(code: str, date_str: str, race_number: int, use_cache: bool):
    if race_number <= 1:
        return []
    client = BoatraceClient(use_cache=use_cache)
    return fetch_day_results(client, code, date_str, list(range(1, race_number)))


def _render_predict_page() -> None:
    st.title("競艇予想（統計・ルールベース）")
    st.caption("※ 統計的な参考情報であり、的中・回収を保証するものではありません。舟券の購入判断はご自身で。")

    all_venue_names = list(VENUES.values())
    venue_names = st.sidebar.multiselect(
        "競艇場（複数選択可）", all_venue_names, default=[all_venue_names[0]]
    )
    race_date = st.sidebar.date_input("開催日", value=date.today())
    race_numbers = st.sidebar.multiselect(
        "レース番号（複数選択可）", list(range(1, 13)), default=[1], format_func=lambda n: f"{n}R"
    )
    use_cache = st.sidebar.checkbox("ローカルキャッシュを使う", value=True)
    show_recent_form = st.sidebar.checkbox(
        "直近成績（過去3節）も取得する", value=True, help="選手6人分で追加リクエストが発生し表示が少し遅くなる"
    )
    st.sidebar.caption("複数選択すると件数分まとめて表示します（多いほど時間がかかります）。")
    run = st.sidebar.button("予想する", type="primary")

    if not run:
        st.info("左のサイドバーで競艇場・開催日・レース番号を選び（複数選択可）「予想する」を押してください。")
        return

    if not venue_names or not race_numbers:
        st.warning("競艇場・レース番号をそれぞれ1つ以上選択してください。")
        return

    date_str = race_date.strftime("%Y%m%d")
    combos = [(v, r) for v in venue_names for r in race_numbers]

    if len(combos) == 1:
        venue_name, race_number = combos[0]
        _render_prediction_body(venue_name, date_str, race_number, use_cache, show_recent_form)
        return

    st.caption(f"選択された{len(combos)}件のレースを表示します。")
    for i, (venue_name, race_number) in enumerate(combos):
        with st.expander(f"{venue_name} {date_str} {race_number}R", expanded=(i == 0)):
            _render_prediction_body(venue_name, date_str, race_number, use_cache, show_recent_form)


def _render_prediction_body(
    venue_name: str, date_str: str, race_number: int, use_cache: bool, show_recent_form: bool
) -> None:
    code = venue_code(venue_name)

    try:
        with st.spinner("出走表・直前情報・オッズを取得中..."):
            before_info, odds_list, prediction = _fetch_prediction(
                code, date_str, race_number, use_cache
            )
    except Exception as exc:
        st.error(f"取得に失敗しました: {exc}")
        return

    ranked = prediction.as_rank_list()
    df = pd.DataFrame(
        [
            {"枠": p.lane, "選手名": p.racer_name, "推定勝率": p.win_probability * 100}
            for p in ranked
        ]
    )
    chart_df = df.sort_values("枠")

    bar = (
        alt.Chart(chart_df)
        .mark_bar(size=24, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("枠:O", title="枠"),
            y=alt.Y(
                "推定勝率:Q",
                title="推定勝率(%)",
                scale=alt.Scale(domain=[0, max(50.0, float(chart_df["推定勝率"].max()) * 1.15)]),
            ),
            color=alt.Color(
                "枠:O",
                scale=alt.Scale(domain=[1, 2, 3, 4, 5, 6], range=LANE_COLORS),
                legend=alt.Legend(title="枠"),
            ),
            tooltip=["枠", "選手名", alt.Tooltip("推定勝率:Q", format=".1f")],
        )
    )
    labels = bar.mark_text(dy=-8, color=INK_SECONDARY).encode(
        text=alt.Text("推定勝率:Q", format=".1f")
    )
    st.altair_chart((bar + labels).properties(height=320), width="stretch")

    st.subheader("予想根拠")
    st.caption(
        "各要素の6艇中の順位（相対比較）に基づく説明。厳密なスコア内訳ではなく、"
        "「他の艇と比べて何が強み/弱みか」を文章化した参考情報。"
    )
    for p in ranked:
        with st.expander(f"{p.lane}号艇 {p.racer_name} － 推定勝率{p.win_probability * 100:.1f}%"):
            st.write(p.rationale_summary)
            factor_df = pd.DataFrame(
                [
                    {
                        "要素": f.label,
                        "内容": f.detail,
                        "評価": "有利" if f.favorable is True else ("不利" if f.favorable is False else "中立"),
                    }
                    for f in p.rationale_factors
                ]
            )
            st.dataframe(factor_df, width="stretch", hide_index=True)

    st.subheader("選手情報")
    recent_forms = {}
    if show_recent_form:
        with st.spinner("直近成績（過去3節）を取得中..."):
            recent_forms = _fetch_recent_forms(
                tuple(e.racer_id for e in prediction.race.entries), use_cache
            )

    racer_rows = []
    for e in sorted(prediction.race.entries, key=lambda x: x.lane):
        row = {
            "枠": e.lane,
            "選手名": e.name,
            "級別": e.racer_class,
            "全国勝率": e.national_win_rate,
            "当地勝率": e.local_win_rate,
            "モーター2連率": e.motor_2nd_rate,
            "ボート2連率": e.boat_2nd_rate,
            "F数": e.flying_count,
            "平均ST": e.avg_start_timing,
            "プロフィール": racer_profile_url(e.racer_id),
        }
        if show_recent_form:
            form = recent_forms.get(e.racer_id)
            row["直近平均着順"] = form.average_finish() if form else None
            row["直近3着内率"] = form.top3_rate() if form else None
        racer_rows.append(row)
    racer_df = pd.DataFrame(racer_rows)

    column_config = {
        "全国勝率": st.column_config.ProgressColumn(
            "全国勝率", format="%.2f", min_value=0, max_value=8
        ),
        "当地勝率": st.column_config.ProgressColumn(
            "当地勝率", format="%.2f", min_value=0, max_value=8
        ),
        "モーター2連率": st.column_config.ProgressColumn(
            "モーター2連率", format="%.1f%%", min_value=0, max_value=100
        ),
        "ボート2連率": st.column_config.ProgressColumn(
            "ボート2連率", format="%.1f%%", min_value=0, max_value=100
        ),
        "F数": st.column_config.NumberColumn("F数", help="フライング回数（多いほどリスク）"),
        "平均ST": st.column_config.NumberColumn("平均ST", format="%.2f"),
        "プロフィール": st.column_config.LinkColumn(
            "プロフィール", display_text="boatrace.jpで見る"
        ),
    }
    if show_recent_form:
        column_config["直近平均着順"] = st.column_config.NumberColumn(
            "直近平均着順", format="%.1f", help="過去3節・boatrace.jp「過去3節成績」より算出。参考情報で予想スコアには未反映"
        )
        column_config["直近3着内率"] = st.column_config.NumberColumn(
            "直近3着内率", format="%.0f%%"
        )
    st.dataframe(racer_df, width="stretch", hide_index=True, column_config=column_config)

    favorite_store = FavoriteStore()

    is_favorite_venue = code in {f["key"] for f in favorite_store.list(kind=FAVORITE_VENUE)}
    fav_venue_toggle = st.checkbox(
        f"「{venue_name}」をお気に入りに登録",
        value=is_favorite_venue,
        key=f"fav_venue_{code}_{date_str}_{race_number}",
    )
    if fav_venue_toggle != is_favorite_venue:
        if fav_venue_toggle:
            favorite_store.add(FAVORITE_VENUE, code, venue_name)
        else:
            favorite_store.remove(FAVORITE_VENUE, code)

    favorite_racers = favorite_store.list(kind=FAVORITE_RACER)
    favorite_racer_ids = {int(f["key"]) for f in favorite_racers}
    racer_label_by_id = {e.racer_id: f"{e.lane}号艇 {e.name}" for e in prediction.race.entries}
    selected_labels = st.multiselect(
        "お気に入り選手に登録/解除（このレースの6人から選択）",
        options=[racer_label_by_id[e.racer_id] for e in prediction.race.entries],
        default=[
            racer_label_by_id[e.racer_id]
            for e in prediction.race.entries
            if e.racer_id in favorite_racer_ids
        ],
        key=f"fav_racers_{code}_{date_str}_{race_number}",
    )
    label_to_racer = {v: k for k, v in racer_label_by_id.items()}
    newly_selected_ids = {label_to_racer[label] for label in selected_labels}
    for e in prediction.race.entries:
        currently_fav = e.racer_id in favorite_racer_ids
        should_fav = e.racer_id in newly_selected_ids
        if should_fav and not currently_fav:
            favorite_store.add(FAVORITE_RACER, str(e.racer_id), e.name)
        elif currently_fav and not should_fav:
            favorite_store.remove(FAVORITE_RACER, str(e.racer_id))

    st.subheader("買い目候補（3連単）")
    st.caption(
        "各艇の推定勝率からHarvilleの公式で近似した組み合わせ確率と、"
        "boatrace.jpのオッズを使い「本命・中穴・大穴」に分類。"
        "オッズは常に変動し、大穴は特にモデルの誤差が乗りやすいため参考程度に。"
    )
    if odds_list is None:
        st.info("オッズ未取得のため「本命」のみ表示しています（発売前・未公開の可能性）。")

    genres = categorize_trifecta(ranked, odds_list, top_n=8)
    genre_captions = {
        GENRE_HONMEI: "的中重視。推定確率が高い順。",
        GENRE_CHUANA: f"オッズ目安 {MID_ODDS_MIN:.0f}〜{LONGSHOT_ODDS_MIN:.0f}倍のうち推定確率が高い順。",
        GENRE_OOANA: "オッズ目安 " f"{LONGSHOT_ODDS_MIN:.0f}倍以上のうち期待値(推定確率×オッズ)が高い順。",
    }
    tab_honmei, tab_chuana, tab_ooana, tab_exacta = st.tabs(
        [GENRE_HONMEI, GENRE_CHUANA, GENRE_OOANA, "2連単"]
    )

    for genre, tab in [(GENRE_HONMEI, tab_honmei), (GENRE_CHUANA, tab_chuana), (GENRE_OOANA, tab_ooana)]:
        with tab:
            st.caption(genre_captions[genre])
            candidates = genres[genre]
            if not candidates:
                st.info("該当する候補がありません（オッズ未取得、または条件に合う組番なし）。")
                continue
            genre_df = pd.DataFrame(
                [
                    {
                        "組番": c.label,
                        "推定確率": c.probability * 100,
                        "オッズ": c.odds,
                        "期待値": c.expected_value,
                    }
                    for c in candidates
                ]
            )
            combo_bar = (
                alt.Chart(genre_df)
                .mark_bar(
                    size=20, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color=CATEGORICAL_PALETTE[0]
                )
                .encode(
                    x=alt.X("組番:N", sort=None, title="組番（1着-2着-3着）"),
                    y=alt.Y("推定確率:Q", title="推定確率(%)"),
                    tooltip=[
                        "組番",
                        alt.Tooltip("推定確率:Q", format=".2f"),
                        alt.Tooltip("オッズ:Q", format=".1f"),
                        alt.Tooltip("期待値:Q", format=".2f"),
                    ],
                )
            )
            combo_labels = combo_bar.mark_text(dy=-8, color=INK_SECONDARY).encode(
                text=alt.Text("推定確率:Q", format=".1f")
            )
            st.altair_chart((combo_bar + combo_labels).properties(height=260), width="stretch")
            st.dataframe(
                genre_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "オッズ": st.column_config.NumberColumn("オッズ", format="%.1f倍"),
                    "期待値": st.column_config.NumberColumn(
                        "期待値", format="%.2f", help="推定確率×オッズ。1.0超で理論上は買い得の目安"
                    ),
                },
            )

    with tab_exacta:
        exacta_df = pd.DataFrame(
            [
                {"組番": t.label, "推定確率": t.probability * 100}
                for t in exacta_candidates(ranked, top_n=6)
            ]
        )
        st.dataframe(exacta_df, width="stretch", hide_index=True)

    odds_history = OddsSnapshotStore().history(code, date_str, race_number)
    history_df = pd.DataFrame(odds_history)
    if not history_df.empty and history_df["combo"].nunique() >= 1 and len(history_df) > history_df["combo"].nunique():
        st.subheader("オッズの推移（本命上位3点）")
        st.caption(
            "このレースをこのアプリで開くたびに、その時点のオッズを記録したもの。"
            "定期的な自動取得ではないため間隔は不定期。"
        )
        history_df["captured_at"] = pd.to_datetime(history_df["captured_at"])
        odds_line = (
            alt.Chart(history_df)
            .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=48, filled=True))
            .encode(
                x=alt.X("captured_at:T", title="記録日時"),
                y=alt.Y("odds:Q", title="オッズ(倍)"),
                color=alt.Color(
                    "combo:N",
                    scale=alt.Scale(range=CATEGORICAL_PALETTE[:3]),
                    legend=alt.Legend(title="組番"),
                ),
                tooltip=["captured_at:T", "combo", alt.Tooltip("odds:Q", format=".1f")],
            )
        )
        st.altair_chart(odds_line.properties(height=260), width="stretch")
    else:
        st.caption("オッズの推移は、このレースを複数回予想すると記録・表示されます。")

    st.subheader("予算配分")
    st.caption("推定確率に比例して100円単位で配分する試算。実際の購入・投票は行わない。")
    budget_col, genre_col = st.columns([2, 1])
    race_key = f"{code}_{date_str}_{race_number}"
    budget = budget_col.number_input(
        "予算（円）", min_value=0, step=100, value=0, key=f"budget_{race_key}"
    )
    budget_genre = genre_col.selectbox(
        "配分対象ジャンル", [GENRE_HONMEI, GENRE_CHUANA, GENRE_OOANA], key=f"budget_genre_{race_key}"
    )
    if budget >= 100:
        target_candidates = genres.get(budget_genre, [])
        allocations = allocate_budget(target_candidates, int(budget))
        if not allocations:
            st.info("配分できる候補がありません（オッズ未取得、または候補数不足）。")
        else:
            alloc_df = pd.DataFrame(
                [
                    {"組番": a.candidate.label, "配分額": a.amount, "推定確率": a.candidate.probability * 100}
                    for a in allocations
                ]
            )
            st.dataframe(alloc_df, width="stretch", hide_index=True)
            total = sum(a.amount for a in allocations)
            st.caption(f"合計 {total}円（予算との差額 {int(budget) - total}円は未配分）")

    if before_info is not None and before_info.exhibitions:
        st.subheader("直前情報")
        ex_df = pd.DataFrame(
            [
                {
                    "枠": e.lane,
                    "展示タイム": e.exhibition_time,
                    "進入": e.entry_course if e.entry_course is not None else "-",
                    "調整体重(kg)": e.adjust_weight,
                    "チルト": e.tilt,
                }
                for e in sorted(before_info.exhibitions, key=lambda x: x.lane)
            ]
        )
        st.dataframe(ex_df, width="stretch", hide_index=True)

        if before_info.weather is not None:
            w = before_info.weather
            cols = st.columns(5)
            cols[0].metric("天候", w.weather or "-")
            cols[1].metric("気温", f"{w.temperature}℃")
            cols[2].metric("風速", f"{w.wind_speed}m")
            cols[3].metric("水温", f"{w.water_temperature}℃")
            cols[4].metric("波高", f"{w.wave_height}cm")
    else:
        st.info(
            "直前情報は未取得または未公開です（レース開始が近づくと公開されます）。"
            "出走表データのみで予想しています。"
        )

    if race_number > 1:
        st.subheader(f"本日ここまでの結果（{venue_name}）")
        earlier = _fetch_earlier_results(code, date_str, race_number, use_cache)
        if not earlier:
            st.info("まだ確定した結果はありません。")
        else:
            for r in earlier:
                top3 = sorted((e for e in r.entries if 1 <= e.rank <= 3), key=lambda e: e.rank)
                top3_text = " ／ ".join(f"{e.rank}着 {e.lane}号艇 {e.name}" for e in top3)
                result_col, link_col = st.columns([4, 1])
                result_col.markdown(f"**{r.race_number}R**: {top3_text}")
                link_col.link_button(
                    "公式サイトで見る", raceresult_url(code, date_str, r.race_number)
                )


def _render_scan_page() -> None:
    st.title("狙い目スキャン（複数場・複数レース横断）")
    st.caption(
        "指定した場・レースをまとめて予想し、ジャンル別の買い目候補を期待値/確率順に一覧表示する。"
        "オッズ未公開のレースは中穴・大穴の判定ができないため対象外になる。"
        "※ 統計的な参考情報であり、的中・回収を保証するものではありません。"
    )

    favorites_only = st.sidebar.checkbox(
        "お気に入りの場のみ対象にする", value=False, key="scan_favorites_only"
    )
    venues_multi = st.sidebar.multiselect(
        "対象競艇場（未選択なら全24場）",
        list(VENUES.values()),
        key="scan_venues",
        disabled=favorites_only,
    )
    scan_date = st.sidebar.date_input("開催日", value=date.today(), key="scan_date")
    races_text = st.sidebar.text_input("対象レース", value="1-12", key="scan_races_text")
    genre = st.sidebar.selectbox(
        "ジャンル", [GENRE_OOANA, GENRE_CHUANA, GENRE_HONMEI], key="scan_genre"
    )
    top_n = st.sidebar.slider("表示件数", min_value=5, max_value=30, value=10, key="scan_top_n")
    use_cache = st.sidebar.checkbox("ローカルキャッシュを使う", value=True, key="scan_use_cache")
    st.sidebar.caption("対象が多いほど時間がかかります（1レースあたり最大1.5秒程度）。")
    run = st.sidebar.button("スキャンする", type="primary")

    if not run:
        st.info("左のサイドバーで条件を選び「スキャンする」を押してください。")
        return

    if favorites_only:
        codes = [venue_code(f["key"]) for f in FavoriteStore().list(kind=FAVORITE_VENUE)]
        if not codes:
            st.warning("お気に入り登録された競艇場がありません。「レース予想」ページでお気に入り登録してください。")
            return
    else:
        codes = [venue_code(v) for v in venues_multi] or list(VENUES.keys())
    races = parse_race_range(races_text)
    date_str = scan_date.strftime("%Y%m%d")
    client = BoatraceClient(use_cache=use_cache)

    total = max(len(codes) * len(races), 1)
    progress = st.progress(0.0)
    status = st.empty()

    collected: list[dict] = []
    ran = skipped = 0
    for i, (code, race_number, _prediction, genres, error) in enumerate(
        scan_races(client, codes, date_str, races), start=1
    ):
        progress.progress(min(i / total, 1.0))
        status.text(f"{VENUES.get(code, code)} {race_number}R を確認中...（実行{ran} / スキップ{skipped}）")
        if error is not None or genres is None:
            skipped += 1
            continue
        ran += 1
        for c in genres.get(genre, []):
            collected.append(
                {
                    "場": VENUES.get(code, code),
                    "R": race_number,
                    "組番": c.label,
                    "推定確率": c.probability * 100,
                    "オッズ": c.odds,
                    "期待値": c.expected_value,
                }
            )
    status.empty()
    progress.empty()
    st.success(f"完了: {ran}レースを確認（{skipped}レースはスキップ）")

    if not collected:
        st.info("該当する候補が見つかりませんでした。")
        return

    sort_key = "期待値" if genre == GENRE_OOANA else "推定確率"
    result_df = (
        pd.DataFrame(collected).sort_values(sort_key, ascending=False).head(top_n).reset_index(drop=True)
    )
    st.dataframe(
        result_df,
        width="stretch",
        hide_index=True,
        column_config={
            "推定確率": st.column_config.NumberColumn("推定確率", format="%.2f%%"),
            "オッズ": st.column_config.NumberColumn("オッズ", format="%.1f倍"),
            "期待値": st.column_config.NumberColumn(
                "期待値", format="%.2f", help="推定確率×オッズ。1.0超で理論上は買い得の目安"
            ),
        },
    )


def _render_backtest_dashboard() -> None:
    st.title("予想の検証ダッシュボード")
    store = BacktestStore()

    with st.expander("新しくbacktestを実行する（過去レースの答え合わせ）"):
        venues_multi = st.multiselect("対象競艇場（未選択なら全24場）", list(VENUES.values()))
        bt_date = st.date_input("対象日（結果が確定している過去日）", key="bt_date")
        races_text = st.text_input("対象レース", value="1-12")
        if st.button("実行"):
            codes = [venue_code(v) for v in venues_multi] or list(VENUES.keys())
            races = parse_race_range(races_text)
            client = BoatraceClient(use_cache=True)
            total = max(len(codes) * len(races), 1)
            progress = st.progress(0.0)
            log_area = st.empty()
            logs: list[str] = []
            ran = skipped = 0
            for i, (code, race_number, outcome, error) in enumerate(
                run_day_backtest(client, store, codes, bt_date.strftime("%Y%m%d"), races), start=1
            ):
                progress.progress(min(i / total, 1.0))
                if error is not None:
                    skipped += 1
                    logs.append(f"{VENUES.get(code, code)} {race_number}R: スキップ")
                else:
                    ran += 1
                    mark = "◎" if outcome.top1_hit else "✕"
                    logs.append(
                        f"{outcome.venue_name} {outcome.race_number}R: "
                        f"予想1位={outcome.predicted_ranking[0]}号艇 "
                        f"実際1着={outcome.actual_winner_lane}号艇 {mark} "
                        f"単勝払戻={outcome.tansho_payout}円"
                    )
                log_area.text("\n".join(logs[-12:]))
            st.success(f"完了: 実行{ran}件 / スキップ{skipped}件")
            st.cache_data.clear()

    filter_venue = st.sidebar.selectbox("場で絞り込み", ["すべて"] + list(VENUES.values()))
    venue_filter_code = None if filter_venue == "すべて" else venue_code(filter_venue)

    stats = store.stats(venue_code=venue_filter_code)
    st.markdown("##### 的中率")
    cols = st.columns(4)
    cols[0].metric("対象レース数", stats["count"])
    cols[1].metric("単勝的中率（予想1位）", f"{stats['top1_rate'] * 100:.1f}%")
    cols[2].metric("予想上位2以内", f"{stats['top2_rate'] * 100:.1f}%")
    cols[3].metric("予想上位3以内", f"{stats['top3_rate'] * 100:.1f}%")

    st.markdown("##### 回収率（毎レース100円ずつ本命1点賭けした場合の試算。100%＝収支トントン）")
    roi_cols = st.columns(3)
    roi_cols[0].metric("単勝回収率", f"{stats['tansho_roi'] * 100:.1f}%")
    roi_cols[1].metric("3連単的中率", f"{stats['trifecta_top1_rate'] * 100:.1f}%")
    roi_cols[2].metric("3連単回収率", f"{stats['trifecta_roi'] * 100:.1f}%")

    daily = store.daily_stats(venue_code=venue_filter_code)
    if daily:
        daily_df = pd.DataFrame(daily)

        st.markdown("##### 的中率の推移")
        hit_label_map = {
            "top1_rate": "単勝的中(予想1位)",
            "top2_rate": "予想上位2以内",
            "top3_rate": "予想上位3以内",
        }
        hit_long_df = daily_df.melt(
            id_vars=["date", "count"],
            value_vars=list(hit_label_map.keys()),
            var_name="指標",
            value_name="値",
        )
        hit_long_df["指標"] = hit_long_df["指標"].map(hit_label_map)
        hit_long_df["値"] = hit_long_df["値"] * 100

        hit_line = (
            alt.Chart(hit_long_df)
            .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True))
            .encode(
                x=alt.X("date:O", title="日付"),
                y=alt.Y("値:Q", title="的中率(%)", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color(
                    "指標:N",
                    scale=alt.Scale(domain=list(hit_label_map.values()), range=CATEGORICAL_PALETTE[:3]),
                    legend=alt.Legend(title="指標"),
                ),
                tooltip=["date", "指標", alt.Tooltip("値:Q", format=".1f")],
            )
        )
        st.altair_chart(hit_line.properties(height=300), width="stretch")

        st.markdown("##### 回収率の推移")
        roi_label_map = {"tansho_roi": "単勝回収率", "trifecta_roi": "3連単回収率"}
        roi_long_df = daily_df.melt(
            id_vars=["date", "count"],
            value_vars=list(roi_label_map.keys()),
            var_name="指標",
            value_name="値",
        )
        roi_long_df["指標"] = roi_long_df["指標"].map(roi_label_map)
        roi_long_df["値"] = roi_long_df["値"] * 100

        roi_max = max(120.0, float(roi_long_df["値"].max()) * 1.15)
        breakeven = alt.Chart(pd.DataFrame({"y": [100]})).mark_rule(
            strokeDash=[4, 4], color=INK_SECONDARY
        ).encode(y="y:Q")
        roi_line = (
            alt.Chart(roi_long_df)
            .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True))
            .encode(
                x=alt.X("date:O", title="日付"),
                y=alt.Y("値:Q", title="回収率(%)", scale=alt.Scale(domain=[0, roi_max])),
                color=alt.Color(
                    "指標:N",
                    scale=alt.Scale(
                        domain=list(roi_label_map.values()), range=CATEGORICAL_PALETTE[3:5]
                    ),
                    legend=alt.Legend(title="指標"),
                ),
                tooltip=["date", "指標", alt.Tooltip("値:Q", format=".1f")],
            )
        )
        st.altair_chart((roi_line + breakeven).properties(height=300), width="stretch")
        st.caption("点線は回収率100%（収支トントン）の基準線。")
    else:
        st.info("まだbacktestデータがありません。上の「新しくbacktestを実行する」から実行してください。")

    st.subheader("直近の結果一覧")
    recent = store.recent(limit=30)
    if recent:
        recent_df = pd.DataFrame(recent)[
            [
                "date",
                "venue_name",
                "race_number",
                "predicted_ranking",
                "actual_winner_lane",
                "top1_hit",
                "tansho_payout",
                "trifecta_top1_hit",
                "trifecta_top1_payout",
            ]
        ]
        st.dataframe(recent_df, width="stretch", hide_index=True)


def _render_patterns_page() -> None:
    st.title("勝ちパターン分析")
    st.caption(
        "backtestで蓄積したデータから「どの場で精度が良いか」「モデルの自信度は"
        "信頼できるか」を確認する。的中や回収を保証するものではなく、あくまで参考情報。"
    )
    store = BacktestStore()

    by_venue = store.stats_by_venue()
    if not by_venue:
        st.info("まだbacktestデータがありません。「検証ダッシュボード」ページから実行してください。")
        return

    st.subheader("場ごとの的中率・回収率")
    venue_df = pd.DataFrame(by_venue).sort_values("top1_rate", ascending=False)
    venue_df["top1_rate_pct"] = venue_df["top1_rate"] * 100
    venue_bar = (
        alt.Chart(venue_df)
        .mark_bar(size=16, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color=CATEGORICAL_PALETTE[0])
        .encode(
            x=alt.X("venue_name:N", sort=None, title="競艇場"),
            y=alt.Y("top1_rate_pct:Q", title="単勝的中率(%)"),
            tooltip=[
                alt.Tooltip("venue_name:N", title="場"),
                alt.Tooltip("count:Q", title="件数"),
                alt.Tooltip("top1_rate_pct:Q", title="単勝的中率", format=".1f"),
            ],
        )
    )
    st.altair_chart(venue_bar.properties(height=320), width="stretch")
    st.dataframe(
        venue_df[["venue_name", "count", "top1_rate", "top2_rate", "top3_rate", "tansho_roi", "trifecta_roi"]],
        width="stretch",
        hide_index=True,
        column_config={
            "venue_name": "場",
            "count": "件数",
            "top1_rate": st.column_config.NumberColumn("単勝的中率", format="%.1f%%"),
            "top2_rate": st.column_config.NumberColumn("上位2以内", format="%.1f%%"),
            "top3_rate": st.column_config.NumberColumn("上位3以内", format="%.1f%%"),
            "tansho_roi": st.column_config.NumberColumn("単勝回収率", format="%.1f%%"),
            "trifecta_roi": st.column_config.NumberColumn("3連単回収率", format="%.1f%%"),
        },
    )

    st.subheader("推定勝率帯ごとの実際の的中率")
    st.caption(
        "予想1位レーンの推定勝率を帯に分け、実際の的中率と比較する。帯が上がるほど"
        "実際の的中率も上がっていれば、モデルの確率の付け方はおおむね妥当という目安になる。"
    )
    by_confidence = [r for r in store.stats_by_confidence() if r["count"] > 0]
    if not by_confidence:
        st.info("該当するデータがありません。")
        return
    conf_df = pd.DataFrame(by_confidence)
    conf_df["top1_rate_pct"] = conf_df["top1_rate"] * 100
    conf_bar = (
        alt.Chart(conf_df)
        .mark_bar(size=40, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color=CATEGORICAL_PALETTE[1])
        .encode(
            x=alt.X("bucket:N", sort=None, title="予想1位の推定勝率帯"),
            y=alt.Y("top1_rate_pct:Q", title="実際の的中率(%)"),
            tooltip=[
                alt.Tooltip("bucket:N", title="推定勝率帯"),
                alt.Tooltip("count:Q", title="件数"),
                alt.Tooltip("top1_rate_pct:Q", title="実際の的中率", format=".1f"),
            ],
        )
    )
    st.altair_chart(conf_bar.properties(height=300), width="stretch")
    st.dataframe(
        conf_df[["bucket", "count", "top1_rate", "tansho_roi"]],
        width="stretch",
        hide_index=True,
        column_config={
            "bucket": "推定勝率帯",
            "count": "件数",
            "top1_rate": st.column_config.NumberColumn("実際の的中率", format="%.1f%%"),
            "tansho_roi": st.column_config.NumberColumn("単勝回収率", format="%.1f%%"),
        },
    )


def _render_favorites_page() -> None:
    st.title("お気に入り管理")
    st.caption("お気に入り選手・お気に入り競艇場の登録状況を確認・削除できる。追加は「レース予想」ページから行う。")
    store = FavoriteStore()

    st.subheader("お気に入り選手")
    racers = store.list(kind=FAVORITE_RACER)
    if not racers:
        st.info("登録なし。「レース予想」ページの選手情報下にあるお気に入り選手欄から追加できます。")
    else:
        for f in racers:
            col1, col2 = st.columns([4, 1])
            col1.markdown(f"**{f['label']}**（登録番号{f['key']}） - [プロフィール]({racer_profile_url(int(f['key']))})")
            if col2.button("削除", key=f"remove_racer_{f['key']}"):
                store.remove(FAVORITE_RACER, f["key"])
                st.rerun()

    st.subheader("お気に入り競艇場")
    venues = store.list(kind=FAVORITE_VENUE)
    if not venues:
        st.info("登録なし。「レース予想」ページのサイドバーから追加できます。")
    else:
        for f in venues:
            col1, col2 = st.columns([4, 1])
            col1.markdown(f"**{f['label']}**")
            if col2.button("削除", key=f"remove_venue_{f['key']}"):
                store.remove(FAVORITE_VENUE, f["key"])
                st.rerun()


def _render_today_page() -> None:
    st.title("今日の予想ログ")
    st.caption(
        "「レース予想」ページで実際に見た予想を自動的に記録し、結果が確定したものから"
        "答え合わせする振り返り用ページ。backtestとは別の記録（同じレースを複数回見た場合は最新の予想で上書き）。"
    )
    target_date = st.sidebar.date_input("対象日", value=date.today(), key="today_date")
    use_cache = st.sidebar.checkbox("ローカルキャッシュを使う", value=True, key="today_use_cache")
    date_str = target_date.strftime("%Y%m%d")

    client = BoatraceClient(use_cache=use_cache)
    log_store = PredictionLogStore()
    rows = list(compare_logged_predictions(client, log_store, date_str))
    if not rows:
        st.info(f"{date_str} 分の予想ログがありません。「レース予想」ページで予想を見るとここに記録されます。")
        return

    resolved = [r for r in rows if r["status"] == "resolved"]
    unresolved = [r for r in rows if r["status"] != "resolved"]

    if resolved:
        hit = sum(1 for r in resolved if r["top1_hit"])
        cols = st.columns(3)
        cols[0].metric("確定分レース数", len(resolved))
        cols[1].metric("的中数", hit)
        cols[2].metric("的中率", f"{hit / len(resolved) * 100:.1f}%")

        resolved_df = pd.DataFrame(resolved)[
            ["venue_name", "race_number", "predicted_top_lane", "predicted_top_probability", "actual_winner_lane", "top1_hit"]
        ]
        st.dataframe(
            resolved_df,
            width="stretch",
            hide_index=True,
            column_config={
                "venue_name": "場",
                "race_number": "R",
                "predicted_top_lane": "予想1位",
                "predicted_top_probability": st.column_config.NumberColumn("推定勝率", format="%.1f%%"),
                "actual_winner_lane": "実際1着",
                "top1_hit": st.column_config.CheckboxColumn("的中"),
            },
        )

    if unresolved:
        st.subheader("未確定（開催前・進行中）")
        unresolved_df = pd.DataFrame(unresolved)[["venue_name", "race_number"]]
        st.dataframe(
            unresolved_df, width="stretch", hide_index=True, column_config={"venue_name": "場", "race_number": "R"}
        )


def main() -> None:
    page = st.sidebar.radio(
        "ページ",
        ["レース予想", "狙い目スキャン", "勝ちパターン分析", "お気に入り管理", "今日の予想ログ", "検証ダッシュボード"],
    )
    st.sidebar.divider()
    if page == "レース予想":
        _render_predict_page()
    elif page == "狙い目スキャン":
        _render_scan_page()
    elif page == "勝ちパターン分析":
        _render_patterns_page()
    elif page == "お気に入り管理":
        _render_favorites_page()
    elif page == "今日の予想ログ":
        _render_today_page()
    else:
        _render_backtest_dashboard()


main()
