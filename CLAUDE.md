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
  storage.py           # backtest結果（的中率・回収率）を蓄積するSQLiteストア（data/kyotei.db）
  dayview.py            # 同一開催日・同一会場の他レース結果をまとめて取得
  models/
    entities.py        # RaceCard, RacerEntry, BeforeInfo, RaceResult, Payout, TrifectaOdds 等
    predictor.py        # 統計・ルールベースの予想ロジック
    combos.py            # 推定勝率から買い目候補（3連単/2連単/3連複）をHarville近似で算出
    genres.py             # 買い目候補を本命/中穴/大穴に分類（推定確率×オッズ）
    allocation.py          # 予算を推定確率に比例して100円単位で配分
  scraper/
    _text.py             # パーサー共通のテキスト正規化ヘルパー
    client.py           # boatrace.jp向けHTTPクライアント（レート制限・キャッシュ付き）
    racelist.py          # 出走表ページのパーサー
    beforeinfo.py         # 直前情報ページ（展示タイム・進入コース・気象情報）のパーサー
    result.py            # レース結果ページのパーサー（着順・払戻金）
    odds.py               # 3連単オッズページのパーサー
web/
  app.py               # Streamlitダッシュボード（レース予想 / 検証ダッシュボード）
scripts/
  collect_history.py    # 過去複数日・全会場のbacktestをまとめて実行しデータ蓄積
  tune_weights.py        # キャッシュ済みHTMLのみでネットワーク不要の重み検証・ランダムサーチ
tests/
  fixtures/             # 保存済みサンプルHTML（パーサーの単体テスト用）
data/
  cache/                # 取得したHTMLのローカルキャッシュ（gitignore対象）
  kyotei.db             # backtest結果のSQLite DB（gitignore対象、ローカル蓄積データ）
```

## 使い方
```powershell
kyotei venues                                              # 場コード一覧
kyotei predict --venue 桐生 --date 20260802 --race 1         # 予想・買い目候補・選手情報を表示
kyotei backtest --venue 桐生 --date 20260731 --race 1         # 過去レース1件を答え合わせ
kyotei backtest-day --date 20260731 --venues all --races 1-12  # 指定日をまとめて答え合わせ
kyotei stats                                                # 蓄積した的中率・回収率を表示
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
  数MB程度の見込みでgit管理上の問題は当面ない。

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

## 現状・今後
- 出走表・直前情報・結果（払戻金含む）・3連単オッズの取得/パース、統計・ルールベース予想、
  買い目候補算出（本命/中穴/大穴ジャンル分け）、予算配分、同日他レース結果表示、選手プロフィール
  リンク、CLI（predict/backtest/backtest-day/stats）、Streamlitダッシュボード（予想画面・
  検証画面）まで実装済み。全24場での動作確認済み。GitHub連携でStreamlit Community Cloudに
  デプロイし、iPhone等からアクセス可能な状態。
- `scripts/collect_history.py`（過去日をまとめてbacktest・データ蓄積）と
  `scripts/tune_weights.py`（キャッシュ済みHTMLのみでネットワーク不要の重み検証・
  ランダムサーチ）も実装済み。一度データを蓄積すれば、以降の重み検証はネット
  アクセスなしで何度でも試せる。
- 未着手: より多くの日数・場でのデータ蓄積による重みの再検証、天候の予想ロジックへの
  反映要否の検討、機械学習モデルへの置き換え。
