from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

import pandas as pd
import requests

from holder_composition import (
    CHAIN_CONFIGS,
    HolderComposition,
    fetch_holder_composition,
    normalize_chain,
    resolve_contract_hint,
)


CEX_DEPOSIT_FLOW_COLUMNS = [
    "cex_deposit_flow_score",
    "cex_deposit_flow_flag",
    "cex_deposit_flow_risk_level",
    "cex_deposit_24h_count",
    "cex_deposit_24h_token_amount",
    "cex_deposit_24h_max_amount",
    "cex_deposit_24h_notional_usd",
    "cex_deposit_24h_max_notional_usd",
    "cex_deposit_24h_total_pct_supply",
    "cex_deposit_24h_max_pct_supply",
    "cex_deposit_24h_whale_sender_count",
    "cex_deposit_24h_whale_sender_token_amount",
    "cex_deposit_24h_whale_sender_max_amount",
    "cex_deposit_24h_top_sender_address",
    "cex_deposit_24h_top_sender_rank",
    "cex_deposit_24h_top_sender_pct",
    "cex_deposit_24h_notional_to_ask_depth_pct",
    "cex_deposit_24h_max_notional_to_ask_depth_pct",
    "cex_deposit_24h_notional_to_volume_pct",
    "cex_deposit_inventory_stress_score",
    "cex_deposit_inventory_stress_note",
    "cex_deposit_24h_target_exchanges",
    "cex_deposit_24h_top_tx",
    "cex_deposit_24h_source_url",
    "cex_deposit_flow_source",
    "cex_deposit_concentration_gate",
    "cex_deposit_flow_note",
    "cex_deposit_flow_evidence_summary",
    "cex_deposit_flow_interpretation",
    "cex_deposit_flow_next_check",
    "cex_deposit_flow_alert_line",
    "cex_deposit_flow_error",
]


WHALE_SENDER_MAX_RANK = 10
WHALE_SENDER_MIN_PCT = 1.0


CEX_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("binance", "Binance"),
    ("bitget", "Bitget"),
    ("gate.io", "Gate"),
    ("gate ", "Gate"),
    ("gate-", "Gate"),
    ("gate:", "Gate"),
    ("okx", "OKX"),
    ("okex", "OKX"),
    ("kraken", "Kraken"),
    ("kucoin", "KuCoin"),
    ("mexc", "MEXC"),
    ("bybit", "Bybit"),
    ("coinbase", "Coinbase"),
    ("htx", "HTX"),
    ("huobi", "HTX"),
    ("bithumb", "Bithumb"),
    ("upbit", "Upbit"),
    ("bitfinex", "Bitfinex"),
    ("crypto.com", "Crypto.com"),
    ("robinhood", "Robinhood"),
)

ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")

ETHERSCAN_V2_API_URL = "https://api.etherscan.io/v2/api"

TOKEN_TRANSFER_API_CONFIGS: dict[str, dict[str, Any]] = {
    "ethereum": {"chainid": "1", "api_key_envs": ("ETHERSCAN_V2_API_KEY", "ETHERSCAN_API_KEY")},
    "bsc": {"chainid": "56", "api_key_envs": ("ETHERSCAN_V2_API_KEY", "ETHERSCAN_API_KEY", "BSCSCAN_API_KEY")},
    "arbitrum": {"chainid": "42161", "api_key_envs": ("ETHERSCAN_V2_API_KEY", "ETHERSCAN_API_KEY", "ARBISCAN_API_KEY")},
    "base": {"chainid": "8453", "api_key_envs": ("ETHERSCAN_V2_API_KEY", "ETHERSCAN_API_KEY", "BASESCAN_API_KEY")},
    "polygon": {"chainid": "137", "api_key_envs": ("ETHERSCAN_V2_API_KEY", "ETHERSCAN_API_KEY", "POLYGONSCAN_API_KEY")},
    "optimism": {"chainid": "10", "api_key_envs": ("ETHERSCAN_V2_API_KEY", "ETHERSCAN_API_KEY", "OPTIMISTIC_ETHERSCAN_API_KEY")},
}


def _default_result(note: str = "", error: str = "") -> dict[str, Any]:
    return {
        "cex_deposit_flow_score": 0.0,
        "cex_deposit_flow_flag": False,
        "cex_deposit_flow_risk_level": "",
        "cex_deposit_24h_count": 0,
        "cex_deposit_24h_token_amount": 0.0,
        "cex_deposit_24h_max_amount": 0.0,
        "cex_deposit_24h_notional_usd": math.nan,
        "cex_deposit_24h_max_notional_usd": math.nan,
        "cex_deposit_24h_total_pct_supply": math.nan,
        "cex_deposit_24h_max_pct_supply": math.nan,
        "cex_deposit_24h_whale_sender_count": 0,
        "cex_deposit_24h_whale_sender_token_amount": 0.0,
        "cex_deposit_24h_whale_sender_max_amount": 0.0,
        "cex_deposit_24h_top_sender_address": "",
        "cex_deposit_24h_top_sender_rank": math.nan,
        "cex_deposit_24h_top_sender_pct": math.nan,
        "cex_deposit_24h_notional_to_ask_depth_pct": math.nan,
        "cex_deposit_24h_max_notional_to_ask_depth_pct": math.nan,
        "cex_deposit_24h_notional_to_volume_pct": math.nan,
        "cex_deposit_inventory_stress_score": 0.0,
        "cex_deposit_inventory_stress_note": "",
        "cex_deposit_24h_target_exchanges": "",
        "cex_deposit_24h_top_tx": "",
        "cex_deposit_24h_source_url": "",
        "cex_deposit_flow_source": "",
        "cex_deposit_concentration_gate": "",
        "cex_deposit_flow_note": note,
        "cex_deposit_flow_evidence_summary": note,
        "cex_deposit_flow_interpretation": "",
        "cex_deposit_flow_next_check": "",
        "cex_deposit_flow_alert_line": "",
        "cex_deposit_flow_error": error,
    }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").replace("$", "").replace("%", "").strip())
    except Exception:
        return None
    return parsed if math.isfinite(parsed) else None


def _pct_value(value: Any) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    if parsed != 0.0 and abs(parsed) <= 1.0:
        return parsed * 100.0
    return parsed


def _holder_pct_value(value: Any) -> float | None:
    return _safe_float(value)


