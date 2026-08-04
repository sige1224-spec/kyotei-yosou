# 競艇予想プロジェクト

## 概要
競艇（ボートレース）の予想ロジック・スクリプトをPythonで開発するプロジェクト。
全24競艇場に対応し、BOATRACE公式サイト（boatrace.jp）から出走表・直前情報・結果を
取得して着順・勝率・買い目候補の予想を行う。CLIとStreamlit製Webダッシュボードの
両方を提供し、Webダッシュボードは Streamlit Community Cloud に公開してiPhone等
外出先からもアクセスできる。

## 技術スタック
- 言語: Python 3.12（`pyproject.toml` で管理、`pip install -e ".[web]"` で開発インストール）
- ライブラリ: requests, beautifulsoup4, lxml（HTML取得・パース）、pytest（テスト）、
  streamlit, altair, pandas（Webダッシュボード、`[web]` extra）
- 予想ロジックは現状 統計・ルールベース。`backtest`/`backtest-day` で結果データを蓄積し、
  精度検証しながら重みを調整する運用。データが十分蓄積されたら scikit-learn 等での
  機械学習モデルへの置き換えを検討。
- バージョン管理: git + GitHub（`gh` CLIで認証済み、アカウント `sige1224-spec`）。
  リポジトリ: https://github.com/sige1224-spec/kyotei-yosou （パブリック）

## ディレクトリ構成
```
src/kyotei/
  constants.py        # 全24競艇場の場コード・場名、コース別1着率の目安
  cli.py               # CLIエントリポイント（`kyotei` コマンド）
  backtest.py          # backtest実行ロジック（CLI・Web共通）
  storage.py           # backtest結果・お気に入り・オッズ推移・予想ログを蓄積するSQLite
                        # ストア群（data/kyotei.db）。BacktestStore/FavoriteStore/
                        # OddsSnapshotStore/PredictionLogStore
  predictionlog.py     # PredictionLogStoreの記録を確定結果と突き合わせる（当日振り返り用）
  dayview.py            # 同一開催日・同一会場の他レース結果をまとめて取得
  favoritesview.py      # お気に入り競艇場で開催中のレース＋お気に入り選手の出走有無をまとめる
  models/
    entities.py        # RaceCard, RacerEntry, BeforeInfo, RaceResult, Payout, TrifectaOdds,
                        # RationaleFactor 等
    predictor.py        # 統計・ルールベースの予想ロジック＋予想根拠（rationale）の生成
    combos.py            # 推定勝率から買い目候補（3連単/2連単/3連複）をHarville近似で算出
    genres.py             # 買い目候補を本命/中穴/大穴に分類（推定確率×オッズ）
    allocation.py          # 予算を推定確率に比例して100円単位で配分
    scan.py                 # 複数場・複数レース横断でジャンル別の狙い目候補を集める
  scraper/
    _text.py             # パーサー共通のテキスト正規化ヘルパー
    client.py           # boatrace.jp向けHTTPクライアント（レート制限・キャッシュ付き）
    racelist.py          # 出走表ページのパーサー
    beforeinfo.py         # 直前情報ページ（展示タイム・進入コース・気象情報）のパーサー
    result.py            # レース結果ページのパーサー（着順・払戻金）
    odds.py               # 3連単オッズページのパーサー
    racerform.py           # 選手プロフィール「過去3節成績」ページのパーサー（直近の着順トレンド）
web/
  app.py               # Streamlitダッシュボード（レース予想 / 狙い目スキャン / 勝ちパターン分析 /
                        # お気に入り管理 / 今日の予想ログ / 検証ダッシュボード の6画面構成）
scripts/
  collect_history.py    # 過去複数日・全会場のbacktestをまとめて実行しデータ蓄積
  tune_weights.py        # キャッシュ済みHTMLのみでネットワーク不要の重み検証・ランダムサーチ
                          # （--with-recent-formで直近成績weightのablationも実行可）
tests/
  fixtures/             # 保存済みサンプルHTML（パーサーの単体テスト用）
data/
  cache/                # 取得したHTMLのローカルキャッシュ（gitignore対象）
  kyotei.db             # backtest結果・お気に入り・オッズ推移・予想ログのSQLite DB
                         # （gitignore対象から明示的に除外し、git管理下に置いている）
```

