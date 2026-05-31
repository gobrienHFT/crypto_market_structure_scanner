from __future__ import annotations

import pandas as pd

import cex_flow_scanner as cex
from holder_composition import HolderComposition, HolderRow


def _composition(*, top10_pct: float = 91.0, top100_pct: float = 99.0) -> HolderComposition:
    top_rows = [HolderRow(rank=1, address="0x1111111111111111111111111111111111111111", percent=top10_pct)]
    for rank in range(2, 11):
        top_rows.append(
            HolderRow(rank=rank, address=f"0x{rank:040x}", percent=0.0)
        )
    if top100_pct > top10_pct:
        top_rows.append(
            HolderRow(rank=11, address="0x2222222222222222222222222222222222222222", percent=top100_pct - top10_pct)
        )
    return HolderComposition(
        symbol="PLAYUSDT",
        chain="base",
        contract_address="0x853a7c99227499dba9db8c3a02aa691afdebf841",
        explorer_name="BaseScan",
        total_supply=1_000_000_000,
        top_holders=top_rows,
    )


class _Response:
    status_code = 200
    text = """
    <table>
      <thead>
        <tr><th>Transaction Hash</th><th>Age</th><th>From</th><th>To</th><th>Amount</th><th>Asset</th></tr>
      </thead>
      <tbody>
        <tr><td>0xaaa</td><td>3 hrs ago</td><td>0xabc</td><td>Bitget Deposit</td><td>1,200,000</td><td>PLAY</td></tr>
        <tr><td>0xbbb</td><td>2 days ago</td><td>0xdef</td><td>Binance 14</td><td>2,000,000</td><td>PLAY</td></tr>
        <tr><td>0xccc</td><td>4 hrs ago</td><td>Kraken 246</td><td>0xghi</td><td>1,000,000</td><td>PLAY</td></tr>
      </tbody>
    </table>
    """


class _ApiResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def test_qualified_whale_sender_requires_top10_or_one_pct_holder() -> None:
    assert cex.is_qualified_whale_sender(1, 91.0)
    assert cex.is_qualified_whale_sender(25, 1.2)
    assert not cex.is_qualified_whale_sender(5, 0.0)
    assert not cex.is_qualified_whale_sender(11, 0.5)


def test_scan_cex_deposit_flow_scores_only_recent_deposits_after_concentration_gate(monkeypatch) -> None:
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition())
    monkeypatch.setattr(cex.requests, "get", lambda *args, **kwargs: _Response())

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "PLAYUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
            "last_price": 0.25,
            "quote_volume_24h": 1_000_000,
            "ask_depth_1pct_usdt": 100_000,
        }
    )

    assert result["cex_deposit_flow_flag"] is True
    assert result["cex_deposit_flow_score"] > 0
    assert result["cex_deposit_24h_count"] == 1
    assert result["cex_deposit_24h_target_exchanges"] == "Bitget"
    assert result["cex_deposit_24h_token_amount"] == 1_200_000
    assert result["cex_deposit_24h_notional_usd"] == 300_000
    assert result["cex_deposit_24h_notional_to_ask_depth_pct"] == 300.0
    assert result["cex_deposit_inventory_stress_score"] >= 80.0
    assert "venue-inventory stress" in result["cex_deposit_inventory_stress_note"]
    assert "top10 91.0%" in result["cex_deposit_concentration_gate"]
    assert "basescan.org/advanced-filter" in result["cex_deposit_24h_source_url"]
    assert result["cex_deposit_flow_risk_level"] in {"Elevated", "High", "Extreme"}
    assert "wallet-to-CEX flow" in result["cex_deposit_flow_evidence_summary"]
    assert "notional $300.00K" in result["cex_deposit_flow_evidence_summary"]
    assert "not a conclusion about intent" in result["cex_deposit_flow_interpretation"]
    assert "OI/volume" in result["cex_deposit_flow_next_check"]
    assert "PLAYUSDT | flow" in result["cex_deposit_flow_alert_line"]
    assert "crime" not in result["cex_deposit_flow_evidence_summary"].lower()
    assert "scam" not in result["cex_deposit_flow_evidence_summary"].lower()


