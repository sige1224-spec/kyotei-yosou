# 毎日の自動実行用スクリプト（Windows タスクスケジューラから起動する想定）。
#
# 1. 前日分の予想ログを確定結果と突き合わせてレビュー（`kyotei today`）
# 2. 翌日分の全レースをまとめて予想し、予想ログに記録（`kyotei predict-all`）
#
# 実行結果は data/logs/ にタイムスタンプ付きで保存される（.gitignore対象）。
# 公式サイトへの負荷軽減のため通常のkyotei CLIと同じレート制限・キャッシュを使う。
# 全24場×12レース想定で概ね80〜90分程度かかる（CLAUDE.md参照）。

$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$LogDir = Join-Path $ProjectRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Now = Get-Date
$Yesterday = $Now.AddDays(-1).ToString("yyyyMMdd")
$Tomorrow = $Now.AddDays(1).ToString("yyyyMMdd")
$LogFile = Join-Path $LogDir ("daily_{0}.log" -f $Now.ToString("yyyyMMdd_HHmmss"))

"=== $Now 前日分レビュー ($Yesterday) ===" | Out-File -FilePath $LogFile -Append -Encoding utf8
kyotei today --date $Yesterday *>> $LogFile

"" | Out-File -FilePath $LogFile -Append -Encoding utf8
"=== $(Get-Date) 翌日分予想 ($Tomorrow) ===" | Out-File -FilePath $LogFile -Append -Encoding utf8
kyotei predict-all --date $Tomorrow --venues all --races 1-12 *>> $LogFile

"" | Out-File -FilePath $LogFile -Append -Encoding utf8
"=== $(Get-Date) 完了 ===" | Out-File -FilePath $LogFile -Append -Encoding utf8