def is_qualified_whale_sender(rank: Any, pct: Any) -> bool:
    rank_value = _safe_float(rank)
    pct_value = _holder_pct_value(pct)
    if pct_value is not None and pct_value >= WHALE_SENDER_MIN_PCT:
        return True
    if rank_value is not None and 0 < rank_value <= WHALE_SENDER_MAX_RANK:
        return pct_value is None or pct_value > 0.0
    return False


def _fmt_pct(value: Any) -> str:
    parsed = _pct_value(value)
    return "n/a" if parsed is None else f"{parsed:.1f}%"


def _fmt_holder_pct(value: Any) -> str:
    parsed = _holder_pct_value(value)
    return "n/a" if parsed is None else f"{parsed:.1f}%"


def _fmt_amount(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(parsed) >= divisor:
            return f"{parsed / divisor:.2f}{suffix}"
    return f"{parsed:.2f}"


def _fmt_usd(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(parsed) >= divisor:
            return f"${parsed / divisor:.2f}{suffix}"
    return f"${parsed:.2f}"


def _row_value(row: Mapping[str, Any] | pd.Series, key: str, default: Any = "") -> Any:
    try:
        value = row.get(key, default)  # type: ignore[attr-defined]
    except Exception:
        value = default
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return value


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = re.sub(r"\s+", " ", str(value).strip())
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _extract_address(value: Any) -> str:
    match = ADDRESS_RE.search(_clean_text(value))
    return match.group(0).lower() if match else ""


def _short_address(value: Any) -> str:
    address = _extract_address(value)
    if not address:
        return ""
    return f"{address[:6]}...{address[-4:]}"


def _exchange_label(value: Any) -> str:
    text = f" {_clean_text(value).lower()} "
    for keyword, label in CEX_KEYWORDS:
        if keyword in text:
            return label
    return ""


def _age_to_hours(value: Any) -> float | None:
    text = _clean_text(value).lower()
    if not text:
        return None
    if text in {"now", "just now"}:
        return 0.0
    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*"
        r"(sec|secs|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours|day|days|week|weeks|month|months)",
        text,
    )
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    if unit.startswith("sec"):
        return amount / 3600.0
    if unit.startswith("min"):
        return amount / 60.0
    if unit.startswith("hr") or unit.startswith("hour"):
        return amount
    if unit.startswith("day"):
        return amount * 24.0
    if unit.startswith("week"):
        return amount * 24.0 * 7.0
    if unit.startswith("month"):
        return amount * 24.0 * 30.0
    return None


def _find_column(columns: list[str], *needles: str) -> str:
    for column in columns:
        normal = column.lower().strip()
        if all(needle.lower() in normal for needle in needles):
            return column
    return ""


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if isinstance(output.columns, pd.MultiIndex):
        output.columns = [" ".join(_clean_text(part) for part in column if _clean_text(part)) for column in output.columns]
    else:
        output.columns = [_clean_text(column) for column in output.columns]
    return output


def build_advanced_filter_url(chain: str, contract: str, *, min_amount: float, max_amount: float = 999_999_999_999.0) -> str:
    config = CHAIN_CONFIGS.get(normalize_chain(chain))
    if config is None:
        return ""
    params = {
        "tkn": contract,
        "txntype": "2",
        "amt": f"{int(min_amount)}~{int(max_amount)}",
    }
    return f"{config.explorer_base_url.rstrip('/')}/advanced-filter?{urlencode(params)}"


def build_token_transfer_api_url(chain: str, contract: str, *, offset: int = 500, api_key: str = "") -> str:
    chain_key = normalize_chain(chain)
    config = TOKEN_TRANSFER_API_CONFIGS.get(chain_key)
    if config is None:
        return ""
    params = {
        "chainid": str(config["chainid"]),
        "module": "account",
        "action": "tokentx",
        "contractaddress": contract,
        "page": 1,
        "offset": max(1, int(offset)),
        "sort": "desc",
    }
    if api_key:
        params["apikey"] = api_key
    return f"{ETHERSCAN_V2_API_URL}?{urlencode(params)}"


def token_transfer_api_key_envs(chain: str) -> tuple[str, ...]:
    config = TOKEN_TRANSFER_API_CONFIGS.get(normalize_chain(chain))
    if config is None:
        return ()
    return tuple(str(value) for value in config.get("api_key_envs", ()))


def _token_transfer_api_key(chain: str) -> tuple[str, str]:
    for env_key in token_transfer_api_key_envs(chain):
        value = os.environ.get(env_key, "").strip()
        if value:
            return value, env_key
    return "", ""


def _read_advanced_filter_rows(html_text: str, *, lookback_hours: int) -> list[dict[str, Any]]:
    try:
        tables = pd.read_html(StringIO(html_text))
    except Exception:
        return []

    parsed: list[dict[str, Any]] = []
    for table in tables:
        frame = _flatten_columns(table)
        columns = list(frame.columns)
        tx_col = _find_column(columns, "transaction") or _find_column(columns, "hash")
        age_col = _find_column(columns, "age") or _find_column(columns, "time")
        from_col = _find_column(columns, "from")
        to_col = _find_column(columns, "to")
        amount_col = _find_column(columns, "amount")
        if not (tx_col and age_col and from_col and to_col and amount_col):
            continue
        for _, row in frame.iterrows():
            age_hours = _age_to_hours(row.get(age_col))
            if age_hours is None or age_hours > lookback_hours:
                continue
            to_text = _clean_text(row.get(to_col))
            exchange = _exchange_label(to_text)
            if not exchange:
                continue
            from_text = _clean_text(row.get(from_col))
            if _exchange_label(from_text):
                continue
            from_address = _extract_address(from_text)
            amount = _safe_float(row.get(amount_col))
            if amount is None or amount <= 0:
                continue
            parsed.append(
                {
                    "tx": _clean_text(row.get(tx_col)),
                    "age_hours": age_hours,
                    "from": from_text,
                    "from_address": from_address,
                    "to": to_text,
                    "exchange": exchange,
                    "amount": amount,
                }
            )
    parsed.sort(key=lambda item: (-float(item["amount"]), float(item["age_hours"])))
    return parsed


def _advanced_filter_block_reason(html_text: str) -> str:
    text = (html_text or "").lower()
    blocked_markers = (
        ("403 forbidden", "HTTP 403 page"),
        ("access denied", "access denied page"),
        ("just a moment", "bot-check page"),
        ("captcha", "captcha page"),
        ("cloudflare", "cloudflare challenge"),
        ("verify you are human", "human-verification page"),
        ("temporarily unavailable", "temporary block page"),
        ("rate limit", "rate-limit page"),
    )
    for marker, reason in blocked_markers:
        if marker in text:
            return reason
    return ""


def _parse_cex_address_labels(raw: str) -> dict[tuple[str, str], str]:
    labels: dict[tuple[str, str], str] = {}
    for chunk in re.split(r"[;\n]+", raw or ""):
        item = chunk.strip()
        if not item:
            continue
        if "=" in item:
            left, label = item.split("=", 1)
            parts = [part.strip() for part in left.split(":")]
            if len(parts) == 1:
                chain, address = "*", parts[0]
            else:
                chain, address = normalize_chain(parts[0]), parts[1]
        else:
            parts = [part.strip() for part in item.split(",")]
            if len(parts) < 2:
                parts = [part.strip() for part in item.split(":")]
            if len(parts) < 2:
                continue
            if len(parts) == 2:
                chain, address, label = "*", parts[0], parts[1]
            else:
                chain, address, label = normalize_chain(parts[0]), parts[1], parts[2]
        match = ADDRESS_RE.search(_clean_text(address))
        clean_label = _clean_text(label)
        if match and clean_label:
            labels[(chain, match.group(0).lower())] = clean_label
    return labels


def load_cex_address_book(path: Path | None = None) -> dict[tuple[str, str], str]:
    labels = _parse_cex_address_labels(os.environ.get("CEX_ADDRESS_LABELS", ""))
    raw_path_text = os.environ.get("CEX_ADDRESS_BOOK_FILE") or os.environ.get("DISCORD_CEX_ADDRESS_BOOK_FILE") or ""
    raw_path = path or (Path(raw_path_text) if raw_path_text.strip() else None)
    if raw_path is not None and raw_path.exists() and raw_path.is_file():
        try:
            frame = pd.read_csv(raw_path)
        except Exception:
            frame = pd.DataFrame()
        if not frame.empty:
            lower_columns = {str(column).lower().strip(): column for column in frame.columns}
            address_col = lower_columns.get("address") or lower_columns.get("wallet") or lower_columns.get("wallet_address")
            label_col = lower_columns.get("label") or lower_columns.get("exchange") or lower_columns.get("name")
            chain_col = lower_columns.get("chain") or lower_columns.get("network")
            if address_col and label_col:
                for _, row in frame.iterrows():
                    match = ADDRESS_RE.search(str(row.get(address_col, "")))
                    label = _clean_text(row.get(label_col, ""))
                    chain = normalize_chain(_clean_text(row.get(chain_col, "*")) or "*") if chain_col else "*"
                    if match and label:
                        labels[(chain, match.group(0).lower())] = label
    return labels


def _cex_label_lookup(
    chain: str,
    composition: HolderComposition,
    *,
    address_book_path: Path | None = None,
) -> dict[str, str]:
    chain_key = normalize_chain(chain)
    labels: dict[str, str] = {}
    for holder in composition.top_holders:
        exchange = _exchange_label(holder.label)
        if exchange and holder.address:
            labels[holder.address.lower()] = exchange
    for (book_chain, address), label in load_cex_address_book(address_book_path).items():
        if book_chain in {"*", "", chain_key}:
            exchange = _exchange_label(label) or _clean_text(label)
            if exchange:
                labels[address.lower()] = exchange
    return labels


def _row_label(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        text = _clean_text(row.get(key, ""))
        if text:
            return text
    return ""


def _token_amount_from_api_row(row: Mapping[str, Any]) -> float | None:
    value = _safe_float(row.get("value") or row.get("Value") or row.get("tokenValue") or row.get("amount"))
    if value is None or value <= 0:
        return None
    decimals = _safe_float(row.get("tokenDecimal") or row.get("tokenDecimals") or row.get("decimals"))
    if decimals is None or decimals < 0 or decimals > 36:
        return value
    return value / (10.0 ** int(decimals))


def _api_row_age_hours(row: Mapping[str, Any], *, now: datetime | None = None) -> float | None:
    ts_raw = row.get("timeStamp") or row.get("timestamp") or row.get("time")
    try:
        ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
    except Exception:
        return None
    now_dt = now or datetime.now(timezone.utc)
    return max(0.0, (now_dt - ts).total_seconds() / 3600.0)


def _read_token_transfer_api_rows(
    payload: Mapping[str, Any],
    *,
    label_by_address: Mapping[str, str],
    lookback_hours: int,
    min_transfer_tokens: float,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], str]:
    result = payload.get("result", [])
    status = str(payload.get("status", "")).strip()
    message = _clean_text(payload.get("message", ""))
    if isinstance(result, str):
        lowered = result.lower()
        if "no transactions" in lowered or "no records" in lowered:
            return [], ""
        return [], result[:180]
    if not isinstance(result, list):
        if status == "0" and message and "no transactions" not in message.lower():
            return [], message[:180]
        return [], ""

    parsed: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, Mapping):
            continue
        age_hours = _api_row_age_hours(item, now=now)
        if age_hours is None or age_hours > lookback_hours:
            continue
        amount = _token_amount_from_api_row(item)
        if amount is None or amount < min_transfer_tokens:
            continue
        to_address = _extract_address(item.get("to")) or _extract_address(item.get("To"))
        from_address = _extract_address(item.get("from")) or _extract_address(item.get("From"))
        to_label = (
            label_by_address.get(to_address, "")
            or _row_label(item, "toName", "toLabel", "to_label", "to_address_label", "toContractName")
        )
        from_label = (
            label_by_address.get(from_address, "")
            or _row_label(item, "fromName", "fromLabel", "from_label", "from_address_label", "fromContractName")
        )
        exchange = _exchange_label(to_label)
        if not exchange:
            continue
        if _exchange_label(from_label):
            continue
        parsed.append(
            {
                "tx": _clean_text(item.get("hash") or item.get("transactionHash") or item.get("tx_hash")),
                "age_hours": age_hours,
                "from": from_label or from_address,
                "from_address": from_address,
                "to": to_label or to_address,
                "exchange": exchange,
                "amount": amount,
            }
        )
    parsed.sort(key=lambda item: (-float(item["amount"]), float(item["age_hours"])))
    return parsed, ""