def test_scan_cex_deposit_flow_falls_back_to_token_transfer_api_after_403(monkeypatch) -> None:
    deposit_address = "0x9999999999999999999999999999999999999999"
    monkeypatch.setenv("CEX_ADDRESS_LABELS", f"base:{deposit_address}=Bitget Deposit")
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition())
    now = pd.Timestamp.utcnow().timestamp()
    calls: list[str] = []

    def fake_get(url, **_kwargs):
        calls.append(str(url))
        if "advanced-filter" in str(url):
            response = _ApiResponse({})
            response.status_code = 403
            return response
        return _ApiResponse(
            {
                "status": "1",
                "message": "OK",
                "result": [
                    {
                        "hash": "0xapi",
                        "timeStamp": str(int(now - 60 * 60)),
                        "from": "0x1111111111111111111111111111111111111111",
                        "to": deposit_address,
                        "value": str(1_500_000 * 10**18),
                        "tokenDecimal": "18",
                    }
                ],
            }
        )

    monkeypatch.setattr(cex.requests, "get", fake_get)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "PLAYUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
            "last_price": 0.20,
            "quote_volume_24h": 2_000_000,
            "ask_depth_1pct_usdt": 100_000,
        },
        min_transfer_tokens=500_000,
    )

    assert any("advanced-filter" in call for call in calls)
    assert any("api.etherscan.io/v2/api" in call and "chainid=8453" in call for call in calls)
    assert result["cex_deposit_flow_flag"] is True
    assert result["cex_deposit_flow_source"] == "token_transfer_api"
    assert result["cex_deposit_flow_error"] == ""
    assert result["cex_deposit_24h_count"] == 1
    assert result["cex_deposit_24h_token_amount"] == 1_500_000
    assert result["cex_deposit_24h_target_exchanges"] == "Bitget"
    assert result["cex_deposit_24h_top_tx"] == "0xapi"
    assert result["cex_deposit_24h_whale_sender_count"] == 1
    assert result["cex_deposit_24h_whale_sender_token_amount"] == 1_500_000
    assert result["cex_deposit_24h_top_sender_rank"] == 1
    assert result["cex_deposit_24h_top_sender_pct"] == 91.0
    assert "API fallback concentration-gated CEX deposit flow" in result["cex_deposit_flow_note"]
    assert "Top-holder sender evidence" in result["cex_deposit_flow_note"]
    assert "1 top-holder sender tx" in result["cex_deposit_flow_evidence_summary"]
    assert "whale-origin total 1.50M" in result["cex_deposit_flow_evidence_summary"]
    assert "rank 1 91.0%" in result["cex_deposit_flow_evidence_summary"]
    assert "1 top-holder sender tx r1 91.0%" in result["cex_deposit_flow_alert_line"]
    assert "api.etherscan.io/v2/api" in result["cex_deposit_24h_source_url"]
    assert "chainid=8453" in result["cex_deposit_24h_source_url"]


def test_scan_cex_deposit_flow_uses_api_when_advanced_filter_has_no_parsed_rows(monkeypatch) -> None:
    deposit_address = "0x8888888888888888888888888888888888888888"
    monkeypatch.setenv("CEX_ADDRESS_LABELS", f"base:{deposit_address}=Binance Deposit")
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition())
    now = pd.Timestamp.utcnow().timestamp()
    calls: list[str] = []

    def fake_get(url, **_kwargs):
        calls.append(str(url))
        if "advanced-filter" in str(url):
            response = _ApiResponse({})
            response.status_code = 200
            response.text = "<html><body><table><tbody></tbody></table></body></html>"
            return response
        return _ApiResponse(
            {
                "status": "1",
                "message": "OK",
                "result": [
                    {
                        "hash": "0xapiemptyhtml",
                        "timeStamp": str(int(now - 20 * 60)),
                        "from": "0x1111111111111111111111111111111111111111",
                        "to": deposit_address,
                        "value": str(2_000_000 * 10**18),
                        "tokenDecimal": "18",
                    }
                ],
            }
        )

    monkeypatch.setattr(cex.requests, "get", fake_get)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "HTMLZEROUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        },
        min_transfer_tokens=500_000,
    )

    assert any("advanced-filter" in call for call in calls)
    assert any("api.etherscan.io/v2/api" in call and "chainid=8453" in call for call in calls)
    assert result["cex_deposit_flow_flag"] is True
    assert result["cex_deposit_flow_source"] == "token_transfer_api"
    assert result["cex_deposit_flow_error"] == ""
    assert result["cex_deposit_24h_count"] == 1
    assert result["cex_deposit_24h_token_amount"] == 2_000_000
    assert result["cex_deposit_24h_target_exchanges"] == "Binance"
    assert result["cex_deposit_24h_whale_sender_count"] == 1
    assert "0xapiemptyhtml" == result["cex_deposit_24h_top_tx"]


