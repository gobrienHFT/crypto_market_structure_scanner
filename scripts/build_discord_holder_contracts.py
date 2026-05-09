from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
APP_DIR = Path(__file__).resolve().parents[1]

CHAIN_BY_ID = {
    1: "ethereum",
    56: "bsc",
    42161: "arbitrum",
    8453: "base",
    137: "polygon",
    10: "optimism",
    43114: "avalanche",
    250: "fantom",
}

CHAIN_PRIORITY = {
    "ethereum": 100,
    "bsc": 96,
    "arbitrum": 92,
    "base": 88,
    "polygon": 82,
    "optimism": 80,
    "avalanche": 75,
    "fantom": 70,
}
NATIVE_OR_WRAPPED_SYMBOLS_TO_SKIP = {
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "XRP",
    "DOGE",
    "ADA",
    "TRX",
    "LTC",
    "BCH",
    "DOT",
    "AVAX",
    "ATOM",
    "TON",
    "KAVA",
    "SUI",
    "APT",
    "NEAR",
    "FIL",
    "ETC",
    "XLM",
    "ALGO",
    "HBAR",
    "ICP",
}

STATIC_TOKEN_LISTS = [
    ("coingecko_static_ethereum", "https://tokens.coingecko.com/uniswap/all.json", 1, 45),
    ("coingecko_static_bsc", "https://tokens.coingecko.com/binance-smart-chain/all.json", 56, 43),
    ("coingecko_static_arbitrum", "https://tokens.coingecko.com/arbitrum-one/all.json", 42161, 42),
    ("coingecko_static_base", "https://tokens.coingecko.com/base/all.json", 8453, 41),
    ("coingecko_static_polygon", "https://tokens.coingecko.com/polygon-pos/all.json", 137, 39),
    ("coingecko_static_optimism", "https://tokens.coingecko.com/optimistic-ethereum/all.json", 10, 38),
    ("coingecko_static_avalanche", "https://tokens.coingecko.com/avalanche/all.json", 43114, 34),
    ("coingecko_static_fantom", "https://tokens.coingecko.com/fantom/all.json", 250, 32),
    ("uniswap", "https://tokens.uniswap.org/", None, 50),
    ("pancakeswap", "https://tokens.pancakeswap.finance/pancakeswap-extended.json", None, 47),
    ("trustwallet_ethereum", "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/ethereum/tokenlist.json", 1, 44),
    ("trustwallet_bsc", "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/smartchain/tokenlist.json", 56, 44),
    ("trustwallet_arbitrum", "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/arbitrum/tokenlist.json", 42161, 44),
    ("trustwallet_base", "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/base/tokenlist.json", 8453, 44),
    ("trustwallet_polygon", "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/polygon/tokenlist.json", 137, 44),
    ("trustwallet_optimism", "https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/optimism/tokenlist.json", 10, 44),
]

ONE_INCH_CHAIN_IDS = (1, 56, 42161, 8453, 137, 10, 43114, 250)
USER_HINTS = [
    ("CHIPUSDT", "arbitrum", "0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e", "user_hint", "Chip", 10_000),
    ("CHIP", "arbitrum", "0x0C1c1C109FE34733fca54b82d7B46B75CFb71F6e", "user_hint", "Chip", 10_000),
]


@dataclass(frozen=True)
class ContractRow:
    symbol: str
    chain: str
    contract_address: str
    name: str
    source: str
    priority: int
    binance_perp: bool = False


def _clean_symbol(value: Any) -> str:
    symbol = str(value or "").upper().strip()
    symbol = re.sub(r"[^A-Z0-9]", "", symbol)
    return symbol[:32]


def _chain_from_token(token: dict[str, Any], fallback_chain_id: int | None) -> str:
    chain_id = token.get("chainId", fallback_chain_id)
    try:
        return CHAIN_BY_ID.get(int(chain_id), "")
    except Exception:
        return ""


def _valid_address(value: Any) -> str:
    text = str(value or "").strip()
    match = ADDRESS_RE.fullmatch(text)
    if not match:
        return ""
    address = match.group(0)
    lowered = address.lower()
    if lowered in {"0x0000000000000000000000000000000000000000", "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"}:
        return ""
    return address


def _fetch_json(session: requests.Session, url: str) -> Any:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def _extract_token_list_rows(
    payload: Any,
    *,
    source: str,
    fallback_chain_id: int | None,
    priority: int,
    binance_bases: set[str],
) -> list[ContractRow]:
    tokens: list[dict[str, Any]]
    if isinstance(payload, dict) and isinstance(payload.get("tokens"), list):
        tokens = [item for item in payload["tokens"] if isinstance(item, dict)]
    elif isinstance(payload, dict):
        tokens = [item for item in payload.values() if isinstance(item, dict)]
    else:
        return []

    rows: list[ContractRow] = []
    for token in tokens:
        symbol = _clean_symbol(token.get("symbol"))
        if symbol in NATIVE_OR_WRAPPED_SYMBOLS_TO_SKIP:
            continue
        chain = _chain_from_token(token, fallback_chain_id)
        address = _valid_address(token.get("address"))
        if not symbol or not chain or not address:
            continue
        is_perp = symbol in binance_bases
        source_priority = priority + (500 if is_perp else 0) + CHAIN_PRIORITY.get(chain, 0)
        rows.append(
            ContractRow(
                symbol=symbol,
                chain=chain,
                contract_address=address,
                name=str(token.get("name") or "").strip(),
                source=source,
                priority=source_priority,
                binance_perp=is_perp,
            )
        )
        if is_perp:
            rows.append(
                ContractRow(
                    symbol=f"{symbol}USDT",
                    chain=chain,
                    contract_address=address,
                    name=str(token.get("name") or "").strip(),
                    source=source,
                    priority=source_priority + 5,
                    binance_perp=True,
                )
            )
    return rows


