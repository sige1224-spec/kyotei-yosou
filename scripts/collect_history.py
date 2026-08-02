"""過去複数日分のレースをまとめてbacktestし、data/cache と data/kyotei.db に蓄積する。

使い方:
    python scripts/collect_history.py 20260728 20260729 20260730 20260731

各日について全24競艇場・全12レースを対象にする（開催がない場・レースは自動でスキップ）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kyotei.backtest import run_day_backtest
from kyotei.constants import VENUES
from kyotei.scraper.client import BoatraceClient
from kyotei.storage import BacktestStore


def main(dates: list[str]) -> None:
    client = BoatraceClient(use_cache=True)
    store = BacktestStore()
    codes = list(VENUES.keys())
    races = list(range(1, 13))

    grand_ran = grand_skipped = 0
    started = time.monotonic()

    for date in dates:
        ran = skipped = 0
        for code, race_number, outcome, error in run_day_backtest(
            client, store, codes, date, races
        ):
            if error is not None:
                skipped += 1
            else:
                ran += 1
        grand_ran += ran
        grand_skipped += skipped
        elapsed = time.monotonic() - started
        print(
            f"[{date}] 実行={ran} スキップ={skipped}  "
            f"(累計 実行={grand_ran} スキップ={grand_skipped}, 経過{elapsed / 60:.1f}分)",
            flush=True,
        )

    print(f"完了: 合計実行={grand_ran} スキップ={grand_skipped}")


if __name__ == "__main__":
    main(sys.argv[1:])