def test_scan_cex_deposit_flow_does_not_call_tiny_top100_sender_whale_origin(monkeypatch) -> None:
    deposit_address = "0x9999999999999999999999999999999999999999"
    monkeypatch.setenv("CEX_ADDRESS_LABELS", f"base:{deposit_address}=Bitget Deposit")
    monkeypatch.setattr(
        cex,
        "fetch_holder_composition",
        lambda *args, **kwargs: _composition(top10_pct=90.0, top100_pct=90.5),
    )
    now = pd.Timestamp.utcnow().timestamp()

    def fake_get(url, **_kwargs):
        if "advanced-filter" in str(url):
            response = _ApiResponse({})
            response.status_code = 403
            return response
        return _ApiResponse(
            {
                "status": "1",
                "message": "OK",
                "result": [
                    {
                        "hash": "0xapi",
                        "timeStamp": str(int(now - 60 * 60)),
                        "from": "0x2222222222222222222222222222222222222222",
                        "to": deposit_address,
                        "value": str(1_500_000 * 10**18),
                        "tokenDecimal": "18",
                    }
                ],
            }
        )

    monkeypatch.setattr(cex.requests, "get", fake_get)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "PLAYUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
            "last_price": 0.20,
            "quote_volume_24h": 2_000_000,
            "ask_depth_1pct_usdt": 100_000,
        },
        min_transfer_tokens=500_000,
    )

    assert result["cex_deposit_flow_flag"] is True
    assert result["cex_deposit_24h_count"] == 1
    assert result["cex_deposit_24h_token_amount"] == 1_500_000
    assert result["cex_deposit_24h_target_exchanges"] == "Bitget"
    assert result["cex_deposit_24h_whale_sender_count"] == 0
    assert result["cex_deposit_24h_whale_sender_token_amount"] == 0.0
    assert "Top-holder sender evidence" not in result["cex_deposit_flow_note"]
    assert "top-holder sender tx" not in result["cex_deposit_flow_evidence_summary"]
    assert "whale-origin" not in result["cex_deposit_flow_alert_line"]


def test_scan_cex_deposit_flow_falls_back_when_explorer_returns_bot_check_page(monkeypatch) -> None:
    deposit_address = "0x8888888888888888888888888888888888888888"
    monkeypatch.setenv("CEX_ADDRESS_LABELS", f"base:{deposit_address}=Gate Deposit")
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition())
    now = pd.Timestamp.utcnow().timestamp()

    def fake_get(url, **_kwargs):
        if "advanced-filter" in str(url):
            response = _ApiResponse({})
            response.status_code = 200
            response.text = "<html><title>Just a moment...</title><body>Verify you are human</body></html>"
            return response
        return _ApiResponse(
            {
                "status": "1",
                "message": "OK",
                "result": [
                    {
                        "hash": "0xbotcheck",
                        "timeStamp": str(int(now - 15 * 60)),
                        "from": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        "to": deposit_address,
                        "value": str(800_000 * 10**18),
                        "tokenDecimal": "18",
                    }
                ],
            }
        )

    monkeypatch.setattr(cex.requests, "get", fake_get)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "GATEUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
            "last_price": 0.10,
            "quote_volume_24h": 1_000_000,
            "ask_depth_1pct_usdt": 50_000,
        },
        min_transfer_tokens=500_000,
    )

    assert result["cex_deposit_flow_flag"] is True
    assert result["cex_deposit_flow_source"] == "token_transfer_api"
    assert result["cex_deposit_flow_error"] == ""
    assert result["cex_deposit_24h_target_exchanges"] == "Gate"
    assert result["cex_deposit_24h_top_tx"] == "0xbotcheck"