def _binance_perp_bases(session: requests.Session) -> set[str]:
    try:
        payload = _fetch_json(session, "https://fapi.binance.com/fapi/v1/exchangeInfo")
    except Exception:
        return set()
    bases: set[str] = set()
    for item in payload.get("symbols", []):
        if not isinstance(item, dict):
            continue
        if item.get("contractType") != "PERPETUAL" or item.get("quoteAsset") != "USDT":
            continue
        base = _clean_symbol(item.get("baseAsset"))
        if base:
            bases.add(base)
    return bases


def collect_contract_rows(*, include_static_coingecko: bool = True) -> list[ContractRow]:
    session = requests.Session()
    session.headers.update({"User-Agent": "crypto-market-structure-scanner-contract-builder/1.0"})
    binance_bases = _binance_perp_bases(session)
    rows: list[ContractRow] = [
        ContractRow(symbol, chain, contract, name, source, priority, symbol.replace("USDT", "") in binance_bases)
        for symbol, chain, contract, source, name, priority in USER_HINTS
    ]

    for chain_id in ONE_INCH_CHAIN_IDS:
        url = f"https://tokens.1inch.io/v1.2/{chain_id}"
        try:
            payload = _fetch_json(session, url)
        except Exception as exc:
            print(f"Skipping 1inch {chain_id}: {exc}")
            continue
        rows.extend(
            _extract_token_list_rows(
                payload,
                source=f"1inch_{chain_id}",
                fallback_chain_id=chain_id,
                priority=52,
                binance_bases=binance_bases,
            )
        )

    for source, url, fallback_chain_id, priority in STATIC_TOKEN_LISTS:
        if source.startswith("coingecko_static") and not include_static_coingecko:
            continue
        try:
            payload = _fetch_json(session, url)
        except Exception as exc:
            print(f"Skipping {source}: {exc}")
            continue
        rows.extend(
            _extract_token_list_rows(
                payload,
                source=source,
                fallback_chain_id=fallback_chain_id,
                priority=priority,
                binance_bases=binance_bases,
            )
        )
    return rows


def choose_primary_rows(rows: list[ContractRow], *, limit: int) -> list[ContractRow]:
    by_symbol: dict[str, ContractRow] = {}
    for row in sorted(rows, key=lambda item: (item.priority, item.binance_perp, item.symbol), reverse=True):
        if row.symbol not in by_symbol:
            by_symbol[row.symbol] = row
    chosen = list(by_symbol.values())
    chosen.sort(key=lambda item: (item.binance_perp, item.priority, item.symbol), reverse=True)
    return chosen[:limit] if limit > 0 else chosen


def write_primary_csv(path: Path, rows: list[ContractRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "chain", "contract_address"])
        for row in rows:
            writer.writerow([row.symbol, row.chain, row.contract_address])


def write_spreadsheet_safe_csv(path: Path, rows: list[ContractRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "chain", "contract_address"])
        for row in rows:
            writer.writerow([row.symbol, row.chain, f'="{row.contract_address}"'])


def write_full_csv(path: Path, rows: list[ContractRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    deduped: dict[tuple[str, str, str], ContractRow] = {}
    for row in rows:
        key = (row.symbol, row.chain, row.contract_address.lower())
        current = deduped.get(key)
        if current is None or row.priority > current.priority:
            deduped[key] = row
    ordered = sorted(deduped.values(), key=lambda item: (item.binance_perp, item.priority, item.symbol), reverse=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "chain", "contract_address", "name", "source", "binance_perp", "priority"])
        for row in ordered:
            writer.writerow([row.symbol, row.chain, row.contract_address, row.name, row.source, int(row.binance_perp), row.priority])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local Discord holder contract hint spreadsheets from no-key public token lists.")
    parser.add_argument("--output", default=str(APP_DIR / "data" / "discord_holder_contracts.csv"))
    parser.add_argument("--full-output", default=str(APP_DIR / "data" / "discord_holder_contracts_full.csv"))
    parser.add_argument("--sheets-output", default=str(APP_DIR / "data" / "discord_holder_contracts_spreadsheet_safe.csv"))
    parser.add_argument("--limit", type=int, default=6000, help="Primary one-contract-per-symbol row limit. Use 0 for all.")
    parser.add_argument("--exclude-coingecko-tokenlists", action="store_true", help="Skip static tokens.coingecko.com token lists.")
    args = parser.parse_args()

    rows = collect_contract_rows(include_static_coingecko=not args.exclude_coingecko_tokenlists)
    primary = choose_primary_rows(rows, limit=args.limit)
    write_primary_csv(Path(args.output), primary)
    write_spreadsheet_safe_csv(Path(args.sheets_output), primary)
    write_full_csv(Path(args.full_output), rows)
    perp_count = sum(1 for row in primary if row.binance_perp)
    print(f"Wrote {len(primary):,} primary contract hints to {args.output} ({perp_count:,} Binance perp symbol matches).")
    print(f"Wrote spreadsheet-safe contract hints to {args.sheets_output}.")
    print(f"Wrote expanded source/audit list to {args.full_output}.")


if __name__ == "__main__":
    main()
