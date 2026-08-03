# 競艇予想アプリ

全24競艇場に対応した、競艇（ボートレース）の予想ロジック・CLI・Webダッシュボード。
BOATRACE公式サイト（boatrace.jp）から出走表・直前情報・結果を取得し、
統計・ルールベースのロジックでレーンごとの推定勝率、買い目候補（3連単・2連単、
本命/中穴/大穴のジャンル分けつき）を算出する。予算を入力すれば買い目への金額配分も
試算できる。過去レースの答え合わせを蓄積し、的中率・回収率を検証する仕組みも備える。
Streamlit Community Cloudにデプロイ済みで、iPhoneなど外出先からもブラウザでアクセスできる。

## セットアップ

```powershell
python -m pip install -e ".[web]"
```

CLIのみで良ければ `python -m pip install -e .` でも可（Webダッシュボードには `[web]` が必要）。

## 使い方（CLI）

```powershell
# 場コード一覧を表示
kyotei venues

# 予想を表示（--venue は場名・場コードどちらでも可。直前情報・オッズが公開済みなら自動で加味）
# 選手6人分の直近成績（過去3節）も取得するため、初回はやや時間がかかる（--no-recent-formで省略可）
kyotei predict --venue 桐生 --date 20260802 --race 1

# 予算を指定すると、本命の買い目に金額を配分する。2R以降は同じ会場の当日それまでの結果も表示
kyotei predict --venue 桐生 --date 20260802 --race 5 --budget 1000

# 過去レース1件を答え合わせしてDBに記録
kyotei backtest --venue 桐生 --date 20260731 --race 1

# 指定日の複数レースをまとめて答え合わせ（全24場対象なら --venues all）
kyotei backtest-day --date 20260731 --venues 桐生,唐津 --races 1-12

# 複数場・複数レースを横断して大穴（高期待値）候補を探す
kyotei scan --date 20260802 --venues all --races 1-12 --genre 大穴 --top 10
kyotei scan --date 20260802 --favorites-only --genre 大穴  # お気に入り競艇場だけに絞る

# 蓄積した的中率を確認
kyotei stats
kyotei stats --venue 桐生 --from 20260701 --to 20260731

# 場ごと・自信度（推定勝率帯）ごとの的中率を分析する（勝ちパターン分析）
kyotei patterns

# お気に入り選手・競艇場の登録・確認
kyotei favorite add-racer 4300 --label 加藤綾
kyotei favorite add-venue 桐生
kyotei favorite list

# 今日 `predict` で実際に見た予想を、確定結果と突き合わせて振り返る
kyotei today --date 20260802
```

`data/kyotei.db` はリポジトリにコミットする運用にしている。ローカルでbacktestを実行して
データを蓄積したら、以下でpushするとスマホ（Streamlit Cloud）側の検証ダッシュボードにも
反映される。

```powershell
git add data/kyotei.db
git commit -m "Update backtest data"
git push
```

## 使い方（Webダッシュボード）

```powershell
streamlit run web/app.py
```

- 「レース予想」ページ: 競艇場・開催日・レース番号を選んで予想を表示。推定勝率のグラフ、
  各艇の「予想根拠」（6艇中の順位に基づく強み/弱みの文章化。厳密なスコア内訳ではなく
  参考情報）、選手情報（級別・全国/当地勝率・モーター/ボート2連率・F数・平均ST・直近3節の
  平均着順/3着内率、公式プロフィールへのリンクつき）、お気に入り選手の登録/解除、
  買い目候補（3連単を本命/中穴/大穴のタブで分類、2連単）、オッズの推移（このページを
  複数回開くと本命上位3点のオッズ変化を記録）、予算を入力しての金額配分、直前情報
  （展示タイム・進入コース・気象情報）、同じ会場の当日それまでのレース結果（公式サイトへの
  リンクつき）、お気に入り競艇場の登録（サイドバー）を確認できる。
- 「狙い目スキャン」ページ: 複数場・複数レースをまとめて予想し、指定ジャンル
  （本命/中穴/大穴）の買い目候補を確率・期待値順に一覧表示する。「今日どのレースを
  見るべきか」を横断的に把握する用途。オッズ未公開のレースは中穴・大穴の判定ができない
  ため対象外。お気に入り競艇場だけに絞って対象を限定することもできる。
- 「勝ちパターン分析」ページ: backtestで蓄積したデータから、場ごとの的中率・回収率と、
  予想1位レーンの推定勝率帯ごとの実際の的中率を確認できる。モデルの自信度（推定勝率）が
  実際の的中率と比例しているかの目安になる。
- 「お気に入り管理」ページ: 登録済みのお気に入り選手・競艇場の一覧確認と削除ができる
  （追加は「レース予想」ページから行う）。
- 「今日の予想ログ」ページ: 「レース予想」ページで実際に見た予想を自動記録し、結果が
  確定したものから答え合わせして振り返る。backtest（出走表データの時点で改めて予想し
  直す検証）とは別の、その日その時点の予想をそのまま記録する仕組み。
- 「検証ダッシュボード」ページ: backtestを画面から実行でき、的中率・回収率の推移グラフと
  直近の結果一覧（払戻金つき）を確認できる。

## 仕組み

- `src/kyotei/scraper/` — boatrace.jp から出走表・直前情報・結果ページ（払戻金含む）を
  取得・パース。取得したHTMLは `data/cache/` にキャッシュし、公式サイトへの負荷を抑える。
