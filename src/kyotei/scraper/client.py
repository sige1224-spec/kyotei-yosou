"""BOATRACE公式サイト向けの節度あるHTTPクライアント。

robots.txt上は全面許可されているが、公式サイトへの負荷を抑えるため
最小アクセス間隔（レート制限）とローカルキャッシュを設ける。
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

BASE_URL = "https://www.boatrace.jp"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"
MIN_INTERVAL_SECONDS = 1.5
USER_AGENT = (
    "kyotei-yosou-app/0.1 (+individual research/hobby project; "
    "contact: sige1224@gmail.com)"
)


class BoatraceClient:
    """boatrace.jp から出走表・直前情報・結果ページを取得するクライアント。"""

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        min_interval: float = MIN_INTERVAL_SECONDS,
        use_cache: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.use_cache = use_cache
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def read_cache(self, cache_key: str) -> str | None:
        """ネットワークに一切アクセスせず、キャッシュ済みHTMLがあれば返す（なければNone）。

        重みチューニングなど、既存キャッシュだけで完結させたい用途向け。
        """
        cache_file = self.cache_dir / f"{cache_key}.html"
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")
        return None

    def get_html(self, path: str, params: dict[str, str], cache_key: str) -> str:
        """指定パスのHTMLを取得する。キャッシュがあればそれを使う。"""
        cache_file = self.cache_dir / f"{cache_key}.html"
        if self.use_cache and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        self._throttle()
        resp = self._session.get(f"{BASE_URL}{path}", params=params, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text

        if self.use_cache:
            cache_file.write_text(html, encoding="utf-8")
        return html

    def get_racelist_html(self, venue_code: str, date: str, race_number: int) -> str:
        cache_key = f"racelist_{venue_code}_{date}_{race_number}"
        return self.get_html(
            "/owpc/pc/race/racelist",
            {"rno": str(race_number), "jcd": venue_code, "hd": date},
            cache_key,
        )

    def get_beforeinfo_html(self, venue_code: str, date: str, race_number: int) -> str:
        cache_key = f"beforeinfo_{venue_code}_{date}_{race_number}"
        return self.get_html(
            "/owpc/pc/race/beforeinfo",
            {"rno": str(race_number), "jcd": venue_code, "hd": date},
            cache_key,
        )

    def get_odds3t_html(self, venue_code: str, date: str, race_number: int) -> str:
        cache_key = f"odds3t_{venue_code}_{date}_{race_number}"
        return self.get_html(
            "/owpc/pc/race/odds3t",
            {"rno": str(race_number), "jcd": venue_code, "hd": date},
            cache_key,
        )

    def get_raceresult_html(self, venue_code: str, date: str, race_number: int) -> str:
        cache_key = f"raceresult_{venue_code}_{date}_{race_number}"
        return self.get_html(
            "/owpc/pc/race/raceresult",
            {"rno": str(race_number), "jcd": venue_code, "hd": date},
            cache_key,
        )
