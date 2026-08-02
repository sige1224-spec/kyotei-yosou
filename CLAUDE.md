# 競艇予想プロジェクト

## 概要
競艇（ボートレース）の予想ロジック・スクリプトをPythonで開発するプロジェクト。
全24競艇場に対応し、BOATRACE公式サイト（boatrace.jp）から出走表・直前情報・結果を
取得して着順・勝率の予想を行う。CLIとStreamlit製Webダッシュボードの両方を提供する。

## 技術スタック
- 言語: Python 3.12（`pyproject.toml` で管理、`pip install -e ".[web]"` で開発インストール）
- ライブラリ: requests, beautifulsoup4, lxml（HTML取得・パース）、pytest（テスト）、
  streamlit, altair, pandas（Webダッシュボード、`[web]` extra）
- 予想ロジックは現状 統計・ルールベース。`backtest`/`backtest-day` で結果データを蓄積し、
  精度検証しながら重みを調整する運用。データが十分蓄積されたら scikit-learn 等での
  機械学習モデルへの置き換えを検討。

## ディレクトリ構成
```
src/kyotei/
  constants.py        # 全24競艇場の場コード・場名、コース別1着率の目安
  cli.py               # CLIエントリポイント（`kyotei` コマンド）
  backtest.py          # backtest実行ロジック（CLI・Web共通）
  storage.py           # backtest結果を蓄積するSQLiteストア（data/kyotei.db）
  models/
    entities.py        # RaceCard, RacerEntry, BeforeInfo, RaceResult, RacePrediction 等
    predictor.py        # 統計・ルールベースの予想ロジック
  scraper/
    _text.py             # パーサー共通のテキスト正規化ヘルパー
    client.py           # boatrace.jp向けHTTPクライアント（レート制限・キャッシュ付き）
    racelist.py          # 出走表ページのパーサー
    beforeinfo.py         # 直前情報ページ（展示タイム・進入コース・気象情報）のパーサー
    result.py            # レース結果ページのパーサー（学習データ収集・答え合わせ用）
web/
  app.py               # Streamlitダッシュボード（レース予想 / 検証ダッシュボード）
tests/
  fixtures/             # 保存済みサンプルHTML（パーサーの単体テスト用）
data/
  cache/                # 取得したHTMLのローカルキャッシュ（gitignore対象）
  kyotei.db             # backtest結果のSQLite DB（gitignore対象外、ローカル蓄積データ）
```

## 使い方
```powershell
kyotei venues                                              # 場コード一覧
kyotei predict --venue 桐生 --date 20260802 --race 1         # 予想表示（直前情報も自動で加味）
kyotei backtest --venue 桐生 --date 20260731 --race 1         # 過去レース1件を答え合わせ
kyotei backtest-day --date 20260731 --venues all --races 1-12  # 指定日をまとめて答え合わせ
kyotei stats                                                # 蓄積した的中率を表示
streamlit run web/app.py                                    # Webダッシュボード起動
python -m pytest                                            # テスト実行
```

## 開発方針・注意点
- データ取得: boatrace.jp をスクレイピング（robots.txtで全面許可を確認済み）。
  公式サイトへの負荷軽減のため、`BoatraceClient` で最小アクセス間隔とローカル
  キャッシュ（`data/cache/`）を設けている。ページテンプレートは全24場共通。
- `backtest-day --venues all` は1レースにつき出走表・直前情報・結果の最大3リクエストを
  投げるため、実測で1日（全24場・全12R）あたり**80〜90分程度**かかる（開催なしの場も
  出走表確認だけで1リクエスト消費するため無視できない）。事前に見積もりが甘く、実際に
  4日分を回して3時間以上かかった実績あり。まとめて回す前に `--venues`/`--races` で
  範囲を絞るか、時間に余裕がある時にバックグラウンド実行すること。
- 舟券購入・投票の自動化は対象外（法規制・利用規約上のリスクがあるため、予想ロジックの開発に留める）。
- 予想結果の的中を保証する表現は避け、あくまで統計的な参考情報として扱う（CLI/Web出力にも明記）。
- 天候・水面気象情報はスコアに組み込まず表示のみに留めている（影響が状況依存で不確実性が
  高いため）。展示タイム・進入コースは判明していれば予想ロジックに反映する。
- `predictor.py` の重み（`PredictorWeights`）は2026-08-02、2026-07-28〜07-30の
  480レース分（`scripts/collect_history.py` で収集）を `scripts/tune_weights.py` で
  オフライン検証した結果に基づく（根拠は `predictor.py` docstring参照）。course/
  local_win_rate/boat_2nd_rateを控えめに調整済み、exhibition_timeはablationで有意差が
  出なかったため据え置き。サンプル数はまだ限定的なので、データが増えたら再検証すること。
  `kyotei stats`/Webの的中率は backtest実行時点の重みでの記録であり、重み変更後に
  過去の記録値が自動で遡って更新されるわけではない点に注意。
- Webダッシュボードのグラフはdatavizスキルの検証済みカテゴリカルパレット
  （`web/app.py` の `CATEGORICAL_PALETTE`）を使用。枠番の色は固定順で割り当てている。

## 現状・今後
- 出走表・直前情報・結果の取得/パース、統計・ルールベース予想、CLI（predict/backtest/
  backtest-day/stats）、Streamlitダッシュボード（予想画面・検証画面）まで実装済み。
  全24場での動作確認済み。
- `scripts/collect_history.py`（過去日をまとめてbacktest・データ蓄積）と
  `scripts/tune_weights.py`（キャッシュ済みHTMLのみでネットワーク不要の重み検証・
  ランダムサーチ）も実装済み。一度データを蓄積すれば、以降の重み検証はネット
  アクセスなしで何度でも試せる。
- 未着手: より多くの日数・場でのデータ蓄積による重みの再検証、天候の予想ロジックへの
  反映要否の検討、機械学習モデルへの置き換え。