## 使い方
```powershell
kyotei venues                                              # 場コード一覧
kyotei predict --venue 桐生 --date 20260802 --race 1         # 予想・予想根拠・買い目候補・選手情報を表示
kyotei predict-all --date 20260803 --venues all --races 1-12  # 指定日の全レースをまとめて予想し予想ログに記録
kyotei favorite today --date 20260802                       # お気に入り競艇場の今日の開催・出走選手をまとめて表示
kyotei backtest --venue 桐生 --date 20260731 --race 1         # 過去レース1件を答え合わせ
kyotei backtest-day --date 20260731 --venues all --races 1-12  # 指定日をまとめて答え合わせ
kyotei scan --date 20260802 --venues all --races 1-12 --genre 大穴  # 複数場・複数レース横断で狙い目候補を探す
kyotei stats                                                # 蓄積した的中率・回収率を表示
kyotei patterns                                             # 場ごと・自信度ごとの的中率を分析（勝ちパターン分析）
kyotei favorite add-racer 4300 --label 加藤綾                 # お気に入り選手を登録
kyotei favorite add-venue 桐生                                # お気に入り競艇場を登録
kyotei favorite list                                        # お気に入り一覧
kyotei today --date 20260802                                 # 今日見た予想を確定結果と突き合わせて振り返る
streamlit run web/app.py                                    # Webダッシュボード起動（ローカル）
python -m pytest                                            # テスト実行
```

## デプロイ
- GitHubリポジトリ `sige1224-spec/kyotei-yosou`（パブリック）に push 済み。
- Streamlit Community Cloud で `web/app.py` をデプロイ済み（ユーザー自身のアカウントで
  操作。Claude側ではGitHub push までしか行えない）。masterブランチにpushすると
  Streamlit Cloud側が自動で再デプロイする。
- `requirements.txt` はサードパーティ依存だけを列挙する構成（`-e .[web]` は使わない）。
  以前 `-e .[web]` にしていたところ、Streamlit Cloud側でeditable installが正しく
  反映されず `kyotei.constants` に新しい関数が無い状態で古いまま実行されて
  `ImportError` になった実績がある（2026-08-02）。src-layoutのため、代わりに
  `web/app.py` の先頭で `sys.path.insert(0, .../src)` して直接importする方式にして
  回避している。変更時はkyoteiを一切pipインストールしていないクリーンなvenvで
  動作確認してから push すること。
- クラウド上は `data/cache` が再デプロイのたびにリセットされる（HTMLキャッシュはクラウドには
  引き継がれない）。`data/kyotei.db` は2026-08-02以降 `.gitignore` の対象から外し
  （`!data/kyotei.db` で明示的に追跡）、リポジトリにコミットする運用にしている。
  そのため **ローカルで `backtest`/`backtest-day` を実行してデータを蓄積したら、
  `git add data/kyotei.db && git commit && git push` でコミットしないとスマホ側
  （Streamlit Cloud）の検証ダッシュボードには反映されない**（自動同期ではなく手動push時点の
  スナップショット）。DBサイズは2026-08-02時点で483レース分で約160KB。1万レース分でも
  数MB程度の見込みでgit管理上の問題は当面ない。同じDBファイルに
  `favorites`（お気に入り選手/競艇場）・`odds_snapshots`（オッズ推移記録）・
  `prediction_log`（予想ログ）のテーブルも同居している（2026-08-03追加、いずれも
  BacktestStoreとは独立したクラス）。

## 開発方針・注意点
- データ取得: boatrace.jp をスクレイピング（robots.txtで全面許可を確認済み）。
  公式サイトへの負荷軽減のため、`BoatraceClient` で最小アクセス間隔とローカル
  キャッシュ（`data/cache/`）を設けている。ページテンプレートは全24場共通。