def test_token_transfer_api_fallback_keeps_min_transfer_threshold(monkeypatch) -> None:
    deposit_address = "0x7777777777777777777777777777777777777777"
    monkeypatch.setenv("CEX_ADDRESS_LABELS", f"base:{deposit_address}=Binance Deposit")
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition())
    now = pd.Timestamp.utcnow().timestamp()

    def fake_get(url, **_kwargs):
        if "advanced-filter" in str(url):
            response = _ApiResponse({})
            response.status_code = 403
            return response
        return _ApiResponse(
            {
                "status": "1",
                "message": "OK",
                "result": [
                    {
                        "hash": "0xsmall",
                        "timeStamp": str(int(now - 10 * 60)),
                        "from": "0xcccccccccccccccccccccccccccccccccccccccc",
                        "to": deposit_address,
                        "value": str(9_999_999 * 10**18),
                        "tokenDecimal": "18",
                    },
                    {
                        "hash": "0xlarge",
                        "timeStamp": str(int(now - 20 * 60)),
                        "from": "0xdddddddddddddddddddddddddddddddddddddddd",
                        "to": deposit_address,
                        "value": str(10_000_000 * 10**18),
                        "tokenDecimal": "18",
                    },
                ],
            }
        )

    monkeypatch.setattr(cex.requests, "get", fake_get)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "THRESHUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        },
        min_transfer_tokens=10_000_000,
    )

    assert result["cex_deposit_flow_source"] == "token_transfer_api"
    assert result["cex_deposit_24h_count"] == 1
    assert result["cex_deposit_24h_token_amount"] == 10_000_000
    assert result["cex_deposit_24h_top_tx"] == "0xlarge"
    assert result["cex_deposit_24h_target_exchanges"] == "Binance"


def test_scan_cex_deposit_flow_does_not_fetch_when_concentration_gate_fails(monkeypatch) -> None:
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition(top10_pct=20.0, top100_pct=45.0))

    def _no_http(*args, **kwargs):  # pragma: no cover - this should never run
        raise AssertionError("advanced filter should not be fetched without concentration")

    monkeypatch.setattr(cex.requests, "get", _no_http)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "PLAYUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        }
    )

    assert result["cex_deposit_flow_flag"] is False
    assert result["cex_deposit_flow_score"] == 0.0
    assert "concentration gate not met" in result["cex_deposit_flow_note"]
    assert result["cex_deposit_flow_risk_level"] == "Watch only"
    assert "no large labelled CEX transfer flow" in result["cex_deposit_flow_evidence_summary"]


def test_scan_cex_deposit_flow_rejects_top100_only_concentration(monkeypatch) -> None:
    monkeypatch.setattr(cex, "fetch_holder_composition", lambda *args, **kwargs: _composition(top10_pct=55.0, top100_pct=99.0))

    def _no_http(*args, **kwargs):  # pragma: no cover - this should never run
        raise AssertionError("CEX transfer sources should not be fetched without top10 control")

    monkeypatch.setattr(cex.requests, "get", _no_http)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "TOP100ONLYUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        }
    )

    assert result["cex_deposit_flow_flag"] is False
    assert result["cex_deposit_flow_source"] == "holder_gate"
    assert "top10 55.0% / top100 99.0%" in result["cex_deposit_concentration_gate"]
    assert "requires top10 >= 90.0%" in result["cex_deposit_concentration_gate"]


def test_scan_cex_deposit_flow_rejects_precomputed_top100_only_concentration(monkeypatch) -> None:
    def _no_holder_fetch(*args, **kwargs):  # pragma: no cover - this should never run
        raise AssertionError("precomputed top10 failure should stop before holder fetch")

    monkeypatch.setattr(cex, "fetch_holder_composition", _no_holder_fetch)

    result = cex.scan_cex_deposit_flow(
        {
            "symbol": "TOP100ONLYUSDT",
            "token_platform": "base",
            "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
            "top10_holder_pct": 55.0,
            "top100_holder_pct": 99.0,
        }
    )

    assert result["cex_deposit_flow_flag"] is False
    assert result["cex_deposit_flow_source"] == "precomputed_holder_gate"
    assert "top10 55.0% / top100 99.0%" in result["cex_deposit_concentration_gate"]
    assert "requires top10 >= 90.0%" in result["cex_deposit_concentration_gate"]


def test_build_cex_flow_discord_block_has_shared_product_language() -> None:
    row = {
        "symbol": "PLAYUSDT",
        "cex_deposit_flow_score": 88,
        "cex_deposit_flow_risk_level": "High",
        "cex_deposit_24h_count": 3,
        "cex_deposit_24h_token_amount": 2_500_000,
        "cex_deposit_24h_max_amount": 1_200_000,
        "cex_deposit_24h_notional_usd": 750_000,
        "cex_deposit_inventory_stress_score": 72,
        "cex_deposit_inventory_stress_note": "venue-inventory stress 72/100; total notional $750.00K",
        "cex_deposit_24h_total_pct_supply": 2.5,
        "cex_deposit_24h_max_pct_supply": 1.2,
        "cex_deposit_24h_whale_sender_count": 1,
        "cex_deposit_24h_whale_sender_token_amount": 1_200_000,
        "cex_deposit_24h_top_sender_address": "0x1111111111111111111111111111111111111111",
        "cex_deposit_24h_top_sender_rank": 1,
        "cex_deposit_24h_top_sender_pct": 91.0,
        "cex_deposit_24h_target_exchanges": "Bitget, Gate",
        "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
        "cex_deposit_24h_source_url": "https://basescan.org/advanced-filter?tkn=0xabc",
    }

    output = cex.build_cex_flow_discord_block(row, max_chars=900)

    assert "/PLAYUSDT" in output
    assert "CEX Flow Score: 88/100 | Risk: High" in output
    assert "Evidence:" in output
    assert "whale-origin total 1.20M" in output
    assert "top sender rank 1 91.0% 0x1111...1111" in output
    assert "Venue-flow read:" in output
    assert "Inventory stress:" in output
    assert "Next check:" in output
    assert "Source: https://basescan.org/advanced-filter?tkn=0xabc" in output
    assert "pump call" not in output.lower()
    assert len(output) <= 900


