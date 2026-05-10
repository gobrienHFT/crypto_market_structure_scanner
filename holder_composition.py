from __future__ import annotations

import csv
import html
import math
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

import pandas as pd
import requests


ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
ROW_RE = re.compile(r"<tr><td>\s*(\d+)\s*</td>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
NUMERIC_TITLE_PERCENT_RE = re.compile(
    r"<td><span[^>]+title=['\"]([0-9][0-9,\.]*)['\"][^>]*>.*?</span></td>\s*<td>\s*([0-9][0-9,\.]*)%",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ChainConfig:
    key: str
    aliases: tuple[str, ...]
    name: str
    chain_id: str
    explorer_name: str
    explorer_base_url: str
    rpc_url: str


CHAIN_CONFIGS: dict[str, ChainConfig] = {
    "ethereum": ChainConfig(
        key="ethereum",
        aliases=("eth", "ethereum mainnet"),
        name="Ethereum",
        chain_id="1",
        explorer_name="Etherscan",
        explorer_base_url="https://etherscan.io",
        rpc_url="https://ethereum-rpc.publicnode.com",
    ),
    "bsc": ChainConfig(
        key="bsc",
        aliases=("bnb", "bnb chain", "binance-smart-chain", "bscscan"),
        name="BNB Chain",
        chain_id="56",
        explorer_name="BscScan",
        explorer_base_url="https://bscscan.com",
        rpc_url="https://bsc-dataseed.binance.org",
    ),
    "arbitrum": ChainConfig(
        key="arbitrum",
        aliases=("arb", "arbitrum-one", "arbiscan"),
        name="Arbitrum",
        chain_id="42161",
        explorer_name="Arbiscan",
        explorer_base_url="https://arbiscan.io",
        rpc_url="https://arb1.arbitrum.io/rpc",
    ),
    "base": ChainConfig(
        key="base",
        aliases=("base-mainnet", "basescan"),
        name="Base",
        chain_id="8453",
        explorer_name="BaseScan",
        explorer_base_url="https://basescan.org",
        rpc_url="https://mainnet.base.org",
    ),
    "polygon": ChainConfig(
        key="polygon",
        aliases=("polygon-pos", "polygonscan"),
        name="Polygon",
        chain_id="137",
        explorer_name="PolygonScan",
        explorer_base_url="https://polygonscan.com",
        rpc_url="https://polygon-rpc.com",
    ),
    "optimism": ChainConfig(
        key="optimism",
        aliases=("optimistic-ethereum", "optimistic etherscan", "optimistic-etherscan"),
        name="Optimism",
        chain_id="10",
        explorer_name="Optimistic Etherscan",
        explorer_base_url="https://optimistic.etherscan.io",
        rpc_url="https://mainnet.optimism.io",
    ),
}


CHAIN_ALIASES: dict[str, str] = {}
for _config in CHAIN_CONFIGS.values():
    CHAIN_ALIASES[_config.key] = _config.key
    for _alias in _config.aliases:
        CHAIN_ALIASES[_alias] = _config.key


BUILT_IN_CONTRACT_HINTS: dict[str, tuple[str, str]] = {
    # Public contract supplied by the user for the CHIP Convex workflow.
    "CHIP": ("arbitrum", "0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e"),
    "CHIPUSDT": ("arbitrum", "0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e"),
}


@dataclass(frozen=True)
class ContractHint:
    symbol: str
    chain: str
    contract_address: str
    source: str = ""


@dataclass
class HolderRow:
    rank: int
    address: str
    percent: float = float("nan")
    balance: float = float("nan")
    label: str = ""
    category: str = ""
    is_contract: bool = False
    is_locked: bool = False
    value_usd: str = ""


@dataclass
class HolderComposition:
    symbol: str
    chain: str
    contract_address: str
    explorer_name: str = ""
    explorer_url: str = ""
    source: str = ""
    token_name: str = ""
    token_symbol: str = ""
    holder_count: float = float("nan")
    total_supply: float = float("nan")
    top_holders: list[HolderRow] = field(default_factory=list)
    tier_rows: list[dict[str, Any]] = field(default_factory=list)
    cohort_rows: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def top_pct(self, n: int) -> float:
        values = [holder.percent for holder in self.top_holders[:n] if _is_finite(holder.percent)]
        return sum(values) if values else float("nan")

    @property
    def observed_top_pct(self) -> float:
        values = [holder.percent for holder in self.top_holders if _is_finite(holder.percent)]
        return sum(values) if values else float("nan")


def normalize_chain(chain: str) -> str:
    value = str(chain or "").strip().lower()
    return CHAIN_ALIASES.get(value, value)


def _candidate_symbols(row: Mapping[str, Any]) -> list[str]:
    symbols: list[str] = []
    for key in ("symbol", "base_asset", "token_symbol"):
        value = str(row.get(key, "") or "").upper().strip()
        if value:
            symbols.append(value)
            if value.endswith("USDT"):
                symbols.append(value[:-4])
    for symbol in list(symbols):
        for prefix in ("1000000", "100000", "10000", "1000"):
            if symbol.startswith(prefix) and len(symbol) > len(prefix):
                symbols.append(symbol[len(prefix) :])
        if symbol.startswith("1M") and len(symbol) > 2:
            symbols.append(symbol[2:])
    return list(dict.fromkeys(symbols))


def _first_text(row: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none", "null"}:
            return text
    return ""


def clean_contract_address(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.strip().strip('"').strip()
    if text.startswith("="):
        text = text[1:].strip().strip('"').strip("'").strip()
    if text.startswith("'"):
        text = text[1:].strip()
    match = ADDRESS_RE.search(text)
    return match.group(0) if match else ""


def _parse_contract_hints_env(raw: str) -> dict[str, ContractHint]:
    hints: dict[str, ContractHint] = {}
    for chunk in re.split(r"[;\n]+", raw or ""):
        item = chunk.strip()
        if not item:
            continue
        if "=" in item:
            symbol, rest = item.split("=", 1)
            parts = [symbol.strip(), *[part.strip() for part in rest.split(":")]]
        else:
            parts = [part.strip() for part in item.split(":")]
        if len(parts) < 3:
            continue
        symbol, chain, contract = parts[0].upper(), normalize_chain(parts[1]), clean_contract_address(parts[2])
        if ADDRESS_RE.fullmatch(contract):
            hints[symbol] = ContractHint(symbol=symbol, chain=chain, contract_address=contract, source="env")
    return hints


def _parse_contract_hints_file(path: Path | None) -> dict[str, ContractHint]:
    if path is None or not path.exists():
        return {}
    hints: dict[str, ContractHint] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            has_header = "symbol" in sample.lower() and "contract" in sample.lower()
            reader = csv.DictReader(handle) if has_header else csv.reader(handle)
            if isinstance(reader, csv.DictReader):
                for row in reader:
                    symbol = str(row.get("symbol") or row.get("base_asset") or "").upper().strip()
                    chain = normalize_chain(str(row.get("chain") or row.get("platform") or ""))
                    contract = clean_contract_address(row.get("contract_address") or row.get("contract") or "")
                    if symbol and chain and ADDRESS_RE.fullmatch(contract):
                        hints[symbol] = ContractHint(symbol, chain, contract, source=str(path))
            else:
                for row in reader:
                    if len(row) < 3:
                        continue
                    symbol, chain, contract = row[0].upper().strip(), normalize_chain(row[1]), clean_contract_address(row[2])
                    if symbol and chain and ADDRESS_RE.fullmatch(contract):
                        hints[symbol] = ContractHint(symbol, chain, contract, source=str(path))
    except Exception:
        return hints
    return hints


def load_contract_hints(path: Path | None = None) -> dict[str, ContractHint]:
    hints = {
        symbol: ContractHint(symbol=symbol, chain=chain, contract_address=contract, source="built-in")
        for symbol, (chain, contract) in BUILT_IN_CONTRACT_HINTS.items()
    }
    hints.update(_parse_contract_hints_file(path))
    hints.update(_parse_contract_hints_env(os.environ.get("DISCORD_HOLDER_CONTRACTS", "")))
    return hints


def resolve_contract_hint(row: Mapping[str, Any], *, hints_path: Path | None = None) -> ContractHint | None:
    hints = load_contract_hints(hints_path)
    for candidate_symbol in _candidate_symbols(row):
        hint = hints.get(candidate_symbol)
        if hint:
            return hint

    contract = clean_contract_address(_first_text(row, ("token_contract", "contract_address", "contract")))
    chain = normalize_chain(_first_text(row, ("token_platform", "chain", "token_chain")))
    symbol = _candidate_symbols(row)[0] if _candidate_symbols(row) else ""
    if ADDRESS_RE.fullmatch(contract) and chain:
        return ContractHint(symbol=symbol, chain=chain, contract_address=contract, source="scan row")

    return None


def _to_float(value: Any) -> float:
    if value in (None, ""):
        return float("nan")
    try:
        parsed = float(str(value).replace(",", "").replace("$", "").replace("%", "").strip())
    except Exception:
        return float("nan")
    return parsed if math.isfinite(parsed) else float("nan")


def _is_finite(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _percent_from_ratio(value: Any) -> float:
    parsed = _to_float(value)
    if not _is_finite(parsed):
        return float("nan")
    return parsed * 100.0 if parsed <= 1.0 else parsed


def _decimal_from_floatish(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _short_address(address: str) -> str:
    if not address:
        return "unknown"
    return f"{address[:6]}...{address[-4:]}" if len(address) > 14 else address


def _format_pct(value: float, decimals: int = 1) -> str:
    if not _is_finite(value):
        return "n/a"
    return f"{float(value):.{decimals}f}%"


def _format_count(value: float) -> str:
    if not _is_finite(value):
        return "n/a"
    return f"{int(float(value)):,}"


def _format_number(value: float) -> str:
    if not _is_finite(value):
        return "n/a"
    value = float(value)
    for suffix, divisor in (("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(value) >= divisor:
            return f"{value / divisor:.2f}{suffix}"
    return f"{value:.2f}"


def _rpc_uint(chain: str, contract: str, selector: str, *, timeout: int) -> int | None:
    config = CHAIN_CONFIGS.get(normalize_chain(chain))
    if config is None or not config.rpc_url:
        return None
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": contract, "data": selector}, "latest"]}
    try:
        response = requests.post(config.rpc_url, json=payload, timeout=timeout)
        if response.status_code != 200:
            return None
        result = response.json().get("result")
        if not result or result == "0x":
            return None
        return int(result, 16)
    except Exception:
        return None


def _fetch_goplus_security(chain: str, contract: str, *, timeout: int) -> dict[str, Any]:
    config = CHAIN_CONFIGS.get(normalize_chain(chain))
    if config is None or not config.chain_id:
        return {}
    try:
        response = requests.get(
            f"https://api.gopluslabs.io/api/v1/token_security/{config.chain_id}",
            params={"contract_addresses": contract},
            headers={"User-Agent": "crypto-market-structure-scanner/1.0", "Accept": "application/json"},
            timeout=timeout,
        )
        if response.status_code != 200:
            return {}
        result = response.json().get("result", {})
        if not isinstance(result, dict):
            return {}
        token = result.get(contract.lower()) or result.get(contract)
        return token if isinstance(token, dict) else {}
    except Exception:
        return {}


def _goplus_holder_rows(token: Mapping[str, Any]) -> list[HolderRow]:
    rows: list[HolderRow] = []
    holders = token.get("holders")
    if not isinstance(holders, list):
        return rows
    for index, item in enumerate(holders, start=1):
        if not isinstance(item, Mapping):
            continue
        address = str(item.get("address") or "").strip()
        if not ADDRESS_RE.fullmatch(address):
            continue
        rows.append(
            HolderRow(
                rank=index,
                address=address,
                percent=_percent_from_ratio(item.get("percent")),
                balance=_to_float(item.get("balance")),
                label=str(item.get("tag") or "").strip(),
                is_contract=str(item.get("is_contract", "0")) in {"1", "true", "True"},
                is_locked=str(item.get("is_locked", "0")) in {"1", "true", "True"},
            )
        )
    return rows


def _explorer_generic_url(config: ChainConfig, contract: str, *, raw_supply: int | None, page: int) -> str:
    params: dict[str, Any] = {"a": contract, "p": page}
    if raw_supply is not None and raw_supply > 0:
        params["s"] = str(raw_supply)
    return f"{config.explorer_base_url.rstrip('/')}/token/generic-tokenholders2?{urlencode(params)}"


def _clean_html_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return " ".join(text.split())


def _extract_label(row_html: str) -> tuple[str, str]:
    category = ""
    category_match = re.search(r"data-bs-title=['\"]([^'\"]+)['\"]", row_html)
    if category_match:
        category = html.unescape(category_match.group(1)).strip()

    label = ""
    title_match = re.search(r"title=['\"]([^'\"]*?)&#10;\(0x[a-fA-F0-9]{40}\)['\"]", row_html)
    if title_match:
        label = html.unescape(title_match.group(1)).strip()
    if not label:
        link_labels = re.findall(r"<a[^>]*>(.*?)</a>", row_html, flags=re.IGNORECASE | re.DOTALL)
        for raw_label in link_labels:
            text = _clean_html_text(raw_label)
            if text and not ADDRESS_RE.search(text) and "..." not in text:
                label = text
                break
    return label, category


def _parse_holder_rows_from_html(text: str, *, total_supply: float | None = None) -> list[HolderRow]:
    rows: list[HolderRow] = []
    total = Decimal(str(total_supply)) if total_supply is not None and _is_finite(float(total_supply)) and total_supply > 0 else None
    for rank_text, row_html in ROW_RE.findall(text):
        address_match = re.search(r"data-clipboard-text=['\"](0x[a-fA-F0-9]{40})['\"]", row_html)
        if not address_match:
            address_match = ADDRESS_RE.search(row_html)
        if not address_match:
            continue
        address = address_match.group(1) if address_match.lastindex else address_match.group(0)
        quantity_match = NUMERIC_TITLE_PERCENT_RE.search(row_html)
        balance = _to_float(quantity_match.group(1)) if quantity_match else float("nan")
        percent = _to_float(quantity_match.group(2)) if quantity_match else float("nan")
        if (not _is_finite(percent) or percent == 0.0 or percent > 100.0) and total is not None and _is_finite(balance):
            balance_decimal = _decimal_from_floatish(balance)
            if balance_decimal is not None and total > 0:
                percent = float(balance_decimal / total * Decimal("100"))
        label, category = _extract_label(row_html)
        value_match = re.search(r"</div></td><td>\s*\$([^<]+)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)
        rows.append(
            HolderRow(
                rank=int(rank_text),
                address=address,
                percent=percent,
                balance=balance,
                label=label,
                category=category,
                value_usd=f"${value_match.group(1).strip()}" if value_match else "",
            )
        )
    return rows


def _read_tables_from_html(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tier_rows: list[dict[str, Any]] = []
    cohort_rows: list[dict[str, Any]] = []
    try:
        tables = pd.read_html(StringIO(text))
    except Exception:
        return tier_rows, cohort_rows
    for frame in tables:
        columns = {str(column).strip().lower(): column for column in frame.columns}
        if "tier" in columns and "% market cap" in columns:
            for _, row in frame.iterrows():
                tier = str(row.get(columns["tier"], "")).strip()
                pct = _to_float(row.get(columns["% market cap"]))
                count = _to_float(row.get(columns.get("holder count", ""), ""))
                if tier:
                    tier_rows.append({"tier": tier, "pct": pct, "holder_count": count})
        if "cohort" in columns and "% market cap" in columns:
            for _, row in frame.iterrows():
                cohort = str(row.get(columns["cohort"], "")).strip()
                pct = _to_float(row.get(columns["% market cap"]))
                if cohort:
                    cohort_rows.append({"cohort": cohort, "pct": pct})
    return tier_rows, cohort_rows


def _fetch_explorer_holders(
    chain: str,
    contract: str,
    *,
    raw_supply: int | None,
    total_supply: float | None,
    timeout: int,
    pages: int,
) -> tuple[list[HolderRow], list[dict[str, Any]], list[dict[str, Any]], str]:
    config = CHAIN_CONFIGS.get(normalize_chain(chain))
    if config is None:
        return [], [], [], ""
    rows_by_rank: dict[int, HolderRow] = {}
    tier_rows: list[dict[str, Any]] = []
    cohort_rows: list[dict[str, Any]] = []
    source = ""
    headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
    for page in range(1, max(1, pages) + 1):
        url = _explorer_generic_url(config, contract, raw_supply=raw_supply, page=page)
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
        except Exception:
            continue
        if response.status_code != 200 or "<table" not in response.text:
            continue
        parsed_rows = _parse_holder_rows_from_html(response.text, total_supply=total_supply)
        for row in parsed_rows:
            rows_by_rank[row.rank] = row
        if page == 1:
            tier_rows, cohort_rows = _read_tables_from_html(response.text)
        source = f"{config.explorer_name} holder endpoint"
    return [rows_by_rank[key] for key in sorted(rows_by_rank)], tier_rows, cohort_rows, source


def fetch_holder_composition(
    row: Mapping[str, Any],
    *,
    hints_path: Path | None = None,
    timeout: int = 12,
    max_holders: int = 100,
) -> HolderComposition:
    symbol = _candidate_symbols(row)[0] if _candidate_symbols(row) else "UNKNOWN"
    hint = resolve_contract_hint(row, hints_path=hints_path)
    if hint is None:
        return HolderComposition(symbol=symbol, chain="", contract_address="", error="no contract hint")

    chain = normalize_chain(hint.chain)
    config = CHAIN_CONFIGS.get(chain)
    if config is None:
        return HolderComposition(symbol=symbol, chain=chain, contract_address=hint.contract_address, error=f"unsupported chain {hint.chain}")

    token = _fetch_goplus_security(chain, hint.contract_address, timeout=timeout)
    goplus_rows = _goplus_holder_rows(token)
    holder_count = _to_float(token.get("holder_count"))
    total_supply = _to_float(token.get("total_supply"))
    token_symbol = str(token.get("token_symbol") or "").upper()
    token_name = str(token.get("token_name") or "")

    decimals = _rpc_uint(chain, hint.contract_address, "0x313ce567", timeout=timeout)
    raw_supply = _rpc_uint(chain, hint.contract_address, "0x18160ddd", timeout=timeout)
    if (not _is_finite(total_supply) or total_supply <= 0) and raw_supply is not None and decimals is not None:
        total_supply = raw_supply / (10**decimals)

    pages = max(1, math.ceil(max_holders / 50))
    explorer_rows, tier_rows, cohort_rows, explorer_source = _fetch_explorer_holders(
        chain,
        hint.contract_address,
        raw_supply=raw_supply,
        total_supply=total_supply if _is_finite(total_supply) else None,
        timeout=timeout,
        pages=pages,
    )
    top_holders = explorer_rows[:max_holders] if explorer_rows else goplus_rows[:max_holders]
    source_parts = [part for part in (explorer_source, "GoPlus token security" if token else "", hint.source) if part]
    return HolderComposition(
        symbol=symbol,
        chain=chain,
        contract_address=hint.contract_address,
        explorer_name=config.explorer_name,
        explorer_url=f"{config.explorer_base_url.rstrip('/')}/token/{hint.contract_address}",
        source=" + ".join(dict.fromkeys(source_parts)) or "contract hint",
        token_name=token_name,
        token_symbol=token_symbol,
        holder_count=holder_count,
        total_supply=total_supply,
        top_holders=top_holders,
        tier_rows=tier_rows,
        cohort_rows=cohort_rows,
    )


def _bucket_rows(rows: list[HolderRow]) -> dict[str, tuple[int, float]]:
    buckets = {
        "Whales >=10%": [row for row in rows if _is_finite(row.percent) and row.percent >= 10.0],
        "Sharks 1-10%": [row for row in rows if _is_finite(row.percent) and 1.0 <= row.percent < 10.0],
        "Dolphins 0.1-1%": [row for row in rows if _is_finite(row.percent) and 0.1 <= row.percent < 1.0],
        "Shrimps <0.1%": [row for row in rows if _is_finite(row.percent) and row.percent < 0.1],
    }
    return {name: (len(items), sum(row.percent for row in items)) for name, items in buckets.items()}


def _tier_line(tier_rows: list[dict[str, Any]]) -> str:
    if not tier_rows:
        return ""
    preferred = []
    for name in ("Whale", "Shark", "Dolphin", "Fish", "Crab", "Shrimp"):
        match = next((row for row in tier_rows if name.lower() in str(row.get("tier", "")).lower()), None)
        if match is not None and _is_finite(match.get("pct", float("nan"))):
            preferred.append(f"{name} {_format_pct(float(match['pct']))}")
    return "Tiers: " + " | ".join(preferred[:5]) if preferred else ""


def _bucket_line(rows: list[HolderRow]) -> str:
    buckets = _bucket_rows(rows)
    parts = []
    for name in ("Whales >=10%", "Sharks 1-10%", "Dolphins 0.1-1%", "Shrimps <0.1%"):
        count, pct = buckets[name]
        if count:
            short = name.split()[0].lower()
            parts.append(f"{short} {count}/{_format_pct(pct)}")
    return "Buckets: " + " | ".join(parts[:4]) if parts else ""


def format_holder_composition_for_discord(
    composition: HolderComposition,
    *,
    include_top_holders: int = 3,
    max_chars: int = 900,
) -> str:
    if composition.error:
        return f"Holder composition: {composition.error}."
    if not composition.top_holders and not composition.tier_rows:
        return "Holder composition: no holder rows returned yet."

    observed_n = len(composition.top_holders)
    lines = [
        f"Holder composition ({composition.explorer_name}, {composition.chain})",
        (
            f"Top1 {_format_pct(composition.top_pct(1), 2)} | "
            f"Top5 {_format_pct(composition.top_pct(5), 2)} | "
            f"Top10 {_format_pct(composition.top_pct(10), 2)} | "
            f"Top{observed_n} {_format_pct(composition.observed_top_pct, 2)}"
        ),
    ]
    meta = []
    if _is_finite(composition.holder_count):
        meta.append(f"holders {_format_count(composition.holder_count)}")
    if _is_finite(composition.total_supply):
        meta.append(f"supply {_format_number(composition.total_supply)}")
    if meta:
        lines.append(" | ".join(meta))
    tier_text = _tier_line(composition.tier_rows)
    lines.append(tier_text or _bucket_line(composition.top_holders))
    if include_top_holders > 0 and composition.top_holders:
        holder_bits = []
        for holder in composition.top_holders[:include_top_holders]:
            label = f" {holder.label}" if holder.label else ""
            category = f" [{holder.category}]" if holder.category else ""
            holder_bits.append(f"#{holder.rank} {_short_address(holder.address)}{label}{category} {_format_pct(holder.percent, 2)}")
        lines.append("Top: " + "; ".join(holder_bits))
    if composition.explorer_url:
        lines.append(composition.explorer_url)
    text = "\n".join(line for line in lines if line)
    return text if len(text) <= max_chars else f"{text[: max_chars - 3]}..."