- `backtest-day --venues all` は1レースにつき出走表・直前情報・結果の最大3リクエストを
  投げるため、実測で1日（全24場・全12R）あたり**80〜90分程度**かかる（開催なしの場も
  出走表確認だけで1リクエスト消費するため無視できない）。事前に見積もりが甘く、実際に
  4日分を回して3時間以上かかった実績あり。まとめて回す前に `--venues`/`--races` で
  範囲を絞るか、時間に余裕がある時にバックグラウンド実行すること。
- 舟券購入・投票の自動化は対象外（法規制・利用規約上のリスクがあるため、予想ロジックと
  買い目候補・回収率試算の「表示」に留める）。
- 予想結果・買い目候補・回収率試算の的中や回収を保証する表現は避け、あくまで統計的な
  参考情報として扱う（CLI/Web出力にも明記）。
- 天候・水面気象情報はスコアに組み込まず表示のみに留めている（影響が状況依存で不確実性が
  高いため）。展示タイム・進入コースは判明していれば予想ロジックに反映する。
- 選手の直近成績（`racerform.py`、boatrace.jp選手プロフィールの「過去3節成績」ページ）も
  同様に表示のみで予想スコアには未反映（2026-08-02追加。backtestでの効果検証を行っておらず、
  安易に重みへ組み込むと過学習のリスクがあるため）。`kyotei predict`は選手6人分を毎回追加
  取得するため`--no-recent-form`で省略可、Webは「直近成績（過去3節）も取得する」チェックボックスで
  制御。2026-08-03、`PredictorWeights.recent_form_weight`（既定値0）としてスコアに
  加味する経路自体は実装済み（`predict_race`に`recent_forms`を渡すと有効化）。
  `scripts/tune_weights.py --with-recent-form`でオフライン検証できるが（初回のみ
  未キャッシュ選手分のネットワークアクセスが発生）、まだ実データでの検証を行っていないため
  既定値0のまま。動かす場合は必ずbaseline比で明確な改善を確認してから。
- 予想根拠（`predictor.py`の`_build_rationale`、`LanePrediction.rationale_summary`/
  `rationale_factors`）は2026-08-03追加。各要素（コース取り・全国勝率・当地勝率・
  モーター2連率・ボート2連率・平均ST・展示タイム・F数）について6艇中の順位を算出し、
  「他艇と比べて何が強み/弱みか」を文章化する。`_normalize_to_shares`によるスコア合成が
  非線形（負値シフト＋正規化）なため、各要素の寄与度を厳密に数値分解するのはミスリーディング
  になると判断し、あえて絶対値ではなく相対順位ベースの説明にしている。CLI/Webの両方で
  「予想根拠」として表示。
- 買い目候補（`combos.py`）はHarvilleの公式（1973年、競馬で提案された手法）で推定勝率から
  着順の組み合わせ確率を近似したもの。艇どうしの展開上の相関は捉えられない単純化である旨を
  明記している。
- ジャンル分け（`genres.py`）は3連単オッズ（`odds.py`、boatrace.jpの odds3t ページ）を
  使い、本命（確率順）/中穴（オッズ7〜30倍で確率順）/大穴（オッズ30倍以上で期待値順）に
  分類する。大穴genreは期待値がモデルとオッズの乖離で見かけ上高く出やすく、backtestでの
  精度検証も未実施（本命の3連単回収率のみ検証済み、上記参照）。過信しないよう明記している。
- 予算配分（`allocation.py`）は推定確率に比例した100円単位の配分試算であり、実際の購入・
  投票は一切行わない。
- 回収率（`storage.py`）は実際の払戻金ページの金額をそのまま使った試算値。「毎レース
  同じ買い方をしていたら」という仮定のシミュレーションであり、購入を推奨するものではない。