def _fetch_token_transfer_api_rows(
    chain: str,
    contract: str,
    *,
    label_by_address: Mapping[str, str],
    timeout: int,
    lookback_hours: int,
    min_transfer_tokens: float,
) -> tuple[list[dict[str, Any]], str, str]:
    chain_key = normalize_chain(chain)
    config = TOKEN_TRANSFER_API_CONFIGS.get(chain_key)
    if config is None:
        return [], "", f"token-transfer API unsupported for {chain_key}"
    api_key, _api_key_env = _token_transfer_api_key(chain_key)
    request_url = build_token_transfer_api_url(chain_key, contract, api_key=api_key)
    source_url = build_token_transfer_api_url(chain_key, contract)
    if not request_url:
        return [], source_url, f"token-transfer API unsupported for {chain_key}"
    try:
        response = requests.get(request_url, timeout=timeout)
    except Exception as exc:
        return [], source_url, f"token-transfer API failed: {exc}"
    if response.status_code != 200:
        return [], source_url, f"token-transfer API HTTP {response.status_code}"
    try:
        payload = response.json()
    except Exception:
        return [], source_url, "token-transfer API returned non-JSON response"
    rows, parse_error = _read_token_transfer_api_rows(
        payload,
        label_by_address=label_by_address,
        lookback_hours=lookback_hours,
        min_transfer_tokens=min_transfer_tokens,
    )
    if parse_error:
        return [], source_url, f"token-transfer API parse error: {parse_error}"
    if rows:
        return rows, source_url, ""
    if not label_by_address:
        return [], source_url, "token-transfer API fallback found transfers but no known CEX address labels are configured"
    return [], source_url, "token-transfer API fallback found no labelled CEX destination matches"