def test_build_cex_flow_discord_block_shows_transfer_data_errors() -> None:
    row = {
        "symbol": "BLOCKEDUSDT",
        "cex_deposit_flow_score": 0,
        "cex_deposit_flow_risk_level": "Watch only",
        "cex_deposit_concentration_gate": "top10 91.0% / top100 99.0%",
        "cex_deposit_flow_error": "advanced filter HTTP 403",
        "cex_deposit_24h_source_url": "https://basescan.org/advanced-filter?tkn=0xabc",
    }

    output = cex.build_cex_flow_discord_block(row, max_chars=900)

    assert "/BLOCKEDUSDT" in output
    assert "Data status: CEX-flow check blocked/error: advanced filter HTTP 403" in output
    assert "Source: https://basescan.org/advanced-filter?tkn=0xabc" in output


def test_enrich_cex_deposit_flows_adds_columns_when_disabled() -> None:
    frame = pd.DataFrame([{"symbol": "PLAYUSDT"}])

    output = cex.enrich_cex_deposit_flows(frame, enabled=False)

    for column in cex.CEX_DEPOSIT_FLOW_COLUMNS:
        assert column in output.columns


def test_build_advanced_filter_url_supports_basescan_example() -> None:
    url = cex.build_advanced_filter_url(
        "base",
        "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        min_amount=500_000,
    )

    assert url.startswith("https://basescan.org/advanced-filter?")
    assert "tkn=0x853a7c99227499dba9db8c3a02aa691afdebf841" in url
    assert "txntype=2" in url
    assert "amt=500000~999999999999" in url


def test_build_token_transfer_api_url_uses_etherscan_v2_chainid() -> None:
    url = cex.build_token_transfer_api_url(
        "base",
        "0x853a7c99227499dba9db8c3a02aa691afdebf841",
        api_key="example",
    )

    assert url.startswith("https://api.etherscan.io/v2/api?")
    assert "chainid=8453" in url
    assert "module=account" in url
    assert "action=tokentx" in url
    assert "contractaddress=0x853a7c99227499dba9db8c3a02aa691afdebf841" in url
    assert "apikey=example" in url


def test_token_transfer_api_key_accepts_arbscan_alias(monkeypatch) -> None:
    for env_name in cex.token_transfer_api_key_envs("arbitrum"):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("ARBSCAN_API_KEY", "arbscan-alias-key")

    api_key, env_name = cex._token_transfer_api_key("arbitrum")

    assert api_key == "arbscan-alias-key"
    assert env_name == "ARBSCAN_API_KEY"


def test_enrich_cex_deposit_flows_with_zero_limit_scans_all_contract_rows(monkeypatch) -> None:
    calls: list[str] = []

    def fake_scan(row, **_kwargs):
        calls.append(str(row["symbol"]))
        result = cex._default_result()
        result.update({"cex_deposit_flow_score": 1.0, "cex_deposit_flow_flag": True})
        return result

    monkeypatch.setattr(cex, "scan_cex_deposit_flow", fake_scan)
    frame = pd.DataFrame(
        [
            {
                "symbol": "PLAYUSDT",
                "token_platform": "base",
                "token_contract": "0x853a7c99227499dba9db8c3a02aa691afdebf841",
            },
            {
                "symbol": "LABUSDT",
                "token_platform": "bsc",
                "token_contract": "0x7ec43cf65f1663f820427c62a5780b8f2e25593a",
            },
        ]
    )

    output = cex.enrich_cex_deposit_flows(frame, max_symbols=0)

    assert set(calls) == {"PLAYUSDT", "LABUSDT"}
    assert output["cex_deposit_flow_flag"].astype(bool).all()
