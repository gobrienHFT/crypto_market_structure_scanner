from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import binance_futures
from binance_futures import BinanceFuturesPublic


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "payload"

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls: list[str] = []
        self.headers = {}

    def request(self, *, url, **_kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def _client(responses) -> BinanceFuturesPublic:
    client = BinanceFuturesPublic(api_key="key", api_secret="secret", retries=1)
    client.session = _Session(responses)
    client._pace = lambda: None
    return client


def test_signed_request_uses_binance_server_time_offset(monkeypatch) -> None:
    monkeypatch.setattr(binance_futures.time, "time", lambda: 2.0)
    client = _client(
        [
            _Response(200, {"serverTime": 1000}),
            _Response(200, [{"symbol": "DEXEUSDT", "positionAmt": "1"}]),
        ]
    )

    rows = client.position_information_v3()

    assert rows[0]["symbol"] == "DEXEUSDT"
    signed_query = parse_qs(urlparse(client.session.urls[1]).query)
    assert signed_query["timestamp"] == ["1000"]
    assert client._server_time_offset_ms == -1000


def test_timestamp_error_forces_resync_and_retries_same_request(monkeypatch) -> None:
    monkeypatch.setattr(binance_futures.time, "time", lambda: 2.0)
    client = _client(
        [
            _Response(400, {"code": -1021, "msg": "Timestamp ahead"}),
            _Response(200, {"serverTime": 1000}),
            _Response(200, [{"symbol": "DEXEUSDT", "positionAmt": "1"}]),
        ]
    )
    client._last_time_sync_monotonic = binance_futures.time.monotonic()

    rows = client.position_information_v3()

    assert rows[0]["symbol"] == "DEXEUSDT"
    assert len(client.session.urls) == 3
    retried_query = parse_qs(urlparse(client.session.urls[2]).query)
    assert retried_query["timestamp"] == ["1000"]