def _composition_top_pct(composition: HolderComposition, n: int) -> float | None:
    value = composition.top_pct(n)
    return value if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def _holder_gate(
    row: Mapping[str, Any],
    composition: HolderComposition,
    *,
    min_top10_pct: float,
    min_top100_pct: float,
) -> tuple[bool, float | None, float | None, str]:
    top10 = _pct_value(row.get("top10_holder_pct")) if hasattr(row, "get") else None
    top100 = _pct_value(row.get("top100_holder_pct")) if hasattr(row, "get") else None
    if top10 is None:
        top10 = _composition_top_pct(composition, 10)
    if top100 is None:
        top100 = composition.observed_top_pct
        if not isinstance(top100, (int, float)) or not math.isfinite(float(top100)):
            top100 = None
    gate = (top10 is not None and top10 >= min_top10_pct) or (top100 is not None and top100 >= min_top100_pct)
    gate_text = f"top10 {_fmt_pct(top10)} / top100 {_fmt_pct(top100)}"
    return gate, top10, top100, gate_text


def _precomputed_gate(
    row: Mapping[str, Any],
    *,
    min_top10_pct: float,
    min_top100_pct: float,
) -> tuple[bool, str] | None:
    top10 = _pct_value(row.get("top10_holder_pct")) if hasattr(row, "get") else None
    top100 = _pct_value(row.get("top100_holder_pct")) if hasattr(row, "get") else None
    if top10 is None or top100 is None:
        return None
    gate = top10 >= min_top10_pct or top100 >= min_top100_pct
    return gate, f"top10 {_fmt_pct(top10)} / top100 {_fmt_pct(top100)}"


def _flow_score(
    *,
    count: int,
    total_pct_supply: float | None,
    max_pct_supply: float | None,
    target_count: int,
    top10: float | None,
    top100: float | None,
    whale_sender_count: int = 0,
    whale_sender_max_pct: float | None = None,
) -> float:
    if count <= 0:
        return 0.0
    score = 35.0 + min(count * 5.0, 25.0)
    if total_pct_supply is not None:
        if total_pct_supply >= 5.0:
            score += 35.0
        elif total_pct_supply >= 1.0:
            score += 18.0
        elif total_pct_supply >= 0.25:
            score += 8.0
    if max_pct_supply is not None:
        if max_pct_supply >= 3.0:
            score += 30.0
        elif max_pct_supply >= 1.0:
            score += 18.0
        elif max_pct_supply >= 0.25:
            score += 8.0
    if target_count >= 2:
        score += 10.0
    if (top10 is not None and top10 >= 90.0) or (top100 is not None and top100 >= 95.0):
        score += 10.0
    if whale_sender_count > 0:
        score += 12.0
    if whale_sender_max_pct is not None:
        if whale_sender_max_pct >= 5.0:
            score += 12.0
        elif whale_sender_max_pct >= 1.0:
            score += 6.0
    return max(0.0, min(100.0, score))