- `src/kyotei/models/predictor.py` — コース別（枠番別）1着率、選手・モーター・ボートの
  成績、展示タイム・進入コース（判明していれば）を重み付き合成した統計・ルールベースの
  予想ロジック。天候・水面気象情報は不確実性が高いためスコアには組み込まず、参考情報として
  表示のみ行う。各艇について「6艇中の順位」に基づく予想根拠（強み/弱みの文章）も生成する。
  選手の直近成績を加味する`recent_form_weight`も実装済みだが、実データでの検証待ちのため
  既定値0（無効）。
- `src/kyotei/models/combos.py` — 各艇の推定勝率からHarvilleの公式（Harville, 1973）で
  3連単・2連単・3連複の組み合わせ確率を近似し、買い目候補として提示する。
- `src/kyotei/scraper/odds.py` — boatrace.jpの3連単オッズページを取得・パース。
- `src/kyotei/models/genres.py` — 推定確率とオッズから、買い目候補を本命（的中重視）・
  中穴・大穴（高配当狙い、期待値順）に分類する。オッズ未取得時は本命のみ。
- `src/kyotei/models/allocation.py` — 予算を推定確率に比例して100円単位で配分する試算。
- `src/kyotei/dayview.py` — 同一開催日・同一会場の他レース結果をまとめて取得する。
- `src/kyotei/models/scan.py` — 複数場・複数レースを横断して予想・オッズ取得を行い、
  指定ジャンルの買い目候補を期待値/確率順にまとめる（`kyotei scan` / Web「狙い目スキャン」）。
- `src/kyotei/scraper/racerform.py` — 選手プロフィールの「過去3節成績」ページを取得・パース。
  直近の着順の並びから平均着順・3着内率を算出する。通算成績とは別の「今の調子」の参考情報で、
  予想スコア（`predictor.py`）には反映していない（未検証のため）。
- `src/kyotei/backtest.py` / `src/kyotei/storage.py`（`BacktestStore`） — 過去レースを
  出走表データの時点で予想し、実際の結果・払戻金と突き合わせて `data/kyotei.db`（SQLite）に
  的中率・回収率を記録・集計する仕組み。`stats_by_venue`/`stats_by_confidence`で
  場ごと・自信度ごとの「勝ちパターン分析」も行える。
- `src/kyotei/storage.py`（`FavoriteStore`） — お気に入り選手・お気に入り競艇場を
  `data/kyotei.db`に記録する。
- `src/kyotei/storage.py`（`OddsSnapshotStore`） — 予想画面を開くたびに本命上位3点の
  3連単オッズを記録し、推移を追えるようにする（バックグラウンドでの定期取得は行わない）。
- `src/kyotei/storage.py`（`PredictionLogStore`） / `src/kyotei/predictionlog.py` —
  実際に見た予想を記録し、結果確定後に答え合わせして振り返る（`kyotei today` / Webの
  「今日の予想ログ」）。
- `web/app.py` — Streamlit製のダッシュボード（レース予想・狙い目スキャン・勝ちパターン分析・
  お気に入り管理・今日の予想ログ・検証ダッシュボードの6画面）。

予想結果・買い目候補・回収率試算は、いずれも統計的な参考情報であり、的中や回収を
保証するものではない。舟券の購入・投票自体は本アプリの対象外（表示のみ）。

## テスト

```powershell
python -m pytest
```

保存済みのサンプルHTML（`tests/fixtures/`）を使ってパーサー・予想ロジック・DB層の単体テストを行う。

## 重みのオフライン検証・チューニング

```powershell
# 過去N日分・全24場のデータを収集（data/cache と data/kyotei.db に蓄積。時間がかかるので注意）
python scripts/collect_history.py 20260728 20260729 20260730

# キャッシュ済みHTMLだけを使い、ネットワーク不要で重みを検証・探索
python scripts/tune_weights.py

# 選手の直近成績(recent_form_weight)のablationも行う場合（未キャッシュ選手分は初回のみネットワークアクセス）
python scripts/tune_weights.py --with-recent-form
```

`tune_weights.py` は展示タイム重みのablation（0倍/0.5倍/2倍で的中率がどう変わるか）と、
重み空間のランダムサーチ（上位5件を表示）を行う。2026-08-02時点の検証結果と、それを
踏まえた `PredictorWeights` の既定値の根拠は `src/kyotei/models/predictor.py` の
docstringに記載している。件数がまだ限定的なため、データが増えたら再検証すること。
`--with-recent-form` を付けると選手の直近成績（過去3節の3着内率）を加味した場合の
的中率も比較できるが、2026-08-03時点では未検証のため `recent_form_weight` は既定値0
（無効）のまま。

`kyotei stats` / Webダッシュボードの的中率は、backtest実行**当時**の重みで計算した
結果を記録したものなので、`predictor.py` の重みを変えても過去の記録値は遡って
更新されない（現在の重みでの答え合わせを見たい場合は改めて `backtest`/`backtest-day` を
実行するか、`tune_weights.py` でキャッシュから再評価する）。

## 今後の拡張予定

- `predictor.py` の重み（`PredictorWeights`）は480レース分の限定的な検証に基づく値。
  `backtest`/`backtest-day` で継続的にデータを蓄積し、的中率を見ながら再調整していく。
- `recent_form_weight`（選手の直近成績をスコアに加味）は実装済みだが実データでの検証待ち。
  `tune_weights.py --with-recent-form` で改善が確認できたら既定値を動かす。
- データが十分に蓄積された段階で、`predictor.py` を scikit-learn 等を使った
  機械学習モデルに置き換え。
- 舟券購入・投票の自動化は対象外（法規制・利用規約上のリスクがあるため）。