- `predictor.py` の重み（`PredictorWeights`）は2026-08-02、2026-07-28〜07-30の
  480レース分（`scripts/collect_history.py` で収集）を `scripts/tune_weights.py` で
  オフライン検証した結果に基づく（根拠は `predictor.py` docstring参照）。course/
  local_win_rate/boat_2nd_rateを控えめに調整済み、exhibition_timeはablationで有意差が
  出なかったため据え置き。サンプル数はまだ限定的なので、データが増えたら再検証すること。
  `kyotei stats`/Webの的中率・回収率は backtest実行時点の重みでの記録であり、重み変更後に
  過去の記録値が自動で遡って更新されるわけではない点に注意（再計算はキャッシュ済み
  レースに対して無料で行える。既存483レースは2026-08-02に再計算済み: 単勝的中率40.4%、
  単勝回収率86.0%、3連単的中率5.8%、3連単回収率81.7%）。
- Webダッシュボードのグラフはdatavizスキルの検証済みカテゴリカルパレット
  （`web/app.py` の `CATEGORICAL_PALETTE`）を使用。枠番の色は固定順で割り当てている。
- お気に入り（`FavoriteStore`、2026-08-03追加）は選手（`kind="racer"`, `key=登録番号`）と
  競艇場（`kind="venue"`, `key=場コード`）の2種類。Webの「レース予想」ページで選手は
  多選択欄、競艇場はサイドバーのチェックボックスから登録・解除する。`kyotei scan
  --favorites-only` / Webの「狙い目スキャン」ページのチェックボックスで、お気に入り
  競艇場だけに絞って横断スキャンできる。
- オッズの推移（`OddsSnapshotStore`、2026-08-03追加）は、そのレースを予想画面で開く
  （＝実際にオッズを取得する）たびに、本命上位3点の3連単オッズを記録する。バックグラウンドで
  定期取得する仕組みは無い（サーバー常駐の仕組みがないため）ので、記録間隔は「利用者が
  そのレースを見た頻度」に依存し不定期。2回以上記録があるレースだけ推移グラフ/一覧を表示する。
- 「今日のお気に入り」（`favoritesview.py`、2026-08-03追加）は、お気に入り競艇場で開催中の
  レースを一覧し、その中にお気に入り選手が出走していれば合わせて示すホーム画面。全24場を
  毎回横断すると負荷が大きくなるため、対象は明示的にお気に入り登録した競艇場のみに限定して
  いる（お気に入り選手個別の全場横断検索はスコープ外。選手プロフィールページで確認する想定）。
  Webの他ページ同様、ボタンを押すまでは取得を行わない（開くたびに自動でリクエストが飛ばない
  ようにするため）。CLIは`kyotei favorite today --date`。
- 天候データの記録・相関分析（2026-08-03追加）は、`backtest`実行時に取得できたbefore_infoの
  気象情報（天候・気温・風速・水温・波高）を`backtests`テーブルにも記録し（列はnullable、
  過去の記録行はNULLのまま）、`BacktestStore.stats_by_weather`/`stats_by_wind_speed`/
  `stats_by_wave_height`で天候・風速帯・波高帯ごとの的中率・回収率を集計できるようにした
  （`kyotei patterns`・Webの「勝ちパターン分析」ページに表示）。あくまで記録・分析のみで、
  `predictor.py`のスコアには引き続き反映していない（天候の影響は状況依存で不確実性が高い
  という既存方針は変更なし。十分なデータが溜まったら反映要否を検討する）。既存キャッシュ済み
  レースもbacktestを再実行すれば遡って天候を記録できる。
- 予想ログ・当日振り返り（`PredictionLogStore`/`predictionlog.py`、2026-08-03追加）は、
  `kyotei predict`・Webの予想画面で実際に見た予想を`prediction_log`テーブルに記録し
  （同一レースは最新の予想で上書き）、`kyotei today --date`・Webの「今日の予想ログ」
  ページで結果確定後に答え合わせする。`backtest`系（出走表データの時点で改めて予想し
  直す検証用）とは目的が異なり、「その時実際に何を見ていたか」をそのまま記録する点が違う。