def _score_linear(value: float | None, low: float, high: float) -> float:
    if value is None or high <= low:
        return 0.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def _first_positive_float(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _safe_float(_row_value(row, key, math.nan))
        if value is not None and value > 0:
            return value
    return None


def _inventory_stress_metrics(
    row: Mapping[str, Any],
    *,
    total_amount: float,
    max_amount: float,
    max_pct_supply: float | None,
) -> dict[str, Any]:
    price = _first_positive_float(row, "last_price", "current_price", "price")
    quote_volume = _first_positive_float(row, "quote_volume_24h", "volume_24h", "coingecko_total_volume_24h")
    ask_depth = _first_positive_float(row, "ask_depth_1pct_usdt", "coinbase_ask_depth_2pct_usd", "coinbase_ask_depth_usd")

    notional = total_amount * price if price is not None else math.nan
    max_notional = max_amount * price if price is not None else math.nan
    notional_to_ask_depth_pct = (
        notional / ask_depth * 100.0
        if ask_depth is not None and math.isfinite(notional) and notional >= 0
        else math.nan
    )
    max_notional_to_ask_depth_pct = (
        max_notional / ask_depth * 100.0
        if ask_depth is not None and math.isfinite(max_notional) and max_notional >= 0
        else math.nan
    )
    notional_to_volume_pct = (
        notional / quote_volume * 100.0
        if quote_volume is not None and math.isfinite(notional) and notional >= 0
        else math.nan
    )

    ask_score = _score_linear(_safe_float(notional_to_ask_depth_pct), 10.0, 250.0)
    max_ask_score = _score_linear(_safe_float(max_notional_to_ask_depth_pct), 8.0, 160.0)
    volume_score = _score_linear(_safe_float(notional_to_volume_pct), 0.15, 6.0)
    supply_score = _score_linear(max_pct_supply, 0.10, 1.50)
    stress_score = max(
        0.0,
        min(
            100.0,
            ask_score * 0.40
            + max_ask_score * 0.22
            + volume_score * 0.24
            + supply_score * 0.14,
        ),
    )

    note = ""
    if stress_score > 0.0:
        parts = [f"venue-inventory stress {stress_score:.0f}/100"]
        if math.isfinite(notional):
            parts.append(f"total notional {_fmt_usd(notional)}")
        if math.isfinite(notional_to_ask_depth_pct):
            parts.append(f"{notional_to_ask_depth_pct:.1f}% of visible 1% ask depth")
        if math.isfinite(notional_to_volume_pct):
            parts.append(f"{notional_to_volume_pct:.2f}% of 24h turnover")
        if max_pct_supply is not None:
            parts.append(f"largest transfer {_fmt_pct(max_pct_supply)} supply")
        note = "; ".join(parts)

    return {
        "cex_deposit_24h_notional_usd": notional,
        "cex_deposit_24h_max_notional_usd": max_notional,
        "cex_deposit_24h_notional_to_ask_depth_pct": notional_to_ask_depth_pct,
        "cex_deposit_24h_max_notional_to_ask_depth_pct": max_notional_to_ask_depth_pct,
        "cex_deposit_24h_notional_to_volume_pct": notional_to_volume_pct,
        "cex_deposit_inventory_stress_score": stress_score,
        "cex_deposit_inventory_stress_note": note,
    }


def _sender_holder_evidence(
    rows: list[dict[str, Any]],
    composition: HolderComposition,
) -> dict[str, Any]:
    holders_by_address = {
        _extract_address(getattr(holder, "address", "")): holder
        for holder in composition.top_holders
        if _extract_address(getattr(holder, "address", ""))
    }
    whale_rows: list[dict[str, Any]] = []
    for item in rows:
        address = _extract_address(item.get("from_address") or item.get("from"))
        holder = holders_by_address.get(address)
        if holder is None:
            continue
        rank_value = _safe_float(getattr(holder, "rank", math.nan))
        rank = int(rank_value) if rank_value is not None and rank_value > 0 else 0
        pct = _holder_pct_value(getattr(holder, "percent", math.nan))
        if not is_qualified_whale_sender(rank, pct):
            continue
        enriched = dict(item)
        enriched["_sender_address"] = address
        enriched["_sender_rank"] = rank
        enriched["_sender_pct"] = pct
        whale_rows.append(enriched)

    if not whale_rows:
        return {
            "cex_deposit_24h_whale_sender_count": 0,
            "cex_deposit_24h_whale_sender_token_amount": 0.0,
            "cex_deposit_24h_whale_sender_max_amount": 0.0,
            "cex_deposit_24h_top_sender_address": "",
            "cex_deposit_24h_top_sender_rank": math.nan,
            "cex_deposit_24h_top_sender_pct": math.nan,
        }

    total = sum(float(item.get("amount") or 0.0) for item in whale_rows)
    top = max(whale_rows, key=lambda item: float(item.get("amount") or 0.0))
    return {
        "cex_deposit_24h_whale_sender_count": len(whale_rows),
        "cex_deposit_24h_whale_sender_token_amount": total,
        "cex_deposit_24h_whale_sender_max_amount": float(top.get("amount") or 0.0),
        "cex_deposit_24h_top_sender_address": top.get("_sender_address", ""),
        "cex_deposit_24h_top_sender_rank": int(top.get("_sender_rank") or 0),
        "cex_deposit_24h_top_sender_pct": (
            float(top["_sender_pct"])
            if top.get("_sender_pct") is not None and math.isfinite(float(top["_sender_pct"]))
            else math.nan
        ),
    }


def infer_cex_flow_risk_level(row: Mapping[str, Any] | pd.Series) -> str:
    score = _safe_float(_row_value(row, "cex_deposit_flow_score", 0.0)) or 0.0
    inventory_stress = _safe_float(_row_value(row, "cex_deposit_inventory_stress_score", 0.0)) or 0.0
    count = _safe_float(_row_value(row, "cex_deposit_24h_count", 0.0)) or 0.0
    total_pct = _pct_value(_row_value(row, "cex_deposit_24h_total_pct_supply", math.nan))
    max_pct = _pct_value(_row_value(row, "cex_deposit_24h_max_pct_supply", math.nan))
    total_pct = total_pct or 0.0
    max_pct = max_pct or 0.0
    if score >= 90.0 or inventory_stress >= 85.0 or total_pct >= 5.0 or max_pct >= 3.0 or count >= 8:
        return "Extreme"
    if score >= 75.0 or inventory_stress >= 65.0 or total_pct >= 1.0 or max_pct >= 1.0 or count >= 3:
        return "High"
    if score >= 50.0 or inventory_stress >= 35.0 or count >= 1:
        return "Elevated"
    return "Watch only"


def build_cex_flow_evidence_summary(row: Mapping[str, Any] | pd.Series) -> str:
    count = int(_safe_float(_row_value(row, "cex_deposit_24h_count", 0)) or 0)
    targets = _clean_text(_row_value(row, "cex_deposit_24h_target_exchanges", "")) or "labelled CEX wallets"
    total_amount = _fmt_amount(_row_value(row, "cex_deposit_24h_token_amount", math.nan))
    max_amount = _fmt_amount(_row_value(row, "cex_deposit_24h_max_amount", math.nan))
    notional = _safe_float(_row_value(row, "cex_deposit_24h_notional_usd", math.nan))
    gate = _clean_text(_row_value(row, "cex_deposit_concentration_gate", "")) or "concentration gate met"
    total_pct = _pct_value(_row_value(row, "cex_deposit_24h_total_pct_supply", math.nan))
    max_pct = _pct_value(_row_value(row, "cex_deposit_24h_max_pct_supply", math.nan))
    whale_sender_count = int(_safe_float(_row_value(row, "cex_deposit_24h_whale_sender_count", 0)) or 0)
    whale_sender_amount = _safe_float(_row_value(row, "cex_deposit_24h_whale_sender_token_amount", 0.0)) or 0.0
    whale_sender_rank = _safe_float(_row_value(row, "cex_deposit_24h_top_sender_rank", math.nan))
    whale_sender_pct = _holder_pct_value(_row_value(row, "cex_deposit_24h_top_sender_pct", math.nan))
    whale_sender_address = _short_address(_row_value(row, "cex_deposit_24h_top_sender_address", ""))
    inventory_note = _clean_text(_row_value(row, "cex_deposit_inventory_stress_note", ""))
    pct_parts: list[str] = []
    if total_pct is not None:
        pct_parts.append(f"total {total_pct:.2f}% of supply")
    if max_pct is not None:
        pct_parts.append(f"largest {max_pct:.2f}% of supply")
    if notional is not None and math.isfinite(notional):
        pct_parts.append(f"notional {_fmt_usd(notional)}")
    if inventory_note:
        pct_parts.append(inventory_note)
    if whale_sender_count > 0:
        sender = f"{whale_sender_count} top-holder sender tx"
        sender += f"; whale-origin total {_fmt_amount(whale_sender_amount)}"
        detail_parts: list[str] = []
        if whale_sender_rank is not None and whale_sender_rank > 0:
            detail_parts.append(f"rank {int(whale_sender_rank)}")
        if whale_sender_pct is not None:
            detail_parts.append(_fmt_holder_pct(whale_sender_pct))
        if whale_sender_address:
            detail_parts.append(whale_sender_address)
        if detail_parts:
            sender += f"; top sender {' '.join(detail_parts)}"
        pct_parts.append(sender)
    pct_text = f"; {'; '.join(pct_parts)}" if pct_parts else ""
    if count <= 0:
        return f"{gate}; no large labelled CEX transfer flow found in the active lookback."
    return (
        f"Concentration-gated wallet-to-CEX flow: {count} large transfer(s) into {targets}; "
        f"total {total_amount} tokens; largest {max_amount}{pct_text}; {gate}."
    )


def build_cex_flow_interpretation(row: Mapping[str, Any] | pd.Series) -> str:
    count = int(_safe_float(_row_value(row, "cex_deposit_24h_count", 0)) or 0)
    if count <= 0:
        return "No venue-flow pressure was detected after the holder concentration gate."
    return (
        "Token inventory moved from non-CEX wallets into labelled exchange wallets after the concentration gate was met. "
        "Treat this as venue-flow and distribution-risk evidence, not a conclusion about intent."
    )


def build_cex_flow_next_check(row: Mapping[str, Any] | pd.Series) -> str:
    count = int(_safe_float(_row_value(row, "cex_deposit_24h_count", 0)) or 0)
    if count <= 0:
        return "Recheck after the next scan window, especially if OI or volume starts expanding."
    return "Watch whether CEX balances keep rising, OI/volume expands, and price absorbs or rejects the added venue inventory."


def build_cex_flow_alert_line(row: Mapping[str, Any] | pd.Series) -> str:
    symbol = str(_row_value(row, "symbol", "")).upper().strip() or "UNKNOWN"
    score = _safe_float(_row_value(row, "cex_deposit_flow_score", 0.0)) or 0.0
    risk = _clean_text(_row_value(row, "cex_deposit_flow_risk_level", "")) or infer_cex_flow_risk_level(row)
    count = int(_safe_float(_row_value(row, "cex_deposit_24h_count", 0.0)) or 0)
    targets = _clean_text(_row_value(row, "cex_deposit_24h_target_exchanges", "")) or "labelled CEX"
    total_amount = _fmt_amount(_row_value(row, "cex_deposit_24h_token_amount", math.nan))
    total_pct = _pct_value(_row_value(row, "cex_deposit_24h_total_pct_supply", math.nan))
    inventory_stress = _safe_float(_row_value(row, "cex_deposit_inventory_stress_score", 0.0)) or 0.0
    whale_sender_count = int(_safe_float(_row_value(row, "cex_deposit_24h_whale_sender_count", 0)) or 0)
    whale_sender_rank = _safe_float(_row_value(row, "cex_deposit_24h_top_sender_rank", math.nan))
    whale_sender_pct = _holder_pct_value(_row_value(row, "cex_deposit_24h_top_sender_pct", math.nan))
    pct_text = f" | {total_pct:.2f}% supply" if total_pct is not None else ""
    stress_text = f" | inventory stress {inventory_stress:.0f}" if inventory_stress > 0.0 else ""
    whale_text = ""
    if whale_sender_count > 0:
        whale_parts = [f"{whale_sender_count} top-holder sender tx"]
        if whale_sender_rank is not None and whale_sender_rank > 0:
            whale_parts.append(f"r{int(whale_sender_rank)}")
        if whale_sender_pct is not None:
            whale_parts.append(_fmt_holder_pct(whale_sender_pct))
        whale_text = f" | {' '.join(whale_parts)}"
    return f"{symbol} | flow {score:.0f}/100 | {risk} | {count} tx | {targets} | total {total_amount}{pct_text}{stress_text}{whale_text}"


def build_cex_flow_discord_block(row: Mapping[str, Any] | pd.Series, *, max_chars: int = 900) -> str:
    symbol = str(_row_value(row, "symbol", "")).upper().strip() or "UNKNOWN"
    score = _safe_float(_row_value(row, "cex_deposit_flow_score", 0.0)) or 0.0
    risk = _clean_text(_row_value(row, "cex_deposit_flow_risk_level", "")) or infer_cex_flow_risk_level(row)
    evidence = _clean_text(_row_value(row, "cex_deposit_flow_evidence_summary", "")) or build_cex_flow_evidence_summary(row)
    interpretation = _clean_text(_row_value(row, "cex_deposit_flow_interpretation", "")) or build_cex_flow_interpretation(row)
    next_check = _clean_text(_row_value(row, "cex_deposit_flow_next_check", "")) or build_cex_flow_next_check(row)
    inventory_note = _clean_text(_row_value(row, "cex_deposit_inventory_stress_note", ""))
    source_url = _clean_text(_row_value(row, "cex_deposit_24h_source_url", ""))
    error = _clean_text(_row_value(row, "cex_deposit_flow_error", ""))
    lines = [
        f"/{symbol}",
        f"CEX Flow Score: {score:.0f}/100 | Risk: {risk}",
        f"Evidence: {evidence}",
        f"Venue-flow read: {interpretation}",
        *( [f"Inventory stress: {inventory_note}"] if inventory_note else [] ),
        f"Next check: {next_check}",
    ]
    if error:
        lines.append(f"Data status: CEX-flow check blocked/error: {error}")
    if source_url:
        lines.append(f"Source: {source_url}")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    trimmed: list[str] = []
    budget = max_chars
    for line in lines:
        if len(line) + 1 <= budget:
            trimmed.append(line)
            budget -= len(line) + 1
        elif budget > 40:
            trimmed.append(line[: max(0, budget - 2)].rstrip() + "..")
            break
    return "\n".join(trimmed)


def _apply_flow_rows_to_result(
    result: dict[str, Any],
    row: Mapping[str, Any],
    composition: HolderComposition,
    rows: list[dict[str, Any]],
    *,
    top10: float | None,
    top100: float | None,
    gate_text: str,
    lookback_hours: int,
    source: str,
) -> dict[str, Any]:
    total_amount = sum(float(item["amount"]) for item in rows)
    max_amount = max(float(item["amount"]) for item in rows)
    total_supply = composition.total_supply if math.isfinite(composition.total_supply) and composition.total_supply > 0 else None
    total_pct_supply = (total_amount / total_supply * 100.0) if total_supply else None
    max_pct_supply = (max_amount / total_supply * 100.0) if total_supply else None
    inventory_stress = _inventory_stress_metrics(
        row,
        total_amount=total_amount,
        max_amount=max_amount,
        max_pct_supply=max_pct_supply,
    )
    targets = sorted({str(item["exchange"]) for item in rows if item.get("exchange")})
    sender_evidence = _sender_holder_evidence(rows, composition)
    whale_sender_count = int(_safe_float(sender_evidence.get("cex_deposit_24h_whale_sender_count", 0)) or 0)
    whale_sender_pct = _holder_pct_value(sender_evidence.get("cex_deposit_24h_top_sender_pct"))
    score = _flow_score(
        count=len(rows),
        total_pct_supply=total_pct_supply,
        max_pct_supply=max_pct_supply,
        target_count=len(targets),
        top10=top10,
        top100=top100,
        whale_sender_count=whale_sender_count,
        whale_sender_max_pct=whale_sender_pct,
    )
    source_prefix = "API fallback " if source == "token_transfer_api" else ""
    sender_note = (
        f" Top-holder sender evidence: {whale_sender_count} transfer(s), "
        f"{_fmt_amount(sender_evidence.get('cex_deposit_24h_whale_sender_token_amount'))} tokens."
        if whale_sender_count > 0
        else ""
    )
    result.update(
        {
            "cex_deposit_flow_score": score,
            "cex_deposit_flow_flag": score > 0.0,
            "cex_deposit_24h_count": len(rows),
            "cex_deposit_24h_token_amount": total_amount,
            "cex_deposit_24h_max_amount": max_amount,
            **inventory_stress,
            "cex_deposit_24h_total_pct_supply": total_pct_supply if total_pct_supply is not None else math.nan,
            "cex_deposit_24h_max_pct_supply": max_pct_supply if max_pct_supply is not None else math.nan,
            **sender_evidence,
            "cex_deposit_24h_target_exchanges": ", ".join(targets),
            "cex_deposit_24h_top_tx": str(rows[0].get("tx", "")),
            "cex_deposit_flow_source": source,
            "cex_deposit_flow_note": (
                f"{source_prefix}concentration-gated CEX deposit flow: {len(rows)} large transfer(s) into "
                f"{', '.join(targets)} in {lookback_hours}h; {gate_text}; total {_fmt_amount(total_amount)} tokens."
                f"{sender_note}"
            ),
        }
    )
    result["cex_deposit_flow_risk_level"] = infer_cex_flow_risk_level(result)
    result["cex_deposit_flow_evidence_summary"] = build_cex_flow_evidence_summary(result)
    result["cex_deposit_flow_interpretation"] = build_cex_flow_interpretation(result)
    result["cex_deposit_flow_next_check"] = build_cex_flow_next_check(result)
    result["cex_deposit_flow_alert_line"] = build_cex_flow_alert_line({"symbol": _row_value(row, "symbol", ""), **result})
    return result


def scan_cex_deposit_flow(
    row: Mapping[str, Any],
    *,
    hints_path: Path | None = None,
    timeout: int = 12,
    max_holders: int = 100,
    lookback_hours: int = 24,
    min_transfer_tokens: float = 500_000.0,
    min_top10_pct: float = 90.0,
    min_top100_pct: float = 90.0,
) -> dict[str, Any]:
    hint = resolve_contract_hint(row, hints_path=hints_path)
    if hint is None:
        return _default_result(error="no contract hint")
    chain = normalize_chain(hint.chain)
    config = CHAIN_CONFIGS.get(chain)
    if config is None:
        return _default_result(error=f"unsupported chain {hint.chain}")

    precomputed_gate = _precomputed_gate(row, min_top10_pct=min_top10_pct, min_top100_pct=min_top100_pct)
    if precomputed_gate is not None:
        gate, gate_text = precomputed_gate
        if not gate:
            result = _default_result()
            result["cex_deposit_concentration_gate"] = gate_text
            result["cex_deposit_flow_source"] = "precomputed_holder_gate"
            result["cex_deposit_flow_note"] = f"concentration gate not met ({gate_text}); recent CEX deposits not scored."
            result["cex_deposit_flow_risk_level"] = infer_cex_flow_risk_level(result)
            result["cex_deposit_flow_evidence_summary"] = build_cex_flow_evidence_summary(result)
            result["cex_deposit_flow_interpretation"] = build_cex_flow_interpretation(result)
            result["cex_deposit_flow_next_check"] = build_cex_flow_next_check(result)
            result["cex_deposit_flow_alert_line"] = build_cex_flow_alert_line({"symbol": _row_value(row, "symbol", ""), **result})
            return result

    try:
        composition = fetch_holder_composition(row, hints_path=hints_path, timeout=timeout, max_holders=max_holders)
    except Exception as exc:
        return _default_result(error=f"holder composition failed: {exc}")
    if composition.error:
        return _default_result(error=composition.error)

    gate, top10, top100, gate_text = _holder_gate(
        row,
        composition,
        min_top10_pct=min_top10_pct,
        min_top100_pct=min_top100_pct,
    )
    result = _default_result()
    result["cex_deposit_concentration_gate"] = gate_text
    if not gate:
        result["cex_deposit_flow_source"] = "holder_gate"
        result["cex_deposit_flow_note"] = f"concentration gate not met ({gate_text}); recent CEX deposits not scored."
        result["cex_deposit_flow_risk_level"] = infer_cex_flow_risk_level(result)
        result["cex_deposit_flow_evidence_summary"] = build_cex_flow_evidence_summary(result)
        result["cex_deposit_flow_interpretation"] = build_cex_flow_interpretation(result)
        result["cex_deposit_flow_next_check"] = build_cex_flow_next_check(result)
        result["cex_deposit_flow_alert_line"] = build_cex_flow_alert_line({"symbol": _row_value(row, "symbol", ""), **result})
        return result

    source_url = build_advanced_filter_url(chain, hint.contract_address, min_amount=min_transfer_tokens)
    result["cex_deposit_24h_source_url"] = source_url
    result["cex_deposit_flow_source"] = "advanced_filter"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; crypto-market-structure-scanner/1.0)", "Accept": "text/html"}
    html_error = ""
    try:
        response = requests.get(source_url, headers=headers, timeout=timeout)
    except Exception as exc:
        html_error = f"advanced filter failed: {exc}"
        rows = []
    else:
        if response.status_code != 200:
            html_error = f"advanced filter HTTP {response.status_code}"
            rows = []
        else:
            block_reason = _advanced_filter_block_reason(response.text)
            if block_reason:
                html_error = f"advanced filter blocked: {block_reason}"
                rows = []
            else:
                rows = _read_advanced_filter_rows(response.text, lookback_hours=lookback_hours)

    if not rows and html_error:
        label_lookup = _cex_label_lookup(chain, composition)
        api_rows, api_source_url, api_error = _fetch_token_transfer_api_rows(
            chain,
            hint.contract_address,
            label_by_address=label_lookup,
            timeout=timeout,
            lookback_hours=lookback_hours,
            min_transfer_tokens=min_transfer_tokens,
        )
        if api_source_url:
            result["cex_deposit_24h_source_url"] = api_source_url
        if api_rows:
            result["cex_deposit_flow_error"] = ""
            return _apply_flow_rows_to_result(
                result,
                row,
                composition,
                api_rows,
                top10=top10,
                top100=top100,
                gate_text=gate_text,
                lookback_hours=lookback_hours,
                source="token_transfer_api",
            )
        result["cex_deposit_flow_source"] = "advanced_filter_blocked_api_fallback"
        result["cex_deposit_flow_error"] = f"{html_error}; {api_error}" if api_error else html_error
        result["cex_deposit_flow_note"] = (
            f"concentration gate met ({gate_text}); transfer source blocked or produced no labelled CEX matches."
        )
        result["cex_deposit_flow_risk_level"] = infer_cex_flow_risk_level(result)
        result["cex_deposit_flow_evidence_summary"] = build_cex_flow_evidence_summary(result)
        result["cex_deposit_flow_interpretation"] = build_cex_flow_interpretation(result)
        result["cex_deposit_flow_next_check"] = build_cex_flow_next_check(result)
        result["cex_deposit_flow_alert_line"] = build_cex_flow_alert_line({"symbol": _row_value(row, "symbol", ""), **result})
        return result

    if not rows:
        result["cex_deposit_flow_note"] = (
            f"concentration gate met ({gate_text}); no large labelled CEX deposits found in last {lookback_hours}h."
        )
        result["cex_deposit_flow_source"] = "advanced_filter"
        result["cex_deposit_flow_evidence_summary"] = build_cex_flow_evidence_summary(result)
        result["cex_deposit_flow_interpretation"] = build_cex_flow_interpretation(result)
        result["cex_deposit_flow_next_check"] = build_cex_flow_next_check(result)
        result["cex_deposit_flow_risk_level"] = infer_cex_flow_risk_level(result)
        result["cex_deposit_flow_alert_line"] = build_cex_flow_alert_line({"symbol": _row_value(row, "symbol", ""), **result})
        return result

    return _apply_flow_rows_to_result(
        result,
        row,
        composition,
        rows,
        top10=top10,
        top100=top100,
        gate_text=gate_text,
        lookback_hours=lookback_hours,
        source="advanced_filter",
    )


