"""beforeinfo/odds3tページが未公開（空）の場合にキャッシュへ永続化されないことの検証。

未公開ページをそのままキャッシュしてしまうと、後で実際に情報が公開されても
空のスナップショットを返し続けてしまう問題があったため、その回帰防止テスト。
実際のHTTPアクセスは行わず、BoatraceClient._session.getを差し替えてテストする。
"""
from kyotei.scraper.client import BoatraceClient


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        pass


def _make_client(tmp_path, responses: list[str]):
    client = BoatraceClient(cache_dir=tmp_path, min_interval=0, use_cache=True)
    calls: list[tuple] = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return _FakeResponse(responses.pop(0))

    client._session.get = fake_get
    return client, calls


def test_beforeinfo_empty_page_is_not_cached_permanently(tmp_path):
    client, calls = _make_client(
        tmp_path,
        ["<html>まだ情報がありません</html>", "<html>weather1_bodyUnit is-fs12 本物のデータ</html>"],
    )

    first = client.get_beforeinfo_html("01", "20260805", 1)
    assert "まだ情報がありません" in first
    assert len(calls) == 1
    cache_file = tmp_path / "beforeinfo_01_20260805_1.html"
    assert not cache_file.exists()

    second = client.get_beforeinfo_html("01", "20260805", 1)
    assert "本物のデータ" in second
    assert len(calls) == 2  # 空だったのでキャッシュされておらず、再度ネットワークアクセスが発生
    assert cache_file.exists()

    client.get_beforeinfo_html("01", "20260805", 1)
    assert len(calls) == 2  # 今度はデータがあったのでキャッシュされ、3回目はネットワークアクセスなし


def test_odds3t_empty_page_is_not_cached_permanently(tmp_path):
    client, calls = _make_client(
        tmp_path, ["<html>発売前</html>", "<html>oddsPoint 本物のオッズ</html>"]
    )

    client.get_odds3t_html("01", "20260805", 1)
    assert len(calls) == 1
    cache_file = tmp_path / "odds3t_01_20260805_1.html"
    assert not cache_file.exists()

    client.get_odds3t_html("01", "20260805", 1)
    assert len(calls) == 2
    assert cache_file.exists()


def test_beforeinfo_published_page_is_cached_normally(tmp_path):
    client, calls = _make_client(
        tmp_path, ["<html>weather1_bodyUnit is-fs12 本物のデータ</html>"]
    )

    client.get_beforeinfo_html("01", "20260802", 1)
    cache_file = tmp_path / "beforeinfo_01_20260802_1.html"
    assert cache_file.exists()

    client.get_beforeinfo_html("01", "20260802", 1)
    assert len(calls) == 1  # 2回目はキャッシュから返るのでネットワークアクセスは1回のみ
