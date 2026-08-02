# 競艇予想アプリ

全24競艇場に対応した、競艇（ボートレース）の予想ロジック・CLI・Webダッシュボード。
BOATRACE公式サイト（boatrace.jp）から出走表・直前情報・結果を取得し、
統計・ルールベースのロジックでレーンごとの推定勝率、買い目候補（3連単・2連単）を算出する。
過去レースの答え合わせを蓄積し、的中率・回収率を検証する仕組みも備える。
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

# 予想を表示（--venue は場名・場コードどちらでも可。直前情報が公開済みなら自動で加味）
kyotei predict --venue 桐生 --date 20260802 --race 1

# 過去レース1件を答え合わせしてDBに記録
kyotei backtest --venue 桐生 --date 20260731 --race 1

# 指定日の複数レースをまとめて答え合わせ（全24場対象なら --venues all）
kyotei backtest-day --date 20260731 --venues 桐生,唐津 --races 1-12

# 蓄積した的中率を確認
kyotei stats
kyotei stats --venue 桐生 --from 20260701 --to 20260731
```

## 使い方（Webダッシュボード）

```powershell
streamlit run web/app.py
```

- 「レース予想」ページ: 競艇場・開催日・レース番号を選んで予想を表示。推定勝率のグラフ、
  選手情報（級別・全国/当地勝率・モーター/ボート2連率・F数・平均ST）、買い目候補
  （3連単・2連単）、直前情報（展示タイム・進入コース・気象情報）を確認できる。
- 「検証ダッシュボード」ページ: backtestを画面から実行でき、的中率・回収率の推移グラフと
  直近の結果一覧（払戻金つき）を確認できる。

## 仕組み

- `src/kyotei/scraper/` — boatrace.jp から出走表・直前情報・結果ページ（払戻金含む）を
  取得・パース。取得したHTMLは `data/cache/` にキャッシュし、公式サイトへの負荷を抑える。
- `src/kyotei/models/predictor.py` — コース別（枠番別）1着率、選手・モーター・ボートの
  成績、展示タイム・進入コース（判明していれば）を重み付き合成した統計・ルールベースの
  予想ロジック。天候・水面気象情報は不確実性が高いためスコアには組み込まず、参考情報として
  表示のみ行う。
- `src/kyotei/models/combos.py` — 各艇の推定勝率からHarvilleの公式（Harville, 1973）で
  3連単・2連単・3連複の組み合わせ確率を近似し、買い目候補として提示する。
- `src/kyotei/backtest.py` / `src/kyotei/storage.py` — 過去レースを出走表データの時点で
  予想し、実際の結果・払戻金と突き合わせて `data/kyotei.db`（SQLite）に的中率・回収率を
  記録・集計する仕組み。
- `web/app.py` — Streamlit製のダッシュボード（予想画面・検証画面）。

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
```

`tune_weights.py` は展示タイム重みのablation（0倍/0.5倍/2倍で的中率がどう変わるか）と、
重み空間のランダムサーチ（上位5件を表示）を行う。2026-08-02時点の検証結果と、それを
踏まえた `PredictorWeights` の既定値の根拠は `src/kyotei/models/predictor.py` の
docstringに記載している。件数がまだ限定的なため、データが増えたら再検証すること。

`kyotei stats` / Webダッシュボードの的中率は、backtest実行**当時**の重みで計算した
結果を記録したものなので、`predictor.py` の重みを変えても過去の記録値は遡って
更新されない（現在の重みでの答え合わせを見たい場合は改めて `backtest`/`backtest-day` を
実行するか、`tune_weights.py` でキャッシュから再評価する）。

## 今後の拡張予定

- `predictor.py` の重み（`PredictorWeights`）は480レース分の限定的な検証に基づく値。
  `backtest`/`backtest-day` で継続的にデータを蓄積し、的中率を見ながら再調整していく。
- データが十分に蓄積された段階で、`predictor.py` を scikit-learn 等を使った
  機械学習モデルに置き換え。
- 舟券購入・投票の自動化は対象外（法規制・利用規約上のリスクがあるため）。