def _candidate_priority(row: pd.Series) -> float:
    top10 = _pct_value(row.get("top10_holder_pct")) or 0.0
    top100 = _pct_value(row.get("top100_holder_pct")) or 0.0
    values = [
        top10,
        min(top100, 100.0),
        _safe_float(row.get("centralized_ownership_score")) or 0.0,
        _safe_float(row.get("float_trap_score")) or 0.0,
        _safe_float(row.get("terminal_edge_score")) or 0.0,
        _safe_float(row.get("trade_bucket_score")) or 0.0,
        _safe_float(row.get("short_account_pct")) or 0.0,
        _safe_float(row.get("daily_quote_volume_multiple")) or 0.0,
    ]
    return sum(values)


def enrich_cex_deposit_flows(
    frame: pd.DataFrame,
    *,
    enabled: bool = True,
    hints_path: Path | None = None,
    max_symbols: int = 0,
    timeout: int = 12,
    max_holders: int = 100,
    lookback_hours: int = 24,
    min_transfer_tokens: float = 500_000.0,
    min_top10_pct: float = 90.0,
    min_top100_pct: float = 90.0,
) -> pd.DataFrame:
    output = frame.copy()
    for column in CEX_DEPOSIT_FLOW_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
    if output.empty or not enabled:
        return output

    candidates: list[tuple[Any, float]] = []
    for index, row in output.iterrows():
        try:
            hint = resolve_contract_hint(row.to_dict(), hints_path=hints_path)
        except Exception:
            hint = None
        if hint is None:
            continue
        candidates.append((index, _candidate_priority(row)))
    candidates.sort(key=lambda item: item[1], reverse=True)

    selected = candidates if max_symbols <= 0 else candidates[:max_symbols]
    for index, _priority in selected:
        row = output.loc[index]
        result = scan_cex_deposit_flow(
            row.to_dict(),
            hints_path=hints_path,
            timeout=timeout,
            max_holders=max_holders,
            lookback_hours=lookback_hours,
            min_transfer_tokens=min_transfer_tokens,
            min_top10_pct=min_top10_pct,
            min_top100_pct=min_top100_pct,
        )
        for column, value in result.items():
            output.at[index, column] = value
    return output