- `kyotei predict-all --date`（2026-08-03追加）は`scan_races`を使って指定日の複数場・
  複数レースをまとめて予想し、`PredictionLogStore`に一括記録する（直前情報・オッズは
  前日以前だとまだ未公開のことが多く、その場合は出走表データのみでの予想になる）。
  `scripts/daily_routine.ps1` から `kyotei today --date <前日>` → `kyotei predict-all
  --date <翌日>` の順に呼び出し、Windows タスクスケジューラのタスク
  `KyoteiDailyRoutine`（毎日20:30起動、`Register-ScheduledTask`で登録済み）から
  自動実行する運用にしている（ユーザーの生活パターン: 平日6:30起床7:00出発、
  20:00頃帰宅、23:30就寝、に合わせて20:30に設定。2026-08-03時点）。全24場×12R想定で
  実行に80〜90分程度かかる（`backtest-day`と同じ3リクエスト/レース構成のため）。
  Claude Code側の課金は発生しない（ローカルのPythonスクリプトとして実行されるだけで、
  Claudeを一切呼び出さない）。実行ログは`data/logs/`にタイムスタンプ付きで保存
  （.gitignore対象）。PCがその時刻に起動している必要がある。タスクの削除は
  `Unregister-ScheduledTask -TaskName KyoteiDailyRoutine`。
- `kyotei today`（`predictionlog.compare_logged_predictions`）は、確定したレースを
  `data/kyotei.db`の`backtests`テーブルにも保存するようにした（2026-08-03追加）。
  `predicted_ranking`/`win_probabilities`から最小限の`RaceCard`/`RacePrediction`を
  組み立て直し、既存の`evaluate_prediction`/`BacktestStore.save`をそのまま再利用している。
  これにより、毎日`predict-all`→`today`を回すだけで`kyotei stats`/`kyotei patterns`・
  Webの「検証ダッシュボード」（日次の的中率・回収率の推移グラフ、直近の結果一覧）に
  自動的に反映される。改めて`backtest`/`backtest-day`を回す必要はない（両方使った場合、
  同じレースは後勝ちでUPSERTされる）。
- 2026-08-03、2つの信頼性バグを修正:
  1. `BoatraceClient.get_beforeinfo_html`/`get_odds3t_html`は、まだ情報が未公開
     （発売前）で中身が空のページを取得した場合、キャッシュに書き込まない
     （`_forget_cache`）ように修正。修正前は`predict-all`で前日に先取りした空ページが
     永続キャッシュされ、当日実際に情報が公開された後も空のまま返り続けるバグがあった。
  2. `kyotei`のCLI（`cli.py`の`main()`）は起動時に標準出力・標準エラーをUTF-8に
     強制するようにした。Windowsのコンソール既定エンコーディング（cp932）は「✕」等の
     一部記号を表現できず、`UnicodeEncodeError`でクラッシュしていた（`kyotei today`が
     不的中レースを表示する際に発生。タスクスケジューラ経由の非対話実行で特に顕在化
     しやすく、毎日の自動レビューが失敗し続ける原因になっていた）。
- `BacktestStore.monthly_stats()`（2026-08-04追加）は`stats_by_venue`等と同じ
  `backtests`テーブルから、`date`（YYYYMMDD文字列）の先頭6文字（YYYYMM）でグルーピングして
  月ごとの的中率・回収率を返す。`daily_stats`が日次の細かい振れ幅を見るのに対し、こちらは
  長期トレンド・季節性を均して見る用途。`kyotei patterns`の出力に`[月ごとの的中率・回収率]`
  セクションとして追加し、Webの「検証ダッシュボード」にも日次推移グラフの下に月次バーチャート
  （的中率・回収率）を追加（該当月が2件以上ある場合のみ表示。1ヶ月分だけでは比較の意味が
  薄いため）。
