from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from archetype_scoring import apply_archetype_model
from binance_futures import BinanceFuturesPublic
from cex_flow_scanner import (
    TOKEN_TRANSFER_API_CONFIGS,
    build_cex_flow_discord_block,
    is_qualified_whale_sender,
    load_cex_address_book,
    token_transfer_api_key_envs,
)
from discord_flag_formatter import (
    DISCORD_EMBED_DESCRIPTION_LIMIT,
    DISCORD_FOOTER,
    DISCORD_PRODUCT_IDENTITY,
    build_discord_flag_card,
    infer_evidence_stack,
    infer_next_check,
    join_discord_flag_cards,
)
from early_pump_radar import apply_early_pump_radar
from historical_examples import exemplar_for_archetype
from holder_composition import (
    clean_contract_address,
    fetch_holder_composition,
    format_holder_composition_for_discord,
    load_contract_hints,
    normalize_chain,
    resolve_contract_hint,
)
from market_structure_scoring import apply_lifecycle_model
from pre_activity_radar import apply_pre_activity_radar
from proof_engine import proof_archive_path, refresh_outcomes, weekly_scoreboard_text, write_weekly_report
from scan_orchestrator import run_fresh_scan_frame
from short_squeeze_scoring import apply_short_squeeze_model
from terminal_engine import apply_terminal_model, build_setup_dossier
from timing_engine import apply_timing_model, build_timing_card
from trade_setup_pipeline import TradeBotConfig, TradeBotRuntime


APP_DIR = Path(__file__).resolve().parent
SYMBOL_QUERY_RE = re.compile(r"^[!/]?\$?([A-Za-z0-9]{2,30})$")
ACCESS_LEVELS = {"free": 0, "paid": 1, "pro": 2}
COMMON_BREAKOUT_WINDOWS = (5, 20, 90, 180)
MAX_DYNAMIC_BREAKOUT_DAYS = 1499
RAVELAB_HOLDER_EVIDENCE_CHAINS = {"ethereum", "bsc", "arbitrum"}
RAVELAB_HOLDER_EVIDENCE_CHAIN_LABEL = "ETH/BNB/ARB"
THESIS_MIN_TOP10_WHALE_PCT = 90.0
RAVELAB_DEFAULT_WHALE_FLOW_MIN_TOKENS = 100_000.0
HOLDER_EXPLORER_SOURCE_PATTERN = re.compile(
    r"\b(?:etherscan|bscscan|arbiscan|explorer)\b|holder\s+endpoint",
    flags=re.IGNORECASE,
)
STATIC_SLASH_COMMAND_NAMES = (
    "alpha",
    "cexdiag",
    "cexflow",
    "cextargets",
    "coin",
    "coincheck",
    "commands",
    "convex",
    "convex_archive",
    "convex_scoreboard",
    "convex_status",
    "corr",
    "crimepump",
    "dossier",
    "earlyflow",
    "floattrap",
    "flowblocked",
    "flowcoin",
    "flowhealth",
    "flowproof",
    "flowstress",
    "funding",
    "help",
    "high",
    "low",
    "precrime",
    "prime",
    "pumpwatch",
    "radar",
    "ravelab",
    "sethflow",
    "setupscore",
    "shorts",
    "squeezeready",
    "startbot",
    "stopbot",
    "sync_commands",
    "terminal",
    "timing",
    "tradebot_status",
    "whales",
)
RESERVED_SYMBOL_QUERY_COMMANDS = {name.upper() for name in STATIC_SLASH_COMMAND_NAMES} | {"CEX_FLOW", "FUNDINGRATES"}
_TRADE_BOT_TASK: asyncio.Task[Any] | None = None
_TRADE_BOT_RUNTIME: TradeBotRuntime | None = None
_TRADE_BOT_STOP_REQUESTED = False

if os.name == "nt" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _load_local_env() -> None:
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return _env_value(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(str(_env_value(name, str(default))).strip())
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    try:
        parsed = float(str(_env_value(name, str(default))).strip())
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _env_csv_ints(name: str) -> set[int]:
    values: set[int] = set()
    for chunk in re.split(r"[,;\s]+", _env_value(name, "")):
        chunk = chunk.strip()
        if chunk.isdigit():
            values.add(int(chunk))
    return values


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _ravelab_whale_flow_floor(min_transfer_tokens: float, whale_flow_min_tokens: float | None = None) -> float:
    override = _safe_float(whale_flow_min_tokens)
    configured = (
        max(0.0, override)
        if override is not None and override > 0
        else _env_float(
            "DISCORD_RAVELAB_WHALE_FLOW_MIN_TOKENS",
            RAVELAB_DEFAULT_WHALE_FLOW_MIN_TOKENS,
            minimum=0.0,
        )
    )
    return max(0.0, float(min_transfer_tokens or 0.0), configured)


def _safe_pct(value: Any) -> float | None:
    try:
        parsed = float(str(value).replace(",", "").replace("%", "").strip())
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    if parsed != 0.0 and abs(parsed) <= 1.0:
        return parsed * 100.0
    return parsed


def _strict_thesis_min_whale_pct(value: Any = None) -> float:
    parsed = _safe_float(value)
    if parsed is None:
        parsed = THESIS_MIN_TOP10_WHALE_PCT
    return max(THESIS_MIN_TOP10_WHALE_PCT, min(float(parsed), 100.0))


def _safe_holder_pct(value: Any) -> float | None:
    try:
        parsed = float(str(value).replace(",", "").replace("%", "").strip())
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _boolish_series(series: Any, *, index: pd.Index | None = None) -> pd.Series:
    if not isinstance(series, pd.Series):
        if series is None and index is not None:
            series = pd.Series(False, index=index)
        else:
            series = pd.Series(series if series is not None else [])
            if index is not None and len(series) == len(index):
                series.index = index
    return series.astype("object").where(pd.notna(series), False).astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "on"})


def _boolish_scalar(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index)
    series = frame[column].fillna("").astype(str).str.strip()
    return series.where(~series.str.lower().isin({"nan", "none", "null", "<na>"}), "")


def _fmt_compact_number(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(parsed) >= divisor:
            return f"{parsed / divisor:.2f}{suffix}"
    return f"{parsed:.2f}".rstrip("0").rstrip(".")


def _chunk_text_lines(lines: list[str], *, max_chars: int = 1850) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        candidate = "\n".join([*current, line]).strip()
        if current and len(candidate) > max_chars:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    return chunks


def _clean_scalar_text(text: Any) -> str:
    if text is None:
        return ""
    try:
        if pd.isna(text):
            return ""
    except (TypeError, ValueError):
        pass
    clean = " ".join(str(text).split())
    return "" if clean.lower() in {"nan", "none", "null", "<na>"} else clean


def _clip_text(text: Any, max_chars: int) -> str:
    clean = _clean_scalar_text(text)
    if len(clean) <= max_chars:
        return clean
    return f"{clean[: max_chars - 3].rstrip()}..."


def _first_nonempty_text(*values: Any) -> str:
    for value in values:
        clean = _clean_scalar_text(value)
        if clean:
            return clean
    return ""


def _normalize_tier(raw_tier: str) -> str:
    tier = str(raw_tier or "").strip().lower()
    return tier if tier in ACCESS_LEVELS else "pro"


def _tier_rank(tier: str) -> int:
    return ACCESS_LEVELS.get(_normalize_tier(tier), ACCESS_LEVELS["pro"])


def _tier_for_role_ids(role_ids: set[int]) -> str:
    pro_roles = _env_csv_ints("DISCORD_PRO_ROLE_IDS")
    paid_roles = _env_csv_ints("DISCORD_PAID_ROLE_IDS")
    if role_ids & pro_roles:
        return "pro"
    if role_ids & paid_roles:
        return "paid"
    return _normalize_tier(_env_value("DISCORD_DEFAULT_USER_TIER", "pro"))


def _role_ids_from_subject(subject: Any) -> set[int]:
    roles = getattr(subject, "roles", []) or []
    role_ids: set[int] = set()
    for role in roles:
        role_id = getattr(role, "id", None)
        if role_id is not None:
            try:
                role_ids.add(int(role_id))
            except Exception:
                pass
    return role_ids


def _interaction_role_ids(interaction: Any) -> set[int]:
    return _role_ids_from_subject(getattr(interaction, "user", None))


def _interaction_tier(interaction: Any) -> str:
    return _tier_for_role_ids(_interaction_role_ids(interaction))


def _tier_allows(tier: str, required: str) -> bool:
    return _tier_rank(tier) >= _tier_rank(required)


def _feature_required_tier(feature: str) -> str:
    defaults = {
        "convex": "free",
        "commands": "free",
        "help": "free",
        "coin": "paid",
        "scoreboard": "paid",
        "archive": "pro",
        "shortcut": "paid",
        "shorts": "free",
        "whales": "paid",
        "funding": "free",
        "high": "free",
        "low": "free",
        "setupscore": "paid",
        "pumpwatch": "paid",
        "precrime": "paid",
        "ravelab": "paid",
        "radar": "paid",
        "prime": "paid",
        "crimepump": "paid",
        "flowproof": "paid",
        "coincheck": "paid",
        "floattrap": "paid",
        "squeezeready": "paid",
        "cextargets": "paid",
        "terminal": "paid",
        "dossier": "paid",
        "timing": "paid",
        "corr": "paid",
        "cexflow": "paid",
        "cexdiag": "paid",
        "earlyflow": "paid",
        "flowcoin": "paid",
        "flowstress": "paid",
        "flowblocked": "paid",
        "flowhealth": "paid",
        "sethflow": "paid",
        "alpha": "paid",
        "sync_commands": "pro",
        "startbot": "pro",
        "stopbot": "pro",
        "tradebot_status": "pro",
    }
    env_name = f"DISCORD_{feature.upper()}_MIN_TIER"
    return _normalize_tier(_env_value(env_name, defaults.get(feature, "paid")))


def _free_sample_limit() -> int:
    return _env_int("DISCORD_FREE_SAMPLE_TOP_N", 3, minimum=1)


def _access_denied_message(feature: str) -> str:
    required = _feature_required_tier(feature)
    return f"This command is available for {required}+ access in this server."


def _holder_contract_hints_path() -> Path:
    return Path(_env_value("DISCORD_HOLDER_CONTRACTS_FILE", str(APP_DIR / "data" / "discord_holder_contracts.csv")))


def _holder_composition_text(row: pd.Series) -> str:
    if not _env_bool("DISCORD_HOLDER_COMPOSITION_ENABLED", True):
        return ""
    try:
        composition = fetch_holder_composition(
            row.to_dict(),
            hints_path=_holder_contract_hints_path(),
            timeout=_env_int("DISCORD_HOLDER_COMPOSITION_TIMEOUT_SECONDS", 12, minimum=3),
            max_holders=_env_int("DISCORD_HOLDER_COMPOSITION_MAX_HOLDERS", 100, minimum=10),
        )
    except Exception as exc:
        return f"Holder composition unavailable: {exc}"
    if composition.error == "no contract hint" and not _env_bool("DISCORD_HOLDER_COMPOSITION_SHOW_MISSING", False):
        return ""
    return format_holder_composition_for_discord(
        composition,
        include_top_holders=_env_int("DISCORD_HOLDER_COMPOSITION_TOP_HOLDERS", 0, minimum=0),
        max_chars=_env_int("DISCORD_HOLDER_COMPOSITION_MAX_CHARS", 520, minimum=200),
    )


def _cex_flow_scan_diagnostic_lines(
    frame: pd.DataFrame,
    *,
    min_whale_pct: float,
    require_holder_evidence: bool = True,
) -> list[str]:
    if frame.empty:
        return ["Coverage: scan rows 0 | contract hints 0 | CEX-flow attempts 0 | raw flow 0"]

    hints_path = _holder_contract_hints_path()
    hint_count = 0
    precomputed_gate_count = 0
    precomputed_concentration_rows = 0
    holder_evidence_mask, _ = _strict_holder_evidence_masks(frame)
    holder_evidence_count = int(holder_evidence_mask.sum())
    for _, row in frame.iterrows():
        row_dict = row.to_dict()
        try:
            if resolve_contract_hint(row_dict, hints_path=hints_path) is not None:
                hint_count += 1
        except Exception:
            pass

        top10 = _safe_pct(row.get("top10_holder_pct"))
        top100 = _safe_pct(row.get("top100_holder_pct"))
        if top10 is not None or top100 is not None:
            precomputed_concentration_rows += 1
        if top10 is not None and top10 >= float(min_whale_pct):
            precomputed_gate_count += 1

    score = pd.to_numeric(frame.get("cex_deposit_flow_score", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    flag = _boolish_series(frame.get("cex_deposit_flow_flag", pd.Series(False, index=frame.index)), index=frame.index)
    raw_flow_mask = flag | score.gt(0.0)
    gate_text = _text_series(frame, "cex_deposit_concentration_gate")
    note_text = _text_series(frame, "cex_deposit_flow_note")
    error_text = _text_series(frame, "cex_deposit_flow_error")
    source_url = _text_series(frame, "cex_deposit_24h_source_url")
    source_kind = _text_series(frame, "cex_deposit_flow_source")
    attempt_mask = raw_flow_mask | gate_text.ne("") | note_text.ne("") | error_text.ne("") | source_url.ne("")
    no_large_mask = note_text.str.contains("no large labelled CEX deposits", case=False, regex=False)
    gate_not_met_mask = note_text.str.contains("concentration gate not met", case=False, regex=False)
    max_symbols = _env_int("CEX_DEPOSIT_FLOW_MAX_SYMBOLS", 0, minimum=0)
    attempt_count = int(attempt_mask.sum())
    no_large_count = int(no_large_mask.sum())
    gate_not_met_count = int(gate_not_met_mask.sum())
    error_count = int(error_text.ne("").sum())
    raw_flow_count = int(raw_flow_mask.sum())
    http_403_count = int(error_text.str.contains("HTTP 403", case=False, regex=False).sum())

    lines = [
        (
            f"Coverage: scan rows {len(frame)} | contract hints {hint_count} | "
            f"precomputed concentration rows {precomputed_concentration_rows} | observed top10 >= {float(min_whale_pct):.1f}% rows {precomputed_gate_count} | "
            f"holder evidence rows {holder_evidence_count} | strict holder gate pass {int(_strict_cex_holder_gate_mask(frame, min_whale_pct=min_whale_pct, require_holder_evidence=require_holder_evidence).sum())}"
        ),
        (
            f"CEX-flow attempts {attempt_count}"
            f" | no-transfer rows {no_large_count}"
            f" | gate-not-met rows {gate_not_met_count}"
            f" | errors {error_count}"
            f" | raw flow {raw_flow_count}"
        ),
    ]
    if max_symbols > 0 and hint_count > max_symbols:
        lines.append(f"CEX scan cap: top {max_symbols} contract-hinted symbols by priority were scanned.")

    if http_403_count > 0 and http_403_count >= max(1, (error_count + 1) // 2):
        lines.append(
            f"Status: explorer blocked {http_403_count} CEX-flow attempts with HTTP 403; API fallback/label coverage decides whether zero raw flow is conclusive."
        )
    elif raw_flow_count == 0 and attempt_count == 0 and hint_count == 0:
        lines.append("Status: no contract-hinted tokens were available for CEX-flow scanning.")
    elif raw_flow_count == 0 and attempt_count == 0:
        lines.append("Status: no CEX-flow attempts were recorded; check scan mode, CEX-flow enablement, and scan cap settings.")
    elif raw_flow_count == 0 and gate_not_met_count >= attempt_count and attempt_count > 0:
        lines.append("Status: holder concentration gate filtered all attempted tokens before CEX-flow scoring.")
    elif raw_flow_count == 0 and no_large_count > 0 and error_count == 0:
        lines.append("Status: scan reached labelled CEX-transfer checks, but no transfers met the threshold/lookback.")
    elif raw_flow_count > 0:
        lines.append("Status: verified labelled CEX-flow rows exist; venue gate decides whether they appear in `/cexflow`.")

    error_counts = error_text[error_text.ne("")].value_counts().head(3)
    if not error_counts.empty:
        summary = "; ".join(f"{str(error)[:80]} x{int(count)}" for error, count in error_counts.items())
        lines.append(f"Top CEX-flow errors: {summary}")
    source_counts = source_kind[source_kind.ne("")].value_counts().head(4)
    if not source_counts.empty:
        summary = "; ".join(f"{str(source)[:50]} x{int(count)}" for source, count in source_counts.items())
        lines.append(f"CEX-flow source paths: {summary}")
    return lines


def _cex_attempt_amount_text(row: pd.Series, *, min_transfer_tokens: float | None = None) -> str:
    count = int(_safe_float(row.get("cex_deposit_24h_count")) or 0)
    total_amount = _safe_float(row.get("cex_deposit_24h_token_amount"))
    max_amount = _safe_float(row.get("cex_deposit_24h_max_amount"))
    total_pct = _safe_pct(row.get("cex_deposit_24h_total_pct_supply"))
    whale_sender = _whale_sender_text(row, include_amount=True)

    if count > 0 or (total_amount is not None and total_amount > 0):
        parts: list[str] = []
        if count > 0:
            parts.append(f"{count} tx")
        if total_amount is not None and total_amount > 0:
            parts.append(f"total {_fmt_compact_number(total_amount)} tokens")
        if max_amount is not None and max_amount > 0:
            parts.append(f"max {_fmt_compact_number(max_amount)}")
        if total_pct is not None:
            parts.append(f"{total_pct:.2f}% supply")
        if whale_sender:
            parts.append(whale_sender)
        return " | ".join(parts)

    error = _clean_scalar_text(row.get("cex_deposit_flow_error", ""))
    if "no labelled CEX destination matches" in error:
        return "API fallback reached token transfers; no labelled CEX destination matched"
    if error and min_transfer_tokens is not None:
        return f"query floor was >= {_fmt_compact_number(min_transfer_tokens)} tokens; no confirmed CEX transfer parsed"
    if error:
        return "no confirmed CEX transfer parsed"
    return ""


def _whale_sender_text(row: pd.Series, *, include_amount: bool = False) -> str:
    count = int(_safe_float(row.get("cex_deposit_24h_whale_sender_count")) or 0)
    if count <= 0 or not _whale_sender_qualifies(row):
        return ""
    parts = [f"{count} top-holder sender tx"]
    amount = _safe_float(row.get("cex_deposit_24h_whale_sender_token_amount"))
    if include_amount and amount is not None and amount > 0:
        parts.append(f"whale-origin {_fmt_compact_number(amount)}")
    rank = _safe_float(row.get("cex_deposit_24h_top_sender_rank"))
    pct = _safe_holder_pct(row.get("cex_deposit_24h_top_sender_pct"))
    address = _short_contract_text(row.get("cex_deposit_24h_top_sender_address", ""))
    detail: list[str] = []
    if rank is not None and rank > 0:
        detail.append(f"r{int(rank)}")
    if pct is not None:
        detail.append(f"{pct:.1f}%")
    if address:
        detail.append(address)
    if detail:
        parts.append(" ".join(detail))
    return " | ".join(parts)


def _whale_sender_qualifies(row: pd.Series) -> bool:
    count = int(_safe_float(row.get("cex_deposit_24h_whale_sender_count")) or 0)
    if count <= 0:
        return False
    return is_qualified_whale_sender(
        row.get("cex_deposit_24h_top_sender_rank"),
        row.get("cex_deposit_24h_top_sender_pct"),
    )


def _cex_flow_attempt_symbol_lines(
    frame: pd.DataFrame,
    *,
    limit: int = 15,
    min_transfer_tokens: float | None = None,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
) -> list[str]:
    if frame.empty:
        return []

    score = pd.to_numeric(frame.get("cex_deposit_flow_score", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    flag = _boolish_series(frame.get("cex_deposit_flow_flag", pd.Series(False, index=frame.index)), index=frame.index)
    raw_flow_mask = flag | score.gt(0.0)
    gate_text = _text_series(frame, "cex_deposit_concentration_gate")
    note_text = _text_series(frame, "cex_deposit_flow_note")
    error_text = _text_series(frame, "cex_deposit_flow_error")
    source_url = _text_series(frame, "cex_deposit_24h_source_url")
    attempt_mask = raw_flow_mask | gate_text.ne("") | note_text.ne("") | error_text.ne("") | source_url.ne("")
    if not bool(attempt_mask.any()):
        return []

    rows = frame.loc[attempt_mask].copy()
    if "symbol" not in rows.columns:
        rows["symbol"] = ""
    strict_holder_pass = _strict_cex_holder_gate_mask(
        rows,
        min_whale_pct=min_whale_pct,
        require_holder_evidence=require_holder_evidence,
    )
    rows["_cex_diag_score"] = score.loc[attempt_mask]
    rows["_cex_diag_rank"] = 5
    rows.loc[raw_flow_mask.loc[attempt_mask], "_cex_diag_rank"] = 0
    rows.loc[error_text.loc[attempt_mask].str.contains("HTTP 403", case=False, regex=False), "_cex_diag_rank"] = 1
    rows.loc[error_text.loc[attempt_mask].ne("") & rows["_cex_diag_rank"].ne(1), "_cex_diag_rank"] = 2
    rows.loc[note_text.loc[attempt_mask].str.contains("no large labelled CEX deposits", case=False, regex=False), "_cex_diag_rank"] = 3
    rows.loc[note_text.loc[attempt_mask].str.contains("concentration gate not met", case=False, regex=False), "_cex_diag_rank"] = 4
    rows.loc[raw_flow_mask.loc[attempt_mask] & (~strict_holder_pass), "_cex_diag_rank"] = 4
    rows = rows.sort_values(["_cex_diag_rank", "_cex_diag_score", "symbol"], ascending=[True, False, True])

    capped_limit = min(max(int(limit), 1), 50)
    lines = ["Attempted symbols (not confirmed transfers unless status starts FLOW):"]
    for _, row in rows.head(capped_limit).iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        row_score = _safe_float(row.get("cex_deposit_flow_score")) or 0.0
        is_flow = bool(row_score > 0.0) or str(row.get("cex_deposit_flow_flag", "")).strip().lower() in {"1", "true", "yes"}
        holder_pass = bool(strict_holder_pass.loc[row.name]) if row.name in strict_holder_pass.index else False
        error = _clip_text(row.get("cex_deposit_flow_error", ""), 70)
        note = _clip_text(row.get("cex_deposit_flow_note", ""), 70)
        gate = _clip_text(row.get("cex_deposit_concentration_gate", ""), 48)
        targets = _clip_text(row.get("cex_deposit_24h_target_exchanges", ""), 40)
        source = _clip_text(row.get("cex_deposit_24h_source_url", ""), 70)
        amount_text = _cex_attempt_amount_text(row, min_transfer_tokens=min_transfer_tokens)

        if is_flow and not holder_pass:
            status = "holder gate not met"
        elif is_flow:
            status = f"FLOW {row_score:.0f}/100" + (f" -> {targets}" if targets else "")
        elif error:
            status = f"blocked/error: {error}"
        elif "no large labelled cex deposits" in note.lower():
            status = "checked: no labelled CEX transfer met threshold/lookback"
        elif "concentration gate not met" in note.lower():
            status = "holder gate not met"
        elif note:
            status = note
        else:
            status = "attempted: no scored flow row"

        detail_parts = [part for part in (amount_text, gate, "query URL available" if source else "") if part]
        detail = f" | {' | '.join(detail_parts)}" if detail_parts else ""
        lines.append(f"/{symbol} | {status}{detail}")

    remaining = len(rows) - min(len(rows), capped_limit)
    if remaining > 0:
        lines.append(f"... {remaining} more attempted symbol(s) hidden; raise the command limit to inspect more.")
    return lines


def _candidate_line(row: pd.Series) -> str:
    holder_text = _holder_composition_text(row)
    return build_discord_flag_card(row, holder_text=holder_text)


def _cache_path() -> Path:
    return Path(_env_value("DISCORD_CONVEX_CACHE_PATH", str(APP_DIR / "data" / "latest_convex_longs.csv")))


def _snapshot_path() -> Path:
    return Path(_env_value("DISCORD_PRE_PUMP_SNAPSHOT_PATH", str(APP_DIR / "data" / "pre_pump_scan_snapshots.csv")))


def _shorts_cache_path() -> Path:
    return Path(_env_value("DISCORD_SHORTS_CACHE_PATH", str(APP_DIR / "data" / "latest_short_account_majority.csv")))


def _whales_cache_path() -> Path:
    return Path(_env_value("DISCORD_WHALES_CACHE_PATH", str(APP_DIR / "data" / "latest_whale_dominance.csv")))


def _normalize_symbol_query(raw_symbol: str) -> str:
    match = SYMBOL_QUERY_RE.fullmatch(str(raw_symbol or "").strip())
    if not match:
        return ""
    symbol = match.group(1).upper()
    if symbol in RESERVED_SYMBOL_QUERY_COMMANDS:
        return ""
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    return symbol


def _looks_like_symbol_shortcut(raw_content: str) -> bool:
    token = str(raw_content or "").strip()
    if not token or " " in token:
        return False
    if not token.startswith(("/", "!")):
        return False
    symbol = _normalize_symbol_query(token)
    raw_symbol = token.lstrip("/!$").upper()
    return bool(symbol) and raw_symbol.endswith("USDT")


def _configured_symbol_slash_aliases() -> list[str]:
    raw = _env_value("DISCORD_SYMBOL_SLASH_ALIASES", "PLAYUSDT")
    symbols: list[str] = []
    for chunk in re.split(r"[,;\s]+", raw):
        symbol = _normalize_symbol_query(chunk)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols[:75]


def _symbol_slash_command_name(symbol: str) -> str:
    normalized = _normalize_symbol_query(symbol)
    if not normalized:
        return ""
    name = normalized.lower()
    return name if re.fullmatch(r"[a-z0-9_-]{1,32}", name) else ""


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _latest_snapshot_frame() -> pd.DataFrame:
    frame = _read_csv_if_exists(_snapshot_path())
    if frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    time_column = "snapshot_ts" if "snapshot_ts" in frame.columns else "scanned_at_utc" if "scanned_at_utc" in frame.columns else ""
    if time_column:
        parsed_time = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
        if parsed_time.notna().any():
            latest = parsed_time.max()
            frame = frame[parsed_time.eq(latest)].copy()
    return frame


def _fresh_scanner_frame(
    scan_mode: str | None = None,
    *,
    cex_min_transfer_tokens: float | None = None,
    cex_lookback_hours: int | None = None,
) -> tuple[pd.DataFrame, str]:
    live_default = _env_bool("DISCORD_TIMING_LIVE_SCAN_ENABLED", True)
    if not _env_bool("DISCORD_COMMAND_LIVE_SCAN_ENABLED", live_default):
        return pd.DataFrame(), "live scan disabled"
    mode = (
        scan_mode
        or _env_value("DISCORD_COMMAND_SCAN_MODE", _env_value("DISCORD_TIMING_SCAN_MODE", "Deep"))
    ).strip() or "Deep"
    return run_fresh_scan_frame(
        mode,
        cex_min_transfer_tokens=cex_min_transfer_tokens,
        cex_lookback_hours=cex_lookback_hours,
    )


def _source_is_unavailable(source: str) -> bool:
    lowered = str(source or "").lower()
    return "unavailable" in lowered or "disabled" in lowered


def _first_nonempty(frame: pd.DataFrame, columns: tuple[str, ...], default: str = "unknown") -> str:
    for column in columns:
        if column not in frame.columns or frame.empty:
            continue
        values = frame[column].dropna().astype(str).str.strip()
        values = values[values.ne("") & ~values.str.lower().isin({"nan", "none", "null"})]
        if not values.empty:
            return str(values.iloc[0])
    return default


def _cache_age_header(frame: pd.DataFrame, source: str) -> str:
    scanned_at = _first_nonempty(frame, ("scanned_at_utc", "snapshot_ts"), "unknown")
    scan_mode = _first_nonempty(frame, ("scan_mode",), "unknown")
    return f"Source: {source} | Scan mode: {scan_mode} | Updated: {scanned_at}"


def _convex_candidates_from_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "trade_bucket" not in frame.columns:
        return pd.DataFrame()
    source = frame.loc[:, ~frame.columns.duplicated()].copy()
    score = pd.to_numeric(source.get("trade_bucket_score"), errors="coerce").fillna(0.0)
    try:
        min_score = float(_env_value("DISCORD_CONVEX_ALERT_MIN_SCORE", "0") or 0)
    except (TypeError, ValueError):
        min_score = 0.0
    candidates = source[source["trade_bucket"].astype(str).eq("Convex Long") & (score >= min_score)].copy()
    if candidates.empty:
        return candidates
    candidates = _apply_core_thesis_candidate_gate(candidates)
    if candidates.empty:
        return candidates
    candidates["_discord_bucket_score"] = pd.to_numeric(candidates.get("trade_bucket_score"), errors="coerce").fillna(0.0)
    return candidates.sort_values(["_discord_bucket_score", "symbol"], ascending=[False, True])


def _row_for_symbol(frame: pd.DataFrame, symbol: str) -> pd.Series | None:
    if frame.empty or "symbol" not in frame.columns:
        return None
    matches = frame[frame["symbol"].astype(str).str.upper().eq(symbol)]
    if matches.empty:
        return None
    return matches.iloc[0]


def _load_coin_scan_row(symbol: str) -> tuple[pd.Series | None, str]:
    fresh_frame, fresh_source = _fresh_scanner_frame()
    if not fresh_frame.empty:
        fresh_row = _row_for_symbol(fresh_frame, symbol)
        if fresh_row is not None:
            return fresh_row, fresh_source
        return None, fresh_source
    if not _source_is_unavailable(fresh_source):
        return None, fresh_source
    cache_row = _row_for_symbol(_read_csv_if_exists(_cache_path()), symbol)
    if cache_row is not None:
        return cache_row, "latest Convex cache"
    snapshot_row = _row_for_symbol(_latest_snapshot_frame(), symbol)
    if snapshot_row is not None:
        return snapshot_row, "latest scanner snapshot"
    return None, ""


def _live_binance_row(symbol: str) -> tuple[pd.Series | None, str]:
    client = BinanceFuturesPublic(timeout=_env_int("DISCORD_COIN_LIVE_TIMEOUT_SECONDS", 10, minimum=3), requests_per_second=3)
    ticker = next((item for item in client.ticker_24hr() if str(item.get("symbol", "")).upper() == symbol), None)
    if not ticker:
        return None, ""

    row: dict[str, Any] = {
        "symbol": symbol,
        "base_asset": symbol.removesuffix("USDT"),
        "last_price": ticker.get("lastPrice"),
        "price_change_24h_pct": ticker.get("priceChangePercent"),
        "quote_volume_24h": ticker.get("quoteVolume"),
        "range_24h_pct": None,
    }
    high = _safe_float(ticker.get("highPrice"))
    low = _safe_float(ticker.get("lowPrice"))
    last = _safe_float(ticker.get("lastPrice"))
    if high is not None and low is not None and last is not None and abs(last) > 1e-12:
        row["range_24h_pct"] = (high - low) / last * 100.0
    try:
        oi = client.open_interest(symbol)
        row["oi_value_usdt"] = (_safe_float(oi.get("openInterest")) or 0.0) * (last or 0.0)
    except Exception:
        pass
    try:
        ratios = client.global_long_short_account_ratio(symbol, period="1h", limit=1)
        if ratios:
            latest = ratios[-1]
            long_account = _safe_float(latest.get("longAccount"))
            short_account = _safe_float(latest.get("shortAccount"))
            if long_account is not None:
                row["long_account_pct"] = long_account * 100.0 if long_account <= 1.0 else long_account
            if short_account is not None:
                row["short_account_pct"] = short_account * 100.0 if short_account <= 1.0 else short_account
            row["long_short_account_ratio"] = latest.get("longShortRatio")
    except Exception:
        pass
    return pd.Series(row), "live Binance futures fallback"


def _coin_stats_description(row: pd.Series, *, source: str) -> str:
    scored = _goal_score_frame(pd.DataFrame([row.to_dict()]))
    enriched = scored.iloc[0] if not scored.empty else apply_timing_model(apply_terminal_model(pd.DataFrame([row.to_dict()]))).iloc[0]
    holder_text = _holder_composition_text(row)
    gate_line = _goal_thesis_gates_line(enriched)
    prefix = (
        f"{DISCORD_PRODUCT_IDENTITY}\n\n"
        f"Scan source: {source}\n"
        f"{gate_line}\n"
        "Read: baseThesis/coreSetup are structure gates; targetFlow/whaleOrigin are flow triggers, not venue proof.\n\n"
    )
    card = build_discord_flag_card(enriched, holder_text=holder_text, max_chars=DISCORD_EMBED_DESCRIPTION_LIMIT - len(prefix))
    return f"{prefix}{card}"


def _load_coin_stats(symbol_query: str) -> tuple[str, str]:
    symbol = _normalize_symbol_query(symbol_query)
    if not symbol:
        return "Coin stats", "Use `/coin symbol:PLAYUSDT` or type `/PLAYUSDT` in the configured channel."
    row, source = _load_coin_scan_row(symbol)
    if row is None:
        row, source = _live_binance_row(symbol)
    if row is None:
        return f"{symbol} stats", "No latest scan row or live Binance futures symbol found yet."
    return f"{symbol} stats", _coin_stats_description(row, source=source)


def _load_candidates(limit: int) -> tuple[str, str]:
    frame, source = _fresh_scanner_frame()
    if not frame.empty:
        frame = _convex_candidates_from_frame(frame)
        if frame.empty:
            description = (
                f"{DISCORD_PRODUCT_IDENTITY}\n\n{source}\n{_thesis_candidate_header(core=True)}\n\n"
                "No current market-structure candidates met the strict core thesis gate."
            )
            return "Fresh scanner sample - no current Convex candidates", description[:DISCORD_EMBED_DESCRIPTION_LIMIT]
    elif not _source_is_unavailable(source):
        description = (
            f"{DISCORD_PRODUCT_IDENTITY}\n\n{source}\n{_thesis_candidate_header(core=True)}\n\n"
            "No current market-structure candidates met the strict core thesis gate."
        )
        return "Fresh scanner sample - no current Convex candidates", description[:DISCORD_EMBED_DESCRIPTION_LIMIT]
    else:
        frame = pd.DataFrame()

    path = _cache_path()
    if frame.empty and not path.exists():
        return (
            "No market-structure scan cache yet",
            f"`{source}`\n\nNo fallback cache exists yet.",
        )
    if frame.empty:
        try:
            frame = pd.read_csv(path)
            source = f"cached fallback from {path.name}"
        except Exception as exc:
            return ("Could not read scanner sample cache", f"`{source}`\n\n`{exc}`")
    if frame.empty:
        return ("No market-structure candidates in the latest scan", f"Cache: `{path}`")

    cache_header = _cache_age_header(frame, source)
    if "trade_bucket" in frame.columns:
        frame = frame[frame["trade_bucket"].astype(str).eq("Convex Long")].copy()
    frame = _apply_core_thesis_candidate_gate(frame)
    if frame.empty:
        return (
            "No market-structure candidates met the strict thesis gate",
            f"{DISCORD_PRODUCT_IDENTITY}\n\n{cache_header}\n{_thesis_candidate_header(core=True)}\n\n"
            "No cached candidates currently pass the strict core thesis gate.",
        )

    score_col = "trade_bucket_score" if "trade_bucket_score" in frame.columns else None
    if score_col:
        frame[score_col] = pd.to_numeric(frame[score_col], errors="coerce").fillna(0.0)
        frame = frame.sort_values([score_col, "symbol"], ascending=[False, True])
    else:
        frame = frame.sort_values("symbol")

    scanned_at = str(frame.get("scanned_at_utc", pd.Series(["unknown"])).iloc[0])
    scan_mode = str(frame.get("scan_mode", pd.Series(["unknown"])).iloc[0])
    frame = apply_terminal_model(frame)
    frame = apply_timing_model(frame)
    lines = [_candidate_line(row) for _, row in frame.head(limit).iterrows()]
    card_budget = DISCORD_EMBED_DESCRIPTION_LIMIT - len(DISCORD_PRODUCT_IDENTITY) - 2
    header = _cache_age_header(frame, source) + "\n" + _thesis_candidate_header(core=True)
    description = f"{DISCORD_PRODUCT_IDENTITY}\n\n{header}\n\n{join_discord_flag_cards(lines, max_chars=card_budget)}"
    title = f"Fresh scanner sample - market-structure candidates ({scan_mode}, {scanned_at})"
    if source.startswith("cached fallback"):
        title = f"Cached scanner sample - market-structure candidates ({scan_mode}, {scanned_at})"
    return title, description


def _load_command_guide() -> tuple[str, list[str]]:
    lines = [
        "Discord operator command guide",
        "Use /radar first. It is the clean hard-gated queue for the thesis: explorer-backed top10 whale control, Binance+Bitget trading evidence, low-float/FDV structure, 60D no-pump/dormancy, squeeze fuel, and early/no-chase tape.",
        "",
        "Primary queue:",
        "/commands - this operator map.",
        "/help - same operator map, easier to remember.",
        "/radar [min_tokens] [whale_flow_min_tokens] [limit] [lookback_hours] [trigger] [breakout_windows] - default operator queue; trigger can show all, triggered, whale-CEX, target-CEX, breakout, or core-watch rows.",
        "/prime - short alias for /radar.",
        "/crimepump - legacy blunt-name alias for /radar.",
        "/alpha [limit] - compact thesis-gated brief across structure, timing, CEX flow, scanner score, and short fuel.",
        "/convex [limit] - legacy market-structure sample after the shared strict thesis gate.",
        "",
        "Thesis drilldown:",
        "/coincheck <symbol> - one-symbol pass/fail checklist across holder, venue, squeeze, dormant/not-late, float, and CEX flow.",
        "/ravelab - diagnostic microscope for the RAVE/LAB analogue stack, blockers, near misses, style filters, and full evidence. Use after /radar, not before it.",
        "/precrime - quiet pre-activity board after hard holder, Binance+Bitget, and 60D no-pump gates.",
        "/pumpwatch - broader hard-gated early-pump catch board after holder, Binance+Bitget, 60D no-pump, float, squeeze, and not-late gates.",
        "/setupscore - strict full-thesis ranking with transfer, holder, venue, 60D no-pump, short, float, and not-late checks.",
        "",
        "Flow and holder diagnostics:",
        "/cexflow [min_tokens] - concentration-gated labelled wallet-to-CEX flow; use require_venue_gate:false only for diagnostics.",
        "/cexdiag - explains empty /cexflow results: attempts, explorer errors, holder-gate survival, and venue-gate survival.",
        "/earlyflow - smaller-transfer sweep for low-float names.",
        "/flowproof <symbol> - audit transfer proof for one symbol.",
        "/flowcoin <symbol> - one-symbol wallet-to-CEX flow check.",
        "/flowstress - CEX deposit inventory stress versus visible liquidity.",
        "/flowblocked - symbols blocked by explorer/API source errors.",
        "/flowhealth - API key, chain fallback, and CEX label coverage.",
        "/sethflow - compact full checklist across massive whale-origin CEX flow, whale control, shorts, float, and dormant structure.",
        "/whales - holder concentration board; diagnostic unless top10 + holder evidence are present.",
        "",
        "Market context:",
        "/high <days> and /low <days> - breakout highs/lows for any 1D-1499D window; use thesis_only:true for hard-gated rows.",
        "/corr [threshold] - BTC-correlation filter; negative correlations always show, threshold cuts highly correlated names.",
        "/shorts - all cached symbols with short-account majority.",
        "/funding - Binance funding/carry board.",
        "/floattrap, /squeezeready, /cextargets, /terminal, /timing - single-lens context boards; raw rows show baseThesis Y/N when available.",
        "",
        "Runtime and records:",
        "/dossier <symbol>, /coin <symbol> - symbol detail views.",
        "/startbot, /stopbot, /tradebot_status - trade-bot runtime controls.",
        "/convex_status, /convex_scoreboard, /convex_archive - cache status, proof scoreboard, and archive export.",
        "/sync_commands - refresh slash-command schema after deploy.",
        "",
        "Rule of thumb: /radar for candidates, /coincheck for one name, /cexdiag or /flowhealth for data problems, /ravelab detail:true for the full evidence stack.",
    ]
    return "Discord command guide", _chunk_text_lines(lines)


def _load_terminal_list(limit: int) -> tuple[str, str]:
    frame, source = _fresh_scanner_frame()
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
        if frame.empty:
            frame = _read_csv_if_exists(_cache_path())
            source = "latest Convex cache fallback"
    if frame.empty:
        return "Market-structure evidence terminal", f"No live scan, scanner snapshot, or cache exists yet. `{source}`"
    frame = apply_terminal_model(frame)
    frame = apply_timing_model(frame)
    frame = _apply_thesis_candidate_gate(frame)
    if frame.empty:
        return "Market-structure evidence terminal", "```text\n" + _thesis_candidate_header() + "\n\nNo current rows met the strict holder-evidence and Binance+Bitget thesis gate.\n```"
    frame = frame.sort_values(["terminal_edge_score", "symbol"], ascending=[False, True]).head(limit)
    header = _cache_age_header(frame, source) + "\n" + _thesis_candidate_header()
    lines = [
        (
            f"{str(row.get('symbol', '')).upper()} | terminal {(_safe_float(row.get('terminal_edge_score')) or 0.0):.1f} | "
            f"{row.get('terminal_setup_archetype', 'watchlist structure')} | shorts "
            f"{(_safe_float(row.get('short_account_pct')) or 0.0):.1f}% | "
            f"{row.get('terminal_liquidity_reality', 'liquidity check required')}"
        )
        for _, row in frame.iterrows()
    ]
    return "Market-structure evidence terminal", "```text\n" + (header + "\n\n" + "\n".join(lines))[:1850] + "\n```"


def _load_dossier(symbol_query: str) -> tuple[str, str]:
    symbol = _normalize_symbol_query(symbol_query)
    if not symbol:
        return "Setup dossier", "Use `/dossier symbol:PLAYUSDT`."
    row, source = _load_coin_scan_row(symbol)
    if row is None:
        row, source = _live_binance_row(symbol)
    if row is None:
        return f"{symbol} dossier", "No latest scan row or live Binance futures symbol found yet."
    scored = _goal_score_frame(pd.DataFrame([row.to_dict()]))
    enriched = scored.iloc[0] if not scored.empty else apply_timing_model(apply_terminal_model(pd.DataFrame([row.to_dict()]))).iloc[0]
    gate_line = _goal_thesis_gates_line(enriched)
    text = (
        f"{gate_line}\n"
        "Read: baseThesis/coreSetup are structure gates; targetFlow/whaleOrigin are flow triggers, not venue proof.\n\n"
        + build_setup_dossier(enriched)
        + "\n\n## Timing\n\n```text\n"
        + build_timing_card(enriched)
        + "\n```"
    )
    return f"{symbol} dossier ({source})", text[:DISCORD_EMBED_DESCRIPTION_LIMIT]


def _load_timing_list(limit: int) -> tuple[str, str]:
    frame, source = _fresh_scanner_frame()
    if frame.empty:
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot"
    if frame.empty:
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    if frame.empty:
        return "Timing watchlist", "No live scan, scanner snapshot, or cache exists yet."
    frame = apply_timing_model(apply_terminal_model(frame))
    frame = _apply_thesis_candidate_gate(frame)
    if frame.empty:
        return "Timing watchlist", "```text\n" + _thesis_candidate_header() + "\n\nNo current timing rows met the strict holder-evidence and Binance+Bitget thesis gate.\n```"
    frame = frame.sort_values(
        ["timing_score", "timing_trigger_score", "timing_too_late_score", "symbol"],
        ascending=[False, False, True, True],
    ).head(limit)
    lines = [
        (
            f"{str(row.get('symbol', '')).upper()} | timing {(_safe_float(row.get('timing_score')) or 0.0):.1f} | "
            f"{row.get('timing_state', 'No timing edge')} | shorts {(_safe_float(row.get('short_account_pct')) or 0.0):.1f}% | "
            f"{row.get('timing_observed_trigger', 'pending')}"
        )
        for _, row in frame.iterrows()
    ]
    header = (
        f"Source: {source} | Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"{_thesis_candidate_header()}"
    )
    return "Timing watchlist", "```text\n" + (header + "\n\n" + "\n".join(lines))[:1850] + "\n```"


def _pct_numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return frame[column].map(_safe_pct).astype("float64")


def _parse_breakout_days(days: Any) -> int | None:
    text = str(days or "").strip().upper()
    match = re.fullmatch(r"([0-9]{1,4})\s*D?", text)
    if not match:
        return None
    parsed = int(match.group(1))
    return parsed if 1 <= parsed <= MAX_DYNAMIC_BREAKOUT_DAYS else None


def _parse_breakout_window_list(windows: Any, *, default: tuple[int, ...] = (1, 2, 3, 4, 5, 20)) -> tuple[list[int], list[str]]:
    text = str(windows or "").strip()
    if not text:
        return list(default), []
    if text.lower() in {"0", "off", "false", "none", "no"}:
        return [], []

    parsed: list[int] = []
    ignored: list[str] = []
    for token in re.split(r"[,;\s]+", text):
        token = token.strip()
        if not token:
            continue
        days = _parse_breakout_days(token)
        if days is None:
            ignored.append(token)
            continue
        if days not in parsed:
            parsed.append(days)
    return parsed[:8], ignored


def _breakout_window_help() -> str:
    common = ", ".join(f"{window}D" for window in COMMON_BREAKOUT_WINDOWS)
    return f"any 1D-{MAX_DYNAMIC_BREAKOUT_DAYS}D window; common dashboard columns: {common}"


def _breakout_source_frame(scan_mode: str | None = None) -> tuple[pd.DataFrame, str]:
    mode = scan_mode or _env_value("DISCORD_BREAKOUT_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep"
    frame, source = _fresh_scanner_frame(mode)
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty:
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    return frame, source


def _breakout_level_from_klines(
    klines: list[list[Any]],
    *,
    days: int,
    direction: str,
) -> tuple[float | None, int]:
    if len(klines) < 2:
        return None, 0
    closed_rows = klines[:-1]
    highs: list[float] = []
    lows: list[float] = []
    for raw in closed_rows:
        if not isinstance(raw, (list, tuple)) or len(raw) <= 3:
            continue
        high = _safe_float(raw[2])
        low = _safe_float(raw[3])
        if high is not None:
            highs.append(high)
        if low is not None:
            lows.append(low)
    values = highs if direction == "high" else lows
    used_days = min(int(days), len(values))
    if used_days <= 0:
        return None, 0
    window = values[-used_days:]
    return (max(window) if direction == "high" else min(window)), used_days


def _current_breakout_observation(row: pd.Series, klines: list[list[Any]], *, direction: str) -> float | None:
    primary = "high_24h" if direction == "high" else "low_24h"
    fallback = "highPrice" if direction == "high" else "lowPrice"
    observed = _safe_float(row.get(primary))
    if observed is None:
        observed = _safe_float(row.get(fallback))
    if observed is None and klines:
        latest = klines[-1]
        if isinstance(latest, (list, tuple)) and len(latest) > 3:
            observed = _safe_float(latest[2 if direction == "high" else 3])
    return observed


def _apply_dynamic_breakout_window(frame: pd.DataFrame, *, direction: str, days: int) -> tuple[pd.DataFrame, dict[str, int]]:
    out = frame.copy()
    broke_column = f"_discord_broke_{direction}_{days}d"
    level_column = f"_discord_{direction}_{days}d_level"
    used_days_column = "_discord_breakout_used_days"
    error_column = "_discord_breakout_error"
    for column in (broke_column, level_column, used_days_column, error_column):
        if column not in out.columns:
            out[column] = False if column == broke_column else ""

    stats = {"checked": 0, "errors": 0, "insufficient": 0}
    if "symbol" not in out.columns:
        stats["errors"] = len(out)
        return out, stats

    timeout = _env_int("DISCORD_BREAKOUT_HTTP_TIMEOUT_SECONDS", _env_int("HTTP_TIMEOUT", 12, minimum=3), minimum=3)
    rps = _env_float("DISCORD_BREAKOUT_REQUESTS_PER_SECOND", 6.0, minimum=0.5)
    client = BinanceFuturesPublic(timeout=timeout, requests_per_second=rps)
    limit = min(MAX_DYNAMIC_BREAKOUT_DAYS + 1, max(2, int(days) + 1))

    for idx, row in out.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip()
        if not symbol:
            out.at[idx, error_column] = "missing symbol"
            stats["errors"] += 1
            continue
        try:
            klines = client.klines_1d(symbol, limit=limit)
            level, used_days = _breakout_level_from_klines(klines, days=days, direction=direction)
            observed = _current_breakout_observation(row, klines, direction=direction)
        except Exception as exc:
            out.at[idx, error_column] = type(exc).__name__
            stats["errors"] += 1
            continue
        if level is None or observed is None:
            out.at[idx, error_column] = "insufficient klines"
            out.at[idx, used_days_column] = int(used_days or 0)
            stats["insufficient"] += 1
            continue
        broke = observed > level if direction == "high" else observed < level
        out.at[idx, broke_column] = bool(broke)
        out.at[idx, level_column] = float(level)
        out.at[idx, used_days_column] = int(used_days)
        stats["checked"] += 1
    return out, stats


def _apply_ravelab_high_breakout_windows(frame: pd.DataFrame, windows: list[int]) -> tuple[pd.DataFrame, dict[str, int]]:
    out = frame.copy()
    out["_ravelab_breakout_any"] = False
    out["_ravelab_breakout_windows"] = "disabled" if not windows else "none"
    stats = {"checked": 0, "errors": 0, "insufficient": 0, "cached": 0}
    if out.empty or not windows:
        return out, stats
    if "symbol" not in out.columns:
        stats["errors"] = len(out)
        out["_ravelab_breakout_windows"] = "missing symbol"
        return out, stats

    windows = sorted(dict.fromkeys(int(window) for window in windows if 1 <= int(window) <= MAX_DYNAMIC_BREAKOUT_DAYS))
    missing_windows = [window for window in windows if f"broke_high_{window}d" not in out.columns]
    timeout = _env_int("DISCORD_BREAKOUT_HTTP_TIMEOUT_SECONDS", _env_int("HTTP_TIMEOUT", 12, minimum=3), minimum=3)
    rps = _env_float("DISCORD_BREAKOUT_REQUESTS_PER_SECOND", 6.0, minimum=0.5)
    client = BinanceFuturesPublic(timeout=timeout, requests_per_second=rps) if missing_windows else None
    max_missing = max(missing_windows) if missing_windows else 0

    for idx, row in out.iterrows():
        hits: list[str] = []
        misses = 0
        unavailable = 0
        klines: list[list[Any]] | None = None
        observed: float | None = None
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip()

        for window in windows:
            static_column = f"broke_high_{window}d"
            if static_column in out.columns:
                stats["cached"] += 1
                if _boolish_scalar(row.get(static_column)):
                    hits.append(f"{window}D")
                else:
                    misses += 1
                continue

            if client is None or not symbol:
                unavailable += 1
                continue
            try:
                if klines is None:
                    klines = client.klines_1d(symbol, limit=min(MAX_DYNAMIC_BREAKOUT_DAYS + 1, max_missing + 1))
                    observed = _current_breakout_observation(row, klines, direction="high")
                level, used_days = _breakout_level_from_klines(klines, days=window, direction="high")
            except Exception:
                stats["errors"] += 1
                unavailable += 1
                continue
            if level is None or observed is None:
                stats["insufficient"] += 1
                unavailable += 1
                continue
            stats["checked"] += 1
            if observed > level:
                suffix = f"({used_days}d)" if used_days and used_days < window else ""
                hits.append(f"{window}D{suffix}")
            else:
                misses += 1

        out.at[idx, "_ravelab_breakout_any"] = bool(hits)
        if hits:
            out.at[idx, "_ravelab_breakout_windows"] = ",".join(hits)
        elif unavailable and not misses:
            out.at[idx, "_ravelab_breakout_windows"] = "unchecked"
        elif unavailable:
            out.at[idx, "_ravelab_breakout_windows"] = f"none ({unavailable} unchecked)"
        else:
            out.at[idx, "_ravelab_breakout_windows"] = "none"
    return out, stats


def _recent_daily_pump_from_klines(klines: list[list[Any]], *, days: int = 60) -> tuple[float | None, int]:
    if len(klines) < 2:
        return None, 0
    pumps: list[float] = []
    for raw in klines[:-1][-max(1, int(days)):]:
        if not isinstance(raw, (list, tuple)) or len(raw) <= 4:
            continue
        open_price = _safe_float(raw[1])
        high = _safe_float(raw[2])
        low = _safe_float(raw[3])
        close = _safe_float(raw[4])
        base = open_price if open_price is not None and open_price > 0 else low if low is not None and low > 0 else close
        if base is None or base <= 0 or high is None:
            continue
        pumps.append(max(0.0, (high / base - 1.0) * 100.0))
    if not pumps:
        return None, 0
    return max(pumps), len(pumps)


def _ravelab_refresh_activity_gates(
    frame: pd.DataFrame,
    *,
    min_history_days: int,
    max_recent_pump_pct: float,
) -> pd.DataFrame:
    out = frame.copy()
    if out.empty:
        return out
    index = out.index
    required_pump_days = max(1, min(60, int(min_history_days)))
    recent_pump = _num_series(out, "_ravelab_recent_max_pump_pct", default=float("nan"))
    observed_days = _num_series(out, "_ravelab_recent_pump_days", default=0.0)
    pump_observed = recent_pump.notna() & observed_days.ge(required_pump_days)
    no_large_recent_pump = pump_observed & recent_pump.lt(max(0.0, float(max_recent_pump_pct)))
    history_days = _num_series(out, "_ravelab_history_days", default=0.0)
    heat = _num_series(out, "_ravelab_heat_score", default=float("nan"))
    heat = heat.fillna(_num_series(out, "pre_activity_heat_score"))
    late_penalty = _max_series(out, "rave_lab_late_penalty_score", "timing_too_late_score", "convexity_late_penalty")
    dormant_2m = (
        history_days.ge(max(1, int(min_history_days)))
        & heat.lt(62.0)
        & late_penalty.lt(66.0)
        & no_large_recent_pump
    )
    major_excluded = _boolish_series(out.get("crime_excluded_major"), index=index)
    out["_ravelab_recent_pump_observed"] = pump_observed & (~major_excluded)
    out["_ravelab_no_large_pump_gate"] = no_large_recent_pump & (~major_excluded)
    out["_ravelab_dormant_2m_gate"] = dormant_2m & (~major_excluded)
    return out


def _apply_ravelab_recent_pump_window(
    frame: pd.DataFrame,
    candidate_mask: pd.Series,
    *,
    min_history_days: int,
    max_recent_pump_pct: float,
    days: int = 60,
) -> tuple[pd.DataFrame, dict[str, int]]:
    out = frame.copy()
    stats = {"checked": 0, "cached": 0, "errors": 0, "insufficient": 0, "skipped": 0}
    if out.empty:
        return out, stats
    required_pump_days = max(1, min(int(days), int(min_history_days)))
    if "_ravelab_recent_pump_source" not in out.columns:
        out["_ravelab_recent_pump_source"] = ""
    recent_pump = _num_series(out, "_ravelab_recent_max_pump_pct", default=float("nan"))
    observed_days = _num_series(out, "_ravelab_recent_pump_days", default=0.0)
    cached_mask = recent_pump.notna() & observed_days.ge(required_pump_days)
    out.loc[cached_mask, "_ravelab_recent_pump_source"] = out.loc[cached_mask, "_ravelab_recent_pump_source"].replace("", "scan60d")
    stats["cached"] = int(cached_mask.sum())

    clean_candidate_mask = candidate_mask.reindex(out.index, fill_value=False).fillna(False).astype(bool)
    missing_mask = clean_candidate_mask & (~cached_mask)
    indices = list(out[missing_mask].index)
    max_checks = _env_int("DISCORD_RAVELAB_MAX_PUMP_CHECKS", 50, minimum=1)
    if len(indices) > max_checks:
        for idx in indices[max_checks:]:
            out.at[idx, "_ravelab_recent_pump_source"] = f"skipped; max {max_checks} checks"
            stats["skipped"] += 1
        indices = indices[:max_checks]

    timeout = _env_int("DISCORD_RAVELAB_HTTP_TIMEOUT_SECONDS", _env_int("HTTP_TIMEOUT", 12, minimum=3), minimum=3)
    rps = _env_float("DISCORD_RAVELAB_REQUESTS_PER_SECOND", _env_float("DISCORD_BREAKOUT_REQUESTS_PER_SECOND", 6.0, minimum=0.5), minimum=0.5)
    client = BinanceFuturesPublic(timeout=timeout, requests_per_second=rps) if indices else None
    limit = max(2, int(days) + 1)
    for idx in indices:
        symbol = _clean_scalar_text(out.at[idx, "symbol"] if "symbol" in out.columns else "").upper().strip()
        if not symbol or client is None:
            out.at[idx, "_ravelab_recent_pump_source"] = "missing symbol"
            stats["errors"] += 1
            continue
        try:
            klines = client.klines_1d(symbol, limit=limit)
            pump, used_days = _recent_daily_pump_from_klines(klines, days=days)
        except Exception as exc:
            out.at[idx, "_ravelab_recent_pump_source"] = f"{type(exc).__name__}"
            stats["errors"] += 1
            continue
        if pump is None or used_days < required_pump_days:
            out.at[idx, "_ravelab_recent_pump_days"] = int(used_days or 0)
            out.at[idx, "_ravelab_recent_pump_source"] = f"insufficient {int(used_days or 0)}d"
            stats["insufficient"] += 1
            continue
        out.at[idx, "_ravelab_recent_max_pump_pct"] = float(pump)
        out.at[idx, "_ravelab_recent_pump_days"] = int(used_days)
        out.at[idx, "_ravelab_recent_pump_source"] = f"binance{int(used_days)}d"
        stats["checked"] += 1

    missing_after = clean_candidate_mask & _text_series(out, "_ravelab_recent_pump_source").eq("")
    out.loc[missing_after, "_ravelab_recent_pump_source"] = "missing 60d pump proof"
    unchecked_after = (~clean_candidate_mask) & _text_series(out, "_ravelab_recent_pump_source").eq("")
    out.loc[unchecked_after, "_ravelab_recent_pump_source"] = "not checked; earlier gate failed"
    out = _ravelab_refresh_activity_gates(
        out,
        min_history_days=min_history_days,
        max_recent_pump_pct=max_recent_pump_pct,
    )
    return out, stats


def _load_breakout_list(side: str, *, days: Any = "20D", limit: int = 0, thesis_only: bool = False) -> tuple[str, list[str]]:
    direction = "high" if str(side).lower().startswith("h") else "low"
    parsed_days = _parse_breakout_days(days)
    title = f"{direction.upper()} breakout screen"
    window_help = _breakout_window_help()
    if parsed_days is None:
        return title, [f"Unsupported breakout window `{days}`. Use {window_help}."]

    frame, source = _breakout_source_frame()
    if frame.empty:
        return title, [f"No live scan, scanner snapshot, or cache exists yet. `{source}`"]
    frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    column = f"broke_{direction}_{parsed_days}d"
    if "symbol" not in frame.columns:
        return (
            title,
            [
                f"{_cache_age_header(frame, source)}\n\n"
                "The current scan source does not include a `symbol` column, so breakout rows cannot be matched."
            ],
        )

    if column in frame.columns:
        filter_text = f"Filter: `{column}` is true | Windows: {window_help}"
        mask = _boolish_series(frame[column], index=frame.index)
    else:
        frame, dynamic_stats = _apply_dynamic_breakout_window(frame, direction=direction, days=parsed_days)
        column = f"_discord_broke_{direction}_{parsed_days}d"
        filter_text = (
            f"Filter: computed prior {parsed_days}D {direction} from Binance daily klines | "
            f"Checked: {dynamic_stats['checked']} | Errors: {dynamic_stats['errors']} | "
            f"Insufficient: {dynamic_stats['insufficient']} | Windows: {window_help}"
        )
        mask = _boolish_series(frame[column], index=frame.index)
    selected = frame[mask].copy()
    if not selected.empty:
        selected = _goal_score_frame(selected)
        selected["_discord_thesis_gate"] = _boolish_series(selected.get("_goal_core_setup_pass"), index=selected.index)
    thesis_match_count = int(_boolish_series(selected.get("_discord_thesis_gate"), index=selected.index).sum()) if not selected.empty else 0
    if thesis_only and not selected.empty:
        selected = selected[_boolish_series(selected.get("_discord_thesis_gate"), index=selected.index)].copy()
    header = (
        f"{parsed_days}D {direction} breakout screen\n"
        f"{_cache_age_header(frame, source)}\n"
        f"{filter_text}\n"
        f"{_thesis_candidate_header(core=True)} | Thesis-only: {bool(thesis_only)} | Thesis breakout matches: {thesis_match_count}"
    )
    if selected.empty:
        qualifier = " and passed the strict thesis gate" if thesis_only else ""
        return title, [header + f"\n\nNo symbols currently broke their {parsed_days}D {direction}{qualifier}."]

    price_change = pd.to_numeric(
        selected.get("price_change_24h_pct", selected.get("day_return_pct", pd.Series(0.0, index=selected.index))),
        errors="coerce",
    ).fillna(0.0)
    selected["_discord_breakout_24h"] = price_change
    score = pd.to_numeric(selected.get("range_breakout_score", pd.Series(0.0, index=selected.index)), errors="coerce").fillna(0.0)
    selected["_discord_breakout_score"] = score
    selected = selected.sort_values(
        ["_discord_thesis_gate", "_discord_breakout_24h", "_discord_breakout_score", "symbol"],
        ascending=[False, direction != "high", False, True],
    )

    requested_limit = int(limit or 0)
    capped_limit = min(max(requested_limit, 0), 300)
    visible = selected.head(capped_limit) if capped_limit > 0 else selected
    hidden_count = max(0, len(selected) - len(visible))
    lines = [
        header,
        "",
        f"Matches: {len(selected)} | Strict thesis matches: {thesis_match_count}" + (f" | Showing: {len(visible)}" if hidden_count else ""),
        "",
    ]
    for _, row in visible.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        line = f"/{symbol} | broke {parsed_days}D {direction}"
        move = _safe_float(row.get("price_change_24h_pct"))
        if move is None:
            move = _safe_float(row.get("day_return_pct"))
        if move is not None:
            line += f" | 24h {move:+.1f}%"
        last_price = _safe_float(row.get("last_price"))
        if last_price is not None:
            line += f" | price {_fmt_compact_number(last_price)}"
        used_days = _safe_float(row.get("_discord_breakout_used_days"))
        if used_days is not None and int(used_days) != parsed_days:
            line += f" | used {int(used_days)}d"
        level = _safe_float(row.get(f"_discord_{direction}_{parsed_days}d_level"))
        if level is None:
            level = _safe_float(row.get(f"{direction}_{parsed_days}d"))
        if level is not None:
            level_label = "prior high" if direction == "high" else "prior low"
            line += f" | {level_label} {_fmt_compact_number(level)}"
        high_count = _safe_float(row.get("range_high_break_count"))
        low_count = _safe_float(row.get("range_low_break_count"))
        if high_count is not None or low_count is not None:
            line += f" | breaks H{int(high_count or 0)}/L{int(low_count or 0)}"
        short_pct = _safe_float(row.get("short_account_pct"))
        if short_pct is not None:
            line += f" | shorts {short_pct:.1f}%"
        thesis_gate = "Y" if _boolish_scalar(row.get("_discord_thesis_gate")) else "N"
        line += f" | thesis {thesis_gate}"
        lines.append(line)
    if hidden_count:
        lines.append(f"... {hidden_count} more match(es) hidden; raise limit to inspect more.")
    return title, _chunk_text_lines(lines)


def _holder_concentration_source_frame(scan_mode: str | None = None) -> tuple[pd.DataFrame, str]:
    mode = scan_mode or _env_value("DISCORD_WHALES_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep"
    frame, source = _fresh_scanner_frame(mode)
    if frame.empty and _source_is_unavailable(source):
        snapshot = _latest_snapshot_frame()
        if not snapshot.empty and {"top10_holder_pct", "top100_holder_pct"} & set(snapshot.columns):
            return snapshot, "latest full scanner snapshot fallback"
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    return frame, source


def _holder_source_frame_for_direct_scan(frame: pd.DataFrame) -> pd.DataFrame:
    if not frame.empty and "symbol" in frame.columns:
        return frame.loc[:, ~frame.columns.duplicated()].copy()
    cache = _read_csv_if_exists(_cache_path())
    if not cache.empty and "symbol" in cache.columns:
        return cache.loc[:, ~cache.columns.duplicated()].copy()
    hints = load_contract_hints(_holder_contract_hints_path())
    rows = [
        {"symbol": hint.symbol, "token_platform": hint.chain, "token_contract": hint.contract_address}
        for hint in hints.values()
    ]
    return pd.DataFrame(rows)


def _bucket_columns_available(frame: pd.DataFrame, bucket_key: str) -> bool:
    if frame.empty:
        return False
    has_top10 = "top10_holder_pct" in frame.columns and _pct_numeric_series(frame, "top10_holder_pct").notna().any()
    has_top100 = "top100_holder_pct" in frame.columns and _pct_numeric_series(frame, "top100_holder_pct").notna().any()
    if bucket_key == "top10":
        return has_top10
    if bucket_key == "top100":
        return has_top100
    if bucket_key == "both":
        return has_top10 and has_top100
    return has_top10 or has_top100


def _whale_cache_is_fresh(path: Path) -> bool:
    ttl_seconds = _env_int("DISCORD_WHALES_CACHE_TTL_SECONDS", 1800, minimum=0)
    return ttl_seconds > 0 and path.exists() and time.time() - path.stat().st_mtime <= ttl_seconds


def _direct_holder_dominance_frame(
    source_frame: pd.DataFrame,
    *,
    max_symbols: int = 0,
    timeout: int | None = None,
    max_holders: int = 100,
) -> tuple[pd.DataFrame, str]:
    source = _holder_source_frame_for_direct_scan(source_frame)
    if source.empty or "symbol" not in source.columns:
        return pd.DataFrame(), "no contract-hinted holder universe available"
    hints_path = _holder_contract_hints_path()
    source = source.copy()
    source["symbol"] = source["symbol"].astype(str).str.upper().str.strip()
    source = source[source["symbol"].ne("")]
    source = source.drop_duplicates(subset=["symbol"], keep="first")
    capped = max(0, int(max_symbols or 0))
    if capped > 0:
        source = source.head(capped)
    timeout_seconds = timeout or _env_int("DISCORD_WHALES_HOLDER_TIMEOUT_SECONDS", 12, minimum=3)
    holder_limit = min(max(int(max_holders), 10), 100)
    rows: list[dict[str, Any]] = []
    errors = 0
    for _, row in source.iterrows():
        row_dict = row.to_dict()
        try:
            hint = resolve_contract_hint(row_dict, hints_path=hints_path)
        except Exception:
            hint = None
        if hint is None:
            errors += 1
            continue
        try:
            composition = fetch_holder_composition(
                row_dict,
                hints_path=hints_path,
                timeout=timeout_seconds,
                max_holders=holder_limit,
            )
        except Exception:
            errors += 1
            continue
        if composition.error:
            errors += 1
            continue
        top10 = composition.top_pct(10)
        top100 = composition.top_pct(100)
        record = row_dict.copy()
        record.update(
            {
                "symbol": str(row_dict.get("symbol", composition.symbol)).upper().strip(),
                "token_platform": composition.chain or hint.chain,
                "token_contract": composition.contract_address or hint.contract_address,
                "top10_holder_pct": top10,
                "top100_holder_pct": top100,
                "holder_count": composition.holder_count,
                "holder_source": composition.source,
                "holder_explorer_url": composition.explorer_url,
                "scanned_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "scan_mode": "live holder composition",
            }
        )
        rows.append(record)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        cache_path = _whales_cache_path()
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(cache_path, index=False)
        except Exception:
            pass
    return frame, f"computed holder composition ({len(rows)} rows, {errors} skipped)"


def _normalize_whale_bucket(bucket: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(bucket or "top100").lower())
    aliases = {
        "100": "top100",
        "top100": "top100",
        "t100": "top100",
        "10": "top10",
        "top10": "top10",
        "t10": "top10",
        "either": "either",
        "any": "either",
        "or": "either",
        "both": "both",
        "and": "both",
    }
    return aliases.get(normalized, "top100")


def _load_whale_dominance_list(
    limit: int,
    *,
    min_pct: float = 90.0,
    bucket: str = "top100",
    require_contract_hint: bool = False,
    max_symbols: int = 0,
    refresh: bool = False,
) -> tuple[str, list[str]]:
    frame, source = _holder_concentration_source_frame()
    threshold = max(0.0, min(float(min_pct), 100.0))
    bucket_key = _normalize_whale_bucket(bucket)
    if not _bucket_columns_available(frame, bucket_key):
        cache_path = _whales_cache_path()
        if not refresh and _whale_cache_is_fresh(cache_path):
            cached = _read_csv_if_exists(cache_path)
            if _bucket_columns_available(cached, bucket_key):
                frame = cached
                source = f"latest whale-dominance cache ({cache_path.name})"
        if not _bucket_columns_available(frame, bucket_key):
            frame, computed_source = _direct_holder_dominance_frame(
                frame,
                max_symbols=max_symbols,
                max_holders=100,
            )
            source = f"{computed_source} from contract hints"
    header = (
        "Whale dominance ranking\n"
        f"Source: {source} | Threshold: >= {threshold:.1f}% | Bucket: {bucket_key} | "
        "Read: diagnostic holder-concentration rows, not the hard-gated crime-pump queue."
    )
    if frame.empty:
        return "Whale dominance ranking", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]
    if "symbol" not in frame.columns:
        return "Whale dominance ranking", [header + "\n\nThe current scan source has no symbol column."]

    rows = frame.loc[:, ~frame.columns.duplicated()].copy()
    top10 = _pct_numeric_series(rows, "top10_holder_pct")
    top100 = _pct_numeric_series(rows, "top100_holder_pct")
    if top10.isna().all() and top100.isna().all():
        return "Whale dominance ranking", [header + "\n\nCould not compute top-holder concentration from the active scan, cache, or contract hints."]

    if require_contract_hint:
        hints_path = _holder_contract_hints_path()
        has_hint: list[bool] = []
        for _, row in rows.iterrows():
            try:
                has_hint.append(resolve_contract_hint(row.to_dict(), hints_path=hints_path) is not None)
            except Exception:
                has_hint.append(False)
        hint_mask = pd.Series(has_hint, index=rows.index)
    else:
        hint_mask = pd.Series(True, index=rows.index)

    if bucket_key == "top10":
        pass_mask = top10.ge(threshold)
        whale_metric = top10
    elif bucket_key == "either":
        pass_mask = top10.ge(threshold) | top100.ge(threshold)
        whale_metric = pd.concat([top10, top100], axis=1).max(axis=1)
    elif bucket_key == "both":
        pass_mask = top10.ge(threshold) & top100.ge(threshold)
        whale_metric = pd.concat([top10, top100], axis=1).min(axis=1)
    else:
        pass_mask = top100.ge(threshold)
        whale_metric = top100

    rows["_whale_top10"] = top10
    rows["_whale_top100"] = top100
    rows["_whale_metric"] = whale_metric
    rows = rows[pass_mask & hint_mask].copy()
    if rows.empty:
        return "Whale dominance ranking", [header + "\n\nNo symbols met the whale-dominance threshold in the active scan source."]

    rows["symbol"] = rows["symbol"].astype(str).str.upper().str.strip()
    rows = rows[rows["symbol"].ne("")]
    rows["_discord_base_thesis_gate"] = _thesis_candidate_gate_mask(rows)
    rows = rows.sort_values(["_whale_metric", "_whale_top10", "symbol"], ascending=[False, False, True])
    rows = rows.drop_duplicates(subset=["symbol"], keep="first")
    visible = rows.head(min(max(int(limit), 1), 300))
    hidden_count = max(0, len(rows) - len(visible))
    base_thesis_count = int(_boolish_series(rows.get("_discord_base_thesis_gate"), index=rows.index).sum())

    lines = [
        header,
        f"Matches: {len(rows)} | Base thesis gate: {base_thesis_count} | Showing: {len(visible)}"
        + (f" | Hidden: {hidden_count}" if hidden_count else ""),
        "",
        "Diagnostic rows: " + " ".join(f"/{symbol}" for symbol in visible["symbol"].tolist()),
        "",
    ]
    for _, row in visible.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        top10_text = f"{float(row['_whale_top10']):.1f}%" if pd.notna(row.get("_whale_top10")) else "n/a"
        top100_text = f"{float(row['_whale_top100']):.1f}%" if pd.notna(row.get("_whale_top100")) else "n/a"
        short_pct = _safe_float(row.get("short_account_pct"))
        short_text = f"{short_pct:.1f}%" if short_pct is not None else "n/a"
        holders = _safe_float(row.get("holder_count"))
        holder_text = f"{holders:.0f}" if holders is not None else "n/a"
        terminal_score = _safe_float(row.get("terminal_edge_score"))
        terminal_text = f"{terminal_score:.0f}" if terminal_score is not None else "n/a"
        cex_score = _safe_float(row.get("cex_deposit_flow_score"))
        cex_text = f"{cex_score:.0f}" if cex_score is not None else "n/a"
        platform = _first_nonempty_text(row.get("token_platform", ""), row.get("chain", ""))
        platform_text = f" | chain {platform}" if platform else ""
        base_thesis = "Y" if _boolish_scalar(row.get("_discord_base_thesis_gate")) else "N"
        lines.append(
            f"/{symbol} | top100 {top100_text} | top10 {top10_text} | holders {holder_text} | "
            f"shorts {short_text} | terminal {terminal_text} | CEX {cex_text} | baseThesis {base_thesis}{platform_text}"
        )
    if hidden_count:
        lines.append(f"... {hidden_count} more match(es) hidden; raise limit to inspect more.")
    return "Whale dominance ranking", _chunk_text_lines(lines)


def _load_corr_list(*, threshold: float = 0.0, limit: int = 0) -> tuple[str, list[str]]:
    scan_mode = _env_value("DISCORD_CORR_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep"
    frame, source = _fresh_scanner_frame(scan_mode)
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty:
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    if frame.empty:
        return "BTC low-correlation screen", [f"No live scan, scanner snapshot, or cache exists yet. `{source}`"]

    frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    corr_column = "corr_to_btc_6m" if "corr_to_btc_6m" in frame.columns else "corr_to_btc" if "corr_to_btc" in frame.columns else ""
    if not corr_column:
        cache_frame = _read_csv_if_exists(_cache_path())
        cache_corr_column = (
            "corr_to_btc_6m"
            if "corr_to_btc_6m" in cache_frame.columns
            else "corr_to_btc"
            if "corr_to_btc" in cache_frame.columns
            else ""
        )
        if cache_corr_column:
            frame = cache_frame.loc[:, ~cache_frame.columns.duplicated()].copy()
            source = "latest Convex cache fallback"
            corr_column = cache_corr_column
    if not corr_column or "symbol" not in frame.columns:
        return (
            "BTC low-correlation screen",
            [
                f"{_cache_age_header(frame, source)}\n\n"
                "The current scan source does not include BTC-correlation columns. Run a full dashboard scan first."
            ],
        )

    max_corr = min(max(float(threshold or 0.0), 0.0), 1.0)
    corr = pd.to_numeric(frame[corr_column], errors="coerce")
    window = pd.to_numeric(frame.get("corr_window_days", pd.Series(0, index=frame.index)), errors="coerce").fillna(0)
    if max_corr > 0.0:
        selected = frame[corr.notna() & corr.le(max_corr)].copy()
    else:
        selected = frame[corr.notna() & corr.lt(0.0)].copy()
    selected["_discord_corr_to_btc"] = corr.loc[selected.index]
    selected["_discord_corr_window_days"] = window.loc[selected.index]
    if not selected.empty:
        selected["_discord_base_thesis_gate"] = _thesis_candidate_gate_mask(selected)
    base_thesis_count = int(_boolish_series(selected.get("_discord_base_thesis_gate"), index=selected.index).sum()) if not selected.empty else 0
    selected = selected.sort_values(["_discord_base_thesis_gate", "_discord_corr_to_btc", "symbol"], ascending=[False, True, True])

    target_window_days = 180
    threshold_text = f"corr <= {max_corr:.2f}" if max_corr > 0.0 else "corr < 0.00"
    header = (
        "BTC low-correlation screen\n"
        f"{_cache_age_header(frame, source)}\n"
        f"Threshold: {threshold_text} | Target window: max {target_window_days}d; younger symbols use available overlap.\n"
        "Read: context screen only; baseThesis Y means strict holder+venue+60D no-pump gate also passed."
    )
    if selected.empty:
        return "BTC low-correlation screen", [header + "\n\nNo symbols currently met the BTC-correlation threshold."]

    requested_limit = int(limit or 0)
    capped_limit = min(max(requested_limit, 0), 300)
    visible = selected.head(capped_limit) if capped_limit > 0 else selected
    hidden_count = max(0, len(selected) - len(visible))

    lines = [
        header,
        "",
        f"Matches: {len(selected)} | Base thesis gate: {base_thesis_count}" + (f" | Showing: {len(visible)}" if hidden_count else ""),
        "",
    ]
    for _, row in visible.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        corr_value = _safe_float(row.get("_discord_corr_to_btc"))
        window_days = int(_safe_float(row.get("_discord_corr_window_days")) or 0)
        window_text = f"used {window_days}d" if window_days > 0 else "used n/a"
        if 0 < window_days < target_window_days:
            window_text += " (max available)"
        line = f"/{symbol} | corr {corr_value:.3f} | {window_text}" if corr_value is not None else f"/{symbol} | corr n/a | {window_text}"
        short_pct = _safe_float(row.get("short_account_pct"))
        if short_pct is not None:
            line += f" | shorts {short_pct:.1f}%"
        day_return = _safe_float(row.get("day_return_pct"))
        if day_return is None:
            day_return = _safe_float(row.get("price_change_24h_pct"))
        if day_return is not None:
            line += f" | 24h {day_return:.1f}%"
        market_type = _clean_scalar_text(row.get("market_type", "")).strip()
        if market_type:
            line += f" | {market_type}"
        base_thesis = "Y" if _boolish_scalar(row.get("_discord_base_thesis_gate")) else "N"
        line += f" | baseThesis {base_thesis}"
        lines.append(line)
    if hidden_count:
        lines.append(f"... {hidden_count} more match(es) hidden; raise limit to inspect more.")
    return "BTC low-correlation screen", _chunk_text_lines(lines)


def _normalize_funding_side(side: str) -> str:
    normalized = str(side or "both").strip().lower().replace("_", "-").replace(" ", "-")
    if normalized in {"short", "shorts", "short-carry", "shorts-receive", "positive", "pos"}:
        return "shorts"
    if normalized in {"long", "longs", "long-carry", "longs-receive", "negative", "neg"}:
        return "longs"
    return "both"


def _format_signed_pct(value: Any, *, decimals: int = 1) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    if abs(parsed) < 0.5 * (10 ** -decimals):
        parsed = 0.0
    sign = "+" if parsed > 0 else ""
    return f"{sign}{parsed:.{decimals}f}%"


def _format_mark_price(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    absolute = abs(parsed)
    if absolute >= 100:
        text = f"{parsed:.2f}"
    elif absolute >= 1:
        text = f"{parsed:.4f}"
    elif absolute >= 0.01:
        text = f"{parsed:.6f}"
    else:
        text = f"{parsed:.8f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _next_funding_text(next_funding_time: Any) -> str:
    timestamp = _safe_float(next_funding_time)
    if timestamp is None or timestamp <= 0:
        return "n/a"
    hours = max(0.0, (timestamp - time.time() * 1000.0) / 3_600_000.0)
    if hours >= 24.0:
        return f"{hours / 24.0:.1f}d"
    if hours >= 1.0:
        return f"{hours:.1f}h"
    return f"{hours * 60.0:.0f}m"


def _funding_account_percentages(client: BinanceFuturesPublic, symbol: str, *, period: str) -> tuple[float | None, float | None]:
    try:
        ratio_rows = client.global_long_short_account_ratio(symbol, period=period, limit=1)
    except Exception:
        return None, None
    if not ratio_rows:
        return None, None
    latest = ratio_rows[-1]
    long_pct = _safe_float(latest.get("longAccount"))
    short_pct = _safe_float(latest.get("shortAccount"))
    if long_pct is not None and abs(long_pct) <= 1.0:
        long_pct *= 100.0
    if short_pct is not None and abs(short_pct) <= 1.0:
        short_pct *= 100.0
    return long_pct, short_pct


def _format_funding_row(row: dict[str, Any]) -> str:
    interval_hours = _safe_float(row.get("funding_interval_hours")) or 8.0
    interval_text = f"{interval_hours:.0f}h" if abs(interval_hours - round(interval_hours)) < 0.01 else f"{interval_hours:.1f}h"
    parts = [
        f"/{row.get('symbol', 'UNKNOWN')}",
        f"funding {_format_signed_pct(row.get('funding_pct'), decimals=4)}/{interval_text}",
        f"ann {_format_signed_pct(row.get('annualized_funding_pct'), decimals=1)}",
        f"mark {_format_mark_price(row.get('mark_price'))}",
    ]
    change_pct = _safe_float(row.get("price_change_24h_pct"))
    if change_pct is not None:
        parts.append(f"24h {_format_signed_pct(change_pct, decimals=1)}")
    quote_volume = _safe_float(row.get("quote_volume_24h"))
    if quote_volume is not None:
        parts.append(f"vol {_fmt_compact_number(quote_volume)}")
    short_pct = _safe_float(row.get("short_account_pct"))
    long_pct = _safe_float(row.get("long_account_pct"))
    if short_pct is not None:
        parts.append(f"shorts {short_pct:.1f}%")
    if long_pct is not None:
        parts.append(f"longs {long_pct:.1f}%")
    parts.append(f"next {_next_funding_text(row.get('next_funding_time'))}")
    return " | ".join(parts)


def _load_funding_leaderboard(
    limit: int,
    *,
    side: str = "both",
    period: str = "1h",
    min_abs_funding_pct: float = 0.0,
) -> tuple[str, list[str]]:
    normalized_side = _normalize_funding_side(side)
    capped_limit = min(max(int(limit or 10), 1), 30)
    minimum_abs = max(0.0, float(min_abs_funding_pct or 0.0))
    ratio_period = str(period or "1h").strip() or "1h"

    try:
        client = BinanceFuturesPublic(
            timeout=_env_int("DISCORD_FUNDING_BINANCE_TIMEOUT_SECONDS", 10, minimum=3),
            requests_per_second=float(_env_value("DISCORD_FUNDING_REQUESTS_PER_SECOND", "8")),
            retries=_env_int("DISCORD_FUNDING_BINANCE_RETRIES", 2, minimum=1),
        )
        mark_rows = client.mark_price()
    except Exception as exc:
        return "Funding carry leaderboard", [f"Live Binance funding scan unavailable: {type(exc).__name__}: {exc}"]

    try:
        ticker_rows = client.ticker_24hr()
    except Exception:
        ticker_rows = []
    ticker_by_symbol = {
        str(item.get("symbol", "")).upper(): item
        for item in ticker_rows
        if str(item.get("symbol", "")).upper().endswith("USDT")
    }

    interval_by_symbol: dict[str, float] = {}
    try:
        for item in client.funding_info():
            symbol = str(item.get("symbol", "")).upper().strip()
            interval = _safe_float(item.get("fundingIntervalHours"))
            if symbol and interval is not None and interval > 0:
                interval_by_symbol[symbol] = interval
    except Exception:
        pass

    rows: list[dict[str, Any]] = []
    for item in mark_rows:
        symbol = str(item.get("symbol", "")).upper().strip()
        if not symbol.endswith("USDT"):
            continue
        funding_rate = _safe_float(item.get("lastFundingRate"))
        if funding_rate is None:
            continue
        funding_pct = funding_rate * 100.0
        if abs(funding_pct) < minimum_abs:
            continue
        interval_hours = interval_by_symbol.get(symbol, 8.0)
        ticker = ticker_by_symbol.get(symbol, {})
        annualized = funding_pct * (24.0 / max(interval_hours, 1e-9)) * 365.0
        rows.append(
            {
                "symbol": symbol,
                "funding_pct": funding_pct,
                "annualized_funding_pct": annualized,
                "funding_interval_hours": interval_hours,
                "next_funding_time": item.get("nextFundingTime"),
                "mark_price": item.get("markPrice"),
                "price_change_24h_pct": ticker.get("priceChangePercent"),
                "quote_volume_24h": ticker.get("quoteVolume"),
            }
        )

    positive_rows = sorted((row for row in rows if _safe_float(row.get("funding_pct")) and row["funding_pct"] > 0), key=lambda row: (-row["funding_pct"], row["symbol"]))
    negative_rows = sorted((row for row in rows if _safe_float(row.get("funding_pct")) and row["funding_pct"] < 0), key=lambda row: (row["funding_pct"], row["symbol"]))
    selected_rows = (
        positive_rows[:capped_limit] + negative_rows[:capped_limit]
        if normalized_side == "both"
        else positive_rows[:capped_limit]
        if normalized_side == "shorts"
        else negative_rows[:capped_limit]
    )

    if _env_bool("DISCORD_FUNDING_INCLUDE_ACCOUNT_RATIO", True):
        for row in selected_rows:
            long_pct, short_pct = _funding_account_percentages(client, _clean_scalar_text(row.get("symbol", "")), period=ratio_period)
            row["long_account_pct"] = long_pct
            row["short_account_pct"] = short_pct

    scanned_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "Funding carry leaderboard",
        f"Source: live Binance futures premiumIndex at {scanned_at}",
        "Read: positive funding = longs pay shorts; negative funding = shorts pay longs. Funding is current/last premiumIndex rate.",
        f"Side: {normalized_side} | Limit per side: {capped_limit} | Account-ratio period: {ratio_period} | Min abs funding: {minimum_abs:.4f}%",
        "",
    ]

    if normalized_side in {"both", "shorts"}:
        visible = positive_rows[:capped_limit]
        lines.append("Short-carry candidates (positive funding; shorts receive)")
        if visible:
            for row in visible:
                lines.append(_format_funding_row(row))
        else:
            lines.append("No positive-funding USDT perpetuals met the requested floor.")
        lines.append("")

    if normalized_side in {"both", "longs"}:
        visible = negative_rows[:capped_limit]
        lines.append("Long-carry candidates (negative funding; longs receive)")
        if visible:
            for row in visible:
                lines.append(_format_funding_row(row))
        else:
            lines.append("No negative-funding USDT perpetuals met the requested floor.")

    if not rows:
        lines.append("No USDT perpetual funding rows met the requested floor.")
    return "Funding carry leaderboard", _chunk_text_lines(lines)


def _load_cex_flow_list(
    limit: int,
    *,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_venue_gate: bool = True,
    title_prefix: str = "Wallet-to-CEX flow monitor",
) -> tuple[str, list[str]]:
    scan_mode = _env_value("DISCORD_CEX_FLOW_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep"
    effective_min_transfer = (
        max(0.0, float(min_tokens))
        if min_tokens is not None and _safe_float(min_tokens) is not None and float(min_tokens) > 0
        else _env_float("CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS", 500_000.0, minimum=0.0)
    )
    effective_lookback = (
        max(1, int(lookback_hours))
        if lookback_hours is not None and _safe_float(lookback_hours) is not None and int(lookback_hours) > 0
        else int(_env_float("CEX_DEPOSIT_FLOW_LOOKBACK_HOURS", 24.0, minimum=1.0))
    )
    frame, source = _fresh_scanner_frame(
        scan_mode,
        cex_min_transfer_tokens=effective_min_transfer,
        cex_lookback_hours=effective_lookback,
    )
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty and _source_is_unavailable(source):
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"

    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    header = (
        f"{title_prefix}\n"
        "The highest-signal read is concentrated holder inventory moving into labelled exchange wallets.\n"
        f"Source: {source} | Holder gate: observed top10 holder >= {effective_min_whale_pct:.1f}% | "
        f"Holder evidence required: {require_holder_evidence} | "
        f"Min transfer: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback:.0f}h | "
        f"{_thesis_venue_header() if require_venue_gate else 'Venue gate: disabled for this command'}"
    )
    if "fallback" in source.lower():
        header += "\nNote: fallback cache may have been generated with a different transfer threshold."
    if frame.empty:
        return title_prefix, [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]

    score = pd.to_numeric(frame.get("cex_deposit_flow_score", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    flag = _boolish_series(frame.get("cex_deposit_flow_flag", pd.Series(False, index=frame.index)), index=frame.index)
    raw_flow = frame[flag | score.gt(0.0)].copy()
    raw_flow_count = len(raw_flow)
    strict_flow = raw_flow[
        _strict_cex_holder_gate_mask(
            raw_flow,
            min_whale_pct=effective_min_whale_pct,
            require_holder_evidence=require_holder_evidence,
        )
    ].copy()
    flow = _apply_thesis_venue_gate(strict_flow) if require_venue_gate else strict_flow.copy()
    header += f"\nFlow rows before holder gate: {raw_flow_count} | After holder gate: {len(strict_flow)} | After venue gate: {len(flow)}"
    diagnostic_lines = _cex_flow_scan_diagnostic_lines(
        frame,
        min_whale_pct=effective_min_whale_pct,
        require_holder_evidence=require_holder_evidence,
    )
    diagnostic_text = "\n".join(diagnostic_lines)
    header += "\n" + diagnostic_text
    if flow.empty:
        if raw_flow_count > 0 and strict_flow.empty:
            message = (
                "Verified labelled CEX transfer rows exist, but none cleared the strict holder gate for this command. "
                "Use `require_holder_evidence:false` only to diagnose missing explorer holder-source snapshot coverage."
            )
        elif raw_flow_count > 0 and require_venue_gate:
            message = (
                "Strict holder-gated CEX transfer flow was found, but none of those rows also met the Binance+Bitget thesis venue gate. "
                "Retry with `require_venue_gate:false` to inspect all labelled CEX-flow rows."
            )
        elif "explorer blocked" in diagnostic_text.lower():
            message = (
                "No verified labelled CEX token-transfer rows were produced because explorer requests were blocked. "
                "Attempted-symbol rows are query attempts at the requested transfer floor, not confirmed transfers."
            )
        else:
            message = (
                "No concentration-gated labelled CEX token-transfer flow was found in the active scan coverage. "
                "That can mean no matching transfers, missing contract hints, unsupported explorer data, or rows outside the scanned universe."
            )
        lines = [header, "", message]
        attempted_lines = _cex_flow_attempt_symbol_lines(
            frame,
            limit=limit,
            min_transfer_tokens=effective_min_transfer,
            min_whale_pct=effective_min_whale_pct,
            require_holder_evidence=require_holder_evidence,
        )
        if attempted_lines:
            lines.extend(["", *attempted_lines])
        return (
            title_prefix,
            _chunk_text_lines(lines),
        )

    flow["_cex_flow_score"] = pd.to_numeric(flow.get("cex_deposit_flow_score"), errors="coerce").fillna(0.0)
    flow["_cex_total_pct"] = pd.to_numeric(
        flow.get("cex_deposit_24h_total_pct_supply", pd.Series(0.0, index=flow.index)),
        errors="coerce",
    ).fillna(0.0)
    flow["_cex_count"] = pd.to_numeric(
        flow.get("cex_deposit_24h_count", pd.Series(0.0, index=flow.index)),
        errors="coerce",
    ).fillna(0.0)
    flow = flow.sort_values(
        ["_cex_flow_score", "_cex_total_pct", "_cex_count", "symbol"],
        ascending=[False, False, False, True],
    ).head(min(max(int(limit), 1), 100))

    summary = "Candidates: " + " ".join(f"/{str(symbol).upper().strip()}" for symbol in flow.get("symbol", pd.Series(dtype="object")).tolist())
    lines = [header, "", summary, ""]
    for _, row in flow.iterrows():
        lines.append(build_cex_flow_discord_block(row, max_chars=900))
        lines.append("")
    return title_prefix, _chunk_text_lines(lines)


def _load_cex_flow_diagnostics(
    *,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_venue_gate: bool = True,
    symbol_limit: int = 15,
) -> tuple[str, str]:
    scan_mode = _env_value("DISCORD_CEX_FLOW_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep"
    effective_min_transfer = (
        max(0.0, float(min_tokens))
        if min_tokens is not None and _safe_float(min_tokens) is not None and float(min_tokens) > 0
        else _env_float("CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS", 500_000.0, minimum=0.0)
    )
    effective_lookback = (
        max(1, int(lookback_hours))
        if lookback_hours is not None and _safe_float(lookback_hours) is not None and int(lookback_hours) > 0
        else int(_env_float("CEX_DEPOSIT_FLOW_LOOKBACK_HOURS", 24.0, minimum=1.0))
    )
    frame, source = _fresh_scanner_frame(
        scan_mode,
        cex_min_transfer_tokens=effective_min_transfer,
        cex_lookback_hours=effective_lookback,
    )
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty and _source_is_unavailable(source):
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"

    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    header = (
        "CEX-flow scan diagnostics\n"
        f"Source: {source} | Holder gate: observed top10 holder >= {effective_min_whale_pct:.1f}% | "
        f"Holder evidence required: {require_holder_evidence} | "
        f"Min transfer: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback:.0f}h | "
        f"{_thesis_venue_header() if require_venue_gate else 'Venue gate: disabled for this command'}"
    )
    if "fallback" in source.lower():
        header += "\nNote: fallback cache may have been generated with a different transfer threshold."
    if frame.empty:
        return "CEX-flow scan diagnostics", header + "\n\nNo live scan, scanner snapshot, or cache exists yet."

    score = pd.to_numeric(frame.get("cex_deposit_flow_score", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    flag = _boolish_series(frame.get("cex_deposit_flow_flag", pd.Series(False, index=frame.index)), index=frame.index)
    raw_flow = frame[flag | score.gt(0.0)].copy()
    strict_flow = raw_flow[
        _strict_cex_holder_gate_mask(
            raw_flow,
            min_whale_pct=effective_min_whale_pct,
            require_holder_evidence=require_holder_evidence,
        )
    ].copy()
    flow = _apply_thesis_venue_gate(strict_flow) if require_venue_gate else strict_flow.copy()
    lines = [
        header,
        f"Flow rows before holder gate: {len(raw_flow)} | After holder gate: {len(strict_flow)} | After venue gate: {len(flow)}",
        *_cex_flow_scan_diagnostic_lines(
            frame,
            min_whale_pct=effective_min_whale_pct,
            require_holder_evidence=require_holder_evidence,
        ),
        "",
        *_cex_flow_attempt_symbol_lines(
            frame,
            limit=symbol_limit,
            min_transfer_tokens=effective_min_transfer,
            min_whale_pct=effective_min_whale_pct,
            require_holder_evidence=require_holder_evidence,
        ),
        "",
        "Read: zero raw flow means no verified labelled CEX-transfer rows were produced.",
        "When HTTP 403 dominates, the scanner tries Etherscan V2 token-transfer APIs; label coverage then becomes the next bottleneck.",
        "Blocked attempted-symbol rows are query attempts at the requested transfer floor, not confirmed transfers.",
        "Use `/flowcoin symbol:<symbol>` for single-coin detail/query URL and `/flowhealth` for API-key/address-label coverage.",
    ]
    return "CEX-flow scan diagnostics", "\n".join(lines)[:DISCORD_EMBED_DESCRIPTION_LIMIT]


def _load_early_flow_list(
    limit: int,
    *,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_venue_gate: bool = True,
) -> tuple[str, list[str]]:
    default_min = _env_float("DISCORD_EARLY_FLOW_MIN_TOKENS", 20_000.0, minimum=0.0)
    return _load_cex_flow_list(
        limit,
        min_tokens=default_min if min_tokens is None else min_tokens,
        lookback_hours=lookback_hours,
        min_whale_pct=min_whale_pct,
        require_holder_evidence=require_holder_evidence,
        require_venue_gate=require_venue_gate,
        title_prefix="Early wallet-to-CEX flow sweep",
    )


def _load_symbol_cex_flow(symbol_query: str, *, min_tokens: float | None = None, lookback_hours: int | None = None) -> tuple[str, str]:
    symbol = _normalize_symbol_query(symbol_query)
    if not symbol:
        return "Symbol CEX flow", "Use `/flowcoin symbol:PLAYUSDT min_tokens:20000`."
    scan_mode = _env_value("DISCORD_CEX_FLOW_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep"
    effective_min_transfer = (
        max(0.0, float(min_tokens))
        if min_tokens is not None and _safe_float(min_tokens) is not None and float(min_tokens) > 0
        else _env_float("CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS", 500_000.0, minimum=0.0)
    )
    effective_lookback = (
        max(1, int(lookback_hours))
        if lookback_hours is not None and _safe_float(lookback_hours) is not None and int(lookback_hours) > 0
        else int(_env_float("CEX_DEPOSIT_FLOW_LOOKBACK_HOURS", 24.0, minimum=1.0))
    )
    frame, source = _fresh_scanner_frame(
        scan_mode,
        cex_min_transfer_tokens=effective_min_transfer,
        cex_lookback_hours=effective_lookback,
    )
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty and _source_is_unavailable(source):
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    row = _row_for_symbol(frame, symbol)
    if row is None:
        return f"{symbol} CEX flow", f"No scan row found for {symbol}. Source: {source or 'unavailable'}"
    header = (
        f"Source: {source}\n"
        f"Min transfer: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h | "
        f"{_thesis_venue_header()} | Symbol detail is not filtered"
    )
    if "fallback" in source.lower():
        header += "\nNote: fallback cache may have been generated with a different transfer threshold."
    return f"{symbol} CEX flow", (header + "\n\n" + build_cex_flow_discord_block(row, max_chars=1500))[:DISCORD_EMBED_DESCRIPTION_LIMIT]


def _cex_scan_frame_for_commands(
    *,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
) -> tuple[pd.DataFrame, str, float, int]:
    scan_mode = _env_value("DISCORD_CEX_FLOW_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep"
    effective_min_transfer = (
        max(0.0, float(min_tokens))
        if min_tokens is not None and _safe_float(min_tokens) is not None and float(min_tokens) > 0
        else _env_float("CEX_DEPOSIT_FLOW_MIN_TRANSFER_TOKENS", 500_000.0, minimum=0.0)
    )
    effective_lookback = (
        max(1, int(lookback_hours))
        if lookback_hours is not None and _safe_float(lookback_hours) is not None and int(lookback_hours) > 0
        else int(_env_float("CEX_DEPOSIT_FLOW_LOOKBACK_HOURS", 24.0, minimum=1.0))
    )
    frame, source = _fresh_scanner_frame(
        scan_mode,
        cex_min_transfer_tokens=effective_min_transfer,
        cex_lookback_hours=effective_lookback,
    )
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty and _source_is_unavailable(source):
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    return frame, source, effective_min_transfer, effective_lookback


def _load_flow_stress_list(
    limit: int,
    *,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    require_venue_gate: bool = True,
) -> tuple[str, list[str]]:
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    header = (
        "CEX inventory-stress monitor\n"
        f"Source: {source} | Min transfer: {_fmt_compact_number(effective_min_transfer)} tokens | "
        f"Lookback: {effective_lookback}h | "
        f"{_thesis_venue_header() if require_venue_gate else 'Venue gate: disabled for this command'}"
        "\nRead: inventory-stress context rows; baseThesis Y means strict holder+venue+60D no-pump gate also passed."
    )
    if frame.empty:
        return "CEX inventory-stress monitor", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]
    stress = pd.to_numeric(
        frame.get("cex_deposit_inventory_stress_score", pd.Series(0.0, index=frame.index)),
        errors="coerce",
    ).fillna(0.0)
    score = pd.to_numeric(frame.get("cex_deposit_flow_score", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    rows = frame[(stress.gt(0.0)) | (score.gt(0.0))].copy()
    raw_count = len(rows)
    if require_venue_gate and not rows.empty:
        rows = _apply_thesis_venue_gate(rows)
    header += f"\nInventory-stress rows before venue gate: {raw_count} | After venue gate: {len(rows)}"
    if rows.empty:
        return "CEX inventory-stress monitor", [header + "\n\nNo CEX inventory-stress rows found in the active scan coverage."]
    rows["_flow_stress"] = stress.loc[rows.index]
    rows["_flow_score"] = score.loc[rows.index]
    rows["_discord_base_thesis_gate"] = _thesis_candidate_gate_mask(rows)
    rows = rows.sort_values(["_flow_stress", "_flow_score", "symbol"], ascending=[False, False, True]).head(min(max(int(limit), 1), 100))
    base_thesis_count = int(_boolish_series(rows.get("_discord_base_thesis_gate"), index=rows.index).sum())
    lines = [
        header,
        f"Stress rows: {len(rows)} | Base thesis gate: {base_thesis_count}",
        "",
        "Stress rows: " + " ".join(f"/{str(symbol).upper().strip()}" for symbol in rows["symbol"].tolist()),
        "",
    ]
    for _, row in rows.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        stress_value = _safe_float(row.get("cex_deposit_inventory_stress_score")) or 0.0
        flow_score = _safe_float(row.get("cex_deposit_flow_score")) or 0.0
        targets = _clip_text(row.get("cex_deposit_24h_target_exchanges", ""), 50) or "labelled CEX"
        notional = _fmt_compact_number(row.get("cex_deposit_24h_notional_usd"))
        depth_pct = _safe_float(row.get("cex_deposit_24h_notional_to_ask_depth_pct"))
        depth_text = f" | deposits/ask {depth_pct:.1f}%" if depth_pct is not None else ""
        source_text = _clip_text(row.get("cex_deposit_flow_source", ""), 40)
        note = _clip_text(_first_nonempty_text(row.get("cex_deposit_inventory_stress_note", ""), row.get("cex_deposit_flow_note", "")), 160)
        base_thesis = "Y" if _boolish_scalar(row.get("_discord_base_thesis_gate")) else "N"
        lines.append(
            f"/{symbol} | stress {stress_value:.0f}/100 | flow {flow_score:.0f}/100 | {targets} | "
            f"notional {notional}{depth_text} | baseThesis {base_thesis} | source {source_text or 'n/a'}"
        )
        if note:
            lines.append(f"  {note}")
    return "CEX inventory-stress monitor", _chunk_text_lines(lines)


def _load_flow_blocked_list(
    limit: int,
    *,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
) -> tuple[str, list[str]]:
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    header = (
        "CEX-flow blocked/error rows\n"
        f"Source: {source} | Min transfer: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h"
    )
    if frame.empty:
        return "CEX-flow blocked/error rows", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]
    error_text = _text_series(frame, "cex_deposit_flow_error")
    rows = frame[error_text.ne("")].copy()
    if rows.empty:
        return "CEX-flow blocked/error rows", [header + "\n\nNo CEX-flow blocked/error rows in the active scan."]
    rows["_http403"] = error_text.loc[rows.index].str.contains("HTTP 403", case=False, regex=False)
    rows["_symbol"] = rows.get("symbol", pd.Series("", index=rows.index)).astype(str)
    rows = rows.sort_values(["_http403", "_symbol"], ascending=[False, True]).head(min(max(int(limit), 1), 100))
    lines = [header, f"Blocked/error rows: {len(frame[error_text.ne('')])}", ""]
    for _, row in rows.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        source_url = _clip_text(row.get("cex_deposit_24h_source_url", ""), 90)
        source_kind = _clip_text(row.get("cex_deposit_flow_source", ""), 50)
        error = _clip_text(row.get("cex_deposit_flow_error", ""), 170)
        lines.append(f"/{symbol} | {error} | source {source_kind or 'n/a'}")
        if source_url:
            lines.append(f"  {source_url}")
    lines.append("")
    lines.append("Read: these are data-source failures or no labelled API matches, not proof that CEX flow is absent.")
    return "CEX-flow blocked/error rows", _chunk_text_lines(lines)


def _load_flow_health(*, min_tokens: float | None = None, lookback_hours: int | None = None, symbol_limit: int = 10) -> tuple[str, str]:
    title, diagnostics = _load_cex_flow_diagnostics(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
        require_venue_gate=False,
        symbol_limit=symbol_limit,
    )
    api_lines = ["", "API fallback readiness:"]
    for chain in sorted(TOKEN_TRANSFER_API_CONFIGS):
        env_keys = token_transfer_api_key_envs(chain)
        present_keys = [env_key for env_key in env_keys if _env_value(env_key, "")]
        key_text = "key present" if present_keys else "no key"
        env_text = " or ".join(env_keys) if env_keys else "unsupported"
        api_lines.append(f"- {chain}: {key_text} ({env_text})")
    address_book = load_cex_address_book()
    api_lines.append(f"- CEX address labels loaded: {len(address_book)}")
    api_lines.append("- Configure CEX_ADDRESS_LABELS or CEX_ADDRESS_BOOK_FILE to classify API token-transfer destinations without scraping explorer labels.")
    return "CEX-flow health", (diagnostics + "\n" + "\n".join(api_lines))[:DISCORD_EMBED_DESCRIPTION_LIMIT]


TARGET_CEX_PATTERN = re.compile(r"\b(?:binance|bitget|gate(?:\.io|io)?)\b", flags=re.IGNORECASE)
BINANCE_PATTERN = re.compile(r"\bbinance\b", flags=re.IGNORECASE)
BITGET_PATTERN = re.compile(r"\bbitget\b", flags=re.IGNORECASE)
GATE_PATTERN = re.compile(r"\bgate(?:\.io|io)?\b", flags=re.IGNORECASE)


def _target_cex_text(row: pd.Series) -> str:
    targets = _clip_text(row.get("cex_deposit_24h_target_exchanges", ""), 60)
    return targets if TARGET_CEX_PATTERN.search(targets) else ""


def _venue_evidence_text(row: pd.Series) -> str:
    targets = _clean_scalar_text(row.get("cex_deposit_24h_target_exchanges", ""))
    top_venue = _clean_scalar_text(row.get("top_venue", ""))

    def evidence(label: str, pattern: re.Pattern[str], share_column: str, *, implicit_perp: bool = False) -> str:
        parts: list[str] = []
        if implicit_perp:
            parts.append("perp")
        share = _safe_float(row.get(share_column))
        if share is not None and share > 0:
            parts.append(f"{share:.1f}%")
        if top_venue and pattern.search(top_venue):
            parts.append("top")
        if targets and pattern.search(targets):
            parts.append("target")
        return f"{label} {','.join(parts[:3]) if parts else 'no'}"

    return "; ".join(
        [
            evidence("Bn", BINANCE_PATTERN, "binance_volume_share_pct", implicit_perp=_boolish_scalar(row.get("_ravelab_binance_perp_universe"))),
            evidence("Bg", BITGET_PATTERN, "bitget_volume_share_pct"),
            evidence("Gate", GATE_PATTERN, "gate_volume_share_pct"),
        ]
    )


def _short_contract_text(contract: Any) -> str:
    text = _clean_scalar_text(contract)
    if not text:
        return ""
    return f"{text[:6]}...{text[-4:]}" if len(text) > 14 else text


def _holder_chain_key(row: pd.Series) -> str:
    chain = _first_nonempty_text(row.get("token_platform", ""), row.get("chain", ""), row.get("token_chain", ""))
    return normalize_chain(chain) if chain else ""


def _holder_contract_address(row: pd.Series) -> str:
    return clean_contract_address(_first_nonempty_text(row.get("token_contract", ""), row.get("contract_address", ""), row.get("contract", "")))


def _holder_evidence_text(row: pd.Series) -> str:
    raw_chain = _first_nonempty_text(row.get("token_platform", ""), row.get("chain", ""), row.get("token_chain", ""))
    chain = normalize_chain(raw_chain) if raw_chain else ""
    source = _first_nonempty_text(row.get("holder_source", ""), row.get("holder_data_source", ""))
    contract = _holder_contract_address(row)
    holders = _safe_float(row.get("holder_count"))
    top10 = _safe_pct(row.get("top10_holder_pct"))
    top100 = _safe_pct(row.get("top100_holder_pct"))
    has_snapshot = bool((holders is not None and holders > 0) or top10 is not None or top100 is not None)
    explorer_source = bool(source and HOLDER_EXPLORER_SOURCE_PATTERN.search(source))

    parts: list[str] = []
    if chain:
        parts.append(f"chain {chain}")
    if holders is not None and holders > 0:
        parts.append(f"holders {holders:.0f}")
    concentration_parts: list[str] = []
    if top10 is not None:
        concentration_parts.append(f"top10 {top10:.1f}%")
    if top100 is not None:
        concentration_parts.append(f"top100 {top100:.1f}%")
    if concentration_parts:
        parts.append(" / ".join(concentration_parts))
    if source:
        parts.append(f"src {_clip_text(source, 28)}")
    if contract:
        parts.append(f"contract {_short_contract_text(contract)}")
    strict_ok = chain in RAVELAB_HOLDER_EVIDENCE_CHAINS and bool(contract) and explorer_source and has_snapshot
    if strict_ok:
        return ", ".join(parts)
    missing: list[str] = []
    if chain not in RAVELAB_HOLDER_EVIDENCE_CHAINS:
        missing.append(f"{RAVELAB_HOLDER_EVIDENCE_CHAIN_LABEL} chain")
    if not contract:
        missing.append("contract")
    if not source:
        missing.append("source")
    elif not explorer_source:
        missing.append("explorer source")
    if not has_snapshot:
        missing.append("holder snapshot")
    detail = ", ".join(parts) if parts else "pct-only"
    return f"{detail}; needs {'+'.join(missing)}"


def _holder_snapshot_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    masks: list[pd.Series] = []
    if "holder_count" in frame.columns:
        masks.append(pd.to_numeric(frame["holder_count"], errors="coerce").gt(0.0).fillna(False))
    for column in ("top10_holder_pct", "top100_holder_pct"):
        if column in frame.columns:
            masks.append(frame[column].map(_safe_pct).notna())
    if not masks:
        return pd.Series(False, index=frame.index)
    return pd.concat(masks, axis=1).any(axis=1).fillna(False)


def _strict_holder_evidence_masks(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if frame.empty:
        empty = pd.Series(False, index=frame.index)
        return empty, empty
    source_cols = [column for column in ("holder_source", "holder_data_source") if column in frame.columns]
    contract_mask = frame.apply(lambda row: bool(_holder_contract_address(row)), axis=1).astype(bool)
    chain_mask = frame.apply(lambda row: _holder_chain_key(row) in RAVELAB_HOLDER_EVIDENCE_CHAINS, axis=1).astype(bool)
    snapshot_mask = _holder_snapshot_mask(frame)
    if source_cols:
        source_mask = pd.concat(
            [
                _text_series(frame, column).str.contains(HOLDER_EXPLORER_SOURCE_PATTERN, regex=True, na=False)
                for column in source_cols
            ],
            axis=1,
        ).any(axis=1)
    else:
        source_mask = pd.Series(False, index=frame.index)
    evidence_mask = chain_mask & contract_mask & source_mask & snapshot_mask
    return evidence_mask.fillna(False), contract_mask.fillna(False)


def _strict_top10_thesis_holder_gate_mask(
    frame: pd.DataFrame,
    *,
    min_whale_pct: float = THESIS_MIN_TOP10_WHALE_PCT,
    require_holder_evidence: bool = True,
) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    threshold = _strict_thesis_min_whale_pct(min_whale_pct)
    gate = _safe_pct_series(frame, "top10_holder_pct").fillna(0.0).ge(threshold)
    if require_holder_evidence:
        holder_evidence_mask, _ = _strict_holder_evidence_masks(frame)
        gate = gate & holder_evidence_mask
    return gate.fillna(False)


def _strict_cex_holder_gate_mask(
    frame: pd.DataFrame,
    *,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    threshold = _strict_thesis_min_whale_pct(min_whale_pct)
    gate = _safe_pct_series(frame, "top10_holder_pct").fillna(0.0).ge(threshold)
    if require_holder_evidence:
        holder_evidence_mask, _ = _strict_holder_evidence_masks(frame)
        gate = gate & holder_evidence_mask
    return gate.fillna(False)


def _binance_bitget_trading_gate_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    top_venue = _text_series(frame, "top_venue")
    symbols = _text_series(frame, "symbol")
    explicit_binance_perp = (
        _boolish_series(frame.get("binance_perp_universe"), index=frame.index)
        | _boolish_series(frame.get("is_binance_perp"), index=frame.index)
        | _boolish_series(frame.get("_ravelab_binance_perp_universe"), index=frame.index)
    )
    implicit_binance_perp = symbols.ne("") if _env_bool("DISCORD_ASSUME_SYMBOLS_ARE_BINANCE_PERPS", False) else pd.Series(False, index=frame.index)
    has_binance = (
        explicit_binance_perp
        | implicit_binance_perp
        | _num_series(frame, "binance_volume_share_pct").gt(0.0)
        | top_venue.str.contains(BINANCE_PATTERN, na=False)
    )
    has_bitget = _num_series(frame, "bitget_volume_share_pct").gt(0.0) | top_venue.str.contains(BITGET_PATTERN, na=False)
    return (has_binance & has_bitget).fillna(False)


def _explicit_binance_bitget_trading_gate_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    top_venue = _text_series(frame, "top_venue")
    explicit_binance_perp = (
        _boolish_series(frame.get("binance_perp_universe"), index=frame.index)
        | _boolish_series(frame.get("is_binance_perp"), index=frame.index)
    )
    has_binance = explicit_binance_perp | _num_series(frame, "binance_volume_share_pct").gt(0.0) | top_venue.str.contains(BINANCE_PATTERN, na=False)
    has_bitget = _num_series(frame, "bitget_volume_share_pct").gt(0.0) | top_venue.str.contains(BITGET_PATTERN, na=False)
    return (has_binance & has_bitget).fillna(False)


def _thesis_venue_header() -> str:
    return "Venue gate: explicit Binance perp marker/share/top venue + Bitget trading evidence required; Gate is optional evidence only"


def _thesis_candidate_header(*, min_whale_pct: float = 90.0, core: bool = False) -> str:
    threshold = _strict_thesis_min_whale_pct(min_whale_pct)
    text = (
        f"Thesis gate: observed top10 holder >= {threshold:.1f}% with "
        f"{RAVELAB_HOLDER_EVIDENCE_CHAIN_LABEL} chain+contract explorer holder-source snapshot evidence | "
        f"{_thesis_venue_header()} | 60D no-pump/dormancy proof required"
    )
    if core:
        text += " | Core setup also requires short majority, low-float/high-FDV, and not-late structure"
    return text


def _apply_thesis_venue_gate(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame[_explicit_binance_bitget_trading_gate_mask(frame)].copy()


def _thesis_candidate_gate_mask(frame: pd.DataFrame, *, min_whale_pct: float = 90.0) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    holder_gate = _strict_top10_thesis_holder_gate_mask(
        frame,
        min_whale_pct=min_whale_pct,
        require_holder_evidence=True,
    )
    return (holder_gate & _explicit_binance_bitget_trading_gate_mask(frame) & _no_recent_pump_proof_mask(frame)).fillna(False)


def _apply_thesis_candidate_gate(frame: pd.DataFrame, *, min_whale_pct: float = 90.0) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame[_thesis_candidate_gate_mask(frame, min_whale_pct=min_whale_pct)].copy()


def _apply_core_thesis_candidate_gate(frame: pd.DataFrame, *, min_whale_pct: float = 90.0, min_short_pct: float = 50.0) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    scored = _goal_score_frame(frame, min_whale_pct=min_whale_pct, min_short_pct=min_short_pct)
    return scored[_boolish_series(scored.get("_goal_core_setup_pass"), index=scored.index)].copy()


def _no_recent_pump_proof_mask(
    frame: pd.DataFrame,
    *,
    min_history_days: int = 60,
    max_recent_pump_pct: float = 35.0,
) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    min_days = max(1, int(min_history_days))
    proof_days = max(1, min(60, min_days))
    history_days = pd.to_numeric(frame.get("history_days", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    recent_pump_days = pd.to_numeric(frame.get("recent_pump_60d_days", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    recent_pump = pd.to_numeric(frame.get("recent_max_pump_60d_pct", pd.Series(float("nan"), index=frame.index)), errors="coerce")
    no_large_flag = _boolish_series(frame.get("no_large_pump_60d_flag"), index=frame.index)
    coverage = history_days.ge(min_days) | recent_pump_days.ge(proof_days)
    pump_window_ready = recent_pump_days.ge(proof_days)
    numeric_pass = recent_pump.notna() & recent_pump.lt(max(0.0, float(max_recent_pump_pct))) & pump_window_ready
    flag_pass = no_large_flag & pump_window_ready
    return (coverage & (numeric_pass | flag_pass)).fillna(False)


def _seth_structure_state(
    row: pd.Series,
    *,
    max_range_pct: float,
    max_day_move_pct: float,
    no_recent_pump_pass: bool,
) -> tuple[str, bool, float, str]:
    setup_score = max(
        _safe_float(row.get("dormant_short_fuse_score")) or 0.0,
        _safe_float(row.get("pre_pump_precision_score")) or 0.0,
        _safe_float(row.get("rave_lab_setup_score")) or 0.0,
        _safe_float(row.get("terminal_pre_ignition_quality_score")) or 0.0,
        _safe_float(row.get("timing_early_score")) or 0.0,
    )
    range_pct = _safe_float(row.get("range_24h_pct")) or 0.0
    day_move = _safe_float(row.get("day_return_pct"))
    if day_move is None:
        day_move = _safe_float(row.get("price_change_24h_pct")) or 0.0
    too_late = _safe_float(row.get("timing_too_late_score")) or 0.0
    volatile = range_pct >= max_range_pct or abs(day_move) >= max_day_move_pct or too_late >= 65.0
    if volatile:
        reasons: list[str] = []
        if range_pct >= max_range_pct:
            reasons.append(f"24h range {range_pct:.1f}%")
        if abs(day_move) >= max_day_move_pct:
            reasons.append(f"24h move {day_move:.1f}%")
        if too_late >= 65.0:
            reasons.append(f"late score {too_late:.0f}")
        return "volatile/late", False, setup_score, ", ".join(reasons[:3])
    if not no_recent_pump_pass:
        return "dormancy unproven", False, setup_score, "missing/failed 60D no-pump proof"
    if setup_score >= 55.0:
        return "dormant candidate", True, setup_score, f"setup {setup_score:.0f}"
    if setup_score >= 35.0:
        return "early watch", True, setup_score, f"setup {setup_score:.0f}"
    return "structure unclear", False, setup_score, f"setup {setup_score:.0f}"


def _load_seth_flow_playbook(
    limit: int,
    *,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    min_short_pct: float = 50.0,
    min_whale_pct: float = 90.0,
    require_whale_origin_flow: bool = True,
    require_dormant: bool = True,
    require_venue_gate: bool = True,
    require_holder_evidence: bool = True,
    max_range_pct: float = 35.0,
    max_day_move_pct: float = 30.0,
) -> tuple[str, list[str]]:
    require_venue_gate = True
    require_holder_evidence = True
    require_dormant = True
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    header = (
        "Seth flow checklist\n"
        f"Source: {source} | Confirmed target-CEX flow only | Min transfer: >= {_fmt_compact_number(effective_min_transfer)} tokens | "
        f"Lookback: {effective_lookback}h | Target CEX: Binance, Gate.io, Bitget | Whale gate: top10 holder >= {effective_min_whale_pct:.1f}% | "
        f"Holder evidence required: {require_holder_evidence} | Short gate: >= {min_short_pct:.1f}% | "
        "Float gate: low-float/FDV evidence required | "
        f"Whale-origin flow required: {require_whale_origin_flow} | "
        f"{_thesis_venue_header() if require_venue_gate else 'Venue gate: disabled for this command'} | "
        f"Structure gate: {'dormant/early only' if require_dormant else 'show volatile too'}"
    )
    if "fallback" in source.lower():
        header += "\nNote: fallback cache may have been generated with a different transfer threshold."
    if frame.empty:
        return "Seth flow checklist", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]

    frame = apply_timing_model(apply_terminal_model(frame.loc[:, ~frame.columns.duplicated()].copy()))
    score = pd.to_numeric(frame.get("cex_deposit_flow_score", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    flag = _boolish_series(frame.get("cex_deposit_flow_flag", pd.Series(False, index=frame.index)), index=frame.index)
    count = pd.to_numeric(frame.get("cex_deposit_24h_count", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    max_amount = pd.to_numeric(frame.get("cex_deposit_24h_max_amount", pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
    targets = _text_series(frame, "cex_deposit_24h_target_exchanges")
    target_mask = targets.str.contains(TARGET_CEX_PATTERN, regex=True)
    flow_mask = (flag | score.gt(0.0)) & count.gt(0.0) & max_amount.ge(effective_min_transfer) & target_mask
    raw_target_flow = frame[flow_mask].copy()
    if not raw_target_flow.empty:
        raw_target_flow = raw_target_flow[_explicit_binance_bitget_trading_gate_mask(raw_target_flow)].copy()

    if raw_target_flow.empty:
        raw_count = int(((flag | score.gt(0.0)) & count.gt(0.0)).sum())
        target_count = int(flow_mask.sum())
        return (
            "Seth flow checklist",
            [
                header
                + f"\n\nConfirmed CEX flow rows: {raw_count} | Target Binance/Gate/Bitget rows: {target_count}"
                + "\nNo confirmed target-CEX flow rows met the requested floor. Blocked/error rows are not transfer confirmations."
            ],
        )

    rows = raw_target_flow.copy()
    top10 = pd.to_numeric(rows.get("top10_holder_pct", pd.Series(0.0, index=rows.index)), errors="coerce")
    top100 = pd.to_numeric(rows.get("top100_holder_pct", pd.Series(0.0, index=rows.index)), errors="coerce")
    shorts = pd.to_numeric(rows.get("short_account_pct", pd.Series(0.0, index=rows.index)), errors="coerce")
    float_score = _max_series(
        rows,
        "low_float_score",
        "float_trap_score",
        "terminal_float_score",
        "terminal_hidden_float_reflexivity_score",
        default=0.0,
    )
    fdv_score = _score_linear_series(_num_series(rows, "fdv_to_market_cap"), 1.8, 12.0)
    locked_score = _score_linear_series(_num_series(rows, "locked_supply_pct"), 15.0, 85.0)
    rows["_seth_float_score"] = pd.concat([float_score, fdv_score, locked_score], axis=1).max(axis=1).fillna(0.0)
    rows["_seth_float_pass"] = rows["_seth_float_score"].ge(55.0)
    holder_evidence_mask, _ = _strict_holder_evidence_masks(rows)
    whale_pct = top10.fillna(0.0)
    rows["_seth_whale_pct"] = whale_pct
    rows["_seth_holder_evidence_pass"] = holder_evidence_mask
    rows["_seth_whale_concentration_pass"] = whale_pct.ge(effective_min_whale_pct)
    rows["_seth_whale_pass"] = rows["_seth_whale_concentration_pass"] & (
        rows["_seth_holder_evidence_pass"] if require_holder_evidence else True
    )
    rows["_seth_whale_origin_flow"] = (
        rows.apply(_whale_sender_qualifies, axis=1).astype(bool)
        & _num_series(rows, "cex_deposit_24h_whale_sender_count").gt(0.0)
        & _num_series(rows, "cex_deposit_24h_whale_sender_token_amount").ge(effective_min_transfer)
    )
    rows["_seth_short_pass"] = shorts.ge(min_short_pct)
    rows["_seth_no_recent_pump_pass"] = _no_recent_pump_proof_mask(rows)
    structure_states: list[str] = []
    structure_passes: list[bool] = []
    structure_scores: list[float] = []
    structure_reasons: list[str] = []
    for _, row in rows.iterrows():
        state, passed, setup_score, reason = _seth_structure_state(
            row,
            max_range_pct=max_range_pct,
            max_day_move_pct=max_day_move_pct,
            no_recent_pump_pass=bool(rows.at[row.name, "_seth_no_recent_pump_pass"]),
        )
        structure_states.append(state)
        structure_passes.append(passed)
        structure_scores.append(setup_score)
        structure_reasons.append(reason)
    rows["_seth_structure_state"] = structure_states
    rows["_seth_structure_pass"] = structure_passes
    rows["_seth_structure_score"] = structure_scores
    rows["_seth_structure_reason"] = structure_reasons
    rows["_seth_flow_score"] = score.loc[rows.index]
    rows["_seth_short_pct"] = shorts.fillna(0.0)
    rows["_seth_score"] = (
        rows["_seth_flow_score"] * 0.38
        + rows["_seth_structure_score"] * 0.20
        + ((rows["_seth_short_pct"] - min_short_pct) * 3.0).clip(lower=0.0, upper=100.0) * 0.16
        + rows["_seth_whale_pct"].fillna(0.0).clip(upper=100.0) * 0.18
        + rows["_seth_float_score"] * 0.08
    )
    rows["_seth_all_pass"] = (
        rows["_seth_whale_pass"]
        & (rows["_seth_whale_origin_flow"] if require_whale_origin_flow else True)
        & rows["_seth_float_pass"]
        & rows["_seth_short_pass"]
        & rows["_seth_structure_pass"]
        & rows["_seth_no_recent_pump_pass"]
    )
    visible = rows[rows["_seth_all_pass"]].copy() if require_dormant else rows.copy()
    if visible.empty:
        visible = rows.sort_values(["_seth_short_pass", "_seth_whale_pass", "_seth_score", "symbol"], ascending=[False, False, False, True]).head(
            min(max(int(limit), 1), 100)
        )
        empty_note = "\nNo rows passed every gate; showing nearest confirmed target-CEX flow rows for diagnosis."
    else:
        empty_note = ""
    visible = visible.sort_values(
        ["_seth_all_pass", "_seth_whale_origin_flow", "_seth_score", "_seth_flow_score", "symbol"],
        ascending=[False, False, False, False, True],
    ).head(min(max(int(limit), 1), 100))

    pass_count = int(rows["_seth_all_pass"].sum())
    whale_origin_count = int(rows["_seth_whale_origin_flow"].sum())
    lines = [
        header,
        f"Confirmed target-CEX flow rows: {len(raw_target_flow)} | Whale-origin rows: {whale_origin_count} | Full checklist pass: {pass_count}{empty_note}",
        "",
        "Checklist: 1 massive target-CEX flow -> 2 top-holder sender -> 3 whale dominated -> 4 low-float/FDV -> 5 >50% short accounts -> 6 dormant/early, not already wild -> 7 research state.",
        "",
        "Candidates: " + " ".join(f"/{str(symbol).upper().strip()}" for symbol in visible.get("symbol", pd.Series(dtype='object')).tolist()),
        "",
    ]
    for _, row in visible.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        flow_score = _safe_float(row.get("cex_deposit_flow_score")) or 0.0
        cex_count = int(_safe_float(row.get("cex_deposit_24h_count")) or 0)
        total_amount = _fmt_compact_number(row.get("cex_deposit_24h_token_amount"))
        max_transfer = _fmt_compact_number(row.get("cex_deposit_24h_max_amount"))
        short_pct = _safe_float(row.get("short_account_pct")) or 0.0
        row_top10 = _safe_float(row.get("top10_holder_pct"))
        row_top100 = _safe_float(row.get("top100_holder_pct"))
        row_float = _safe_float(row.get("_seth_float_score")) or 0.0
        range_pct = _safe_float(row.get("range_24h_pct"))
        day_move = _safe_float(row.get("day_return_pct"))
        if day_move is None:
            day_move = _safe_float(row.get("price_change_24h_pct"))
        targets_text = _target_cex_text(row) or "target CEX"
        state = str(row.get("_seth_structure_state", "structure unclear"))
        action = (
            "RESEARCH: whale-origin dormant candidate; wait for absorption/reclaim evidence"
            if require_whale_origin_flow or _boolish_scalar(row.get("_seth_whale_origin_flow"))
            else "RESEARCH: target-CEX dormant candidate; whale-origin relaxed"
        )
        if not _boolish_scalar(row.get("_seth_whale_concentration_pass")):
            action = "WAIT: whale concentration below floor"
        elif require_holder_evidence and not _boolish_scalar(row.get("_seth_holder_evidence_pass")):
            action = "WAIT: holder evidence missing"
        elif require_whale_origin_flow and not _boolish_scalar(row.get("_seth_whale_origin_flow")):
            action = "WAIT: whale-origin sender not verified"
        elif not _boolish_scalar(row.get("_seth_float_pass")):
            action = "WAIT: low-float/FDV gate failed"
        elif not bool(row.get("_seth_short_pass")):
            action = "WAIT: short-account gate failed"
        elif not _boolish_scalar(row.get("_seth_no_recent_pump_pass")):
            action = "WAIT: 60D no-pump proof missing"
        elif state == "volatile/late":
            action = "SKIP: already volatile/late"
        elif not bool(row.get("_seth_structure_pass")):
            action = "WAIT: structure not clean enough"
        range_text = f"{range_pct:.1f}%" if range_pct is not None else "n/a"
        day_text = f"{day_move:.1f}%" if day_move is not None else "n/a"
        top10_text = f"{row_top10:.1f}%" if row_top10 is not None else "n/a"
        top100_text = f"{row_top100:.1f}%" if row_top100 is not None else "n/a"
        holder_ev = "Y" if _boolish_scalar(row.get("_seth_holder_evidence_pass")) else "N"
        whale_origin_text = _whale_sender_text(row, include_amount=True)
        whale_origin_flag = "Y" if _boolish_scalar(row.get("_seth_whale_origin_flow")) else "N"
        no_pump = "Y" if _boolish_scalar(row.get("_seth_no_recent_pump_pass")) else "N"
        lines.append(
            f"/{symbol} | {action} | flow {flow_score:.0f}/100 | {cex_count} tx into {targets_text} | "
            f"total {total_amount}, max {max_transfer} | top10 {top10_text}, top100 {top100_text} | "
            f"holderEv {holder_ev} | whaleOrigin {whale_origin_flag}{f' {whale_origin_text}' if whale_origin_text else ''} | "
            f"float {row_float:.0f}/100 | noPump60 {no_pump} | shorts {short_pct:.1f}% | structure {state}"
        )
        lines.append(
            f"  chart gate: range {range_text}, 24h {day_text}, {_clip_text(row.get('_seth_structure_reason', ''), 80)} | "
            "not a trade instruction; validate OI/volume and price absorption."
        )
    return "Seth flow checklist", _chunk_text_lines(lines)


def _num_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype("float64")


def _max_series(frame: pd.DataFrame, *columns: str, default: float = 0.0) -> pd.Series:
    parts = [_num_series(frame, column, default=float("nan")) for column in columns if column in frame.columns]
    if not parts:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.concat(parts, axis=1).max(axis=1).fillna(default).astype("float64")


def _score_linear_series(series: pd.Series, low: float, high: float, *, invert: bool = False) -> pd.Series:
    if high <= low:
        return pd.Series(0.0, index=series.index, dtype="float64")
    scored = ((series.astype("float64") - low) / (high - low) * 100.0).clip(lower=0.0, upper=100.0)
    return 100.0 - scored if invert else scored


def _first_row_float(row: pd.Series, *columns: str) -> float | None:
    for column in columns:
        value = _safe_float(row.get(column))
        if value is not None:
            return value
    return None


def _confirmed_cex_flow_mask(frame: pd.DataFrame, *, min_transfer_tokens: float = 0.0, target_only: bool = True) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    score = _num_series(frame, "cex_deposit_flow_score")
    flag = _boolish_series(frame.get("cex_deposit_flow_flag", pd.Series(False, index=frame.index)), index=frame.index)
    count = _num_series(frame, "cex_deposit_24h_count")
    max_amount = _num_series(frame, "cex_deposit_24h_max_amount")
    targets = _text_series(frame, "cex_deposit_24h_target_exchanges")
    flow_mask = (flag | score.gt(0.0)) & count.gt(0.0) & max_amount.ge(max(0.0, float(min_transfer_tokens or 0.0)))
    if target_only:
        flow_mask = flow_mask & targets.str.contains(TARGET_CEX_PATTERN, regex=True)
    return flow_mask.fillna(False)


def _whale_component_series(frame: pd.DataFrame) -> pd.Series:
    top10 = _safe_pct_series(frame, "top10_holder_pct")
    top100 = _safe_pct_series(frame, "top100_holder_pct")
    return pd.concat(
        [
            _score_linear_series(top10.fillna(0.0), 55.0, 92.0),
            _score_linear_series(top100.fillna(0.0), 82.0, 99.5),
            _num_series(frame, "centralized_ownership_score"),
            _num_series(frame, "terminal_control_plane_score"),
            _score_linear_series(_num_series(frame, "cluster_manipulable_supply_pct"), 8.0, 45.0),
        ],
        axis=1,
    ).max(axis=1)


def _safe_pct_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return frame[column].map(_safe_pct).astype("float64")


def _goal_score_frame(
    frame: pd.DataFrame,
    *,
    min_transfer_tokens: float = 0.0,
    min_short_pct: float = 50.0,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_binance_bitget: bool = True,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    require_holder_evidence = True
    require_binance_bitget = True
    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    output = apply_timing_model(apply_terminal_model(frame.loc[:, ~frame.columns.duplicated()].copy()))
    target_flow = _confirmed_cex_flow_mask(output, min_transfer_tokens=min_transfer_tokens, target_only=True)
    any_flow = _confirmed_cex_flow_mask(output, min_transfer_tokens=min_transfer_tokens, target_only=False)
    flow_strength = _max_series(
        output,
        "cex_deposit_flow_score",
        "cex_deposit_inventory_stress_score",
        "terminal_exchange_flow_score",
    )
    target_flow_component = flow_strength.where(target_flow, 0.0)
    whale_component = _whale_component_series(output)
    float_component = pd.concat(
        [
            _num_series(output, "low_float_score"),
            _num_series(output, "float_trap_score"),
            _num_series(output, "terminal_float_score"),
            _num_series(output, "terminal_hidden_float_reflexivity_score"),
            _score_linear_series(_num_series(output, "fdv_to_market_cap"), 1.8, 12.0),
            _score_linear_series(_num_series(output, "locked_supply_pct"), 15.0, 85.0),
        ],
        axis=1,
    ).max(axis=1)
    short_pct = _safe_pct_series(output, "short_account_pct").fillna(_num_series(output, "short_account_pct"))
    short_component = pd.concat(
        [
            _score_linear_series(short_pct, min_short_pct, 72.0),
            _num_series(output, "short_dominance_score"),
            _num_series(output, "short_account_build_score"),
            _num_series(output, "short_liquidation_fuel_score"),
            _num_series(output, "terminal_short_pressure_score"),
            _num_series(output, "forced_buying_setup_score"),
        ],
        axis=1,
    ).max(axis=1)
    structure_component = pd.concat(
        [
            _num_series(output, "terminal_pre_ignition_quality_score"),
            _num_series(output, "timing_score"),
            _num_series(output, "dormant_short_fuse_score"),
            _num_series(output, "pre_pump_precision_score"),
            _num_series(output, "rave_lab_setup_score"),
            _num_series(output, "accumulation_absorption_score"),
        ],
        axis=1,
    ).max(axis=1)
    late_risk = pd.concat(
        [
            _num_series(output, "timing_too_late_score"),
            _num_series(output, "convexity_late_penalty"),
            _num_series(output, "no_chase_penalty_score"),
            _num_series(output, "exit_fragility_score") * 0.7,
        ],
        axis=1,
    ).max(axis=1)
    not_late_component = (100.0 - late_risk).clip(lower=0.0, upper=100.0)
    top10 = _safe_pct_series(output, "top10_holder_pct").fillna(0.0)
    top100 = _safe_pct_series(output, "top100_holder_pct").fillna(0.0)
    whale_pct = top10.fillna(0.0)
    holder_evidence_mask, _ = _strict_holder_evidence_masks(output)
    whale_concentration_pass = whale_pct.ge(effective_min_whale_pct)
    whale_pass = whale_concentration_pass & (holder_evidence_mask if require_holder_evidence else True)
    venue_pass = _explicit_binance_bitget_trading_gate_mask(output)
    no_recent_pump_pass = _no_recent_pump_proof_mask(output)
    short_pass = short_pct.ge(min_short_pct)
    float_pass = float_component.ge(55.0) | _num_series(output, "fdv_to_market_cap").ge(4.0) | _num_series(output, "locked_supply_pct").ge(45.0)
    structure_pass = structure_component.ge(35.0) & not_late_component.ge(45.0) & no_recent_pump_pass
    base_thesis_pass = whale_pass & venue_pass & no_recent_pump_pass
    core_setup_pass = base_thesis_pass & short_pass & float_pass & structure_pass
    flow_setup_pass = core_setup_pass & target_flow

    setup_score = (
        target_flow_component * 0.23
        + whale_component * 0.19
        + float_component * 0.17
        + short_component * 0.18
        + structure_component * 0.14
        + not_late_component * 0.09
        + target_flow.astype(float) * 4.0
        + whale_pass.astype(float) * 3.0
        + venue_pass.astype(float) * 3.0
        + short_pass.astype(float) * 3.0
        + float_pass.astype(float) * 2.0
        - (~no_recent_pump_pass).astype(float) * 18.0
    ).clip(lower=0.0, upper=100.0)

    output["_goal_setup_score"] = setup_score
    output["_goal_target_flow"] = target_flow
    output["_goal_any_flow"] = any_flow
    output["_goal_whale_component"] = whale_component
    output["_goal_whale_pct"] = whale_pct
    output["_goal_min_whale_pct"] = effective_min_whale_pct
    output["_goal_whale_concentration_pass"] = whale_concentration_pass
    output["_goal_holder_evidence_pass"] = holder_evidence_mask
    output["_goal_holder_evidence_required"] = bool(require_holder_evidence)
    output["_goal_venue_pass"] = venue_pass
    output["_goal_venue_required"] = bool(require_binance_bitget)
    output["_goal_no_recent_pump_pass"] = no_recent_pump_pass
    output["_goal_base_thesis_pass"] = base_thesis_pass
    output["_goal_float_component"] = float_component
    output["_goal_short_component"] = short_component
    output["_goal_structure_component"] = structure_component
    output["_goal_not_late_component"] = not_late_component
    output["_goal_whale_pass"] = whale_pass
    output["_goal_short_pass"] = short_pass
    output["_goal_float_pass"] = float_pass
    output["_goal_structure_pass"] = structure_pass
    output["_goal_core_setup_pass"] = core_setup_pass
    output["_goal_flow_setup_pass"] = flow_setup_pass
    output["_goal_all_pass"] = flow_setup_pass
    return output


def _goal_thesis_gates_line(row: pd.Series) -> str:
    yes_no = lambda value: "Y" if _boolish_scalar(value) else "N"
    return (
        f"Thesis gates: baseThesis {yes_no(row.get('_goal_base_thesis_pass'))} | "
        f"coreSetup {yes_no(row.get('_goal_core_setup_pass'))} | "
        f"flowSetup {yes_no(row.get('_goal_flow_setup_pass', row.get('_goal_all_pass')))} | "
        f"targetFlow {yes_no(row.get('_goal_target_flow'))} | "
        f"holder {yes_no(row.get('_goal_whale_pass'))} | "
        f"venueBnBg {yes_no(row.get('_goal_venue_pass'))} | "
        f"float {yes_no(row.get('_goal_float_pass'))} | "
        f"shorts {yes_no(row.get('_goal_short_pass'))} | "
        f"noPump60 {yes_no(row.get('_goal_no_recent_pump_pass'))} | "
        f"whaleOrigin {'Y' if _whale_sender_text(row, include_amount=False) else 'N'}"
    )


def _goal_core_row_status(row: pd.Series, *, min_score: float = 60.0) -> str:
    score = _safe_float(row.get("_goal_setup_score")) or 0.0
    if _boolish_scalar(row.get("_goal_core_setup_pass")) and score >= min_score:
        return "PASS"
    if not _boolish_scalar(row.get("_goal_base_thesis_pass")):
        return _goal_row_status(row, min_score=min_score)
    if not _boolish_scalar(row.get("_goal_short_pass")):
        return "WATCH"
    if not _boolish_scalar(row.get("_goal_float_pass")):
        return "WATCH"
    if not _boolish_scalar(row.get("_goal_structure_pass")):
        return "WATCH"
    return "WATCH"


def _goal_row_status(row: pd.Series, *, min_score: float = 60.0) -> str:
    if _boolish_scalar(row.get("_goal_all_pass")) and (_safe_float(row.get("_goal_setup_score")) or 0.0) >= min_score:
        return "PASS"
    if not _boolish_scalar(row.get("_goal_target_flow")):
        return "DATA GAP" if _boolish_scalar(row.get("_goal_any_flow")) or _clean_scalar_text(row.get("cex_deposit_flow_error", "")) else "REJECT"
    missing: list[str] = []
    if not _boolish_scalar(row.get("_goal_whale_concentration_pass")):
        missing.append("whale")
    elif _boolish_scalar(row.get("_goal_holder_evidence_required")) and not _boolish_scalar(row.get("_goal_holder_evidence_pass")):
        missing.append("holder evidence")
    if _boolish_scalar(row.get("_goal_venue_required")) and not _boolish_scalar(row.get("_goal_venue_pass")):
        missing.append("venue")
    if not _boolish_scalar(row.get("_goal_short_pass")):
        missing.append("short")
    if not _boolish_scalar(row.get("_goal_float_pass")):
        missing.append("float")
    if not _boolish_scalar(row.get("_goal_no_recent_pump_pass")):
        missing.append("60D no-pump")
    if not _boolish_scalar(row.get("_goal_structure_pass")):
        missing.append("timing")
    return "WATCH" if missing else "WATCH"


def _setup_score_line(row: pd.Series, *, min_score: float = 60.0) -> str:
    symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
    status = _goal_row_status(row, min_score=min_score)
    score = _safe_float(row.get("_goal_setup_score")) or 0.0
    targets = _target_cex_text(row) or _clip_text(row.get("cex_deposit_24h_target_exchanges", ""), 36) or "no target CEX"
    flow_score = _safe_float(row.get("cex_deposit_flow_score")) or 0.0
    cex_count = int(_safe_float(row.get("cex_deposit_24h_count")) or 0)
    max_amount = _fmt_compact_number(row.get("cex_deposit_24h_max_amount"))
    top10 = _safe_pct(row.get("top10_holder_pct"))
    top100 = _safe_pct(row.get("top100_holder_pct"))
    whale_pct = _safe_pct(row.get("_goal_whale_pct"))
    holder_ev = "Y" if _boolish_scalar(row.get("_goal_holder_evidence_pass")) else "N"
    venue_ev = "Y" if _boolish_scalar(row.get("_goal_venue_pass")) else "N"
    no_pump = "Y" if _boolish_scalar(row.get("_goal_no_recent_pump_pass")) else "N"
    short_pct = _safe_pct(row.get("short_account_pct"))
    float_score = _safe_float(row.get("_goal_float_component")) or 0.0
    fdv_ratio = _safe_float(row.get("fdv_to_market_cap"))
    structure = _safe_float(row.get("_goal_structure_component")) or 0.0
    oi = _safe_float(row.get("oi_delta_pct"))
    parts = [
        f"/{symbol}",
        f"{status}",
        f"score {score:.0f}",
        f"flow {flow_score:.0f} {targets} {cex_count}tx max {max_amount}",
        f"whale {whale_pct:.1f}%" if whale_pct is not None else "whale n/a",
        f"holderEv {holder_ev}",
        f"venueBnBg {venue_ev}",
        f"noPump60 {no_pump}",
        f"whale t10 {top10:.1f}%" if top10 is not None else "whale t10 n/a",
        f"t100 {top100:.1f}%" if top100 is not None else "t100 n/a",
        f"shorts {short_pct:.1f}%" if short_pct is not None else "shorts n/a",
        f"float {float_score:.0f}",
    ]
    if fdv_ratio is not None and fdv_ratio > 0:
        parts.append(f"FDV/MC {fdv_ratio:.1f}x")
    parts.append(f"structure {structure:.0f}")
    if oi is not None:
        parts.append(f"OI {oi:.1f}%")
    return " | ".join(parts)


def _load_setup_score_list(
    limit: int,
    *,
    min_score: float = 60.0,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    min_short_pct: float = 50.0,
    min_whale_pct: float = 90.0,
    strict: bool = True,
    require_holder_evidence: bool = True,
    require_binance_bitget: bool = True,
) -> tuple[str, list[str]]:
    strict = True
    require_holder_evidence = True
    require_binance_bitget = True
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    header = (
        "Insider-structure setup score\n"
        f"Source: {source} | Transfer floor: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h | "
        "Target CEX: Binance, Gate.io, Bitget | "
        f"Gates: top10 holder >= {effective_min_whale_pct:.1f}%, holder evidence required {require_holder_evidence}, "
        f"Binance+Bitget required {require_binance_bitget}, 60D no-pump required, shorts >= {min_short_pct:.1f}%, "
        f"low-float/FDV, not-late structure | Strict: {strict}"
    )
    if frame.empty:
        return "Insider-structure setup score", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]
    scored = _goal_score_frame(
        frame,
        min_transfer_tokens=effective_min_transfer,
        min_short_pct=min_short_pct,
        min_whale_pct=effective_min_whale_pct,
        require_holder_evidence=require_holder_evidence,
        require_binance_bitget=require_binance_bitget,
    )
    selected = scored[scored["_goal_setup_score"].ge(max(0.0, float(min_score)))].copy()
    if strict:
        selected = selected[selected["_goal_all_pass"]].copy()
    if selected.empty:
        nearest = scored.sort_values(["_goal_all_pass", "_goal_setup_score", "symbol"], ascending=[False, False, True]).head(
            min(max(int(limit), 1), 50)
        )
        lines = [
            header,
            "",
            "No rows passed the requested setup-score filters. Nearest rows:",
            "",
            *[_setup_score_line(row, min_score=min_score) for _, row in nearest.iterrows()],
        ]
        return "Insider-structure setup score", _chunk_text_lines(lines)
    selected = selected.sort_values(["_goal_setup_score", "_goal_target_flow", "symbol"], ascending=[False, False, True]).head(
        min(max(int(limit), 1), 100)
    )
    lines = [
        header,
        f"Matches: {len(selected)} | Read: rank-order evidence, not an execution instruction.",
        "",
        "Candidates: " + " ".join(f"/{str(symbol).upper().strip()}" for symbol in selected["symbol"].tolist()),
        "",
    ]
    for _, row in selected.iterrows():
        lines.append(_setup_score_line(row, min_score=min_score))
    return "Insider-structure setup score", _chunk_text_lines(lines)


def _load_pump_watch_list(
    limit: int,
    *,
    min_score: float = 55.0,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_binance_bitget: bool = True,
    require_target_flow: bool = False,
    require_venue_gate: bool = True,
    require_dormant_60d: bool = True,
) -> tuple[str, list[str]]:
    require_holder_evidence = True
    require_binance_bitget = True
    require_venue_gate = True
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    header = (
        "Early pump watch\n"
        f"Source: {source} | Transfer floor: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h | "
        "Target CEX: Binance, Gate.io, Bitget | "
        f"Min radar: {float(min_score):.0f} | Holder gate: top10 >= {effective_min_whale_pct:.1f}% | "
        f"Holder evidence required: {require_holder_evidence} | Binance+Bitget required: {require_binance_bitget} | "
        f"Target flow required: {require_target_flow} | "
        f"60D no-pump required: {require_dormant_60d} | "
        "Float/FDV required: True | Squeeze fuel required: True | Not-late required: True | "
        f"{'Additional venue gate: target-CEX/venue-support check enabled' if require_venue_gate else 'Additional venue gate: disabled for this command'}"
    )
    if frame.empty:
        return "Early pump watch", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]

    scored = frame.loc[:, ~frame.columns.duplicated()].copy()
    scored = apply_terminal_model(scored)
    scored = apply_archetype_model(scored)
    scored = apply_timing_model(scored)
    scored = apply_early_pump_radar(scored, min_transfer_tokens=effective_min_transfer)
    holder_gate = _strict_top10_thesis_holder_gate_mask(
        scored,
        min_whale_pct=effective_min_whale_pct,
        require_holder_evidence=require_holder_evidence,
    )
    holder_count = int(holder_gate.sum())
    scored = scored[holder_gate].copy()
    if scored.empty:
        return "Early pump watch", [header + f"\n\nRows after strict holder gate: {holder_count}. No rows met the holder concentration/evidence gate."]
    venue_pair_gate = _explicit_binance_bitget_trading_gate_mask(scored)
    venue_pair_count = int(venue_pair_gate.sum())
    if require_binance_bitget:
        scored = scored[venue_pair_gate].copy()
    if scored.empty:
        return "Early pump watch", [header + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count}. No rows met the required trading-venue evidence."]
    if require_venue_gate:
        venue_gate = _boolish_series(scored.get("early_pump_venue_gate", pd.Series(False, index=scored.index)), index=scored.index)
        scored = scored[venue_gate].copy()
    if scored.empty:
        return "Early pump watch", [header + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count}. No rows survived the venue gate."]
    dormant_gate = _boolish_series(scored.get("early_pump_no_recent_pump_gate", pd.Series(False, index=scored.index)), index=scored.index)
    dormant_count = int(dormant_gate.sum())
    if require_dormant_60d:
        scored = scored[dormant_gate].copy()
    if scored.empty:
        return "Early pump watch", [
            header
            + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count} | "
            + f"60D no-pump proof rows: {dormant_count}. No rows had enough 60D no-pump/dormancy proof."
        ]
    float_gate = _boolish_series(scored.get("early_pump_float_gate", pd.Series(False, index=scored.index)), index=scored.index)
    float_count = int(float_gate.sum())
    scored = scored[float_gate].copy()
    if scored.empty:
        return "Early pump watch", [
            header
            + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count} | "
            + f"60D no-pump proof rows: {dormant_count} | Float/FDV rows: {float_count}. "
            + "No rows had enough low-float/high-FDV structure evidence."
        ]
    squeeze_gate = _boolish_series(scored.get("early_pump_short_gate", pd.Series(False, index=scored.index)), index=scored.index)
    squeeze_count = int(squeeze_gate.sum())
    scored = scored[squeeze_gate].copy()
    if scored.empty:
        return "Early pump watch", [
            header
            + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count} | "
            + f"60D no-pump proof rows: {dormant_count} | Float/FDV rows: {float_count} | Squeeze-fuel rows: {squeeze_count}. "
            + "No rows had enough short-squeeze fuel."
        ]
    not_late_gate = _boolish_series(scored.get("early_pump_not_late_gate", pd.Series(False, index=scored.index)), index=scored.index)
    not_late_count = int(not_late_gate.sum())
    scored = scored[not_late_gate].copy()
    if scored.empty:
        return "Early pump watch", [
            header
            + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count} | "
            + f"60D no-pump proof rows: {dormant_count} | Float/FDV rows: {float_count} | "
            + f"Squeeze-fuel rows: {squeeze_count} | Not-late rows: {not_late_count}. No rows were early enough."
        ]

    score = _num_series(scored, "early_pump_radar_score")
    target_flow = _boolish_series(scored.get("early_pump_confirmed_target_flow", pd.Series(False, index=scored.index)), index=scored.index)
    selected = scored[score.ge(max(0.0, float(min_score)))].copy()
    if require_target_flow:
        selected = selected[target_flow.loc[selected.index]].copy()
    if selected.empty:
        nearest = scored.sort_values(
            ["early_pump_alert_flag", "early_pump_confirmed_target_flow", "early_pump_radar_score", "symbol"],
            ascending=[False, False, False, True],
        ).head(min(max(int(limit), 1), 30))
        lines = [
            header,
            "",
            "No rows passed the requested pump-watch filters. Nearest rows:",
            "",
            *[_pump_watch_line(row) for _, row in nearest.iterrows()],
        ]
        return "Early pump watch", _chunk_text_lines(lines)

    selected = selected.sort_values(
        [
            "early_pump_alert_flag",
            "early_pump_confirmed_target_flow",
            "early_pump_radar_score",
            "early_pump_flow_score",
            "early_pump_short_squeeze_score",
            "symbol",
        ],
        ascending=[False, False, False, False, False, True],
    ).head(min(max(int(limit), 1), 100))
    target_count = int(_boolish_series(selected.get("early_pump_confirmed_target_flow"), index=selected.index).sum())
    lines = [
        header,
        f"Gate rows: strict holder {holder_count} | Binance+Bitget {venue_pair_count} | 60D no-pump {dormant_count} | Float/FDV {float_count} | Squeeze fuel {squeeze_count} | Not-late {not_late_count} | Shown after radar filters {len(selected)}",
        f"Matches: {len(selected)} | Confirmed target-flow rows: {target_count} | Read: rank-order evidence, not an execution instruction.",
        "",
        "Candidates: " + " ".join(f"/{str(symbol).upper().strip()}" for symbol in selected.get("symbol", pd.Series(dtype='object')).tolist()),
        "",
    ]
    for _, row in selected.iterrows():
        lines.append(_pump_watch_line(row))
    return "Early pump watch", _chunk_text_lines(lines)


def _pump_watch_line(row: pd.Series) -> str:
    symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
    radar = _safe_float(row.get("early_pump_radar_score")) or 0.0
    state = _clip_text(row.get("early_pump_state", ""), 32) or "No edge"
    signal = _clip_text(row.get("early_pump_primary_signal", ""), 44) or "signal n/a"
    targets = _target_cex_text(row) or "no target flow"
    flow_score = _safe_float(row.get("early_pump_flow_score")) or 0.0
    cex_count = int(_safe_float(row.get("cex_deposit_24h_count")) or 0)
    max_amount = _fmt_compact_number(row.get("cex_deposit_24h_max_amount"))
    top10 = _safe_pct(row.get("top10_holder_pct"))
    top100 = _safe_pct(row.get("top100_holder_pct"))
    short_pct = _safe_pct(row.get("short_account_pct"))
    top10_text = f"{top10:.1f}%" if top10 is not None else "n/a"
    top100_text = f"{top100:.1f}%" if top100 is not None else "n/a"
    short_text = f"{short_pct:.1f}%" if short_pct is not None else "n/a"
    float_score = _safe_float(row.get("early_pump_float_score")) or 0.0
    timing = _safe_float(row.get("early_pump_timing_score")) or 0.0
    not_late = _safe_float(row.get("early_pump_not_late_score")) or 0.0
    no_pump = "Y" if _boolish_scalar(row.get("early_pump_no_recent_pump_gate")) else "N"
    archetype = _clip_text(row.get("archetype_best_match", ""), 36)
    next_check = _clip_text(row.get("early_pump_next_check", ""), 96)
    archetype_suffix = f" | {archetype}" if archetype and archetype != "No strong case-study analogue" else ""
    next_suffix = f" | next: {next_check}" if next_check else ""
    return (
        f"/{symbol} | {state} | radar {radar:.0f}/100 | {signal} | "
        f"flow {flow_score:.0f} {targets} {cex_count}tx max {max_amount} | "
        f"top10 {top10_text}, top100 {top100_text} | shorts {short_text} | "
        f"float {float_score:.0f} | timing {timing:.0f} | not-late {not_late:.0f} | noPump60 {no_pump}"
        f"{archetype_suffix}{next_suffix}"
    )


def _precrime_line(row: pd.Series) -> str:
    symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
    score = _safe_float(row.get("pre_activity_pump_score")) or 0.0
    state = _clip_text(row.get("pre_activity_state", ""), 34) or "No latent edge"
    signal = _clip_text(row.get("pre_activity_primary_signal", ""), 46) or "signal n/a"
    targets = _target_cex_text(row) or "no target flow"
    behavior = _safe_float(row.get("pre_activity_behavior_score")) or 0.0
    control = _safe_float(row.get("pre_activity_control_score")) or 0.0
    float_score = _safe_float(row.get("pre_activity_float_score")) or 0.0
    quiet = _safe_float(row.get("pre_activity_quiet_score")) or 0.0
    heat = _safe_float(row.get("pre_activity_heat_score")) or 0.0
    thin = _safe_float(row.get("pre_activity_thin_book_score")) or 0.0
    ref_symbol = _clip_text(row.get("archetype_reference_symbol", ""), 16)
    ref_date = _clip_text(row.get("archetype_reference_date", ""), 16)
    cex_count = int(_safe_float(row.get("cex_deposit_24h_count")) or 0)
    max_amount = _fmt_compact_number(row.get("cex_deposit_24h_max_amount"))
    top10 = _safe_pct(row.get("top10_holder_pct"))
    top100 = _safe_pct(row.get("top100_holder_pct"))
    short_pct = _safe_pct(row.get("short_account_pct"))
    top10_text = f"{top10:.1f}%" if top10 is not None else "n/a"
    top100_text = f"{top100:.1f}%" if top100 is not None else "n/a"
    short_text = f"{short_pct:.1f}%" if short_pct is not None else "n/a"
    next_check = _clip_text(row.get("pre_activity_next_check", ""), 100)
    no_pump = "Y" if _boolish_scalar(row.get("pre_activity_no_recent_pump_gate")) else "N"
    ref_suffix = f" | anchor {ref_symbol} {ref_date}".rstrip() if ref_symbol or ref_date else ""
    return (
        f"/{symbol} | {state} | latent {score:.0f}/100 | {signal} | "
        f"CEX-tell {behavior:.0f} {targets} {cex_count}tx max {max_amount} | "
        f"control {control:.0f} | float {float_score:.0f} | thin-book {thin:.0f} | "
        f"quiet {quiet:.0f} heat {heat:.0f} | noPump60 {no_pump} | top10 {top10_text}, top100 {top100_text} | shorts {short_text}"
        f"{ref_suffix}{f' | next: {next_check}' if next_check else ''}"
    )


def _load_precrime_list(
    limit: int,
    *,
    min_score: float = 58.0,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_binance_bitget: bool = True,
    require_target_flow: bool = False,
    require_quiet: bool = True,
    require_behavior_gate: bool = True,
    require_dormant_60d: bool = True,
) -> tuple[str, list[str]]:
    require_holder_evidence = True
    require_binance_bitget = True
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    header = (
        "Pre-activity crime-pump radar\n"
        f"Source: {source} | Transfer floor: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h | "
        "Target CEX: Binance, Gate.io, Bitget | "
        f"Min latent score: {float(min_score):.0f} | Holder gate: top10 >= {effective_min_whale_pct:.1f}% | "
        f"Holder evidence required: {require_holder_evidence} | Binance+Bitget required: {require_binance_bitget} | "
        f"Target flow required: {require_target_flow} | "
        "Float/FDV structure required: True | "
        f"Quiet required: {require_quiet} | Behaviour gate required: {require_behavior_gate} | "
        f"60D no-pump required: {require_dormant_60d}"
    )
    if frame.empty:
        return "Pre-activity radar", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]

    scored = frame.loc[:, ~frame.columns.duplicated()].copy()
    scored = apply_terminal_model(scored)
    scored = apply_archetype_model(scored)
    scored = apply_timing_model(scored)
    scored = apply_early_pump_radar(scored, min_transfer_tokens=effective_min_transfer)
    scored = apply_pre_activity_radar(scored, min_transfer_tokens=effective_min_transfer)
    holder_gate = _strict_top10_thesis_holder_gate_mask(
        scored,
        min_whale_pct=effective_min_whale_pct,
        require_holder_evidence=require_holder_evidence,
    )
    holder_count = int(holder_gate.sum())
    scored = scored[holder_gate].copy()
    if scored.empty:
        return "Pre-activity radar", [header + f"\n\nRows after strict holder gate: {holder_count}. No rows met the holder concentration/evidence gate."]
    venue_pair_gate = _explicit_binance_bitget_trading_gate_mask(scored)
    venue_pair_count = int(venue_pair_gate.sum())
    if require_binance_bitget:
        scored = scored[venue_pair_gate].copy()
    if scored.empty:
        return "Pre-activity radar", [header + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count}. No rows met the required trading-venue evidence."]
    dormant_gate = _boolish_series(scored.get("pre_activity_no_recent_pump_gate", pd.Series(False, index=scored.index)), index=scored.index)
    dormant_count = int(dormant_gate.sum())
    if require_dormant_60d:
        scored = scored[dormant_gate].copy()
    if scored.empty:
        return "Pre-activity radar", [
            header
            + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count} | "
            + f"60D no-pump proof rows: {dormant_count}. No rows had enough 60D no-pump/dormancy proof."
        ]
    structure_gate = _boolish_series(scored.get("pre_activity_structure_gate", pd.Series(False, index=scored.index)), index=scored.index)
    structure_count = int(structure_gate.sum())
    scored = scored[structure_gate].copy()
    if scored.empty:
        return "Pre-activity radar", [
            header
            + f"\n\nRows after strict holder gate: {holder_count} | After Binance+Bitget gate: {venue_pair_count} | "
            + f"60D no-pump proof rows: {dormant_count} | Float/FDV structure rows: {structure_count}. "
            + "No rows had enough low-float/high-FDV structure evidence."
        ]

    score = _num_series(scored, "pre_activity_pump_score")
    selected = scored[score.ge(max(0.0, float(min_score)))].copy()
    if require_target_flow:
        target_flow = _boolish_series(selected.get("pre_activity_confirmed_target_flow"), index=selected.index)
        selected = selected[target_flow].copy()
    if require_quiet:
        quiet_gate = _boolish_series(selected.get("pre_activity_quiet_gate"), index=selected.index)
        selected = selected[quiet_gate].copy()
    if require_behavior_gate:
        behavior_gate = _boolish_series(selected.get("pre_activity_behavior_gate"), index=selected.index)
        selected = selected[behavior_gate].copy()

    if selected.empty:
        nearest = scored.sort_values(
            [
                "pre_activity_alert_flag",
                "pre_activity_confirmed_target_flow",
                "pre_activity_pump_score",
                "pre_activity_quiet_score",
                "symbol",
            ],
            ascending=[False, False, False, False, True],
        ).head(min(max(int(limit), 1), 30))
        lines = [
            header,
            "",
            "No rows passed the requested pre-activity filters. Nearest rows:",
            "",
            *[_precrime_line(row) for _, row in nearest.iterrows()],
        ]
        return "Pre-activity radar", _chunk_text_lines(lines)

    selected = selected.sort_values(
        [
            "pre_activity_alert_flag",
            "pre_activity_confirmed_target_flow",
            "pre_activity_pump_score",
            "pre_activity_behavior_score",
            "pre_activity_quiet_score",
            "symbol",
        ],
        ascending=[False, False, False, False, False, True],
    ).head(min(max(int(limit), 1), 100))
    target_count = int(_boolish_series(selected.get("pre_activity_confirmed_target_flow"), index=selected.index).sum())
    quiet_count = int(_boolish_series(selected.get("pre_activity_quiet_gate"), index=selected.index).sum())
    symbols = " ".join(f"/{str(symbol).upper().strip()}" for symbol in selected.get("symbol", pd.Series(dtype='object')).tolist())
    lines = [
        header,
        f"Gate rows: strict holder {holder_count} | Binance+Bitget {venue_pair_count} | 60D no-pump {dormant_count} | Float/FDV structure {structure_count} | Shown after latent filters {len(selected)}",
        f"Matches: {len(selected)} | Target-flow rows: {target_count} | Quiet-gated rows: {quiet_count} | Read: structural-risk evidence, not trade instruction.",
        "",
        f"Candidates: {symbols}" if symbols else "Candidates: none",
        "",
    ]
    for _, row in selected.iterrows():
        lines.append(_precrime_line(row))
    return "Pre-activity radar", _chunk_text_lines(lines)


def _ravelab_side_from_scores(rave_score: float, lab_score: float) -> str:
    if rave_score >= lab_score + 5.0:
        return "RAVE-like"
    if lab_score >= rave_score + 5.0:
        return "LAB-like"
    return "Mixed RAVE/LAB"


def _ravelab_anchor_for_side(side: str, rave_score: float, lab_score: float) -> tuple[str, str]:
    if side == "Mixed RAVE/LAB":
        label = "RAVE-style cap-table reflexivity" if rave_score >= lab_score else "LAB-style venue-inventory stress"
    elif side == "RAVE-like":
        label = "RAVE-style cap-table reflexivity"
    else:
        label = "LAB-style venue-inventory stress"
    exemplar = exemplar_for_archetype(label)
    return (exemplar.symbol, exemplar.event_date) if exemplar is not None else ("", "")


def _ravelab_apply_thesis_columns(
    frame: pd.DataFrame,
    *,
    min_squeeze_score: float,
    min_transfer_tokens: float = 0.0,
    min_whale_flow_tokens: float | None = None,
) -> pd.DataFrame:
    output = frame.copy()
    if output.empty:
        return output
    index = output.index
    whale_gate = _boolish_series(output.get("_ravelab_whale_gate"), index=index)
    holder_gate = _boolish_series(output.get("_ravelab_holder_evidence_gate"), index=index)
    venue_gate = _boolish_series(output.get("_ravelab_venue_gate"), index=index)
    float_gate = _boolish_series(output.get("_ravelab_float_gate"), index=index)
    no_pump_gate = _boolish_series(output.get("_ravelab_no_large_pump_gate"), index=index)
    dormant_gate = _boolish_series(output.get("_ravelab_dormant_2m_gate"), index=index)
    early_gate = _boolish_series(output.get("_ravelab_early_gate"), index=index)
    target_flow = _boolish_series(output.get("_ravelab_target_flow"), index=index)
    breakout_any = _boolish_series(output.get("_ravelab_breakout_any"), index=index)
    squeeze_gate = _ravelab_squeeze_gate_series(output, min_squeeze_score=min_squeeze_score)
    transfer_floor = max(0.0, float(min_transfer_tokens or 0.0))
    whale_flow_floor = _ravelab_whale_flow_floor(transfer_floor, min_whale_flow_tokens)
    qualified_whale_sender = output.apply(_whale_sender_qualifies, axis=1).astype(bool)
    whale_origin_flow = (
        qualified_whale_sender
        & _num_series(output, "cex_deposit_24h_whale_sender_count").gt(0.0)
        & _num_series(output, "cex_deposit_24h_count").gt(0.0)
        & _num_series(output, "cex_deposit_24h_whale_sender_token_amount").ge(whale_flow_floor)
        & target_flow
    )
    core_gates = {
        "whale90+evidence": whale_gate & holder_gate,
        "Binance+Bitget": venue_gate,
        "float/FDV": float_gate,
        "2mo no-pump": no_pump_gate & dormant_gate,
        "squeeze": squeeze_gate,
        "early/no-chase": early_gate,
    }
    core_count = pd.Series(0, index=index, dtype="int64")
    missing: list[str] = []
    for label, mask in core_gates.items():
        clean_mask = mask.fillna(False).astype(bool)
        core_count = core_count + clean_mask.astype(int)
        missing.append(pd.Series(label, index=index).where(~clean_mask, other=""))
    missing_frame = pd.concat(missing, axis=1)
    missing_text = missing_frame.apply(lambda row: ",".join(part for part in row.tolist() if part), axis=1)

    thesis_score = (
        core_count.astype(float) / max(len(core_gates), 1) * 72.0
        + _num_series(output, "_ravelab_early_score") * 0.10
        + _num_series(output, "_ravelab_breakout_score") * 0.05
        + target_flow.astype(float) * 4.0
        + whale_origin_flow.astype(float) * 8.0
        + breakout_any.astype(float) * 5.0
    ).clip(lower=0.0, upper=100.0)

    states: list[str] = []
    for idx in index:
        full_core = int(core_count.loc[idx]) >= len(core_gates)
        has_whale_flow = bool(whale_origin_flow.loc[idx])
        has_breakout = bool(breakout_any.loc[idx])
        if full_core and has_whale_flow and has_breakout:
            states.append("A4 PRIME+FLOW+BREAKOUT")
        elif full_core and has_whale_flow:
            states.append("A3 WHALE-CEX PRIME")
        elif full_core and has_breakout:
            states.append("A2 BREAKOUT PRIME")
        elif full_core:
            states.append("A1 CORE PRIME")
        else:
            states.append(f"B{max(0, len(core_gates) - int(core_count.loc[idx]))} BLOCKED")

    output["_ravelab_squeeze_gate"] = squeeze_gate
    output["_ravelab_whale_origin_flow"] = whale_origin_flow
    output["_ravelab_whale_flow_floor_tokens"] = whale_flow_floor
    output["_ravelab_core_gate_count"] = core_count
    output["_ravelab_core_gate_total"] = len(core_gates)
    output["_ravelab_missing_core_gates"] = missing_text
    output["_ravelab_thesis_score"] = thesis_score
    output["_ravelab_state"] = states
    return output


def _ravelab_squeeze_gate_series(frame: pd.DataFrame, *, min_squeeze_score: float) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    threshold = max(0.0, float(min_squeeze_score))
    short_pct = _safe_pct_series(frame, "short_account_pct").fillna(_num_series(frame, "short_account_pct"))
    short_crowd_score = _num_series(frame, "_ravelab_short_crowd_score")
    if "_ravelab_short_crowd_score" not in frame.columns:
        short_crowd_score = pd.concat(
            [
                _score_linear_series(short_pct.fillna(0.0), 50.0, 72.0),
                _num_series(frame, "short_dominance_score"),
            ],
            axis=1,
        ).max(axis=1).fillna(0.0)
    fuel_score = _num_series(frame, "_ravelab_squeeze_fuel_score")
    squeeze_score = _num_series(frame, "_ravelab_squeeze_score")
    paired_fuel_floor = max(40.0, threshold * 0.75)
    independent_fuel_floor = max(75.0, threshold + 20.0)
    short_majority = short_pct.ge(50.0) | short_crowd_score.ge(threshold)
    paired_stack = short_majority & squeeze_score.ge(threshold) & fuel_score.ge(paired_fuel_floor)
    independent_stack = fuel_score.ge(independent_fuel_floor) & squeeze_score.ge(threshold)
    return (paired_stack | independent_stack).fillna(False)


def _score_ravelab_early_frame(
    frame: pd.DataFrame,
    *,
    min_whale_pct: float = 90.0,
    min_history_days: int = 60,
    max_recent_pump_pct: float = 35.0,
    min_transfer_tokens: float = 0.0,
) -> pd.DataFrame:
    scored = frame.loc[:, ~frame.columns.duplicated()].copy()
    scored = apply_terminal_model(scored)
    scored = apply_archetype_model(scored)
    scored = apply_timing_model(scored)
    scored = apply_lifecycle_model(scored)
    scored = apply_short_squeeze_model(scored)
    scored = apply_early_pump_radar(scored, min_transfer_tokens=min_transfer_tokens)
    scored = apply_pre_activity_radar(scored, min_transfer_tokens=min_transfer_tokens)

    index = scored.index
    rave = _num_series(scored, "archetype_rave_score")
    lab = _num_series(scored, "archetype_lab_score")
    dashboard_setup = _num_series(scored, "rave_lab_setup_score")
    latent = _num_series(scored, "pre_activity_pump_score")
    top10 = _safe_pct_series(scored, "top10_holder_pct").fillna(0.0)
    top100 = _safe_pct_series(scored, "top100_holder_pct").fillna(0.0)
    whale_pct = top10.fillna(0.0)
    whale_component = pd.concat(
        [
            _score_linear_series(top100, 88.0, 99.5),
            _score_linear_series(top10, 82.0, 97.0),
            _num_series(scored, "centralized_ownership_score"),
            _num_series(scored, "terminal_control_plane_score"),
            _num_series(scored, "holder_concentration_score"),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    control = _max_series(
        scored,
        "pre_activity_control_score",
        "terminal_control_plane_score",
        "centralized_ownership_score",
        "holder_concentration_score",
    )
    float_score = _max_series(scored, "pre_activity_float_score", "low_float_score", "float_trap_score", "terminal_float_score")
    fdv_to_mcap = _num_series(scored, "fdv_to_market_cap")
    locked_supply_pct = _num_series(scored, "locked_supply_pct")
    controlled_float_score = pd.concat(
        [
            float_score,
            _num_series(scored, "terminal_hidden_float_reflexivity_score"),
            _score_linear_series(fdv_to_mcap, 1.8, 12.0),
            _score_linear_series(locked_supply_pct, 15.0, 85.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    controlled_float_gate = (
        controlled_float_score.ge(55.0)
        | fdv_to_mcap.ge(4.0)
        | locked_supply_pct.ge(45.0)
        | (top10.ge(82.0) & top100.ge(97.0))
    )
    behavior = _max_series(
        scored,
        "pre_activity_behavior_score",
        "cex_deposit_flow_score",
        "cex_deposit_inventory_stress_score",
        "inventory_transfer_risk_score",
    )
    short_pct = _safe_pct_series(scored, "short_account_pct").fillna(_num_series(scored, "short_account_pct"))
    short_crowd_score = pd.concat(
        [
            _num_series(scored, "short_dominance_score"),
            _num_series(scored, "short_crowding_score"),
            _score_linear_series(short_pct, 50.0, 72.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    squeeze_fuel = pd.concat(
        [
            _num_series(scored, "short_account_build_score"),
            _num_series(scored, "silent_oi_accumulation_score"),
            _num_series(scored, "short_liquidation_fuel_score"),
            _num_series(scored, "short_squeeze_score"),
            _num_series(scored, "funding_flip_score"),
            _boolish_series(scored.get("fresh_flip_flag"), index=index).astype(float) * 100.0,
            _num_series(scored, "forced_buying_setup_score"),
            _num_series(scored, "perp_squeeze_confluence_score"),
            _score_linear_series(_num_series(scored, "oi_to_24h_volume_pct"), 2.0, 18.0),
            _score_linear_series(_num_series(scored, "oi_delta_pct"), 0.5, 7.5),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    squeeze = pd.concat(
        [
            _num_series(scored, "early_pump_short_squeeze_score") * 0.55 + squeeze_fuel * 0.45,
            short_crowd_score * 0.60 + squeeze_fuel * 0.40,
            squeeze_fuel,
            short_crowd_score * 0.45 + _num_series(scored, "terminal_short_pressure_score") * 0.55,
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    short_build_pp = _num_series(scored, "short_account_change_max_pp")
    short_drop_pp = (-_num_series(scored, "short_account_change_min_pp")).clip(lower=0.0)
    oi_delta = _num_series(scored, "oi_delta_pct")
    volume_multiple = _max_series(scored, "hour_volume_multiple", "daily_quote_volume_multiple", "hour_trade_count_multiple")
    day_return_abs = _num_series(scored, "day_return_pct", default=float("nan")).abs()
    day_return_abs = day_return_abs.fillna(_num_series(scored, "price_change_24h_pct").abs())
    hour_return_abs = _num_series(scored, "hour_return_pct").abs()
    range_pct = _num_series(scored, "range_24h_pct")
    forced_flow = (
        short_crowd_score * 0.30
        + squeeze_fuel * 0.30
        + _score_linear_series(short_build_pp, 0.5, 4.0) * 0.16
        + _score_linear_series(oi_delta, 0.5, 8.0) * 0.16
        + _score_linear_series(volume_multiple, 1.2, 5.0) * 0.08
    ).clip(lower=0.0, upper=100.0)
    quiet = _num_series(scored, "pre_activity_quiet_score")
    late_penalty = _max_series(scored, "rave_lab_late_penalty_score", "timing_too_late_score", "convexity_late_penalty")
    heat = pd.concat(
        [
            _score_linear_series(day_return_abs, 20.0, 90.0),
            _score_linear_series(hour_return_abs, 5.0, 18.0),
            _score_linear_series(range_pct, 12.0, 45.0),
            _score_linear_series(volume_multiple, 3.0, 12.0),
            _score_linear_series(_num_series(scored, "daily_quote_volume_multiple"), 3.0, 12.0),
            _score_linear_series(_num_series(scored, "hour_trade_count_multiple"), 3.0, 12.0),
            _num_series(scored, "cmc_mover_score") * 0.85,
            _num_series(scored, "crime_exhaustion_score") * 0.75,
            late_penalty,
        ],
        axis=1,
    ).max(axis=1).fillna(0.0).clip(lower=0.0, upper=100.0)
    short_fade_risk = pd.concat(
        [
            _score_linear_series(short_drop_pp, 1.0, 6.0),
            _score_linear_series((50.0 - short_pct).clip(lower=0.0), 0.0, 12.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    blowoff_activity = pd.concat(
        [
            _score_linear_series(volume_multiple, 3.0, 12.0),
            _score_linear_series(_num_series(scored, "hour_volume_multiple"), 3.0, 12.0),
            _score_linear_series(_num_series(scored, "day_return_pct").abs(), 20.0, 90.0),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    exhaustion = pd.concat(
        [
            _num_series(scored, "crime_exhaustion_score"),
            _num_series(scored, "exit_fragility_score") * 0.85,
            late_penalty,
            heat * 0.85,
            short_fade_risk * 0.70 + blowoff_activity * 0.30,
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    not_late = pd.concat(
        [
            _num_series(scored, "early_pump_not_late_score"),
            (100.0 - heat).clip(lower=0.0, upper=100.0),
            (100.0 - late_penalty).clip(lower=0.0, upper=100.0),
            _boolish_series(scored.get("no_chase_ok_flag"), index=index).astype(float) * 100.0,
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    targets = _text_series(scored, "cex_deposit_24h_target_exchanges")
    top_venue = _text_series(scored, "top_venue")
    binance_share = _num_series(scored, "binance_volume_share_pct")
    bitget_share = _num_series(scored, "bitget_volume_share_pct")
    gate_share = _num_series(scored, "gate_volume_share_pct")
    explicit_binance_perp = (
        _boolish_series(scored.get("binance_perp_universe"), index=index)
        | _boolish_series(scored.get("is_binance_perp"), index=index)
    )
    has_binance = explicit_binance_perp | binance_share.gt(0.0) | top_venue.str.contains(BINANCE_PATTERN, na=False)
    has_bitget = bitget_share.gt(0.0) | top_venue.str.contains(BITGET_PATTERN, na=False)
    has_gate = gate_share.gt(0.0) | top_venue.str.contains(GATE_PATTERN, na=False) | targets.str.contains(GATE_PATTERN, na=False)
    venue_component = (
        has_binance.astype(float) * 44.0
        + has_bitget.astype(float) * 44.0
        + has_gate.astype(float) * 12.0
        + _num_series(scored, "binance_bitget_gate_share_pct").clip(lower=0.0, upper=100.0) * 0.10
    ).clip(lower=0.0, upper=100.0)
    target_flow = _confirmed_cex_flow_mask(scored, min_transfer_tokens=min_transfer_tokens, target_only=True)
    history_days = _num_series(scored, "history_days", default=0.0)
    recent_pump = _num_series(scored, "recent_max_pump_60d_pct", default=float("nan"))
    recent_pump_days = _num_series(scored, "recent_pump_60d_days", default=0.0)
    recent_pump_observed = recent_pump.notna() & recent_pump_days.ge(max(1, min(60, int(min_history_days))))
    recent_pump_or_current = pd.concat([recent_pump, day_return_abs], axis=1).max(axis=1).fillna(0.0)
    no_large_recent_pump = recent_pump_or_current.lt(max(0.0, float(max_recent_pump_pct)))
    dormant_2m = (
        history_days.ge(max(1, int(min_history_days)))
        & heat.lt(62.0)
        & late_penalty.lt(66.0)
        & no_large_recent_pump
    )
    broke_5d = _boolish_series(scored.get("broke_high_5d"), index=index)
    broke_20d = _boolish_series(scored.get("broke_high_20d"), index=index)
    breakout = (
        broke_5d.astype(float) * 35.0
        + broke_20d.astype(float) * 25.0
        + _score_linear_series(_num_series(scored, "range_high_break_count"), 1.0, 4.0) * 0.22
        + _score_linear_series(_num_series(scored, "distance_to_high_5d_pct", 25.0), -1.0, 5.0, invert=True) * 0.12
        + _score_linear_series(_num_series(scored, "distance_to_high_20d_pct", 35.0), -1.0, 8.0, invert=True) * 0.06
    ).clip(lower=0.0, upper=100.0)
    major_excluded = _boolish_series(scored.get("crime_excluded_major"), index=index)

    rave_component = (
        rave * 0.28
        + whale_component * 0.24
        + dashboard_setup * 0.10
        + control * 0.14
        + float_score * 0.10
        + quiet * 0.08
        + squeeze * 0.06
    )
    lab_component = (
        lab * 0.24
        + whale_component * 0.18
        + venue_component * 0.18
        + behavior * 0.15
        + squeeze * 0.09
        + dashboard_setup * 0.06
        + latent * 0.06
        + target_flow.astype(float) * 4.0
    )
    side_score = pd.concat([rave_component, lab_component], axis=1).max(axis=1).fillna(0.0)
    early_score = (
        whale_component * 0.20
        + venue_component * 0.18
        + not_late * 0.15
        + squeeze * 0.14
        + side_score * 0.13
        + latent * 0.08
        + behavior * 0.06
        + breakout * 0.04
        + target_flow.astype(float) * 3.0
        - heat.sub(62.0).clip(lower=0.0) * 0.28
    ).where(~major_excluded, other=0.0).clip(lower=0.0, upper=100.0)
    archetype_score = pd.concat([rave, lab], axis=1).max(axis=1).fillna(0.0)
    whale_gate = _ravelab_whale_gate_series(scored, min_whale_pct=min_whale_pct)
    venue_gate = has_binance & has_bitget
    structure_gate = whale_gate & venue_gate & controlled_float_gate & dormant_2m & ((control >= 55.0) | (controlled_float_score >= 55.0))
    early_gate = ((quiet >= 45.0) | (not_late >= 58.0)) & heat.lt(68.0) & exhaustion.lt(70.0) & (~major_excluded)

    scored["_ravelab_rave_score"] = rave
    scored["_ravelab_lab_score"] = lab
    scored["_ravelab_archetype_score"] = archetype_score
    scored["_ravelab_side_score"] = side_score.clip(lower=0.0, upper=100.0)
    scored["_ravelab_early_score"] = early_score
    scored["_ravelab_whale_pct"] = whale_pct
    scored["_ravelab_whale_score"] = whale_component
    scored["_ravelab_whale_gate"] = whale_gate & (~major_excluded)
    scored["_ravelab_binance_perp_universe"] = explicit_binance_perp & (~major_excluded)
    scored["_ravelab_has_binance"] = has_binance & (~major_excluded)
    scored["_ravelab_has_bitget"] = has_bitget & (~major_excluded)
    scored["_ravelab_has_gate"] = has_gate & (~major_excluded)
    scored["_ravelab_venue_score"] = venue_component
    scored["_ravelab_venue_gate"] = venue_gate & (~major_excluded)
    scored["_ravelab_float_score"] = controlled_float_score
    scored["_ravelab_float_gate"] = controlled_float_gate & (~major_excluded)
    scored["_ravelab_fdv_to_mcap"] = fdv_to_mcap
    scored["_ravelab_locked_supply_pct"] = locked_supply_pct
    scored["_ravelab_squeeze_score"] = squeeze
    scored["_ravelab_short_crowd_score"] = short_crowd_score
    scored["_ravelab_squeeze_fuel_score"] = squeeze_fuel
    scored["_ravelab_forced_flow_score"] = forced_flow
    scored["_ravelab_exhaustion_score"] = exhaustion
    scored["_ravelab_heat_score"] = heat
    scored["_ravelab_short_build_pp"] = short_build_pp
    scored["_ravelab_short_drop_pp"] = short_drop_pp
    scored["_ravelab_oi_delta_pct"] = oi_delta
    scored["_ravelab_volume_multiple"] = volume_multiple
    scored["_ravelab_short_majority_gate"] = short_pct.ge(50.0) & (~major_excluded)
    scored["_ravelab_squeeze_gate"] = _ravelab_squeeze_gate_series(scored, min_squeeze_score=50.0) & (~major_excluded)
    scored["_ravelab_history_days"] = history_days
    scored["_ravelab_min_history_days"] = int(min_history_days)
    scored["_ravelab_recent_max_pump_pct"] = recent_pump_or_current
    scored["_ravelab_recent_pump_days"] = recent_pump_days.where(recent_pump_observed, other=0.0)
    scored["_ravelab_max_recent_pump_pct"] = float(max_recent_pump_pct)
    scored["_ravelab_no_large_pump_gate"] = no_large_recent_pump & (~major_excluded)
    scored["_ravelab_dormant_2m_gate"] = dormant_2m & (~major_excluded)
    scored["_ravelab_breakout_score"] = breakout
    scored["_ravelab_structure_gate"] = structure_gate & (~major_excluded)
    scored["_ravelab_early_gate"] = early_gate
    scored["_ravelab_target_flow"] = target_flow & (~major_excluded)
    scored["_ravelab_alert_flag"] = early_score.ge(62.0) & structure_gate & early_gate & (~major_excluded)
    scored["_ravelab_side"] = [
        _ravelab_side_from_scores(float(rave_value or 0.0), float(lab_value or 0.0))
        for rave_value, lab_value in zip(rave.tolist(), lab.tolist())
    ]
    return scored


def _ravelab_forced_flow_text(row: pd.Series) -> str:
    forced = _safe_float(row.get("_ravelab_forced_flow_score")) or 0.0
    exhaustion = _safe_float(row.get("_ravelab_exhaustion_score")) or 0.0
    short_pct = _safe_pct(row.get("short_account_pct"))
    short_build = _safe_float(row.get("_ravelab_short_build_pp")) or 0.0
    short_drop = _safe_float(row.get("_ravelab_short_drop_pp")) or 0.0
    oi_delta = _safe_float(row.get("_ravelab_oi_delta_pct"))
    volume_multiple = _safe_float(row.get("_ravelab_volume_multiple"))
    if exhaustion >= 70.0:
        phase = "EXHAUST"
    elif forced >= 70.0:
        phase = "FORCED"
    elif _boolish_scalar(row.get("_ravelab_whale_origin_flow")) or _boolish_scalar(row.get("_ravelab_target_flow")):
        phase = "INVENTORY"
    elif short_pct is not None and short_pct >= 50.0:
        phase = "FUEL"
    else:
        phase = "WATCH"
    parts = [f"{phase} {forced:.0f}/100", f"exh {exhaustion:.0f}"]
    if short_pct is not None:
        parts.append(f"shorts {short_pct:.1f}%")
    if short_build >= 0.1:
        parts.append(f"+short {short_build:.1f}pp")
    if short_drop >= 1.0:
        parts.append(f"shorts fade {short_drop:.1f}pp")
    if oi_delta is not None and abs(oi_delta) >= 0.1:
        parts.append(f"OI {oi_delta:+.1f}%")
    if volume_multiple is not None and volume_multiple >= 1.2:
        parts.append(f"volx {volume_multiple:.1f}")
    return " ".join(parts)


def _ravelab_next_check(row: pd.Series) -> str:
    side = _clean_scalar_text(row.get("_ravelab_side", ""))
    min_history_days = int(_safe_float(row.get("_ravelab_min_history_days")) or 60)
    if not _boolish_scalar(row.get("_ravelab_whale_gate")):
        return "skip until holder concentration clears the 90% whale gate"
    if not _boolish_scalar(row.get("_ravelab_venue_gate")):
        return "skip until Binance and Bitget venue evidence are both present"
    exhaustion = _safe_float(row.get("_ravelab_exhaustion_score")) or 0.0
    short_drop = _safe_float(row.get("_ravelab_short_drop_pp")) or 0.0
    short_pct = _safe_pct(row.get("short_account_pct")) or 0.0
    if exhaustion >= 70.0 or (short_drop >= 3.0 and short_pct < 50.0):
        return "avoid chase/late risk until short crowd, OI, funding, and volume reset"
    if not _boolish_scalar(row.get("_ravelab_float_gate")):
        return "wait for low-float, FDV/MC gap, locked-supply, or extreme top-wallet float evidence"
    has_no_pump_gate = hasattr(row, "index") and "_ravelab_no_large_pump_gate" in row.index
    if has_no_pump_gate and not _boolish_scalar(row.get("_ravelab_no_large_pump_gate")):
        pump_source = _clean_scalar_text(row.get("_ravelab_recent_pump_source", ""))
        if "insufficient" in pump_source or "missing" in pump_source or "skipped" in pump_source or "not checked" in pump_source:
            return "wait; load 60D daily-candle pump proof before treating dormancy as real"
        max_pump = _safe_float(row.get("_ravelab_max_recent_pump_pct")) or 35.0
        return f"wait; recent daily pump exceeded {max_pump:.0f}% no-pump gate"
    if not _boolish_scalar(row.get("_ravelab_dormant_2m_gate")):
        return f"wait; needs {min_history_days}d history, 60D no-large-pump proof, and no chase heat"
    if not _boolish_scalar(row.get("_ravelab_early_gate")):
        return "wait for heat/late penalty to reset before treating it as early"
    if side != "RAVE-like" and not _boolish_scalar(row.get("_ravelab_target_flow")):
        return "verify labelled Binance/Bitget/Gate inventory flow or venue-inventory stress"
    if side == "RAVE-like":
        return "watch 1D-5D highs, first volume lift, and OI expansion without chase heat"
    return "watch for absorption after target-CEX inventory movement and first perp response"


def _ravelab_stage_label(row: pd.Series) -> str:
    core_count = int(_safe_float(row.get("_ravelab_core_gate_count")) or 0)
    core_total = int(_safe_float(row.get("_ravelab_core_gate_total")) or 6)
    if core_count >= core_total:
        if _boolish_scalar(row.get("_ravelab_whale_origin_flow")) and _boolish_scalar(row.get("_ravelab_breakout_any")):
            return "A4 PRIME+FLOW+BREAKOUT"
        if _boolish_scalar(row.get("_ravelab_whale_origin_flow")):
            return "A3 WHALE-CEX PRIME"
        if _boolish_scalar(row.get("_ravelab_breakout_any")):
            return "A2 BREAKOUT PRIME"
        return "A1 CORE PRIME"
    return f"B{max(0, core_total - core_count)} BLOCKED"


def _ravelab_trigger_text(row: pd.Series, *, fallback: str = "core watch") -> str:
    triggers: list[str] = []
    if _boolish_scalar(row.get("_ravelab_whale_origin_flow")):
        amount_value = row.get("cex_deposit_24h_whale_sender_token_amount")
        if _safe_float(amount_value) is None:
            amount_value = row.get("cex_deposit_24h_max_amount")
        triggers.append(f"whale-CEX {_fmt_compact_number(amount_value)}")
    elif _boolish_scalar(row.get("_ravelab_target_flow")):
        targets = _target_cex_text(row) or "target CEX"
        triggers.append(f"target-CEX {targets} {_fmt_compact_number(row.get('cex_deposit_24h_max_amount'))}")
    if _boolish_scalar(row.get("_ravelab_breakout_any")):
        triggers.append(f"breakout {_clip_text(row.get('_ravelab_breakout_windows', ''), 28) or 'yes'}")
    if _boolish_scalar(row.get("fresh_flip_flag")):
        triggers.append("funding flip")
    return ", ".join(triggers[:4]) if triggers else fallback


def _ravelab_queue_summary_lines(frame: pd.DataFrame, *, limit: int = 8) -> list[str]:
    if frame.empty:
        return []
    trigger_entries: list[str] = []
    core_entries: list[str] = []
    for _, row in frame.head(max(1, int(limit))).iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        stage = _ravelab_stage_label(row).split()[0]
        entry = f"/{symbol} {stage} ({_ravelab_trigger_text(row)})"
        has_trigger = (
            _boolish_scalar(row.get("_ravelab_whale_origin_flow"))
            or _boolish_scalar(row.get("_ravelab_target_flow"))
            or _boolish_scalar(row.get("_ravelab_breakout_any"))
            or _boolish_scalar(row.get("fresh_flip_flag"))
        )
        if stage in {"A2", "A3", "A4"} or (stage == "A1" and has_trigger):
            trigger_entries.append(entry)
        elif stage == "A1":
            core_entries.append(entry)
    lines: list[str] = []
    if trigger_entries:
        lines.append("Trigger queue: " + " | ".join(trigger_entries))
    if core_entries:
        lines.append("Core watch: " + " | ".join(core_entries))
    return lines


def _crime_pump_operator_line(row: pd.Series) -> str:
    symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
    stage = _ravelab_stage_label(row)
    stage = {
        "A1 CORE PRIME": "A1 CORE",
        "A2 BREAKOUT PRIME": "A2 BREAKOUT",
        "A3 WHALE-CEX PRIME": "A3 WHALE-CEX",
        "A4 PRIME+FLOW+BREAKOUT": "A4 FLOW+BREAKOUT",
    }.get(stage, stage)
    side = _clip_text(row.get("_ravelab_side", ""), 18) or "RAVE/LAB"
    thesis = _safe_float(row.get("_ravelab_thesis_score")) or 0.0
    whale_pct = _safe_pct(row.get("_ravelab_whale_pct"))
    whale_text = f"{whale_pct:.1f}%" if whale_pct is not None else "n/a"
    has_binance = "Y" if _boolish_scalar(row.get("_ravelab_has_binance")) else "N"
    has_bitget = "Y" if _boolish_scalar(row.get("_ravelab_has_bitget")) else "N"
    has_gate = "Y" if _boolish_scalar(row.get("_ravelab_has_gate")) else "N"
    holder_evidence_gate = "Y" if _boolish_scalar(row.get("_ravelab_holder_evidence_gate")) else "N"
    history_days = _safe_float(row.get("_ravelab_history_days"))
    history_text = f"{history_days:.0f}d" if history_days is not None and history_days > 0 else "n/a"
    recent_pump = _safe_float(row.get("_ravelab_recent_max_pump_pct"))
    recent_pump_days = _safe_float(row.get("_ravelab_recent_pump_days"))
    pump_text = "n/a"
    if recent_pump is not None:
        pump_text = f"{recent_pump:.1f}%"
        if recent_pump_days is not None and recent_pump_days > 0:
            pump_text += f"/{recent_pump_days:.0f}d"
    squeeze = _safe_float(row.get("_ravelab_squeeze_score")) or 0.0
    squeeze_fuel = _safe_float(row.get("_ravelab_squeeze_fuel_score")) or 0.0
    float_score = _safe_float(row.get("_ravelab_float_score")) or 0.0
    fdv_ratio = _safe_float(row.get("_ravelab_fdv_to_mcap"))
    short_pct = _safe_pct(row.get("short_account_pct"))
    short_text = f"{short_pct:.1f}%" if short_pct is not None else "n/a"
    fdv_text = f" FDV/MC {fdv_ratio:.1f}x" if fdv_ratio is not None and fdv_ratio > 0 else ""
    breakout_windows = _clip_text(row.get("_ravelab_breakout_windows", ""), 32) or "none"
    trigger_text = _ravelab_trigger_text(row)
    mechanics_text = _ravelab_forced_flow_text(row)
    targets = _target_cex_text(row) or "no target flow"
    max_amount = _fmt_compact_number(row.get("cex_deposit_24h_max_amount"))
    whale_flow = _whale_sender_text(row, include_amount=True)
    flow_text = f"{targets} max {max_amount}"
    if whale_flow:
        flow_text += f" | {whale_flow}"
    return (
        f"/{symbol} | {stage} | {side} | trigger {trigger_text} | thesis {thesis:.0f}/100 | whale {whale_text} holderEv {holder_evidence_gate} | "
        f"venues Bn/Bg/Gate {has_binance}/{has_bitget}/{has_gate} | float {float_score:.0f}{fdv_text} | hist {history_text} pump60 {pump_text} | "
        f"flowMech {mechanics_text} | squeeze {squeeze:.0f} fuel {squeeze_fuel:.0f} shorts {short_text} | highs {breakout_windows} | CEX {flow_text}\n"
        f"  next: {_clip_text(_ravelab_next_check(row), 120)}"
    )


def _ravelab_line(row: pd.Series, *, detail: bool = False) -> str:
    symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
    score = _safe_float(row.get("_ravelab_early_score")) or 0.0
    thesis_score = _safe_float(row.get("_ravelab_thesis_score")) or 0.0
    side = _clip_text(row.get("_ravelab_side", ""), 18) or "RAVE/LAB"
    state = _ravelab_stage_label(row)
    rave = _safe_float(row.get("_ravelab_rave_score")) or 0.0
    lab = _safe_float(row.get("_ravelab_lab_score")) or 0.0
    setup = _safe_float(row.get("rave_lab_setup_score")) or 0.0
    latent = _safe_float(row.get("pre_activity_pump_score")) or 0.0
    targets = _target_cex_text(row) or "no target flow"
    cex_count = int(_safe_float(row.get("cex_deposit_24h_count")) or 0)
    max_amount = _fmt_compact_number(row.get("cex_deposit_24h_max_amount"))
    control = _safe_float(row.get("pre_activity_control_score")) or _safe_float(row.get("centralized_ownership_score")) or 0.0
    float_score = _safe_float(row.get("pre_activity_float_score")) or _safe_float(row.get("low_float_score")) or 0.0
    ravelab_float_score = _safe_float(row.get("_ravelab_float_score")) or float_score
    fdv_ratio = _safe_float(row.get("_ravelab_fdv_to_mcap"))
    quiet = _safe_float(row.get("pre_activity_quiet_score")) or 0.0
    heat = _safe_float(row.get("_ravelab_heat_score")) or _safe_float(row.get("pre_activity_heat_score")) or 0.0
    top10 = _safe_pct(row.get("top10_holder_pct"))
    top100 = _safe_pct(row.get("top100_holder_pct"))
    short_pct = _safe_pct(row.get("short_account_pct"))
    whale_pct = _safe_pct(row.get("_ravelab_whale_pct"))
    squeeze = _safe_float(row.get("_ravelab_squeeze_score")) or 0.0
    squeeze_fuel = _safe_float(row.get("_ravelab_squeeze_fuel_score")) or 0.0
    short_squeeze_model = _safe_float(row.get("short_squeeze_score"))
    crime_model = _safe_float(row.get("crime_pump_score_v2"))
    breakout = _safe_float(row.get("_ravelab_breakout_score")) or 0.0
    core_count = int(_safe_float(row.get("_ravelab_core_gate_count")) or 0)
    core_total = int(_safe_float(row.get("_ravelab_core_gate_total")) or 6)
    missing_core = _clip_text(row.get("_ravelab_missing_core_gates", ""), 66) or "none"
    history_days = _safe_float(row.get("_ravelab_history_days"))
    recent_pump = _safe_float(row.get("_ravelab_recent_max_pump_pct"))
    recent_pump_days = _safe_float(row.get("_ravelab_recent_pump_days"))
    breakout_windows = _clip_text(row.get("_ravelab_breakout_windows", ""), 44) or "n/a"
    has_binance = "Y" if _boolish_scalar(row.get("_ravelab_has_binance")) else "N"
    has_bitget = "Y" if _boolish_scalar(row.get("_ravelab_has_bitget")) else "N"
    has_gate = "Y" if _boolish_scalar(row.get("_ravelab_has_gate")) else "N"
    dormant = "Y" if _boolish_scalar(row.get("_ravelab_dormant_2m_gate")) else "N"
    has_no_pump_gate = hasattr(row, "index") and "_ravelab_no_large_pump_gate" in row.index
    no_pump = "Y" if _boolish_scalar(row.get("_ravelab_no_large_pump_gate")) else "N" if has_no_pump_gate else "?"
    whale_gate = "Y" if _boolish_scalar(row.get("_ravelab_whale_gate")) else "N"
    holder_evidence_gate = "Y" if _boolish_scalar(row.get("_ravelab_holder_evidence_gate")) else "N"
    venue_gate = "Y" if _boolish_scalar(row.get("_ravelab_venue_gate")) else "N"
    squeeze_gate = "Y" if _boolish_scalar(row.get("_ravelab_squeeze_gate", squeeze >= 50.0)) else "N"
    float_gate = "Y" if _boolish_scalar(row.get("_ravelab_float_gate")) else "N"
    short_majority = "Y" if _boolish_scalar(row.get("_ravelab_short_majority_gate", False)) else "N"
    fresh_flip = "Y" if _boolish_scalar(row.get("fresh_flip_flag")) else "N"
    top10_text = f"{top10:.1f}%" if top10 is not None else "n/a"
    top100_text = f"{top100:.1f}%" if top100 is not None else "n/a"
    whale_text = f"{whale_pct:.1f}%" if whale_pct is not None else "n/a"
    short_text = f"{short_pct:.1f}%" if short_pct is not None else "n/a"
    history_text = f"{history_days:.0f}d" if history_days is not None and history_days > 0 else "n/a"
    fdv_text = f"{fdv_ratio:.1f}x" if fdv_ratio is not None and fdv_ratio > 0 else "n/a"
    if recent_pump is not None:
        pump_text = f"{recent_pump:.1f}%"
        if recent_pump_days is not None and recent_pump_days > 0:
            pump_text += f"/{recent_pump_days:.0f}d"
    else:
        pump_text = "n/a"
    pump_source = _clip_text(row.get("_ravelab_recent_pump_source", ""), 28) or "unverified"
    holder_evidence = _holder_evidence_text(row)
    venue_evidence = _venue_evidence_text(row)
    whale_flow = _whale_sender_text(row, include_amount=True)
    whale_flow_text = f" whale-CEX {whale_flow}" if whale_flow else ""
    anchor_symbol, anchor_date = _ravelab_anchor_for_side(side, rave, lab)
    anchor = f" | anchor {anchor_symbol} {anchor_date}" if anchor_symbol else ""
    next_check = _clip_text(_ravelab_next_check(row), 96)
    crime_text = f" crime {crime_model:.0f}/100" if crime_model is not None and crime_model > 0 else ""
    short_squeeze_text = f" ssq {short_squeeze_model:.0f}" if short_squeeze_model is not None and short_squeeze_model > 0 else ""
    trigger_text = _ravelab_trigger_text(row)
    mechanics_text = _ravelab_forced_flow_text(row)
    headline = (
        f"/{symbol} | {side} | {state} | core {core_count}/{core_total} | "
        f"trigger {trigger_text} | thesis {thesis_score:.0f}/100{crime_text} early {score:.0f}/100 | blockers {missing_core}{anchor}"
    )
    proof = (
        f"  proof: whale {whale_text} holderEv {holder_evidence_gate} | venues Bn {has_binance}/Bg {has_bitget}/Gate {has_gate} | "
        f"float {ravelab_float_score:.0f}({float_gate}) FDV/MC {fdv_text} | "
        f"noPump {no_pump} pump60 {pump_text} {pump_source} | hist {history_text} dormant2m {dormant} | "
        f"flowMech {mechanics_text} | "
        f"squeeze {squeeze:.0f}({squeeze_gate}) fuel {squeeze_fuel:.0f}{short_squeeze_text} flip {fresh_flip} shortMaj {short_majority} shorts {short_text} | highs {breakout_windows} | "
        f"CEX {targets} {cex_count}tx max {max_amount}{whale_flow_text} | holder {holder_evidence} | venue {venue_evidence}"
    )
    if not detail:
        return "\n".join([headline, proof, f"  next: {next_check}"])
    hard_gates = (
        f"  hard gates: whale {whale_gate} holderEv {holder_evidence_gate} venue {venue_gate} float {float_gate} "
        f"noPump {no_pump} dormant2m {dormant} squeeze {squeeze_gate} | "
        f"venues Bn {has_binance}/Bg {has_bitget}/Gate {has_gate} | highs {breakout_windows}"
    )
    evidence = (
        f"  evidence: whale {whale_text} (t10 {top10_text}, t100 {top100_text}) | holder {holder_evidence} | float {ravelab_float_score:.0f} FDV/MC {fdv_text} | "
        f"venue {venue_evidence} | flowMech {mechanics_text} | squeeze {squeeze:.0f} fuel {squeeze_fuel:.0f}{short_squeeze_text} flip {fresh_flip} shortMaj {short_majority} shorts {short_text} | history {history_text} pump60 {pump_text} {pump_source}"
    )
    flow = (
        f"  flow/timing: CEX {targets} {cex_count}tx max {max_amount}{whale_flow_text} | "
        f"breakout {breakout:.0f} | control {control:.0f} float {float_score:.0f} | quiet {quiet:.0f} heat {heat:.0f} | "
        f"RAVE {rave:.0f} LAB {lab:.0f} dashboard {setup:.0f} latent {latent:.0f}{anchor}"
    )
    return "\n".join([headline, hard_gates, evidence, flow, f"  next: {next_check}"])


def _ravelab_holder_evidence_counts(frame: pd.DataFrame) -> tuple[int, int, int]:
    if frame.empty:
        return 0, 0, 0
    evidence_mask, contract_mask = _ravelab_holder_evidence_masks(frame)
    return int(evidence_mask.sum()), int(contract_mask.sum()), int((~evidence_mask).sum())


def _ravelab_holder_evidence_masks(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    return _strict_holder_evidence_masks(frame)


def _ravelab_whale_control_series(frame: pd.DataFrame) -> pd.Series:
    return _safe_pct_series(frame, "top10_holder_pct").fillna(0.0)


def _ravelab_whale_gate_series(frame: pd.DataFrame, *, min_whale_pct: float) -> pd.Series:
    return _ravelab_whale_control_series(frame).ge(_strict_thesis_min_whale_pct(min_whale_pct)).fillna(False)


def _ravelab_near_miss_rows(
    scored: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    limit: int,
    style_key: str,
    min_score: float,
    min_archetype: float,
    min_squeeze_score: float,
    require_holder_evidence: bool,
    require_binance_bitget: bool,
) -> pd.DataFrame:
    require_holder_evidence = True
    require_binance_bitget = True
    if scored.empty or limit <= 0:
        return pd.DataFrame()
    candidates = scored.copy()
    if "symbol" in candidates.columns and not selected.empty and "symbol" in selected.columns:
        selected_symbols = set(selected["symbol"].astype(str).str.upper().str.strip())
        candidates = candidates[~candidates["symbol"].astype(str).str.upper().str.strip().isin(selected_symbols)].copy()
    if candidates.empty:
        return candidates

    base_mask = (
        _num_series(candidates, "_ravelab_early_score").ge(max(0.0, float(min_score)))
        & _num_series(candidates, "_ravelab_archetype_score").ge(max(0.0, float(min_archetype)))
        & _boolish_series(candidates.get("_ravelab_whale_gate"), index=candidates.index)
        & _boolish_series(candidates.get("_ravelab_squeeze_gate"), index=candidates.index)
        & _num_series(candidates, "_ravelab_core_gate_count").ge(3.0)
    )
    candidates = candidates[base_mask].copy()
    if candidates.empty:
        return candidates
    if require_holder_evidence:
        candidates = candidates[_boolish_series(candidates.get("_ravelab_holder_evidence_gate"), index=candidates.index)].copy()
    if require_binance_bitget:
        candidates = candidates[_boolish_series(candidates.get("_ravelab_venue_gate"), index=candidates.index)].copy()
    if candidates.empty:
        return candidates
    if style_key == "rave":
        candidates = candidates[candidates["_ravelab_side"].astype(str).isin(["RAVE-like", "Mixed RAVE/LAB"])].copy()
    elif style_key == "lab":
        candidates = candidates[candidates["_ravelab_side"].astype(str).isin(["LAB-like", "Mixed RAVE/LAB"])].copy()
    if candidates.empty:
        return candidates
    return candidates.sort_values(
        [
            "_ravelab_core_gate_count",
            "_ravelab_whale_origin_flow",
            "_ravelab_holder_evidence_gate",
            "_ravelab_venue_gate",
            "_ravelab_float_gate",
            "_ravelab_dormant_2m_gate",
            "_ravelab_thesis_score",
            "_ravelab_early_score",
            "_ravelab_whale_pct",
            "symbol",
        ],
        ascending=[False, False, False, False, False, False, False, False, False, True],
    ).head(min(max(int(limit), 0), 30))


def _normalize_ravelab_trigger_filter(trigger_filter: str) -> str:
    normalized = str(trigger_filter or "all").strip().lower().replace("-", "_")
    aliases = {
        "any": "triggered",
        "trigger": "triggered",
        "triggers": "triggered",
        "whale": "flow",
        "whale_flow": "flow",
        "cex": "target_flow",
        "cex_flow": "target_flow",
        "target": "target_flow",
        "targetflow": "target_flow",
        "breakouts": "breakout",
        "high": "breakout",
        "highs": "breakout",
        "core_watch": "core",
        "watch": "core",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"all", "triggered", "flow", "target_flow", "breakout", "core"} else "all"


def _ravelab_trigger_filter_mask(frame: pd.DataFrame, trigger_filter: str) -> pd.Series:
    if frame.empty:
        return pd.Series(False, index=frame.index)
    mode = _normalize_ravelab_trigger_filter(trigger_filter)
    whale_flow = _boolish_series(frame.get("_ravelab_whale_origin_flow"), index=frame.index)
    target_flow = _boolish_series(frame.get("_ravelab_target_flow"), index=frame.index)
    breakout = _boolish_series(frame.get("_ravelab_breakout_any"), index=frame.index)
    funding_flip = _boolish_series(frame.get("fresh_flip_flag"), index=frame.index)
    core_full = _num_series(frame, "_ravelab_core_gate_count").ge(_num_series(frame, "_ravelab_core_gate_total", default=6.0))
    if mode == "flow":
        return whale_flow.fillna(False)
    if mode == "target_flow":
        return target_flow.fillna(False)
    if mode == "breakout":
        return breakout.fillna(False)
    if mode == "triggered":
        return (whale_flow | target_flow | breakout | funding_flip).fillna(False)
    if mode == "core":
        return (core_full & ~(whale_flow | target_flow | breakout | funding_flip)).fillna(False)
    return pd.Series(True, index=frame.index)


def _ravelab_base_funnel_mask_and_steps(
    scored: pd.DataFrame,
    *,
    min_score: float,
    min_archetype: float,
    require_holder_evidence: bool,
    require_binance_bitget: bool,
    require_dormant_2m: bool,
    require_quiet: bool,
    require_target_flow: bool,
    require_whale_origin_flow: bool,
    style_key: str,
) -> tuple[pd.Series, list[tuple[str, int]]]:
    require_holder_evidence = True
    require_binance_bitget = True
    require_dormant_2m = True
    if scored.empty:
        return pd.Series(False, index=scored.index), [("scan", 0)]
    index = scored.index
    mask = (
        _num_series(scored, "_ravelab_early_score").ge(max(0.0, float(min_score)))
        & _num_series(scored, "_ravelab_archetype_score").ge(max(0.0, float(min_archetype)))
    )
    steps: list[tuple[str, int]] = [("scan", len(scored)), ("score", int(mask.sum()))]

    mask = mask & _boolish_series(scored.get("_ravelab_whale_gate"), index=index)
    steps.append(("whale90", int(mask.sum())))
    if require_holder_evidence:
        mask = mask & _boolish_series(scored.get("_ravelab_holder_evidence_gate"), index=index)
        steps.append(("holderSrc", int(mask.sum())))
    if require_binance_bitget:
        mask = mask & _boolish_series(scored.get("_ravelab_venue_gate"), index=index)
        steps.append(("Bn+Bg", int(mask.sum())))
    mask = mask & _boolish_series(scored.get("_ravelab_float_gate"), index=index)
    steps.append(("float", int(mask.sum())))
    mask = mask & _boolish_series(scored.get("_ravelab_squeeze_gate"), index=index)
    steps.append(("squeeze", int(mask.sum())))
    if require_dormant_2m:
        mask = mask & _boolish_series(scored.get("_ravelab_dormant_2m_gate"), index=index)
        steps.append(("dormant", int(mask.sum())))
    if style_key == "rave":
        mask = mask & scored["_ravelab_side"].astype(str).isin(["RAVE-like", "Mixed RAVE/LAB"])
        steps.append(("raveStyle", int(mask.sum())))
    elif style_key == "lab":
        mask = mask & scored["_ravelab_side"].astype(str).isin(["LAB-like", "Mixed RAVE/LAB"])
        steps.append(("labStyle", int(mask.sum())))
    if require_quiet:
        mask = mask & _boolish_series(scored.get("_ravelab_early_gate"), index=index)
        steps.append(("early", int(mask.sum())))
    if require_target_flow:
        mask = mask & _boolish_series(scored.get("_ravelab_target_flow"), index=index)
        steps.append(("targetCEX", int(mask.sum())))
    if require_whale_origin_flow:
        mask = mask & _boolish_series(scored.get("_ravelab_whale_origin_flow"), index=index)
        steps.append(("whale-CEX", int(mask.sum())))
    return mask.fillna(False), steps


def _ravelab_funnel_line(steps: list[tuple[str, int]]) -> str:
    return "Gate funnel: " + " -> ".join(f"{label} {count}" for label, count in steps)


def _ravelab_core_full_count(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    core_total = _num_series(frame, "_ravelab_core_gate_total", default=6.0)
    return int(_num_series(frame, "_ravelab_core_gate_count").ge(core_total).sum())


def _ravelab_core_label(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "Core 6/6"
    core_total = _num_series(frame, "_ravelab_core_gate_total", default=6.0)
    total = int(_safe_float(core_total.max()) or 6)
    return f"Core {total}/{total}"


def _ravelab_lane_counts_line(frame: pd.DataFrame, *, trigger_filter_key: str = "all", shown_count: int | None = None) -> str:
    label = "Trigger lanes before filter" if _normalize_ravelab_trigger_filter(trigger_filter_key) != "all" else "Trigger lanes"
    shown = len(frame) if shown_count is None else int(shown_count)
    if frame.empty:
        return f"{label}: triggered 0 | whale-CEX 0 | target-CEX 0 | breakout 0 | core-watch 0 | shown {shown}"
    whale_flow = _boolish_series(frame.get("_ravelab_whale_origin_flow"), index=frame.index)
    target_flow = _boolish_series(frame.get("_ravelab_target_flow"), index=frame.index)
    breakout = _boolish_series(frame.get("_ravelab_breakout_any"), index=frame.index)
    core_watch = _ravelab_trigger_filter_mask(frame, "core")
    triggered = _ravelab_trigger_filter_mask(frame, "triggered")
    return (
        f"{label}: triggered {int(triggered.sum())} | whale-CEX {int(whale_flow.sum())} | "
        f"target-CEX {int(target_flow.sum())} | breakout {int(breakout.sum())} | "
        f"core-watch {int(core_watch.sum())} | shown {shown}"
    )


def _load_ravelab_list(
    limit: int,
    *,
    min_score: float = 0.0,
    min_archetype: float = 0.0,
    min_whale_pct: float = 90.0,
    min_squeeze_score: float = 50.0,
    min_history_days: int = 60,
    max_recent_pump_pct: float = 35.0,
    min_tokens: float | None = None,
    whale_flow_min_tokens: float | None = None,
    lookback_hours: int | None = None,
    breakout_windows: str = "1D,2D,3D,4D,5D,20D",
    style: str = "both",
    require_quiet: bool = True,
    require_target_flow: bool = False,
    require_binance_bitget: bool = True,
    require_dormant_2m: bool = True,
    require_holder_evidence: bool = True,
    require_breakout_high: bool = False,
    require_whale_origin_flow: bool = False,
    trigger_filter: str = "all",
    near_miss_limit: int = 5,
    detail: bool = False,
    compact: bool = False,
    compact_title: str = "Crime-pump early queue",
) -> tuple[str, list[str]]:
    require_binance_bitget = True
    require_dormant_2m = True
    require_holder_evidence = True
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    effective_whale_flow_floor = _ravelab_whale_flow_floor(effective_min_transfer, whale_flow_min_tokens)
    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    style_key = str(style or "both").strip().lower()
    if style_key not in {"both", "rave", "lab"}:
        style_key = "both"
    trigger_filter_key = _normalize_ravelab_trigger_filter(trigger_filter)
    operator_title = _clip_text(compact_title, 60) or "Crime-pump early queue"
    breakout_days, ignored_breakout_windows = _parse_breakout_window_list(breakout_windows)
    breakout_label = ",".join(f"{days}D" for days in breakout_days) if breakout_days else "disabled"
    pump_proof_days = max(1, min(60, int(min_history_days)))
    ignored_breakout_text = (
        f" | Ignored breakout windows: {', '.join(ignored_breakout_windows[:5])}"
        if ignored_breakout_windows
        else ""
    )
    header = (
        "Strict RAVE/LAB crime-pump early radar\n"
        f"Source: {source} | Transfer floor: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h | "
        f"Whale-CEX floor: {_fmt_compact_number(effective_whale_flow_floor)} tokens | "
        f"Style: {style_key} | Min early score: {float(min_score):.0f} | Min RAVE/LAB archetype: {float(min_archetype):.0f} | "
        f"Whale gate: top10 >= {effective_min_whale_pct:.1f}% | Squeeze stack gate: >= {float(min_squeeze_score):.0f} | "
        f"History gate: >= {int(min_history_days)}d | Max recent pump: < {float(max_recent_pump_pct):.0f}% over 60d | "
        f"Holder evidence required: {require_holder_evidence} | "
        f"Binance+Bitget required: {require_binance_bitget} | Dormant 2m required: {require_dormant_2m} | "
        f"Quiet required: {require_quiet} | Target flow required: {require_target_flow} | Whale-origin CEX required: {require_whale_origin_flow} | "
        f"High breakout windows: {breakout_label} | Breakout required: {require_breakout_high} | Near misses: {max(0, int(near_miss_limit))} | "
        f"Trigger filter: {trigger_filter_key} | Detail: {detail}{ignored_breakout_text}\n"
        f"No-pump proof: requires {pump_proof_days}D closed daily-candle pump history; missing/insufficient proof fails dormant2m.\n"
        "Core gates: top10 whale-control threshold with chain+contract explorer holder-source snapshot evidence, Binance+Bitget, float/FDV trap, 2mo no-pump/dormancy, squeeze stack, early/no-chase.\n"
        "Anchors: RAVEUSDT 2026-04-18 = cap-table reflexivity; LABUSDT 2026-05-11 = venue-inventory stress."
    )
    if frame.empty:
        return "RAVE/LAB early radar", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]

    scored = _score_ravelab_early_frame(
        frame,
        min_whale_pct=effective_min_whale_pct,
        min_history_days=min_history_days,
        max_recent_pump_pct=max_recent_pump_pct,
        min_transfer_tokens=effective_min_transfer,
    )
    holder_evidence_mask, _ = _ravelab_holder_evidence_masks(scored)
    scored["_ravelab_holder_evidence_gate"] = holder_evidence_mask
    scored["_ravelab_squeeze_gate"] = _ravelab_squeeze_gate_series(scored, min_squeeze_score=min_squeeze_score)
    pump_check_mask = (
        _num_series(scored, "_ravelab_early_score").ge(max(0.0, float(min_score)))
        & _num_series(scored, "_ravelab_archetype_score").ge(max(0.0, float(min_archetype)))
        & _boolish_series(scored.get("_ravelab_whale_gate"), index=scored.index)
        & _boolish_series(scored.get("_ravelab_squeeze_gate"), index=scored.index)
        & _boolish_series(scored.get("_ravelab_float_gate"), index=scored.index)
    )
    if require_holder_evidence:
        pump_check_mask = pump_check_mask & _boolish_series(scored.get("_ravelab_holder_evidence_gate"), index=scored.index)
    if require_binance_bitget:
        pump_check_mask = pump_check_mask & _boolish_series(scored.get("_ravelab_venue_gate"), index=scored.index)
    scored, pump_stats = _apply_ravelab_recent_pump_window(
        scored,
        pump_check_mask,
        min_history_days=int(min_history_days),
        max_recent_pump_pct=float(max_recent_pump_pct),
        days=60,
    )
    scored = _ravelab_apply_thesis_columns(
        scored,
        min_squeeze_score=min_squeeze_score,
        min_transfer_tokens=effective_min_transfer,
        min_whale_flow_tokens=effective_whale_flow_floor,
    )
    base_mask, funnel_steps = _ravelab_base_funnel_mask_and_steps(
        scored,
        min_score=min_score,
        min_archetype=min_archetype,
        require_holder_evidence=require_holder_evidence,
        require_binance_bitget=require_binance_bitget,
        require_dormant_2m=require_dormant_2m,
        require_quiet=require_quiet,
        require_target_flow=require_target_flow,
        require_whale_origin_flow=require_whale_origin_flow,
        style_key=style_key,
    )
    selected = scored[base_mask].copy()
    breakout_stats = {"checked": 0, "errors": 0, "insufficient": 0, "cached": 0}
    if not selected.empty:
        selected, breakout_stats = _apply_ravelab_high_breakout_windows(selected, breakout_days)
        selected = _ravelab_apply_thesis_columns(
            selected,
            min_squeeze_score=min_squeeze_score,
            min_transfer_tokens=effective_min_transfer,
            min_whale_flow_tokens=effective_whale_flow_floor,
        )
        if require_breakout_high:
            selected = selected[_boolish_series(selected.get("_ravelab_breakout_any"), index=selected.index)].copy()
    if require_breakout_high:
        funnel_steps.append(("breakout", len(selected)))
    lanes_before_trigger = selected.copy()
    if trigger_filter_key != "all":
        if not selected.empty:
            selected = selected[_ravelab_trigger_filter_mask(selected, trigger_filter_key)].copy()
        funnel_steps.append((f"trigger:{trigger_filter_key}", len(selected)))
    funnel_steps.append(("shown", len(selected)))
    funnel_line = _ravelab_funnel_line(funnel_steps)
    lane_counts_line = _ravelab_lane_counts_line(lanes_before_trigger, trigger_filter_key=trigger_filter_key, shown_count=len(selected))
    holder_evidence_rows, holder_contract_rows, holder_pct_only_rows = _ravelab_holder_evidence_counts(selected)

    if selected.empty:
        gate_counts = (
            f"Gate counts before filters: whale {int(_boolish_series(scored.get('_ravelab_whale_gate'), index=scored.index).sum())} | "
            f"holder evidence {int(_boolish_series(scored.get('_ravelab_holder_evidence_gate'), index=scored.index).sum())} | "
            f"Binance+Bitget {int(_boolish_series(scored.get('_ravelab_venue_gate'), index=scored.index).sum())} | "
            f"float/FDV {int(_boolish_series(scored.get('_ravelab_float_gate'), index=scored.index).sum())} | "
            f"no-pump {int(_boolish_series(scored.get('_ravelab_no_large_pump_gate'), index=scored.index).sum())} | "
            f"dormant2m/history {int(_boolish_series(scored.get('_ravelab_dormant_2m_gate'), index=scored.index).sum())} | "
            f"squeeze {int(_boolish_series(scored.get('_ravelab_squeeze_gate'), index=scored.index).sum())} | "
            f"{_ravelab_core_label(scored).lower()} {_ravelab_core_full_count(scored)} | "
            f"whale-origin CEX {int(_boolish_series(scored.get('_ravelab_whale_origin_flow'), index=scored.index).sum())}"
        )
        if compact:
            lines = [
                operator_title,
                (
                    f"Source: {source} | Floor: {_fmt_compact_number(effective_min_transfer)} tokens | "
                    f"Whale-CEX >= {_fmt_compact_number(effective_whale_flow_floor)} | "
                    f"Lookback: {effective_lookback}h | Trigger: {trigger_filter_key} | Breakouts: {breakout_label}"
                ),
                "Hard gates: top10 whale-control threshold with ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence; Binance+Bitget; float/FDV trap; 60D no-pump/dormant; squeeze stack; early/no-chase.",
                gate_counts,
                funnel_line,
                lane_counts_line,
                "",
                "No hard-gated early crime-pump candidates passed the current operator filters.",
                "Use `/ravelab near_miss_limit:5 detail:true` for blockers and data-coverage diagnostics.",
            ]
            return operator_title, _chunk_text_lines(lines)
        nearest = scored.sort_values(
            [
                "_ravelab_core_gate_count",
                "_ravelab_whale_origin_flow",
                "_ravelab_whale_gate",
                "_ravelab_holder_evidence_gate",
                "_ravelab_venue_gate",
                "_ravelab_dormant_2m_gate",
                "_ravelab_squeeze_score",
                "_ravelab_thesis_score",
                "_ravelab_early_score",
                "symbol",
            ],
            ascending=[False, False, False, False, False, False, False, False, False, True],
        ).head(min(max(int(limit), 1), 30))
        lines = [
            header,
            gate_counts,
            funnel_line,
            lane_counts_line,
            (
                f"Holder evidence rows: {holder_evidence_rows} with {RAVELAB_HOLDER_EVIDENCE_CHAIN_LABEL} chain+contract explorer holder-source snapshot | "
                f"contract rows {holder_contract_rows} | pct-only rows {holder_pct_only_rows}"
            ),
            (
                f"Breakout high checks: {breakout_label} | dynamic checks {breakout_stats['checked']} | "
                f"errors {breakout_stats['errors']} | insufficient {breakout_stats['insufficient']}"
            ),
            (
                f"Daily pump checks: cached {pump_stats['cached']} | Binance checked {pump_stats['checked']} | "
                f"errors {pump_stats['errors']} | insufficient {pump_stats['insufficient']} | skipped {pump_stats['skipped']}"
            ),
            "",
            "No rows passed the requested strict filters. Nearest rows, with failed gates visible:",
            "",
            *[_ravelab_line(row, detail=detail) for _, row in nearest.iterrows()],
        ]
        return "RAVE/LAB early radar", _chunk_text_lines(lines)

    selected = selected.sort_values(
        [
            "_ravelab_core_gate_count",
            "_ravelab_whale_origin_flow",
            "_ravelab_alert_flag",
            "_ravelab_target_flow",
            "_ravelab_holder_evidence_gate",
            "_ravelab_breakout_any",
            "_ravelab_whale_pct",
            "_ravelab_thesis_score",
            "_ravelab_early_score",
            "_ravelab_squeeze_score",
            "_ravelab_archetype_score",
            "symbol",
        ],
        ascending=[False, False, False, False, False, False, False, False, False, False, False, True],
    ).head(min(max(int(limit), 1), 100))
    near_misses = _ravelab_near_miss_rows(
        scored,
        selected,
        limit=max(0, int(near_miss_limit)),
        style_key=style_key,
        min_score=min_score,
        min_archetype=min_archetype,
        min_squeeze_score=min_squeeze_score,
        require_holder_evidence=require_holder_evidence,
        require_binance_bitget=require_binance_bitget,
    )
    target_count = int(_boolish_series(selected.get("_ravelab_target_flow"), index=selected.index).sum())
    whale_origin_count = int(_boolish_series(selected.get("_ravelab_whale_origin_flow"), index=selected.index).sum())
    core_count = _ravelab_core_full_count(selected)
    core_label = _ravelab_core_label(selected)
    rave_count = int(selected["_ravelab_side"].astype(str).eq("RAVE-like").sum())
    lab_count = int(selected["_ravelab_side"].astype(str).eq("LAB-like").sum())
    mixed_count = int(selected["_ravelab_side"].astype(str).eq("Mixed RAVE/LAB").sum())
    gate_summary = (
        f"All shown rows passed top10 whale-control >= {effective_min_whale_pct:.1f}%"
        f"{', explorer holder-source snapshot evidence' if require_holder_evidence else ''}"
        f"{', Binance+Bitget' if require_binance_bitget else ''}"
        ", float/FDV trap"
        f"{f', no recent pump >= {float(max_recent_pump_pct):.0f}%, history >= {int(min_history_days)}d and dormant2m' if require_dormant_2m else ''}"
        f", squeeze stack >= {float(min_squeeze_score):.0f}."
    )
    symbols = " ".join(f"/{str(symbol).upper().strip()}" for symbol in selected.get("symbol", pd.Series(dtype='object')).tolist())
    queue_summary = _ravelab_queue_summary_lines(selected)
    if compact:
        triggered_count = int(_ravelab_trigger_filter_mask(selected, "triggered").sum())
        breakout_count = int(_boolish_series(selected.get("_ravelab_breakout_any"), index=selected.index).sum())
        lines = [
            operator_title,
            (
                f"Source: {source} | Floor: {_fmt_compact_number(effective_min_transfer)} tokens | "
                f"Whale-CEX >= {_fmt_compact_number(effective_whale_flow_floor)} | "
                f"Lookback: {effective_lookback}h | Trigger: {trigger_filter_key} | Breakouts: {breakout_label}"
            ),
            "Hard gates: top10 whale-control threshold with ETH/BNB/ARB chain+contract explorer holder-source snapshot evidence; Binance+Bitget; float/FDV trap; 60D no-pump/dormant; squeeze stack; early/no-chase.",
            (
                f"Matches: {len(selected)} | {core_label}: {core_count} | Triggered: {triggered_count} | "
                f"Whale-origin CEX: {whale_origin_count} | Target-flow: {target_count} | Breakout highs: {breakout_count}"
            ),
            funnel_line,
            lane_counts_line,
        ]
        if queue_summary:
            lines.extend(queue_summary)
        lines.extend(["", f"Candidates: {symbols}" if symbols else "Candidates: none", ""])
        for _, row in selected.iterrows():
            lines.append(_crime_pump_operator_line(row))
        lines.extend(["", "Use `/ravelab near_miss_limit:5 detail:true` for blocked rows and full evidence."])
        return operator_title, _chunk_text_lines(lines)
    lines = [
        header,
        (
            f"Matches: {len(selected)} | RAVE-like: {rave_count} | LAB-like: {lab_count} | Mixed: {mixed_count} | "
            f"{core_label}: {core_count} | Target-flow rows: {target_count} | Whale-origin CEX rows: {whale_origin_count} | "
            f"Near misses shown: {len(near_misses)} | Read: historical-analogue screen, not trade instruction."
        ),
        funnel_line,
        lane_counts_line,
    ]
    if queue_summary:
        lines.extend(queue_summary)
    lines.extend([
        gate_summary,
        (
            f"Holder evidence rows: {holder_evidence_rows} with {RAVELAB_HOLDER_EVIDENCE_CHAIN_LABEL} chain+contract explorer holder-source snapshot | "
            f"contract rows {holder_contract_rows} | pct-only rows {holder_pct_only_rows}"
        ),
        (
            f"Breakout high checks: {breakout_label} | dynamic checks {breakout_stats['checked']} | "
            f"cached flags {breakout_stats['cached']} | errors {breakout_stats['errors']} | insufficient {breakout_stats['insufficient']}"
        ),
        (
            f"Daily pump checks: cached {pump_stats['cached']} | Binance checked {pump_stats['checked']} | "
            f"errors {pump_stats['errors']} | insufficient {pump_stats['insufficient']} | skipped {pump_stats['skipped']}"
        ),
        "",
        f"Candidates: {symbols}" if symbols else "Candidates: none",
        "",
    ])
    for _, row in selected.iterrows():
        lines.append(_ravelab_line(row, detail=detail))
    if not near_misses.empty:
        lines.extend(
            [
                "",
                "Near misses (blocked, not eligible yet; failed gates are shown as blockers):",
                "",
            ]
        )
        for _, row in near_misses.iterrows():
            lines.append(_ravelab_line(row, detail=detail))
    return "RAVE/LAB early radar", _chunk_text_lines(lines)


def _load_crimepump_list(
    limit: int,
    *,
    min_tokens: float | None = None,
    whale_flow_min_tokens: float | None = None,
    lookback_hours: int | None = None,
    trigger: str = "all",
    breakout_windows: str = "1D,2D,3D,4D,5D,20D",
    compact_title: str = "Crime-pump early queue",
) -> tuple[str, list[str]]:
    trigger_key = _normalize_ravelab_trigger_filter(trigger)
    return _load_ravelab_list(
        limit,
        min_score=0.0,
        min_archetype=0.0,
        min_whale_pct=90.0,
        min_squeeze_score=50.0,
        min_history_days=60,
        max_recent_pump_pct=35.0,
        min_tokens=min_tokens,
        whale_flow_min_tokens=whale_flow_min_tokens,
        lookback_hours=lookback_hours,
        breakout_windows=breakout_windows,
        style="both",
        require_quiet=True,
        require_target_flow=False,
        require_binance_bitget=True,
        require_dormant_2m=True,
        require_holder_evidence=True,
        require_breakout_high=False,
        require_whale_origin_flow=False,
        trigger_filter=trigger_key,
        near_miss_limit=0,
        detail=False,
        compact=True,
        compact_title=compact_title,
    )


def _load_radar_list(
    limit: int,
    *,
    min_tokens: float | None = None,
    whale_flow_min_tokens: float | None = None,
    lookback_hours: int | None = None,
    trigger: str = "all",
    breakout_windows: str = "1D,2D,3D,4D,5D,20D",
) -> tuple[str, list[str]]:
    return _load_crimepump_list(
        limit,
        min_tokens=min_tokens,
        whale_flow_min_tokens=whale_flow_min_tokens,
        lookback_hours=lookback_hours,
        trigger=trigger,
        breakout_windows=breakout_windows,
        compact_title="Early structure radar",
    )


def _load_prime_list(
    limit: int,
    *,
    min_tokens: float | None = None,
    whale_flow_min_tokens: float | None = None,
    lookback_hours: int | None = None,
    trigger: str = "all",
    breakout_windows: str = "1D,2D,3D,4D,5D,20D",
) -> tuple[str, list[str]]:
    _title, chunks = _load_crimepump_list(
        limit,
        min_tokens=min_tokens,
        whale_flow_min_tokens=whale_flow_min_tokens,
        lookback_hours=lookback_hours,
        trigger=trigger,
        breakout_windows=breakout_windows,
        compact_title="Prime crime-pump queue",
    )
    return "Prime crime-pump queue", chunks


def _load_flow_proof(symbol_query: str, *, min_tokens: float | None = None, lookback_hours: int | None = None) -> tuple[str, str]:
    symbol = _normalize_symbol_query(symbol_query)
    if not symbol:
        return "Flow proof", "Use `/flowproof symbol:PLAYUSDT min_tokens:20000`."
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    row = _row_for_symbol(frame, symbol)
    if row is None:
        return f"{symbol} flow proof", f"No scan row found for {symbol}. Source: {source or 'unavailable'}"
    row_frame = pd.DataFrame([row.to_dict()])
    target_confirmed = bool(
        _confirmed_cex_flow_mask(row_frame, min_transfer_tokens=effective_min_transfer, target_only=True).iloc[0]
    )
    any_confirmed = bool(
        _confirmed_cex_flow_mask(row_frame, min_transfer_tokens=effective_min_transfer, target_only=False).iloc[0]
    )
    scored = _goal_score_frame(row_frame, min_transfer_tokens=effective_min_transfer)
    scored_row = scored.iloc[0] if not scored.empty else row
    thesis_line = _goal_thesis_gates_line(scored_row)
    if target_confirmed:
        verdict = "VERIFIED target-CEX transfer evidence"
    elif any_confirmed:
        verdict = "VERIFIED non-target CEX transfer; not Binance/Gate/Bitget"
    elif _clean_scalar_text(row.get("cex_deposit_flow_error", "")):
        verdict = "DATA GAP: transfer source blocked/error or no labelled destination match"
    else:
        verdict = "NO VERIFIED CEX transfer at this floor/lookback"
    top_tx = _clip_text(row.get("cex_deposit_24h_top_tx", ""), 90) or "n/a"
    source_url = _clip_text(row.get("cex_deposit_24h_source_url", ""), 240)
    whale_sender = _whale_sender_text(row, include_amount=True)
    lines = [
        f"{symbol} flow proof",
        f"Verdict: {verdict}",
        f"Source: {source} | Floor: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h",
        "Read: only rows with count > 0, largest transfer above floor, and a labelled destination are treated as confirmed.",
        "Transfer labels prove flow only; they do not prove the Binance+Bitget trading-venue gate.",
        thesis_line,
        "",
        f"Targets: {_clip_text(row.get('cex_deposit_24h_target_exchanges', ''), 80) or 'n/a'}",
        f"Transfers: {int(_safe_float(row.get('cex_deposit_24h_count')) or 0)}",
        f"Total token amount: {_fmt_compact_number(row.get('cex_deposit_24h_token_amount'))}",
        f"Largest transfer: {_fmt_compact_number(row.get('cex_deposit_24h_max_amount'))}",
        f"Total notional: {_fmt_compact_number(row.get('cex_deposit_24h_notional_usd'))}",
        f"Total supply pct: {(_safe_pct(row.get('cex_deposit_24h_total_pct_supply')) or 0.0):.2f}%",
        f"Largest supply pct: {(_safe_pct(row.get('cex_deposit_24h_max_pct_supply')) or 0.0):.2f}%",
        *( [f"Whale sender: {whale_sender}"] if whale_sender else [] ),
        f"Top tx/hash: {top_tx}",
        f"Flow source: {_clip_text(row.get('cex_deposit_flow_source', ''), 80) or 'n/a'}",
        f"Concentration gate: {_clip_text(row.get('cex_deposit_concentration_gate', ''), 120) or 'n/a'}",
    ]
    error = _clip_text(row.get("cex_deposit_flow_error", ""), 220)
    note = _clip_text(row.get("cex_deposit_flow_note", ""), 240)
    if error:
        lines.append(f"Data status: {error}")
    if note:
        lines.append(f"Note: {note}")
    if source_url:
        lines.append(f"Query/source URL: {source_url}")
    return f"{symbol} flow proof", "\n".join(lines)[:DISCORD_EMBED_DESCRIPTION_LIMIT]


def _load_coin_check(
    symbol_query: str,
    *,
    min_score: float = 60.0,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
    min_short_pct: float = 50.0,
    min_whale_pct: float = 90.0,
    require_holder_evidence: bool = True,
    require_binance_bitget: bool = True,
) -> tuple[str, str]:
    require_holder_evidence = True
    require_binance_bitget = True
    symbol = _normalize_symbol_query(symbol_query)
    if not symbol:
        return "Coin checklist", "Use `/coincheck symbol:PLAYUSDT min_tokens:20000`."
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    row = _row_for_symbol(frame, symbol)
    if row is None:
        return f"{symbol} checklist", f"No scan row found for {symbol}. Source: {source or 'unavailable'}"
    effective_min_whale_pct = _strict_thesis_min_whale_pct(min_whale_pct)
    scored = _goal_score_frame(
        pd.DataFrame([row.to_dict()]),
        min_transfer_tokens=effective_min_transfer,
        min_short_pct=min_short_pct,
        min_whale_pct=effective_min_whale_pct,
        require_holder_evidence=require_holder_evidence,
        require_binance_bitget=require_binance_bitget,
    )
    scored_row = scored.iloc[0]
    status = _goal_core_row_status(scored_row, min_score=min_score)
    score = _safe_float(scored_row.get("_goal_setup_score")) or 0.0

    def gate_line(label: str, passed: bool, detail: str) -> str:
        return f"{'PASS' if passed else 'FAIL'} {label}: {detail}"

    top10 = _safe_pct(scored_row.get("top10_holder_pct"))
    top100 = _safe_pct(scored_row.get("top100_holder_pct"))
    whale_pct = _safe_pct(scored_row.get("_goal_whale_pct"))
    holder_evidence = _holder_evidence_text(scored_row)
    short_pct = _safe_pct(scored_row.get("short_account_pct"))
    float_score = _safe_float(scored_row.get("_goal_float_component")) or 0.0
    structure = _safe_float(scored_row.get("_goal_structure_component")) or 0.0
    history_days = _safe_float(scored_row.get("history_days"))
    pump60 = _safe_float(scored_row.get("recent_max_pump_60d_pct"))
    pump_days = _safe_float(scored_row.get("recent_pump_60d_days"))
    history_text = f"{history_days:.0f}d" if history_days is not None else "n/a"
    pump_text = f"{pump60:.1f}%/{pump_days:.0f}d" if pump60 is not None and pump_days is not None else "n/a"
    lines = [
        f"{symbol} manipulation-structure checklist",
        f"Verdict: {status} | setup score {score:.0f}/100 | Source: {source}",
        f"Transfer floor: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h | Top10 whale floor: >= {effective_min_whale_pct:.1f}%",
        _goal_thesis_gates_line(scored_row),
        "Read: baseThesis/coreSetup can pass before CEX flow; targetFlow/whaleOrigin are trigger/risk evidence, not venue proof.",
        "",
        gate_line("target CEX flow", _boolish_scalar(scored_row.get("_goal_target_flow")), f"{_target_cex_text(scored_row) or 'no Binance/Gate/Bitget confirmed transfer'}; max {_fmt_compact_number(scored_row.get('cex_deposit_24h_max_amount'))}"),
        gate_line("Binance+Bitget trading venue", _boolish_scalar(scored_row.get("_goal_venue_pass")) or not require_binance_bitget, _venue_evidence_text(scored_row)),
        gate_line(
            "top10 whale dominance",
            _boolish_scalar(scored_row.get("_goal_whale_pass")),
            (
                f"top10 gate {whale_pct:.1f}% | top100 context {top100:.1f}% | holder {holder_evidence}"
                if whale_pct is not None and top10 is not None and top100 is not None
                else f"holder {holder_evidence}"
            ),
        ),
        gate_line("short dominance", _boolish_scalar(scored_row.get("_goal_short_pass")), f"short accounts {short_pct:.1f}%" if short_pct is not None else "short accounts n/a"),
        gate_line("low-float/high-FDV", _boolish_scalar(scored_row.get("_goal_float_pass")), f"float {float_score:.0f}/100 | FDV/MC {_fmt_compact_number(scored_row.get('fdv_to_market_cap'))}x | locked {_fmt_compact_number(scored_row.get('locked_supply_pct'))}%"),
        gate_line(
            "60D no-pump/dormancy",
            _boolish_scalar(scored_row.get("_goal_no_recent_pump_pass")),
            f"history {history_text} | pump60 {pump_text}",
        ),
        gate_line("dormant/not-late structure", _boolish_scalar(scored_row.get("_goal_structure_pass")), f"structure {structure:.0f}/100 | not-late {(_safe_float(scored_row.get('_goal_not_late_component')) or 0.0):.0f}/100"),
        "",
        _setup_score_line(scored_row, min_score=min_score),
    ]
    return f"{symbol} checklist", "\n".join(lines)[:DISCORD_EMBED_DESCRIPTION_LIMIT]


def _load_float_trap_list(limit: int, *, min_score: float = 60.0) -> tuple[str, list[str]]:
    frame, source = _fresh_scanner_frame(_env_value("DISCORD_FLOATTRAP_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep")
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty:
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    header = (
        "Low-float / high-FDV trap ranking\n"
        f"Source: {source} | Minimum score: {float(min_score):.0f} | "
        "Read: diagnostic float/FDV lens, not the hard-gated crime-pump queue."
    )
    if frame.empty:
        return "Low-float / high-FDV trap ranking", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]
    scored = apply_terminal_model(frame.loc[:, ~frame.columns.duplicated()].copy())
    if "symbol" not in scored.columns:
        return "Low-float / high-FDV trap ranking", [header + "\n\nThe active scan source has no symbol column."]
    top10 = _safe_pct_series(scored, "top10_holder_pct").fillna(0.0)
    top100 = _safe_pct_series(scored, "top100_holder_pct").fillna(0.0)
    fdv_score = _score_linear_series(_num_series(scored, "fdv_to_market_cap"), 1.8, 12.0)
    scored["_floattrap_fdv_ratio"] = _num_series(scored, "fdv_to_market_cap")
    scored["_floattrap_rank_score"] = pd.concat(
        [
            _num_series(scored, "low_float_score"),
            _num_series(scored, "float_trap_score"),
            _num_series(scored, "terminal_float_score"),
            _num_series(scored, "terminal_hidden_float_reflexivity_score"),
            _score_linear_series(top10, 55.0, 92.0),
            _score_linear_series(top100, 82.0, 99.5),
            fdv_score,
            _score_linear_series(_num_series(scored, "locked_supply_pct"), 15.0, 85.0),
        ],
        axis=1,
    ).max(axis=1)
    selected = scored[scored["_floattrap_rank_score"].ge(max(0.0, float(min_score)))].copy()
    if selected.empty:
        return "Low-float / high-FDV trap ranking", [header + "\n\nNo symbols met the float-trap threshold."]
    selected = selected.sort_values(["_floattrap_rank_score", "_floattrap_fdv_ratio", "symbol"], ascending=[False, False, True]).head(
        min(max(int(limit), 1), 100)
    )
    selected["_discord_base_thesis_gate"] = _thesis_candidate_gate_mask(selected)
    base_thesis_count = int(_boolish_series(selected.get("_discord_base_thesis_gate"), index=selected.index).sum())
    lines = [
        header,
        f"Diagnostic rows: {len(selected)} | Base thesis gate: {base_thesis_count}",
        "",
        "Diagnostic rows: " + " ".join(f"/{str(symbol).upper().strip()}" for symbol in selected["symbol"].tolist()),
        "",
    ]
    for _, row in selected.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        base_thesis = "Y" if _boolish_scalar(row.get("_discord_base_thesis_gate")) else "N"
        lines.append(
            f"/{symbol} | float {(_safe_float(row.get('_floattrap_rank_score')) or 0.0):.0f}/100 | "
            f"low-float {(_safe_float(row.get('low_float_score')) or 0.0):.0f} | trap {(_safe_float(row.get('float_trap_score')) or 0.0):.0f} | "
            f"FDV {_fmt_compact_number(row.get('fdv_usd'))} | MC {_fmt_compact_number(row.get('market_cap_usd'))} | "
            f"FDV/MC {_fmt_compact_number(row.get('fdv_to_market_cap'))}x | circ {_fmt_compact_number(row.get('circulating_supply_pct'))}% | "
            f"locked {_fmt_compact_number(row.get('locked_supply_pct'))}% | top100 {_fmt_compact_number(row.get('top100_holder_pct'))}% | "
            f"shorts {_fmt_compact_number(row.get('short_account_pct'))}% | baseThesis {base_thesis}"
        )
    return "Low-float / high-FDV trap ranking", _chunk_text_lines(lines)


def _funding_pressure_value(row: pd.Series) -> float | None:
    for column in ("predicted_funding_pct", "carry_funding_pct", "last_settled_funding_pct", "funding_rate", "funding_pct"):
        value = _safe_pct(row.get(column))
        if value is not None:
            return value
    return None


def _load_squeeze_ready_list(limit: int, *, min_short_pct: float = 50.0, min_score: float = 55.0) -> tuple[str, list[str]]:
    frame, source = _fresh_scanner_frame(_env_value("DISCORD_SQUEEZE_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep")
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty:
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    header = (
        "Squeeze-ready short-crowd ranking\n"
        f"Source: {source} | Short gate: >= {min_short_pct:.1f}% | Minimum score: {min_score:.0f} | "
        "Read: diagnostic short-squeeze lens, not the hard-gated crime-pump queue."
    )
    if frame.empty:
        return "Squeeze-ready short-crowd ranking", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]
    scored = _goal_score_frame(frame, min_short_pct=min_short_pct)
    short_pct = _safe_pct_series(scored, "short_account_pct").fillna(_num_series(scored, "short_account_pct"))
    oi_component = pd.concat(
        [
            _score_linear_series(_num_series(scored, "oi_delta_pct"), 0.5, 8.0),
            _score_linear_series(_num_series(scored, "oi_to_market_cap_pct"), 4.0, 30.0),
            _num_series(scored, "silent_oi_accumulation_score"),
        ],
        axis=1,
    ).max(axis=1)
    funding_pressure = scored.apply(lambda row: abs(min(_funding_pressure_value(row) or 0.0, 0.0)), axis=1).astype("float64")
    funding_component = _score_linear_series(funding_pressure, 0.002, 0.08)
    scored["_squeeze_ready_score"] = (
        _score_linear_series(short_pct, min_short_pct, 75.0) * 0.28
        + _num_series(scored, "terminal_short_pressure_score") * 0.20
        + oi_component * 0.18
        + funding_component * 0.08
        + _num_series(scored, "_goal_whale_component") * 0.12
        + _num_series(scored, "_goal_float_component") * 0.08
        + _num_series(scored, "_goal_structure_component") * 0.06
    ).clip(lower=0.0, upper=100.0)
    selected = scored[short_pct.ge(min_short_pct) & scored["_squeeze_ready_score"].ge(max(0.0, float(min_score)))].copy()
    if selected.empty:
        return "Squeeze-ready short-crowd ranking", [header + "\n\nNo symbols met the squeeze-ready filters."]
    selected = selected.sort_values(["_squeeze_ready_score", "short_account_pct", "symbol"], ascending=[False, False, True]).head(
        min(max(int(limit), 1), 100)
    )
    selected["_discord_base_thesis_gate"] = _thesis_candidate_gate_mask(selected)
    base_thesis_count = int(_boolish_series(selected.get("_discord_base_thesis_gate"), index=selected.index).sum())
    lines = [
        header,
        f"Diagnostic rows: {len(selected)} | Base thesis gate: {base_thesis_count}",
        "",
        "Diagnostic rows: " + " ".join(f"/{str(symbol).upper().strip()}" for symbol in selected["symbol"].tolist()),
        "",
    ]
    for _, row in selected.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        funding = _funding_pressure_value(row)
        target_flow = "target CEX flow" if bool(row.get("_goal_target_flow")) else "no target CEX flow"
        base_thesis = "Y" if _boolish_scalar(row.get("_discord_base_thesis_gate")) else "N"
        lines.append(
            f"/{symbol} | squeeze {(_safe_float(row.get('_squeeze_ready_score')) or 0.0):.0f}/100 | "
            f"shorts {(_safe_pct(row.get('short_account_pct')) or 0.0):.1f}% | OI {_fmt_compact_number(row.get('oi_delta_pct'))}% | "
            f"funding {_format_signed_pct(funding, decimals=4) if funding is not None else 'n/a'} | "
            f"whale {(_safe_float(row.get('_goal_whale_component')) or 0.0):.0f} | float {(_safe_float(row.get('_goal_float_component')) or 0.0):.0f} | "
            f"{target_flow} | baseThesis {base_thesis}"
        )
    return "Squeeze-ready short-crowd ranking", _chunk_text_lines(lines)


def _load_cex_targets_list(
    limit: int,
    *,
    min_tokens: float | None = None,
    lookback_hours: int | None = None,
) -> tuple[str, list[str]]:
    frame, source, effective_min_transfer, effective_lookback = _cex_scan_frame_for_commands(
        min_tokens=min_tokens,
        lookback_hours=lookback_hours,
    )
    header = (
        "Target CEX transfer board\n"
        f"Source: {source} | Target CEX: Binance, Gate.io, Bitget | Floor: {_fmt_compact_number(effective_min_transfer)} tokens | Lookback: {effective_lookback}h\n"
        "Read: raw confirmed transfer hits; baseThesis Y means strict holder+venue+60D no-pump gate also passed."
    )
    if frame.empty:
        return "Target CEX transfer board", [header + "\n\nNo live scan, scanner snapshot, or cache exists yet."]
    mask = _confirmed_cex_flow_mask(frame, min_transfer_tokens=effective_min_transfer, target_only=True)
    rows = frame[mask].copy()
    if rows.empty:
        return "Target CEX transfer board", [header + "\n\nNo confirmed Binance/Gate/Bitget transfer rows met the requested floor/lookback."]
    rows["_target_flow_score"] = pd.to_numeric(rows.get("cex_deposit_flow_score", pd.Series(0.0, index=rows.index)), errors="coerce").fillna(0.0)
    rows["_target_max_amount"] = pd.to_numeric(rows.get("cex_deposit_24h_max_amount", pd.Series(0.0, index=rows.index)), errors="coerce").fillna(0.0)
    rows["_discord_base_thesis_gate"] = _thesis_candidate_gate_mask(rows)
    rows["_discord_no_pump_proof"] = _no_recent_pump_proof_mask(rows)
    rows = rows.sort_values(["_target_flow_score", "_target_max_amount", "symbol"], ascending=[False, False, True]).head(
        min(max(int(limit), 1), 100)
    )
    base_thesis_count = int(_boolish_series(rows.get("_discord_base_thesis_gate"), index=rows.index).sum())
    exchange_counts: dict[str, int] = {"Binance": 0, "Bitget": 0, "Gate": 0}
    for target_text in rows.get("cex_deposit_24h_target_exchanges", pd.Series(dtype="object")).astype(str):
        lowered = target_text.lower()
        if "binance" in lowered:
            exchange_counts["Binance"] += 1
        if "bitget" in lowered:
            exchange_counts["Bitget"] += 1
        if "gate" in lowered:
            exchange_counts["Gate"] += 1
    counts = " | ".join(f"{exchange} {count}" for exchange, count in exchange_counts.items() if count)
    lines = [
        header,
        f"Transfer rows: {len(rows)} | Base thesis gate: {base_thesis_count}" + (f" | {counts}" if counts else ""),
        "",
        "Transfer rows: " + " ".join(f"/{str(symbol).upper().strip()}" for symbol in rows["symbol"].tolist()),
        "",
    ]
    for _, row in rows.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        whale_sender = _whale_sender_text(row)
        base_thesis = "Y" if _boolish_scalar(row.get("_discord_base_thesis_gate")) else "N"
        no_pump = "Y" if _boolish_scalar(row.get("_discord_no_pump_proof")) else "N"
        lines.append(
            f"/{symbol} | {_target_cex_text(row)} | flow {(_safe_float(row.get('cex_deposit_flow_score')) or 0.0):.0f}/100 | "
            f"{int(_safe_float(row.get('cex_deposit_24h_count')) or 0)} tx | total {_fmt_compact_number(row.get('cex_deposit_24h_token_amount'))} | "
            f"max {_fmt_compact_number(row.get('cex_deposit_24h_max_amount'))} | top tx {_clip_text(row.get('cex_deposit_24h_top_tx', ''), 48) or 'n/a'} | "
            f"baseThesis {base_thesis} | noPump60 {no_pump} | source {_clip_text(row.get('cex_deposit_flow_source', ''), 38) or 'n/a'}"
            f"{f' | {whale_sender}' if whale_sender else ''}"
        )
    return "Target CEX transfer board", _chunk_text_lines(lines)


def _load_alpha_brief(limit: int) -> tuple[str, list[str]]:
    scan_mode = _env_value("DISCORD_ALPHA_SCAN_MODE", _env_value("DISCORD_COMMAND_SCAN_MODE", "Deep")).strip() or "Deep"
    frame, source = _fresh_scanner_frame(scan_mode)
    if frame.empty and _source_is_unavailable(source):
        frame = _latest_snapshot_frame()
        source = "latest full scanner snapshot fallback"
    if frame.empty:
        frame = _read_csv_if_exists(_cache_path())
        source = "latest Convex cache fallback"
    if frame.empty:
        return "Alpha brief", [f"No live scan, scanner snapshot, or cache exists yet. `{source}`"]

    source_frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    source_frame = _apply_core_thesis_candidate_gate(source_frame)
    thesis_header = _thesis_candidate_header(core=True)
    if source_frame.empty:
        return "Alpha brief", [thesis_header + "\n\nNo rows met the strict core thesis gate."]

    def num(column: str) -> pd.Series:
        return pd.to_numeric(source_frame.get(column, pd.Series(0.0, index=source_frame.index)), errors="coerce").fillna(0.0)

    terminal = num("terminal_edge_score")
    timing = num("timing_score")
    cex_flow = pd.concat(
        [
            num("cex_deposit_flow_score"),
            num("terminal_exchange_flow_score"),
            num("target_cex_flow_score"),
        ],
        axis=1,
    ).max(axis=1)
    scanner = pd.concat(
        [
            num("trade_bucket_score"),
            num("convexity_entry_score"),
            num("convexity_score"),
        ],
        axis=1,
    ).max(axis=1)
    short_component = ((num("short_account_pct") - 50.0) * 4.0).clip(lower=0.0, upper=100.0)
    balanced = terminal * 0.36 + timing * 0.28 + cex_flow * 0.18 + scanner * 0.12 + short_component * 0.06
    flow_priority = cex_flow * 0.72 + terminal * 0.18 + timing * 0.10
    structure_priority = terminal * 0.58 + timing * 0.25 + scanner * 0.17
    source_frame["_discord_alpha_brief_score"] = pd.concat([balanced, flow_priority, structure_priority], axis=1).max(axis=1)

    min_score = _env_float("DISCORD_ALPHA_BRIEF_MIN_SCORE", 35.0, minimum=0.0)
    selected = source_frame[source_frame["_discord_alpha_brief_score"].ge(min_score)].copy()
    if selected.empty:
        return "Alpha brief", [thesis_header + f"\n\nNo rows reached the alpha brief minimum score of {min_score:.0f}."]

    selected = selected.sort_values(
        ["_discord_alpha_brief_score", "terminal_edge_score", "timing_score", "symbol"],
        ascending=[False, False, False, True],
    ).head(min(max(int(limit), 1), 50))

    header = (
        "Alpha brief - strict thesis-gated convex watchlist\n"
        f"{_cache_age_header(selected, source)}\n"
        f"{thesis_header}\n"
        "Ranking blends structural edge, timing quality, wallet-to-CEX flow, scanner score, and short-account fuel."
    )
    symbols = " ".join(f"/{str(symbol).upper().strip()}" for symbol in selected.get("symbol", pd.Series(dtype="object")).tolist())
    lines = [header, "", f"Candidates: {symbols}" if symbols else "Candidates: none", ""]
    for _, row in selected.iterrows():
        symbol = _clean_scalar_text(row.get("symbol", "")).upper().strip() or "UNKNOWN"
        brief_score = _safe_float(row.get("_discord_alpha_brief_score")) or 0.0
        terminal_score = _safe_float(row.get("terminal_edge_score")) or 0.0
        timing_score = _safe_float(row.get("timing_score")) or 0.0
        flow_values = [
            _safe_float(row.get("cex_deposit_flow_score")),
            _safe_float(row.get("terminal_exchange_flow_score")),
            _safe_float(row.get("target_cex_flow_score")),
        ]
        flow_score = max([value for value in flow_values if value is not None] or [0.0])
        short_pct = _safe_float(row.get("short_account_pct"))
        short_text = f"{short_pct:.1f}%" if short_pct is not None else "n/a"
        state = _first_nonempty_text(row.get("timing_state", ""), row.get("terminal_setup_archetype", "watchlist structure"))
        lines.append(
            f"{symbol} | brief {brief_score:.1f} | terminal {terminal_score:.0f} | timing {timing_score:.0f} | "
            f"CEX {flow_score:.0f} | shorts {short_text} | {state}"
        )
        lines.append(f"  evidence: {_clip_text(infer_evidence_stack(row), 170)}")
        lines.append(f"  next: {_clip_text(infer_next_check(row), 150)}")
    return "Alpha brief", _chunk_text_lines(lines)


def _trade_bot_client() -> BinanceFuturesPublic:
    return BinanceFuturesPublic(
        timeout=_env_int("TRADE_BOT_HTTP_TIMEOUT_SECONDS", 12, minimum=3),
        requests_per_second=_env_int("TRADE_BOT_REQUESTS_PER_SECOND", 3, minimum=1),
        api_key=os.environ.get("BINANCE_API_KEY", ""),
        api_secret=os.environ.get("BINANCE_API_SECRET", ""),
    )


def _trade_bot_text(message: str) -> str:
    return "```text\n" + str(message or "").strip()[:1850] + "\n```"


async def _safe_trade_bot_send(channel: Any, message: str) -> str:
    webhook_url = _env_value("TRADE_BOT_DISCORD_WEBHOOK_URL", _env_value("DISCORD_WEBHOOK_URL"))
    send_method = _env_value("TRADE_BOT_DISCORD_SEND_METHOD", "webhook_first").lower()
    errors: list[str] = []

    async def try_webhook() -> str:
        if not webhook_url:
            return "webhook not configured"
        try:
            response = await asyncio.to_thread(
                requests.post,
                webhook_url,
                json={"username": "Convex Trade Setup Bot", "content": _trade_bot_text(message)},
                timeout=15,
            )
            if response.status_code < 300:
                return ""
            return f"webhook HTTP {response.status_code}: {response.text[:180]}"
        except Exception as webhook_exc:
            return f"webhook {type(webhook_exc).__name__}: {webhook_exc}"

    async def try_channel() -> str:
        try:
            await channel.send(_trade_bot_text(message))
            return ""
        except Exception as exc:
            return f"channel {type(exc).__name__}: {exc}"

    if send_method in {"webhook", "webhook_first"}:
        error = await try_webhook()
        if not error:
            return ""
        errors.append(error)
        if send_method == "webhook":
            return "; ".join(errors)

    error = await try_channel()
    if not error:
        return ""
    errors.append(error)

    if send_method not in {"webhook", "webhook_first"}:
        error = await try_webhook()
        if not error:
            return ""
        errors.append(error)

    return "; ".join(errors)


async def _trade_bot_loop(channel: Any, config: TradeBotConfig) -> None:
    global _TRADE_BOT_RUNTIME, _TRADE_BOT_STOP_REQUESTED
    runtime = TradeBotRuntime(config)
    _TRADE_BOT_RUNTIME = runtime
    client = _trade_bot_client()
    stopped_cleanly = False
    try:
        startup_message = (
            "Trade setup bot started.\n"
            f"Mode: {config.mode}\n"
            f"Scan mode: {config.scan_mode}\n"
            f"Interval: {config.interval_seconds}s\n"
            "Live orders require TRADE_BOT_LIVE_ENABLED=1. Paper mode is the default."
        )
        runtime.last_message = startup_message
        send_error = await _safe_trade_bot_send(channel, startup_message)
        if send_error:
            runtime.last_message = f"Started, but Discord channel send failed: {send_error}"
        while not _TRADE_BOT_STOP_REQUESTED:
            try:
                frame, source = await asyncio.to_thread(_fresh_scanner_frame, config.scan_mode)
                if frame.empty:
                    message = f"No fresh scan frame available: {source}"
                else:
                    frame = apply_timing_model(apply_terminal_model(frame))
                    message = await asyncio.to_thread(runtime.run_cycle, frame, client)
                should_notify = True
                if message.startswith("No setup") and not _env_bool("TRADE_BOT_NOTIFY_NO_SETUP", False):
                    should_notify = False
                if " open; mark " in message and not _env_bool("TRADE_BOT_NOTIFY_MONITOR", False):
                    should_notify = False
                if should_notify:
                    send_error = await _safe_trade_bot_send(channel, message)
                    if send_error:
                        runtime.last_message = f"{message} | Discord send failed: {send_error}"
            except asyncio.CancelledError:
                stopped_cleanly = True
                break
            except Exception as exc:
                message = f"Trade setup bot cycle error: {exc}"
                if runtime:
                    runtime.last_message = message
                send_error = await _safe_trade_bot_send(channel, message)
                if send_error:
                    runtime.last_message = f"{message} | Discord send failed: {send_error}"
            try:
                await asyncio.sleep(max(15, int(config.interval_seconds)))
            except asyncio.CancelledError:
                stopped_cleanly = True
                break
    except Exception as exc:
        runtime.last_message = f"Trade setup bot fatal error: {type(exc).__name__}: {exc}"
    finally:
        if runtime and (_TRADE_BOT_STOP_REQUESTED or stopped_cleanly):
            runtime.last_message = "stop requested"
        if _TRADE_BOT_STOP_REQUESTED or stopped_cleanly:
            await _safe_trade_bot_send(channel, "Trade setup bot stopped.")


def _load_shorts_list() -> tuple[str, list[str]]:
    live_frame, live_error = _load_live_shorts_frame()
    if not live_frame.empty:
        return _format_shorts_frame(live_frame, source="live Binance account-ratio scan")
    if live_error:
        cache_title, cache_chunks = _load_cached_shorts_list(f"Live scan unavailable: {live_error}")
        return cache_title, cache_chunks
    return _load_cached_shorts_list("")


def _load_live_shorts_frame() -> tuple[pd.DataFrame, str]:
    cache_path = _shorts_cache_path()
    ttl_seconds = _env_int("DISCORD_SHORTS_CACHE_TTL_SECONDS", 120, minimum=0)
    if ttl_seconds > 0 and cache_path.exists() and time.time() - cache_path.stat().st_mtime <= ttl_seconds:
        try:
            cached = pd.read_csv(cache_path)
            if not cached.empty:
                return cached, ""
        except Exception:
            pass

    try:
        client = BinanceFuturesPublic(
            timeout=_env_int("DISCORD_SHORTS_BINANCE_TIMEOUT_SECONDS", 10, minimum=3),
            requests_per_second=float(_env_value("DISCORD_SHORTS_REQUESTS_PER_SECOND", "8")),
            retries=_env_int("DISCORD_SHORTS_BINANCE_RETRIES", 2, minimum=1),
        )
        symbols = [item.symbol for item in client.perpetual_usdt_symbols() if item.symbol]
    except Exception as exc:
        return pd.DataFrame(), str(exc)

    max_symbols = _env_int("DISCORD_SHORTS_MAX_SYMBOLS", 0, minimum=0)
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    period = _env_value("DISCORD_SHORTS_RATIO_PERIOD", "5m")
    rows: list[dict[str, Any]] = []
    errors = 0
    for symbol in symbols:
        try:
            ratio_rows = client.global_long_short_account_ratio(symbol, period=period, limit=1)
        except Exception:
            errors += 1
            continue
        if not ratio_rows:
            continue
        latest = ratio_rows[-1]
        long_pct = _safe_float(latest.get("longAccount"))
        short_pct = _safe_float(latest.get("shortAccount"))
        ratio = _safe_float(latest.get("longShortRatio"))
        if long_pct is not None and abs(long_pct) <= 1.0:
            long_pct *= 100.0
        if short_pct is not None and abs(short_pct) <= 1.0:
            short_pct *= 100.0
        if short_pct is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "short_account_pct": short_pct,
                "long_account_pct": long_pct,
                "long_short_account_ratio": ratio,
                "scan_mode": f"live {period}",
                "scanned_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, f"no live account-ratio rows returned ({errors} symbol errors)"
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(cache_path, index=False)
    except Exception:
        pass
    return frame, ""


def _load_cached_shorts_list(prefix: str = "") -> tuple[str, list[str]]:
    path = _cache_path()
    if not path.exists():
        message = f"No scanner cache yet: `{path}`"
        return "Short-account majority list", [f"{prefix}\n{message}".strip()]
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return "Short-account majority list", [f"{prefix}\nCould not read scanner cache: `{exc}`".strip()]
    if frame.empty or "short_account_pct" not in frame.columns:
        return "Short-account majority list", [f"{prefix}\nNo short-account percentage data exists in the latest cache.".strip()]
    return _format_shorts_frame(frame, source="latest scanner cache", prefix=prefix)


def _format_shorts_frame(frame: pd.DataFrame, *, source: str, prefix: str = "") -> tuple[str, list[str]]:
    frame = frame.copy()
    frame["short_account_pct"] = pd.to_numeric(frame["short_account_pct"], errors="coerce")
    matches = frame[frame["short_account_pct"].gt(50.0)].copy()
    if matches.empty:
        return "Short-account majority list", [f"{prefix}\nNo tokens have more than 50% of accounts short in {source}.".strip()]
    matches["symbol"] = matches["symbol"].astype(str).str.upper().str.strip()
    matches = matches[matches["symbol"].ne("")].drop_duplicates(subset=["symbol"], keep="first")
    matches = matches.sort_values(["short_account_pct", "symbol"], ascending=[False, True])
    scanned_at = str(frame.get("scanned_at_utc", pd.Series(["unknown"])).iloc[0])
    scan_mode = str(frame.get("scan_mode", pd.Series(["unknown"])).iloc[0])
    include_pct = _env_bool("DISCORD_SHORTS_INCLUDE_PCT", True)
    symbols = [
        f"{row.symbol} {float(row.short_account_pct):.1f}%" if include_pct else str(row.symbol)
        for row in matches[["symbol", "short_account_pct"]].itertuples(index=False)
    ]
    header = (
        f"Short-account majority tokens ({len(symbols)})\n"
        f"Threshold: >50% accounts short | Source: {source} | Scan: {scan_mode} | Updated: {scanned_at}\n\n"
    )
    if prefix:
        header = f"{prefix}\n\n{header}"
    chunks: list[str] = []
    current = header
    for symbol in symbols:
        addition = f"{symbol}\n"
        if len(current) + len(addition) > 1850:
            chunks.append(current.rstrip())
            current = addition
        else:
            current += addition
    if current.strip():
        chunks.append(current.rstrip())
    return "Short-account majority list", chunks


def _cache_status() -> str:
    path = _cache_path()
    if not path.exists():
        return f"No cache file yet: `{path}`"
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return f"Cache exists but could not be read: `{exc}`"
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    archive = proof_archive_path()
    archive_rows = len(pd.read_csv(archive)) if archive.exists() else 0
    return f"Cache: `{path}`\nRows: `{len(frame)}`\nModified: `{modified}`\nProof archive rows: `{archive_rows}`"


def _scoreboard_text() -> str:
    if _env_bool("DISCORD_SCOREBOARD_REFRESH_OUTCOMES", True):
        refresh_outcomes(max_rows=_env_int("DISCORD_SCOREBOARD_REFRESH_MAX_ROWS", 20, minimum=1))
    if _env_bool("DISCORD_WEEKLY_REPORT_WRITE_ENABLED", True):
        write_weekly_report()
    return weekly_scoreboard_text()


def main(*, force_disable_symbol_shortcuts: bool = False) -> None:
    _load_local_env()
    try:
        import discord
        from discord import app_commands
    except ImportError:
        print("discord.py is not installed. Run: python -m pip install discord.py")
        raise SystemExit(1)

    token = _env_value("DISCORD_BOT_TOKEN")
    if not token:
        print("Set DISCORD_BOT_TOKEN in .env before starting the bot.")
        raise SystemExit(1)

    guild_id_raw = _env_value("DISCORD_GUILD_ID")
    allowed_channel_raw = _env_value("DISCORD_ALLOWED_CHANNEL_ID")
    default_top_n = max(1, int(_env_value("DISCORD_CONVEX_COMMAND_TOP_N", "10")))
    default_cexflow_top_n = _env_int("DISCORD_CEX_FLOW_TOP_N", 25, minimum=1)
    default_alpha_top_n = _env_int("DISCORD_ALPHA_TOP_N", 15, minimum=1)
    default_funding_top_n = _env_int("DISCORD_FUNDING_TOP_N", 10, minimum=1)
    announce_online = _env_value("DISCORD_ANNOUNCE_ONLINE", "0").strip().lower() in {"1", "true", "yes", "on"}
    message_content_intent_enabled = _env_bool("DISCORD_MESSAGE_CONTENT_INTENT_ENABLED", False)
    symbol_shortcuts_enabled = _env_bool("DISCORD_SYMBOL_SHORTCUTS_ENABLED", False) and message_content_intent_enabled
    if force_disable_symbol_shortcuts:
        symbol_shortcuts_enabled = False
    symbol_slash_aliases = _configured_symbol_slash_aliases()
    guild = discord.Object(id=int(guild_id_raw)) if guild_id_raw.strip().isdigit() else None
    allowed_channel_id = int(allowed_channel_raw) if allowed_channel_raw.strip().isdigit() else None

    intents = discord.Intents.default()
    if symbol_shortcuts_enabled:
        intents.message_content = True
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    def _channel_allowed(interaction: discord.Interaction) -> bool:
        return allowed_channel_id is None or interaction.channel_id == allowed_channel_id

    command_kwargs = {"name": "convex", "description": "Show the latest market-structure scanner sample."}
    if guild is not None:
        command_kwargs["guild"] = guild

    @tree.command(**command_kwargs)
    async def convex(interaction: discord.Interaction, limit: int = default_top_n) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        tier = _interaction_tier(interaction)
        if not _tier_allows(tier, _feature_required_tier("convex")):
            await interaction.response.send_message(_access_denied_message("convex"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        capped_limit = min(max(int(limit), 1), 25)
        if tier == "free":
            capped_limit = min(capped_limit, _free_sample_limit())
        title, description = await asyncio.to_thread(_load_candidates, capped_limit)
        embed = discord.Embed(title=title, description=description, color=0x22C55E)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    commands_kwargs = {"name": "commands", "description": "Show the recommended Discord operator command map."}
    if guild is not None:
        commands_kwargs["guild"] = guild

    @tree.command(**commands_kwargs)
    async def commands(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("commands")):
            await interaction.response.send_message(_access_denied_message("commands"), ephemeral=True)
            return
        await _send_command_guide(interaction)

    async def _send_command_guide(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(_load_command_guide)
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0x38BDF8)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    help_kwargs = {"name": "help", "description": "Show the recommended Discord operator command map."}
    if guild is not None:
        help_kwargs["guild"] = guild

    @tree.command(**help_kwargs)
    async def help(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("help")):
            await interaction.response.send_message(_access_denied_message("help"), ephemeral=True)
            return
        await _send_command_guide(interaction)

    shorts_kwargs = {"name": "shorts", "description": "List every cached token with more than 50% of accounts short."}
    if guild is not None:
        shorts_kwargs["guild"] = guild

    @tree.command(**shorts_kwargs)
    async def shorts(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("shorts")):
            await interaction.response.send_message(_access_denied_message("shorts"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(_load_shorts_list)
        if not chunks:
            chunks = ["No short-account majority tokens found."]
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF59E0B)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    high_kwargs = {"name": "high", "description": "Show symbols that broke above a prior-day high."}
    if guild is not None:
        high_kwargs["guild"] = guild

    @tree.command(**high_kwargs)
    @app_commands.describe(
        days=f"Breakout window, for example 7D, 20D, or 365D. Supports 1D-{MAX_DYNAMIC_BREAKOUT_DAYS}D.",
        limit="Maximum rows to return. Use 0 for all matching rows.",
        thesis_only="Only show rows passing top10 holder evidence, Binance+Bitget, 60D no-pump, float, short, and not-late gates.",
    )
    async def high(interaction: discord.Interaction, days: str = "20D", limit: int = 0, thesis_only: bool = False) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("high")):
            await interaction.response.send_message(_access_denied_message("high"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_breakout_list,
            "high",
            days=days,
            limit=min(max(int(limit), 0), 300),
            thesis_only=thesis_only,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0x22C55E)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    low_kwargs = {"name": "low", "description": "Show symbols that broke below a prior-day low."}
    if guild is not None:
        low_kwargs["guild"] = guild

    @tree.command(**low_kwargs)
    @app_commands.describe(
        days=f"Breakout window, for example 7D, 20D, or 365D. Supports 1D-{MAX_DYNAMIC_BREAKOUT_DAYS}D.",
        limit="Maximum rows to return. Use 0 for all matching rows.",
        thesis_only="Only show rows passing top10 holder evidence, Binance+Bitget, 60D no-pump, float, short, and not-late gates.",
    )
    async def low(interaction: discord.Interaction, days: str = "20D", limit: int = 0, thesis_only: bool = False) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("low")):
            await interaction.response.send_message(_access_denied_message("low"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_breakout_list,
            "low",
            days=days,
            limit=min(max(int(limit), 0), 300),
            thesis_only=thesis_only,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xEF4444)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    funding_kwargs = {"name": "funding", "description": "Rank Binance USDT perps by funding carry for longs and shorts."}
    if guild is not None:
        funding_kwargs["guild"] = guild

    @tree.command(**funding_kwargs)
    @app_commands.describe(
        side="Which carry side to show: both, shorts, or longs.",
        limit="Rows per side to return.",
        period="Binance global long/short account-ratio period, for example 5m, 15m, 1h, or 4h.",
        min_abs_funding_pct="Minimum absolute funding percent, for example 0.01 for 0.01%.",
    )
    @app_commands.choices(
        side=[
            app_commands.Choice(name="both", value="both"),
            app_commands.Choice(name="shorts receive positive funding", value="shorts"),
            app_commands.Choice(name="longs receive negative funding", value="longs"),
        ]
    )
    async def funding(
        interaction: discord.Interaction,
        side: str = "both",
        limit: int = default_funding_top_n,
        period: str = "1h",
        min_abs_funding_pct: float = 0.0,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("funding")):
            await interaction.response.send_message(_access_denied_message("funding"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_funding_leaderboard,
            min(max(int(limit), 1), 30),
            side=side,
            period=period,
            min_abs_funding_pct=min_abs_funding_pct,
        )
        if not chunks:
            chunks = ["No funding rows found."]
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0x14B8A6)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    setupscore_kwargs = {"name": "setupscore", "description": "Rank the full low-float whale/CEX-flow short-squeeze thesis."}
    if guild is not None:
        setupscore_kwargs["guild"] = guild

    @tree.command(**setupscore_kwargs)
    @app_commands.describe(
        min_score="Minimum setup score to show.",
        min_tokens="Minimum token amount per confirmed transfer.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        min_short_pct="Minimum short-account percentage.",
        min_whale_pct="Top10 holder concentration floor. Values below 90 are treated as 90.",
    )
    async def setupscore(
        interaction: discord.Interaction,
        min_score: float = 60.0,
        min_tokens: float = 20_000.0,
        limit: int = 20,
        lookback_hours: int = 24,
        min_short_pct: float = 50.0,
        min_whale_pct: float = 90.0,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("setupscore")):
            await interaction.response.send_message(_access_denied_message("setupscore"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_setup_score_list,
            min(max(int(limit), 1), 100),
            min_score=max(0.0, min(float(min_score), 100.0)),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            min_short_pct=max(0.0, min(float(min_short_pct), 100.0)),
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0x22C55E)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    pumpwatch_kwargs = {"name": "pumpwatch", "description": "Rank early pump candidates across target flow, whales, shorts, float, and timing."}
    if guild is not None:
        pumpwatch_kwargs["guild"] = guild

    @tree.command(**pumpwatch_kwargs)
    @app_commands.describe(
        min_score="Minimum pump radar score to show.",
        min_tokens="Minimum token amount per confirmed transfer.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        min_whale_pct="Top10 holder concentration floor. Values below 90 are treated as 90.",
        require_target_flow="Only show rows with confirmed Binance/Gate/Bitget transfer evidence.",
        require_dormant_60d="Require 60D no-pump/dormancy proof before showing score-only rows.",
    )
    async def pumpwatch(
        interaction: discord.Interaction,
        min_score: float = 55.0,
        min_tokens: float = 20_000.0,
        limit: int = 20,
        lookback_hours: int = 24,
        min_whale_pct: float = 90.0,
        require_target_flow: bool = False,
        require_dormant_60d: bool = True,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("pumpwatch")):
            await interaction.response.send_message(_access_denied_message("pumpwatch"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_pump_watch_list,
            min(max(int(limit), 1), 100),
            min_score=max(0.0, min(float(min_score), 100.0)),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
            require_target_flow=require_target_flow,
            require_dormant_60d=require_dormant_60d,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xEF4444)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    precrime_kwargs = {"name": "precrime", "description": "Rank quiet latent setups before price/volume activity appears."}
    if guild is not None:
        precrime_kwargs["guild"] = guild

    @tree.command(**precrime_kwargs)
    @app_commands.describe(
        min_score="Minimum pre-activity score to show.",
        min_tokens="Minimum token amount per confirmed transfer.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        min_whale_pct="Top10 holder concentration floor. Values below 90 are treated as 90.",
        require_target_flow="Only show rows with confirmed Binance/Gate/Bitget transfer evidence.",
        require_quiet="Require the no-chase quiet/low-activity gate.",
        require_behavior_gate="Require target CEX flow, venue-inventory tell, or short-fuse venue behaviour.",
        require_dormant_60d="Require 60D no-pump/dormancy proof before showing score-only rows.",
    )
    async def precrime(
        interaction: discord.Interaction,
        min_score: float = 58.0,
        min_tokens: float = 20_000.0,
        limit: int = 20,
        lookback_hours: int = 24,
        min_whale_pct: float = 90.0,
        require_target_flow: bool = False,
        require_quiet: bool = True,
        require_behavior_gate: bool = True,
        require_dormant_60d: bool = True,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("precrime")):
            await interaction.response.send_message(_access_denied_message("precrime"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_precrime_list,
            min(max(int(limit), 1), 100),
            min_score=max(0.0, min(float(min_score), 100.0)),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
            require_target_flow=require_target_flow,
            require_quiet=require_quiet,
            require_behavior_gate=require_behavior_gate,
            require_dormant_60d=require_dormant_60d,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0x8B5CF6)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    ravelab_kwargs = {"name": "ravelab", "description": "Strict early screen for whale-controlled Binance+Bitget squeeze structures."}
    if guild is not None:
        ravelab_kwargs["guild"] = guild

    @tree.command(**ravelab_kwargs)
    @app_commands.describe(
        min_score="Optional minimum early-structure score. Default 0 lets hard gates lead.",
        min_archetype="Optional minimum RAVE or LAB historical-analogue score. Default 0 does not force analogy.",
        min_whale_pct="Required top10 holder concentration floor. Values below 90 are treated as 90.",
        min_squeeze_score="Required short-squeeze/perp-fuel score. Default 50.",
        min_history_days="Required history coverage for the dormancy/no-pump gate. Default 60.",
        max_recent_pump_pct="Reject rows with a daily high expansion above this in the last 60d. Default 35.",
        min_tokens="Minimum token amount per confirmed transfer.",
        whale_flow_min_tokens="Minimum top-holder-origin CEX transfer amount for the A3 whale-CEX lane.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        breakout_windows="Comma-separated high-breakout windows to check after hard gates, e.g. 1D,2D,3D,4D.",
        style="Show both, RAVE-like, or LAB-like structures.",
        require_quiet="Require early/no-chase heat gate.",
        require_target_flow="Only show rows with confirmed Binance/Gate/Bitget transfer evidence.",
        require_breakout_high="Only show rows that broke at least one requested high-breakout window.",
        require_whale_origin_flow="Only show rows where a confirmed target-CEX transfer came from a scanned top-holder wallet and clears whale_flow_min_tokens.",
        trigger_filter="Filter strict rows to all, triggered, whale-CEX flow, target-CEX flow, breakout, or core-watch only.",
        near_miss_limit="Blocked high-signal rows to show after strict matches. Use 0 to hide.",
        detail="Show full multi-line evidence instead of the compact staged read.",
    )
    @app_commands.choices(
        style=[
            app_commands.Choice(name="both", value="both"),
            app_commands.Choice(name="RAVE-like", value="rave"),
            app_commands.Choice(name="LAB-like", value="lab"),
        ],
        trigger_filter=[
            app_commands.Choice(name="all hard-gated rows", value="all"),
            app_commands.Choice(name="triggered only", value="triggered"),
            app_commands.Choice(name="whale-CEX flow", value="flow"),
            app_commands.Choice(name="target-CEX flow", value="target_flow"),
            app_commands.Choice(name="breakout highs", value="breakout"),
            app_commands.Choice(name="core watch only", value="core"),
        ]
    )
    async def ravelab(
        interaction: discord.Interaction,
        min_score: float = 0.0,
        min_archetype: float = 0.0,
        min_whale_pct: float = 90.0,
        min_squeeze_score: float = 50.0,
        min_history_days: int = 60,
        max_recent_pump_pct: float = 35.0,
        min_tokens: float = 20_000.0,
        whale_flow_min_tokens: float = 0.0,
        limit: int = 20,
        lookback_hours: int = 24,
        breakout_windows: str = "1D,2D,3D,4D,5D,20D",
        style: str = "both",
        require_quiet: bool = True,
        require_target_flow: bool = False,
        require_breakout_high: bool = False,
        require_whale_origin_flow: bool = False,
        trigger_filter: str = "all",
        near_miss_limit: int = 5,
        detail: bool = False,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("ravelab")):
            await interaction.response.send_message(_access_denied_message("ravelab"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_ravelab_list,
            min(max(int(limit), 1), 100),
            min_score=max(0.0, min(float(min_score), 100.0)),
            min_archetype=max(0.0, min(float(min_archetype), 100.0)),
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
            min_squeeze_score=max(0.0, min(float(min_squeeze_score), 100.0)),
            min_history_days=max(1, int(min_history_days)),
            max_recent_pump_pct=max(0.0, float(max_recent_pump_pct)),
            min_tokens=min_tokens if min_tokens > 0 else None,
            whale_flow_min_tokens=whale_flow_min_tokens if whale_flow_min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            breakout_windows=breakout_windows,
            style=style,
            require_quiet=require_quiet,
            require_target_flow=require_target_flow,
            require_breakout_high=require_breakout_high,
            require_whale_origin_flow=require_whale_origin_flow,
            trigger_filter=trigger_filter,
            near_miss_limit=min(max(int(near_miss_limit), 0), 30),
            detail=detail,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    radar_kwargs = {"name": "radar", "description": "Primary hard-gated early structure radar."}
    if guild is not None:
        radar_kwargs["guild"] = guild

    @tree.command(**radar_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per confirmed transfer.",
        whale_flow_min_tokens="Minimum top-holder-origin CEX transfer amount for the whale-CEX trigger lane.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        trigger="Filter to all, triggered, whale-CEX flow, target-CEX flow, breakout, or core-watch rows.",
        breakout_windows="Comma-separated high-breakout windows to check after hard gates, e.g. 1D,2D,3D,4D.",
    )
    @app_commands.choices(
        trigger=[
            app_commands.Choice(name="all hard-gated rows", value="all"),
            app_commands.Choice(name="triggered only", value="triggered"),
            app_commands.Choice(name="whale-CEX flow", value="flow"),
            app_commands.Choice(name="target-CEX flow", value="target_flow"),
            app_commands.Choice(name="breakout highs", value="breakout"),
            app_commands.Choice(name="core watch only", value="core"),
        ]
    )
    async def radar(
        interaction: discord.Interaction,
        min_tokens: float = 20_000.0,
        whale_flow_min_tokens: float = 0.0,
        limit: int = 12,
        lookback_hours: int = 24,
        trigger: str = "all",
        breakout_windows: str = "1D,2D,3D,4D,5D,20D",
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("radar")):
            await interaction.response.send_message(_access_denied_message("radar"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_radar_list,
            min(max(int(limit), 1), 50),
            min_tokens=min_tokens if min_tokens > 0 else None,
            whale_flow_min_tokens=whale_flow_min_tokens if whale_flow_min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            trigger=trigger,
            breakout_windows=breakout_windows,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    crimepump_kwargs = {"name": "crimepump", "description": "Legacy alias for the hard-gated early structure radar."}
    if guild is not None:
        crimepump_kwargs["guild"] = guild

    @tree.command(**crimepump_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per confirmed transfer.",
        whale_flow_min_tokens="Minimum top-holder-origin CEX transfer amount for the whale-CEX trigger lane.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        trigger="Filter to all, triggered, whale-CEX flow, target-CEX flow, breakout, or core-watch rows.",
        breakout_windows="Comma-separated high-breakout windows to check after hard gates, e.g. 1D,2D,3D,4D.",
    )
    @app_commands.choices(
        trigger=[
            app_commands.Choice(name="all hard-gated rows", value="all"),
            app_commands.Choice(name="triggered only", value="triggered"),
            app_commands.Choice(name="whale-CEX flow", value="flow"),
            app_commands.Choice(name="target-CEX flow", value="target_flow"),
            app_commands.Choice(name="breakout highs", value="breakout"),
            app_commands.Choice(name="core watch only", value="core"),
        ]
    )
    async def crimepump(
        interaction: discord.Interaction,
        min_tokens: float = 20_000.0,
        whale_flow_min_tokens: float = 0.0,
        limit: int = 12,
        lookback_hours: int = 24,
        trigger: str = "all",
        breakout_windows: str = "1D,2D,3D,4D,5D,20D",
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("crimepump")):
            await interaction.response.send_message(_access_denied_message("crimepump"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_crimepump_list,
            min(max(int(limit), 1), 50),
            min_tokens=min_tokens if min_tokens > 0 else None,
            whale_flow_min_tokens=whale_flow_min_tokens if whale_flow_min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            trigger=trigger,
            breakout_windows=breakout_windows,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    prime_kwargs = {"name": "prime", "description": "Clean strict queue for hard-gated early crime-pump structures."}
    if guild is not None:
        prime_kwargs["guild"] = guild

    @tree.command(**prime_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per confirmed transfer.",
        whale_flow_min_tokens="Minimum top-holder-origin CEX transfer amount for the whale-CEX trigger lane.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        trigger="Filter to all, triggered, whale-CEX flow, target-CEX flow, breakout, or core-watch rows.",
        breakout_windows="Comma-separated high-breakout windows to check after hard gates, e.g. 1D,2D,3D,4D.",
    )
    @app_commands.choices(
        trigger=[
            app_commands.Choice(name="all hard-gated rows", value="all"),
            app_commands.Choice(name="triggered only", value="triggered"),
            app_commands.Choice(name="whale-CEX flow", value="flow"),
            app_commands.Choice(name="target-CEX flow", value="target_flow"),
            app_commands.Choice(name="breakout highs", value="breakout"),
            app_commands.Choice(name="core watch only", value="core"),
        ]
    )
    async def prime(
        interaction: discord.Interaction,
        min_tokens: float = 20_000.0,
        whale_flow_min_tokens: float = 0.0,
        limit: int = 12,
        lookback_hours: int = 24,
        trigger: str = "all",
        breakout_windows: str = "1D,2D,3D,4D,5D,20D",
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("prime")):
            await interaction.response.send_message(_access_denied_message("prime"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_prime_list,
            min(max(int(limit), 1), 50),
            min_tokens=min_tokens if min_tokens > 0 else None,
            whale_flow_min_tokens=whale_flow_min_tokens if whale_flow_min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            trigger=trigger,
            breakout_windows=breakout_windows,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    flowproof_kwargs = {"name": "flowproof", "description": "Show transfer proof and data status for one symbol."}
    if guild is not None:
        flowproof_kwargs["guild"] = guild

    @tree.command(**flowproof_kwargs)
    @app_commands.describe(
        symbol="Symbol to inspect, for example PLAYUSDT or PLAY.",
        min_tokens="Minimum token amount per confirmed transfer.",
        lookback_hours="Transfer lookback window in hours.",
    )
    async def flowproof(
        interaction: discord.Interaction,
        symbol: str,
        min_tokens: float = 20_000.0,
        lookback_hours: int = 24,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("flowproof")):
            await interaction.response.send_message(_access_denied_message("flowproof"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(
            _load_flow_proof,
            symbol,
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
        )
        embed = discord.Embed(title=title, description=f"```text\n{description}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    coincheck_kwargs = {"name": "coincheck", "description": "Run one symbol through the full manipulation-structure checklist."}
    if guild is not None:
        coincheck_kwargs["guild"] = guild

    @tree.command(**coincheck_kwargs)
    @app_commands.describe(
        symbol="Symbol to inspect, for example PLAYUSDT or PLAY.",
        min_score="Minimum setup score for a PASS verdict.",
        min_tokens="Minimum token amount per confirmed transfer.",
        lookback_hours="Transfer lookback window in hours.",
        min_short_pct="Minimum short-account percentage.",
        min_whale_pct="Top10 holder concentration floor. Values below 90 are treated as 90.",
    )
    async def coincheck(
        interaction: discord.Interaction,
        symbol: str,
        min_score: float = 60.0,
        min_tokens: float = 20_000.0,
        lookback_hours: int = 24,
        min_short_pct: float = 50.0,
        min_whale_pct: float = 90.0,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("coincheck")):
            await interaction.response.send_message(_access_denied_message("coincheck"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(
            _load_coin_check,
            symbol,
            min_score=max(0.0, min(float(min_score), 100.0)),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            min_short_pct=max(0.0, min(float(min_short_pct), 100.0)),
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
        )
        embed = discord.Embed(title=title, description=f"```text\n{description}\n```", color=0x22C55E)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    floattrap_kwargs = {"name": "floattrap", "description": "Diagnostic low-float/high-FDV context board."}
    if guild is not None:
        floattrap_kwargs["guild"] = guild

    @tree.command(**floattrap_kwargs)
    @app_commands.describe(
        min_score="Minimum float-trap score to show.",
        limit="Maximum rows to return.",
    )
    async def floattrap(interaction: discord.Interaction, min_score: float = 60.0, limit: int = 25) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("floattrap")):
            await interaction.response.send_message(_access_denied_message("floattrap"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_float_trap_list,
            min(max(int(limit), 1), 100),
            min_score=max(0.0, min(float(min_score), 100.0)),
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xA855F7)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    squeezeready_kwargs = {"name": "squeezeready", "description": "Diagnostic short-crowd squeeze-fuel context board."}
    if guild is not None:
        squeezeready_kwargs["guild"] = guild

    @tree.command(**squeezeready_kwargs)
    @app_commands.describe(
        min_short_pct="Minimum short-account percentage.",
        min_score="Minimum squeeze-ready score to show.",
        limit="Maximum rows to return.",
    )
    async def squeezeready(interaction: discord.Interaction, min_short_pct: float = 50.0, min_score: float = 55.0, limit: int = 25) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("squeezeready")):
            await interaction.response.send_message(_access_denied_message("squeezeready"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_squeeze_ready_list,
            min(max(int(limit), 1), 100),
            min_short_pct=max(0.0, min(float(min_short_pct), 100.0)),
            min_score=max(0.0, min(float(min_score), 100.0)),
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF59E0B)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    cextargets_kwargs = {"name": "cextargets", "description": "Diagnostic confirmed transfers into Binance, Gate.io, or Bitget."}
    if guild is not None:
        cextargets_kwargs["guild"] = guild

    @tree.command(**cextargets_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per confirmed transfer.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
    )
    async def cextargets(
        interaction: discord.Interaction,
        min_tokens: float = 20_000.0,
        limit: int = 25,
        lookback_hours: int = 24,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("cextargets")):
            await interaction.response.send_message(_access_denied_message("cextargets"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_cex_targets_list,
            min(max(int(limit), 1), 100),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    whales_kwargs = {"name": "whales", "description": "Rank symbols by top-holder whale dominance."}
    if guild is not None:
        whales_kwargs["guild"] = guild

    @tree.command(**whales_kwargs)
    @app_commands.describe(
        min_pct="Minimum holder concentration percentage. Default 90.",
        bucket="Which holder bucket to rank: top100, top10, either, or both.",
        limit="Maximum rows to return.",
        require_contract_hint="Only include rows with a known token contract hint.",
        max_symbols="Maximum symbols to live-fetch when holder columns are missing. Use 0 for all.",
        refresh="Ignore the whale cache and recompute holder composition when needed.",
    )
    async def whales(
        interaction: discord.Interaction,
        min_pct: float = 90.0,
        bucket: str = "top100",
        limit: int = 50,
        require_contract_hint: bool = False,
        max_symbols: int = 0,
        refresh: bool = False,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("whales")):
            await interaction.response.send_message(_access_denied_message("whales"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_whale_dominance_list,
            min(max(int(limit), 1), 300),
            min_pct=min_pct,
            bucket=bucket,
            require_contract_hint=require_contract_hint,
            max_symbols=max(0, int(max_symbols)),
            refresh=refresh,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xA855F7)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    terminal_kwargs = {"name": "terminal", "description": "Show top market-structure evidence rows."}
    if guild is not None:
        terminal_kwargs["guild"] = guild

    @tree.command(**terminal_kwargs)
    async def terminal(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("terminal")):
            await interaction.response.send_message(_access_denied_message("terminal"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(_load_terminal_list, _env_int("DISCORD_TERMINAL_TOP_N", 25, minimum=1))
        embed = discord.Embed(title=title, description=description, color=0x8B5CF6)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    timing_kwargs = {"name": "timing", "description": "Show symbols with the strongest current timing conditions."}
    if guild is not None:
        timing_kwargs["guild"] = guild

    @tree.command(**timing_kwargs)
    async def timing(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("timing")):
            await interaction.response.send_message(_access_denied_message("timing"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(_load_timing_list, _env_int("DISCORD_TIMING_TOP_N", 25, minimum=1))
        embed = discord.Embed(title=title, description=description, color=0x22C55E)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    corr_kwargs = {"name": "corr", "description": "Show symbols below a BTC-correlation cutoff."}
    if guild is not None:
        corr_kwargs["guild"] = guild

    @tree.command(**corr_kwargs)
    @app_commands.describe(
        threshold="Maximum BTC correlation to show. 0.5 means corr_to_btc <= +0.50; negatives always pass.",
        limit="Maximum rows to return. Use 0 for all matching rows.",
    )
    async def corr(interaction: discord.Interaction, threshold: float = 0.0, limit: int = 0) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("corr")):
            await interaction.response.send_message(_access_denied_message("corr"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_corr_list,
            threshold=threshold,
            limit=min(max(int(limit), 0), 300),
        )
        if not chunks:
            chunks = ["No negative BTC-correlation rows found."]
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0x38BDF8)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    cexflow_kwargs = {"name": "cexflow", "description": "Show concentration-gated large CEX token-transfer flow."}
    if guild is not None:
        cexflow_kwargs["guild"] = guild

    @tree.command(**cexflow_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per transfer, for example 20000.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        min_whale_pct="Top10 holder concentration floor. Values below 90 are treated as 90.",
        require_holder_evidence="Require ETH/BNB/ARB chain, contract, and explorer holder-source snapshot evidence for the holder gate.",
        require_venue_gate="Require Binance perp plus Bitget trading evidence. Disable for raw CEX-flow sweep.",
    )
    async def cexflow(
        interaction: discord.Interaction,
        min_tokens: float = 0.0,
        limit: int = default_cexflow_top_n,
        lookback_hours: int = 24,
        min_whale_pct: float = 90.0,
        require_holder_evidence: bool = True,
        require_venue_gate: bool = True,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("cexflow")):
            await interaction.response.send_message(_access_denied_message("cexflow"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_cex_flow_list,
            min(max(int(limit), 1), 100),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
            require_holder_evidence=require_holder_evidence,
            require_venue_gate=require_venue_gate,
        )
        if not chunks:
            chunks = ["No concentration-gated large CEX token-transfer flow found."]
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    cexdiag_kwargs = {"name": "cexdiag", "description": "Explain CEX-flow scan coverage and filter bottlenecks."}
    if guild is not None:
        cexdiag_kwargs["guild"] = guild

    @tree.command(**cexdiag_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per transfer, for example 1000.",
        lookback_hours="Transfer lookback window in hours.",
        min_whale_pct="Top10 holder concentration floor. Values below 90 are treated as 90.",
        require_holder_evidence="Require ETH/BNB/ARB chain, contract, and explorer holder-source snapshot evidence for the holder gate.",
        require_venue_gate="Show how many raw CEX-flow rows survive the Binance+Bitget thesis venue gate.",
        symbol_limit="How many attempted symbols to list.",
    )
    async def cexdiag(
        interaction: discord.Interaction,
        min_tokens: float = 0.0,
        lookback_hours: int = 24,
        min_whale_pct: float = 90.0,
        require_holder_evidence: bool = True,
        require_venue_gate: bool = True,
        symbol_limit: int = 15,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("cexdiag")):
            await interaction.response.send_message(_access_denied_message("cexdiag"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(
            _load_cex_flow_diagnostics,
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
            require_holder_evidence=require_holder_evidence,
            require_venue_gate=require_venue_gate,
            symbol_limit=min(max(int(symbol_limit), 1), 50),
        )
        embed = discord.Embed(title=title, description=f"```text\n{description}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    earlyflow_kwargs = {"name": "earlyflow", "description": "Search smaller whale-to-CEX transfers for early low-float flow."}
    if guild is not None:
        earlyflow_kwargs["guild"] = guild

    @tree.command(**earlyflow_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per transfer. Defaults to DISCORD_EARLY_FLOW_MIN_TOKENS or 20000.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        min_whale_pct="Top10 holder concentration floor. Values below 90 are treated as 90.",
        require_holder_evidence="Require ETH/BNB/ARB chain, contract, and explorer holder-source snapshot evidence for the holder gate.",
        require_venue_gate="Require Binance perp plus Bitget trading evidence. Disable for raw early-flow sweep.",
    )
    async def earlyflow(
        interaction: discord.Interaction,
        min_tokens: float = 0.0,
        limit: int = default_cexflow_top_n,
        lookback_hours: int = 24,
        min_whale_pct: float = 90.0,
        require_holder_evidence: bool = True,
        require_venue_gate: bool = True,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("earlyflow")):
            await interaction.response.send_message(_access_denied_message("earlyflow"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_early_flow_list,
            min(max(int(limit), 1), 100),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
            require_holder_evidence=require_holder_evidence,
            require_venue_gate=require_venue_gate,
        )
        if not chunks:
            chunks = ["No early wallet-to-CEX token-transfer flow found."]
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    flowcoin_kwargs = {"name": "flowcoin", "description": "Inspect wallet-to-CEX flow for one symbol with a custom threshold."}
    if guild is not None:
        flowcoin_kwargs["guild"] = guild

    @tree.command(**flowcoin_kwargs)
    @app_commands.describe(
        symbol="Symbol to inspect, for example PLAYUSDT or PLAY.",
        min_tokens="Minimum token amount per transfer, for example 20000.",
        lookback_hours="Transfer lookback window in hours.",
    )
    async def flowcoin(
        interaction: discord.Interaction,
        symbol: str,
        min_tokens: float = 0.0,
        lookback_hours: int = 24,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("flowcoin")):
            await interaction.response.send_message(_access_denied_message("flowcoin"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(
            _load_symbol_cex_flow,
            symbol,
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
        )
        embed = discord.Embed(title=title, description=f"```text\n{description}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    flowstress_kwargs = {"name": "flowstress", "description": "Rank CEX deposit inventory stress versus visible liquidity."}
    if guild is not None:
        flowstress_kwargs["guild"] = guild

    @tree.command(**flowstress_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per transfer, for example 20000.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        require_venue_gate="Also apply the Binance+Bitget thesis venue gate.",
    )
    async def flowstress(
        interaction: discord.Interaction,
        min_tokens: float = 0.0,
        limit: int = default_cexflow_top_n,
        lookback_hours: int = 24,
        require_venue_gate: bool = True,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("flowstress")):
            await interaction.response.send_message(_access_denied_message("flowstress"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_flow_stress_list,
            min(max(int(limit), 1), 100),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            require_venue_gate=require_venue_gate,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    flowblocked_kwargs = {"name": "flowblocked", "description": "List CEX-flow rows blocked by explorer/API data-source errors."}
    if guild is not None:
        flowblocked_kwargs["guild"] = guild

    @tree.command(**flowblocked_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per transfer, for example 20000.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
    )
    async def flowblocked(
        interaction: discord.Interaction,
        min_tokens: float = 0.0,
        limit: int = 25,
        lookback_hours: int = 24,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("flowblocked")):
            await interaction.response.send_message(_access_denied_message("flowblocked"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_flow_blocked_list,
            min(max(int(limit), 1), 100),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    flowhealth_kwargs = {"name": "flowhealth", "description": "Show CEX-flow source health, API fallback status, and label coverage."}
    if guild is not None:
        flowhealth_kwargs["guild"] = guild

    @tree.command(**flowhealth_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per transfer, for example 20000.",
        lookback_hours="Transfer lookback window in hours.",
        symbol_limit="How many attempted symbols to list.",
    )
    async def flowhealth(
        interaction: discord.Interaction,
        min_tokens: float = 0.0,
        lookback_hours: int = 24,
        symbol_limit: int = 10,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("flowhealth")):
            await interaction.response.send_message(_access_denied_message("flowhealth"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(
            _load_flow_health,
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            symbol_limit=min(max(int(symbol_limit), 1), 50),
        )
        embed = discord.Embed(title=title, description=f"```text\n{description}\n```", color=0xF97316)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    sethflow_kwargs = {"name": "sethflow", "description": "Run the whale-origin CEX-flow, whale, shorts, and dormant-structure checklist."}
    if guild is not None:
        sethflow_kwargs["guild"] = guild

    @tree.command(**sethflow_kwargs)
    @app_commands.describe(
        min_tokens="Minimum token amount per transfer, for example 10000000.",
        limit="Maximum rows to return.",
        lookback_hours="Transfer lookback window in hours.",
        min_short_pct="Minimum short-account percentage, default 50.",
        min_whale_pct="Top10 holder concentration floor. Values below 90 are treated as 90.",
        require_whale_origin_flow="Require the confirmed transfer sender to match a scanned top-holder wallet.",
    )
    async def sethflow(
        interaction: discord.Interaction,
        min_tokens: float = 10_000_000.0,
        limit: int = 15,
        lookback_hours: int = 24,
        min_short_pct: float = 50.0,
        min_whale_pct: float = 90.0,
        require_whale_origin_flow: bool = True,
    ) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("sethflow")):
            await interaction.response.send_message(_access_denied_message("sethflow"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(
            _load_seth_flow_playbook,
            min(max(int(limit), 1), 100),
            min_tokens=min_tokens if min_tokens > 0 else None,
            lookback_hours=lookback_hours if lookback_hours > 0 else None,
            min_short_pct=max(0.0, min(float(min_short_pct), 100.0)),
            min_whale_pct=max(0.0, min(float(min_whale_pct), 100.0)),
            require_whale_origin_flow=require_whale_origin_flow,
        )
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0x14B8A6)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    alpha_kwargs = {"name": "alpha", "description": "Show a strict holder-and-venue-gated alpha brief."}
    if guild is not None:
        alpha_kwargs["guild"] = guild

    @tree.command(**alpha_kwargs)
    async def alpha(interaction: discord.Interaction, limit: int = default_alpha_top_n) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("alpha")):
            await interaction.response.send_message(_access_denied_message("alpha"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, chunks = await asyncio.to_thread(_load_alpha_brief, min(max(int(limit), 1), 50))
        if not chunks:
            chunks = ["No alpha brief rows found."]
        embed = discord.Embed(title=title, description=f"```text\n{chunks[0]}\n```", color=0x14B8A6)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```text\n{chunk}\n```")

    startbot_kwargs = {"name": "startbot", "description": "Start the gated trade setup bot. Defaults to paper mode."}
    if guild is not None:
        startbot_kwargs["guild"] = guild

    @tree.command(**startbot_kwargs)
    @app_commands.describe(mode="paper or live", scan_mode="Fast, Deep, or Full ATH")
    async def startbot(interaction: discord.Interaction, mode: str = "paper", scan_mode: str = "Deep") -> None:
        global _TRADE_BOT_TASK, _TRADE_BOT_STOP_REQUESTED
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("startbot")):
            await interaction.response.send_message(_access_denied_message("startbot"), ephemeral=True)
            return
        if _TRADE_BOT_TASK is not None and not _TRADE_BOT_TASK.done():
            await interaction.response.send_message("Trade setup bot is already running. Use `/tradebot_status` or `/stopbot`.", ephemeral=True)
            return
        if interaction.channel is None:
            await interaction.response.send_message("Could not resolve the current Discord channel.", ephemeral=True)
            return
        config = TradeBotConfig.from_env(mode=mode, scan_mode=scan_mode)
        if config.mode == "live" and not _env_bool("TRADE_BOT_LIVE_ENABLED", False):
            await interaction.response.send_message(
                "Live mode refused because `TRADE_BOT_LIVE_ENABLED=1` is not set. Start with `/startbot mode:paper`.",
                ephemeral=True,
            )
            return
        _TRADE_BOT_STOP_REQUESTED = False
        _TRADE_BOT_TASK = asyncio.create_task(_trade_bot_loop(interaction.channel, config))
        await interaction.response.send_message(
            f"Trade setup bot starting in `{config.mode}` mode. Scan mode `{config.scan_mode}`. Use `/tradebot_status` for state.",
            ephemeral=True,
        )

    stopbot_kwargs = {"name": "stopbot", "description": "Stop the trade setup bot loop."}
    if guild is not None:
        stopbot_kwargs["guild"] = guild

    @tree.command(**stopbot_kwargs)
    async def stopbot(interaction: discord.Interaction) -> None:
        global _TRADE_BOT_TASK, _TRADE_BOT_STOP_REQUESTED
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("stopbot")):
            await interaction.response.send_message(_access_denied_message("stopbot"), ephemeral=True)
            return
        _TRADE_BOT_STOP_REQUESTED = True
        if _TRADE_BOT_TASK is not None and not _TRADE_BOT_TASK.done():
            _TRADE_BOT_TASK.cancel()
        await interaction.response.send_message("Trade setup bot stop requested.", ephemeral=True)

    tradebot_status_kwargs = {"name": "tradebot_status", "description": "Show trade setup bot status and tracked PnL."}
    if guild is not None:
        tradebot_status_kwargs["guild"] = guild

    @tree.command(**tradebot_status_kwargs)
    async def tradebot_status(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("tradebot_status")):
            await interaction.response.send_message(_access_denied_message("tradebot_status"), ephemeral=True)
            return
        running = _TRADE_BOT_TASK is not None and not _TRADE_BOT_TASK.done()
        task_note = ""
        if _TRADE_BOT_TASK is not None and _TRADE_BOT_TASK.done():
            try:
                exc = _TRADE_BOT_TASK.exception()
            except asyncio.CancelledError:
                exc = None
                task_note = "Task: cancelled"
            if exc is not None:
                task_note = f"Task exception: {type(exc).__name__}: {exc}"
            elif not task_note:
                task_note = "Task: exited"
        status = _TRADE_BOT_RUNTIME.status_text() if _TRADE_BOT_RUNTIME is not None else "Trade setup bot has not been started in this process."
        task_line = f"\n{task_note}" if task_note else ""
        await interaction.response.send_message(_trade_bot_text(f"Running: {running}{task_line}\n{status}"), ephemeral=True)

    dossier_kwargs = {"name": "dossier", "description": "Show the market-structure evidence dossier for one symbol."}
    if guild is not None:
        dossier_kwargs["guild"] = guild

    @tree.command(**dossier_kwargs)
    @app_commands.describe(symbol="Symbol to inspect, for example PLAYUSDT or PLAY")
    async def dossier(interaction: discord.Interaction, symbol: str) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("dossier")):
            await interaction.response.send_message(_access_denied_message("dossier"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(_load_dossier, symbol)
        embed = discord.Embed(title=title, description=description, color=0x8B5CF6)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    coin_kwargs = {"name": "coin", "description": "Show latest scan/live stats for one futures symbol."}
    if guild is not None:
        coin_kwargs["guild"] = guild

    @tree.command(**coin_kwargs)
    @app_commands.describe(symbol="Symbol to inspect, for example PLAYUSDT or PLAY")
    async def coin(interaction: discord.Interaction, symbol: str) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("coin")):
            await interaction.response.send_message(_access_denied_message("coin"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        title, description = await asyncio.to_thread(_load_coin_stats, symbol)
        embed = discord.Embed(title=title, description=description, color=0x38BDF8)
        embed.set_footer(text=DISCORD_FOOTER)
        await interaction.followup.send(embed=embed)

    def _make_symbol_alias_command(alias_symbol: str):
        async def symbol_alias(interaction: discord.Interaction) -> None:
            if not _channel_allowed(interaction):
                await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
                return
            if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("coin")):
                await interaction.response.send_message(_access_denied_message("coin"), ephemeral=True)
                return
            await interaction.response.defer(thinking=True)
            title, description = await asyncio.to_thread(_load_coin_stats, alias_symbol)
            embed = discord.Embed(title=title, description=description, color=0x38BDF8)
            embed.set_footer(text=DISCORD_FOOTER)
            await interaction.followup.send(embed=embed)

        return symbol_alias

    for alias_symbol in symbol_slash_aliases:
        alias_name = _symbol_slash_command_name(alias_symbol)
        if not alias_name:
            continue
        alias_kwargs = {"name": alias_name, "description": f"Show {alias_symbol} scan/live stats."}
        if guild is not None:
            alias_kwargs["guild"] = guild
        tree.command(**alias_kwargs)(_make_symbol_alias_command(alias_symbol))

    status_kwargs = {"name": "convex_status", "description": "Show Discord Convex cache status."}
    if guild is not None:
        status_kwargs["guild"] = guild

    @tree.command(**status_kwargs)
    async def convex_status(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        status = await asyncio.to_thread(_cache_status)
        await interaction.response.send_message(status)

    scoreboard_kwargs = {"name": "convex_scoreboard", "description": "Show trailing proof-engine outcome stats."}
    if guild is not None:
        scoreboard_kwargs["guild"] = guild

    @tree.command(**scoreboard_kwargs)
    async def convex_scoreboard(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("scoreboard")):
            await interaction.response.send_message(_access_denied_message("scoreboard"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        text = await asyncio.to_thread(_scoreboard_text)
        await interaction.followup.send(f"```text\n{text[:1800]}\n```")

    archive_kwargs = {"name": "convex_archive", "description": "Export archived scanner flags and outcomes."}
    if guild is not None:
        archive_kwargs["guild"] = guild

    @tree.command(**archive_kwargs)
    async def convex_archive(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("archive")):
            await interaction.response.send_message(_access_denied_message("archive"), ephemeral=True)
            return
        path = proof_archive_path()
        if not path.exists():
            await interaction.response.send_message("No proof archive exists yet.")
            return
        await interaction.response.defer(thinking=True)
        await interaction.followup.send("Proof archive export.", file=discord.File(str(path), filename=path.name))

    sync_kwargs = {"name": "sync_commands", "description": "Force slash-command resync for this bot."}
    if guild is not None:
        sync_kwargs["guild"] = guild

    @tree.command(**sync_kwargs)
    async def sync_commands(interaction: discord.Interaction) -> None:
        if not _channel_allowed(interaction):
            await interaction.response.send_message("This command is locked to the configured alert channel.", ephemeral=True)
            return
        if not _tier_allows(_interaction_tier(interaction), _feature_required_tier("sync_commands")):
            await interaction.response.send_message(_access_denied_message("sync_commands"), ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        synced = await tree.sync(guild=guild) if guild is not None else await tree.sync()
        names = ", ".join(f"/{command.name}" for command in synced) or "none"
        scope = f"guild {guild.id}" if guild is not None else "global"
        await interaction.followup.send(
            f"Synced slash commands to {scope}: {names}\n"
            "If Discord still says a command is outdated, close the command composer and type the command again.",
            ephemeral=True,
        )

    @client.event
    async def on_message(message: discord.Message) -> None:
        if not symbol_shortcuts_enabled or message.author.bot:
            return
        if allowed_channel_id is not None and message.channel.id != allowed_channel_id:
            return
        if not _tier_allows(_tier_for_role_ids(_role_ids_from_subject(message.author)), _feature_required_tier("shortcut")):
            return
        if not _looks_like_symbol_shortcut(message.content):
            return
        symbol = _normalize_symbol_query(message.content)
        async with message.channel.typing():
            title, description = await asyncio.to_thread(_load_coin_stats, symbol)
        embed = discord.Embed(title=title, description=description, color=0x38BDF8)
        embed.set_footer(text=DISCORD_FOOTER)
        await message.reply(embed=embed, mention_author=False)

    @client.event
    async def on_ready() -> None:
        guilds = ", ".join(f"{connected_guild.name} ({connected_guild.id})" for connected_guild in client.guilds)
        print(f"Connected guilds: {guilds or 'none'}")
        print(f"Configured DISCORD_GUILD_ID: {guild_id_raw or 'not set'}")
        print(f"Configured DISCORD_ALLOWED_CHANNEL_ID: {allowed_channel_raw or 'not set'}")
        print(
            "Raw text symbol shortcuts: "
            f"{'enabled' if symbol_shortcuts_enabled else 'disabled'} "
            "(requires DISCORD_MESSAGE_CONTENT_INTENT_ENABLED=1 and Discord Developer Portal > Bot > Message Content Intent)."
        )
        if force_disable_symbol_shortcuts:
            print("Symbol shortcuts were forced off because Discord rejected privileged intents.")
        print(
            "Symbol slash aliases: "
            + (", ".join(f"/{_symbol_slash_command_name(symbol)}" for symbol in symbol_slash_aliases) or "none")
        )

        if guild is not None:
            if _env_bool("DISCORD_CLEAR_GLOBAL_COMMANDS_ON_GUILD_SYNC", False):
                tree.clear_commands(guild=None)
                cleared = await tree.sync()
                print(f"Cleared global slash-command scope; remaining global commands: {len(cleared)}.")
            commands = await tree.sync(guild=guild)
            scope = f"guild {guild.id}"
        else:
            commands = await tree.sync()
            scope = "global"
        command_names = ", ".join(f"/{command.name}" for command in commands) or "none"
        print(f"Discord Convex bot logged in as {client.user}. Slash commands synced to {scope}: {command_names}.")
        print(
            "If Discord says a command is outdated after a schema change, close the slash-command composer and retry. "
            "Guild commands usually refresh within a few minutes; global commands can take longer."
        )

        if allowed_channel_id is None:
            print("DISCORD_ALLOWED_CHANNEL_ID is not set; commands are allowed in any channel.")
            return

        channel = client.get_channel(allowed_channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(allowed_channel_id)
            except Exception as exc:
                print(f"Could not access DISCORD_ALLOWED_CHANNEL_ID {allowed_channel_id}: {exc}")
                print("Check that the bot is invited to the server and can view that channel.")
                return

        print(f"Allowed channel resolved: #{getattr(channel, 'name', 'unknown')} ({allowed_channel_id})")
        if announce_online:
            try:
                await channel.send(
                    "Convex bot online. Start with `/radar`, use `/coincheck symbol:PLAYUSDT` for one name, "
                    "and use `/help` or `/commands` for the full operator map. Diagnostics: `/cexdiag min_tokens:1000`, "
                    "`/flowhealth`, `/whales min_pct:90`, `/high days:20D thesis_only:true`, `/low days:20D thesis_only:true`."
                )
            except Exception as exc:
                print(f"Bot is online but could not post to allowed channel {allowed_channel_id}: {exc}")

    client.run(token)


def run_with_backoff() -> None:
    _load_local_env()
    retry_seconds = max(15, int(_env_value("DISCORD_LOGIN_RETRY_SECONDS", "90")))
    max_retry_seconds = max(retry_seconds, int(_env_value("DISCORD_LOGIN_MAX_RETRY_SECONDS", "600")))
    force_disable_symbol_shortcuts = False

    while True:
        try:
            main(force_disable_symbol_shortcuts=force_disable_symbol_shortcuts)
            return
        except KeyboardInterrupt:
            raise
        except SystemExit:
            raise
        except Exception as exc:
            status = getattr(exc, "status", None)
            code = getattr(exc, "code", None)
            is_privileged_intent_error = exc.__class__.__name__ == "PrivilegedIntentsRequired"
            if is_privileged_intent_error and not force_disable_symbol_shortcuts:
                print(
                    "Discord rejected the Message Content Intent. Restarting without raw /SYMBOL shortcuts; "
                    "`/coin PLAYUSDT` and configured lowercase aliases such as `/playusdt` will still work."
                )
                force_disable_symbol_shortcuts = True
                continue
            is_rate_limited = status == 429 or code == 40062 or "429 Too Many Requests" in str(exc)
            if not is_rate_limited:
                raise
            print(f"Discord login is rate-limited. Waiting {retry_seconds}s before retrying instead of exiting.")
            time.sleep(retry_seconds)
            retry_seconds = min(max_retry_seconds, retry_seconds * 2)


if __name__ == "__main__":
    run_with_backoff()
