from __future__ import annotations

import math
import re
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
    "cex_deposit_24h_total_pct_supply",
    "cex_deposit_24h_max_pct_supply",
    "cex_deposit_24h_target_exchanges",
    "cex_deposit_24h_top_tx",
    "cex_deposit_24h_source_url",
    "cex_deposit_concentration_gate",
    "cex_deposit_flow_note",
    "cex_deposit_flow_evidence_summary",
    "cex_deposit_flow_interpretation",
    "cex_deposit_flow_next_check",
    "cex_deposit_flow_alert_line",
    "cex_deposit_flow_error",
]


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


def _default_result(note: str = "", error: str = "") -> dict[str, Any]:
    return {
        "cex_deposit_flow_score": 0.0,
        "cex_deposit_flow_flag": False,
        "cex_deposit_flow_risk_level": "",
        "cex_deposit_24h_count": 0,
        "cex_deposit_24h_token_amount": 0.0,
        "cex_deposit_24h_max_amount": 0.0,
        "cex_deposit_24h_total_pct_supply": math.nan,
        "cex_deposit_24h_max_pct_supply": math.nan,
        "cex_deposit_24h_target_exchanges": "",
        "cex_deposit_24h_top_tx": "",
        "cex_deposit_24h_source_url": "",
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


def _fmt_pct(value: Any) -> str:
    parsed = _pct_value(value)
    return "n/a" if parsed is None else f"{parsed:.1f}%"


def _fmt_amount(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(parsed) >= divisor:
            return f"{parsed / divisor:.2f}{suffix}"
    return f"{parsed:.2f}"


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
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


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
            amount = _safe_float(row.get(amount_col))
            if amount is None or amount <= 0:
                continue
            parsed.append(
                {
                    "tx": _clean_text(row.get(tx_col)),
                    "age_hours": age_hours,
                    "from": from_text,
                    "to": to_text,
                    "exchange": exchange,
                    "amount": amount,
                }
            )
    parsed.sort(key=lambda item: (-float(item["amount"]), float(item["age_hours"])))
    return parsed


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
    return max(0.0, min(100.0, score))


def infer_cex_flow_risk_level(row: Mapping[str, Any] | pd.Series) -> str:
    score = _safe_float(_row_value(row, "cex_deposit_flow_score", 0.0)) or 0.0
    count = _safe_float(_row_value(row, "cex_deposit_24h_count", 0.0)) or 0.0
    total_pct = _pct_value(_row_value(row, "cex_deposit_24h_total_pct_supply", math.nan))
    max_pct = _pct_value(_row_value(row, "cex_deposit_24h_max_pct_supply", math.nan))
    total_pct = total_pct or 0.0
    max_pct = max_pct or 0.0
    if score >= 90.0 or total_pct >= 5.0 or max_pct >= 3.0 or count >= 8:
        return "Extreme"
    if score >= 75.0 or total_pct >= 1.0 or max_pct >= 1.0 or count >= 3:
        return "High"
    if score >= 50.0 or count >= 1:
        return "Elevated"
    return "Watch only"


def build_cex_flow_evidence_summary(row: Mapping[str, Any] | pd.Series) -> str:
    count = int(_safe_float(_row_value(row, "cex_deposit_24h_count", 0)) or 0)
    targets = _clean_text(_row_value(row, "cex_deposit_24h_target_exchanges", "")) or "labelled CEX wallets"
    total_amount = _fmt_amount(_row_value(row, "cex_deposit_24h_token_amount", math.nan))
    max_amount = _fmt_amount(_row_value(row, "cex_deposit_24h_max_amount", math.nan))
    gate = _clean_text(_row_value(row, "cex_deposit_concentration_gate", "")) or "concentration gate met"
    total_pct = _pct_value(_row_value(row, "cex_deposit_24h_total_pct_supply", math.nan))
    max_pct = _pct_value(_row_value(row, "cex_deposit_24h_max_pct_supply", math.nan))
    pct_parts: list[str] = []
    if total_pct is not None:
        pct_parts.append(f"total {total_pct:.2f}% of supply")
    if max_pct is not None:
        pct_parts.append(f"largest {max_pct:.2f}% of supply")
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
    pct_text = f" | {total_pct:.2f}% supply" if total_pct is not None else ""
    return f"{symbol} | flow {score:.0f}/100 | {risk} | {count} tx | {targets} | total {total_amount}{pct_text}"


def build_cex_flow_discord_block(row: Mapping[str, Any] | pd.Series, *, max_chars: int = 900) -> str:
    symbol = str(_row_value(row, "symbol", "")).upper().strip() or "UNKNOWN"
    score = _safe_float(_row_value(row, "cex_deposit_flow_score", 0.0)) or 0.0
    risk = _clean_text(_row_value(row, "cex_deposit_flow_risk_level", "")) or infer_cex_flow_risk_level(row)
    evidence = _clean_text(_row_value(row, "cex_deposit_flow_evidence_summary", "")) or build_cex_flow_evidence_summary(row)
    interpretation = _clean_text(_row_value(row, "cex_deposit_flow_interpretation", "")) or build_cex_flow_interpretation(row)
    next_check = _clean_text(_row_value(row, "cex_deposit_flow_next_check", "")) or build_cex_flow_next_check(row)
    source_url = _clean_text(_row_value(row, "cex_deposit_24h_source_url", ""))
    lines = [
        f"/{symbol}",
        f"CEX Flow Score: {score:.0f}/100 | Risk: {risk}",
        f"Evidence: {evidence}",
        f"Venue-flow read: {interpretation}",
        f"Next check: {next_check}",
    ]
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


def scan_cex_deposit_flow(
    row: Mapping[str, Any],
    *,
    hints_path: Path | None = None,
    timeout: int = 12,
    max_holders: int = 100,
    lookback_hours: int = 24,
    min_transfer_tokens: float = 500_000.0,
    min_top10_pct: float = 80.0,
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
        result["cex_deposit_flow_note"] = f"concentration gate not met ({gate_text}); recent CEX deposits not scored."
        result["cex_deposit_flow_risk_level"] = infer_cex_flow_risk_level(result)
        result["cex_deposit_flow_evidence_summary"] = build_cex_flow_evidence_summary(result)
        result["cex_deposit_flow_interpretation"] = build_cex_flow_interpretation(result)
        result["cex_deposit_flow_next_check"] = build_cex_flow_next_check(result)
        result["cex_deposit_flow_alert_line"] = build_cex_flow_alert_line({"symbol": _row_value(row, "symbol", ""), **result})
        return result

    source_url = build_advanced_filter_url(chain, hint.contract_address, min_amount=min_transfer_tokens)
    result["cex_deposit_24h_source_url"] = source_url
    headers = {"User-Agent": "Mozilla/5.0 (compatible; crypto-market-structure-scanner/1.0)", "Accept": "text/html"}
    try:
        response = requests.get(source_url, headers=headers, timeout=timeout)
    except Exception as exc:
        result["cex_deposit_flow_error"] = f"advanced filter failed: {exc}"
        return result
    if response.status_code != 200:
        result["cex_deposit_flow_error"] = f"advanced filter HTTP {response.status_code}"
        return result

    rows = _read_advanced_filter_rows(response.text, lookback_hours=lookback_hours)
    if not rows:
        result["cex_deposit_flow_note"] = (
            f"concentration gate met ({gate_text}); no large labelled CEX deposits found in last {lookback_hours}h."
        )
        result["cex_deposit_flow_evidence_summary"] = build_cex_flow_evidence_summary(result)
        result["cex_deposit_flow_interpretation"] = build_cex_flow_interpretation(result)
        result["cex_deposit_flow_next_check"] = build_cex_flow_next_check(result)
        result["cex_deposit_flow_risk_level"] = infer_cex_flow_risk_level(result)
        result["cex_deposit_flow_alert_line"] = build_cex_flow_alert_line({"symbol": _row_value(row, "symbol", ""), **result})
        return result

    total_amount = sum(float(item["amount"]) for item in rows)
    max_amount = max(float(item["amount"]) for item in rows)
    total_supply = composition.total_supply if math.isfinite(composition.total_supply) and composition.total_supply > 0 else None
    total_pct_supply = (total_amount / total_supply * 100.0) if total_supply else None
    max_pct_supply = (max_amount / total_supply * 100.0) if total_supply else None
    targets = sorted({str(item["exchange"]) for item in rows if item.get("exchange")})
    score = _flow_score(
        count=len(rows),
        total_pct_supply=total_pct_supply,
        max_pct_supply=max_pct_supply,
        target_count=len(targets),
        top10=top10,
        top100=top100,
    )
    result.update(
        {
            "cex_deposit_flow_score": score,
            "cex_deposit_flow_flag": score > 0.0,
            "cex_deposit_24h_count": len(rows),
            "cex_deposit_24h_token_amount": total_amount,
            "cex_deposit_24h_max_amount": max_amount,
            "cex_deposit_24h_total_pct_supply": total_pct_supply if total_pct_supply is not None else math.nan,
            "cex_deposit_24h_max_pct_supply": max_pct_supply if max_pct_supply is not None else math.nan,
            "cex_deposit_24h_target_exchanges": ", ".join(targets),
            "cex_deposit_24h_top_tx": str(rows[0].get("tx", "")),
            "cex_deposit_flow_note": (
                f"concentration-gated CEX deposit flow: {len(rows)} large transfer(s) into "
                f"{', '.join(targets)} in {lookback_hours}h; {gate_text}; total {_fmt_amount(total_amount)} tokens."
            ),
        }
    )
    result["cex_deposit_flow_risk_level"] = infer_cex_flow_risk_level(result)
    result["cex_deposit_flow_evidence_summary"] = build_cex_flow_evidence_summary(result)
    result["cex_deposit_flow_interpretation"] = build_cex_flow_interpretation(result)
    result["cex_deposit_flow_next_check"] = build_cex_flow_next_check(result)
    result["cex_deposit_flow_alert_line"] = build_cex_flow_alert_line({"symbol": _row_value(row, "symbol", ""), **result})
    return result


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
    min_top10_pct: float = 80.0,
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