- 開催グレード（一般/G3/G2/G1/SG）の取得・記録を2026-08-04に実装。
  `racelist.py`の`_parse_grade`が出走表ページの見出しdiv（`heading2_title`）の
  クラス名（例: `is-G3b`。末尾`b`等は見出しレイアウトの接尾辞でグレードとは無関係）から
  正規表現`is-(SG|G1|G2|G3|normal)`で判定し、`RaceCard.grade`に保持する（判定できなければ
  空文字）。`evaluate_prediction`が`prediction.race.grade`をそのまま`BacktestOutcome.grade`
  に引き継ぎ、`backtests`テーブルに記録（既存行はNULLのまま。天候と同様、backtestを
  再実行すれば遡って記録できる）。`prediction_log`テーブルにも`grade`列を追加し、
  `kyotei predict`/Web予想画面 → `PredictionLogStore.log`で記録 → `kyotei today`/
  `compare_logged_predictions`で`backtests`へ引き継がれる経路も対応済み（`predict-all`→
  `today`の日次自動フローでも遡らずグレードが記録される）。`BacktestStore.stats_by_grade()`
  で集計し、`kyotei patterns`に`[グレードごとの的中率・回収率]`セクション、Webの
  「勝ちパターン分析」ページに同内容のグラフ・表を追加。件数順ではなく格付け順
  （一般→G3→G2→G1→SG）で表示。`kyotei predict`・Webの予想画面には非一般戦のみ
  `[G3]`等のグレード表示を追加（ユーザーが重賞を特に重視しているため）。
  SG/G1/G2は開催数自体が少ないため、当面はサンプル数が少ない点に注意（表示上も明記）。

## 現状・今後
- 出走表・直前情報・結果（払戻金含む）・3連単オッズ・選手の直近成績（過去3節）の取得/パース、
  統計・ルールベース予想＋予想根拠の文章化、買い目候補算出（本命/中穴/大穴ジャンル分け）、
  予算配分、同日他レース結果表示、複数場・複数レース横断の狙い目スキャン（`scan.py`、
  お気に入り競艇場での絞り込み対応）、勝ちパターン分析（場ごと/自信度ごとの的中率、
  2026-08-03から天候・風速・波高ごと、2026-08-04から月ごと・グレードごとの的中率も追加）、
  お気に入り選手・競艇場管理、
  「今日のお気に入り」ホーム画面、オッズ推移記録、当日予想ログの振り返り、複数日ぶんの
  全レース一括予想（`predict-all`）、選手プロフィールリンク、CLI（predict/predict-all/
  backtest/backtest-day/scan/stats/patterns/favorite/today）、Streamlitダッシュボード
  （今日のお気に入り・レース予想・狙い目スキャン・勝ちパターン分析・お気に入り管理・
  今日の予想ログ・検証ダッシュボードの7画面。「レース予想」は競艇場・レース番号を複数選択
  して一括表示可能）まで実装済み。全24場での動作確認済み。GitHub連携でStreamlit Community
  Cloudにデプロイし、iPhone等からアクセス可能な状態。backtestデータ・お気に入り・
  オッズ推移・予想ログはいずれも同じ`data/kyotei.db`に同居しgit管理下に置いているため、
  ローカルで蓄積したデータをpushすればスマホ側にも反映される。
- `scripts/collect_history.py`（過去日をまとめてbacktest・データ蓄積）と
  `scripts/tune_weights.py`（キャッシュ済みHTMLのみでネットワーク不要の重み検証・
  ランダムサーチ。`--with-recent-form`で直近成績weightのablationも可能）も実装済み。
  一度データを蓄積すれば、以降の重み検証はネットアクセスなしで何度でも試せる。
- Windowsタスクスケジューラのタスク`KyoteiDailyRoutine`（毎日20:30起動）で、
  `scripts/daily_routine.ps1`から「前日分レビュー（`kyotei today`）→翌日分の全レース
  予想（`kyotei predict-all`）」を自動実行する運用を2026-08-03に追加（詳細は上記
  デプロイ節参照）。
- 未着手: より多くの日数・場でのデータ蓄積による重みの再検証、`recent_form_weight`の
  実データでの検証（現状0のまま）、天候データが十分溜まった後の予想ロジックへの反映要否の
  検討（記録・分析基盤は2026-08-03に整備済み、スコアへの反映はまだ）、機械学習モデルへの
  置き換え。
