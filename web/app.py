"""競艇予想Webダッシュボード（Streamlit）。

起動方法:
    streamlit run web/app.py

全24競艇場に対応した「レース予想」ページと、backtestで蓄積した
的中率を確認する「検証ダッシュボード」ページの2画面構成。
"""
from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from kyotei.backtest import parse_race_range, run_day_backtest
from kyotei.constants import VENUES, racer_profile_url, venue_code
from kyotei.models.combos import exacta_candidates, trifecta_candidates
from kyotei.models.predictor import predict_race
from kyotei.scraper.beforeinfo import parse_beforeinfo_html
from kyotei.scraper.client import BoatraceClient
from kyotei.scraper.racelist import parse_racelist_html
from kyotei.storage import BacktestStore

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
    prediction = predict_race(race, before_info=before_info)
    return before_info, prediction


def _render_predict_page() -> None:
    st.title("競艇予想（統計・ルールベース）")
    st.caption("※ 統計的な参考情報であり、的中・回収を保証するものではありません。舟券の購入判断はご自身で。")

    venue_name = st.sidebar.selectbox("競艇場", list(VENUES.values()))
    race_date = st.sidebar.date_input("開催日", value=date.today())
    race_number = st.sidebar.selectbox("レース番号", list(range(1, 13)), format_func=lambda n: f"{n}R")
    use_cache = st.sidebar.checkbox("ローカルキャッシュを使う", value=True)
    run = st.sidebar.button("予想する", type="primary")

    if not run:
        st.info("左のサイドバーで競艇場・開催日・レース番号を選び「予想する」を押してください。")
        return

    code = venue_code(venue_name)
    date_str = race_date.strftime("%Y%m%d")

    try:
        with st.spinner("出走表・直前情報を取得中..."):
            before_info, prediction = _fetch_prediction(code, date_str, race_number, use_cache)
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

    st.subheader("選手情報")
    racer_df = pd.DataFrame(
        [
            {
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
            for e in sorted(prediction.race.entries, key=lambda x: x.lane)
        ]
    )
    st.dataframe(
        racer_df,
        width="stretch",
        hide_index=True,
        column_config={
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
        },
    )

    st.subheader("買い目候補")
    st.caption(
        "各艇の推定勝率からHarvilleの公式で近似した組み合わせ確率。"
        "実際のレース展開の相関までは考慮していない参考値。"
    )
    tab_trifecta, tab_exacta = st.tabs(["3連単", "2連単"])

    with tab_trifecta:
        trifecta_df = pd.DataFrame(
            [
                {"組番": t.label, "推定確率": t.probability * 100}
                for t in trifecta_candidates(ranked, top_n=8)
            ]
        )
        combo_bar = (
            alt.Chart(trifecta_df)
            .mark_bar(size=20, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color=CATEGORICAL_PALETTE[0])
            .encode(
                x=alt.X("組番:N", sort=None, title="組番（1着-2着-3着）"),
                y=alt.Y("推定確率:Q", title="推定確率(%)"),
                tooltip=["組番", alt.Tooltip("推定確率:Q", format=".2f")],
            )
        )
        combo_labels = combo_bar.mark_text(dy=-8, color=INK_SECONDARY).encode(
            text=alt.Text("推定確率:Q", format=".1f")
        )
        st.altair_chart((combo_bar + combo_labels).properties(height=280), width="stretch")
        st.dataframe(trifecta_df, width="stretch", hide_index=True)

    with tab_exacta:
        exacta_df = pd.DataFrame(
            [
                {"組番": t.label, "推定確率": t.probability * 100}
                for t in exacta_candidates(ranked, top_n=6)
            ]
        )
        st.dataframe(exacta_df, width="stretch", hide_index=True)

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


def main() -> None:
    page = st.sidebar.radio("ページ", ["レース予想", "検証ダッシュボード"])
    st.sidebar.divider()
    if page == "レース予想":
        _render_predict_page()
    else:
        _render_backtest_dashboard()


main()
