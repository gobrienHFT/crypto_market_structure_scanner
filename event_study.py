from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

import pandas as pd

from binance_futures import BinanceFuturesPublic


CASE_STUDY_SYMBOLS = ("RAVEUSDT", "LABUSDT", "VELVETUSDT", "RIVERUSDT", "SIRENUSDT", "STOUSDT")

LOCAL_SNAPSHOT_FILES = (
    Path("crypto_market_structure/fixtures/historical_exports/2026-04-20T17-22_export.csv"),
    Path("crypto_market_structure/fixtures/historical_exports/2026-04-28T18-29_export.csv"),
    Path("crypto_market_structure/fixtures/historical_exports/2026-04-28T18-30_export.csv"),
    # Compatibility names keep the backfill helper usable with a caller's
    # temporary root and older local exports without keeping generated files
    # in this repository's root.
    Path("2026-04-20T17-22_export.csv"),
    Path("2026-04-28T18-29_export.csv"),
    Path("2026-04-28T18-30_export.csv"),
    Path("data/latest_convex_longs.csv"),
    Path("data/latest_short_account_roc.csv"),
    Path("data/latest_short_account_trend.csv"),
    Path("data/latest_short_account_majority.csv"),
    Path("data/pre_pump_scan_snapshots.csv"),
)

CONTRACT_HINT_FILES = (
    Path("data/discord_holder_contracts.csv"),
    Path("data/discord_holder_contracts_full.csv"),
)

EVENT_STUDY_COLUMNS = [
    "symbol",
    "event_date",
    "mechanism_hypothesis",
    "local_snapshot_count",
    "best_snapshot_file",
    "best_snapshot_time",
    "local_evidence_status",
    "observed_phase",
    "contract_hint_status",
    "contract_hint_chain",
    "contract_hint_address",
    "price_event_date",
    "price_event_date_source",
    "last_price",
    "day_return_pct",
    "hour_return_pct",
    "carry_funding_pct",
    "predicted_funding_pct",
    "short_account_pct",
    "short_account_roc_1h_pp",
    "oi_delta_pct",
    "broke_high_5d",
    "broke_high_20d",
    "broke_high_90d",
    "ath_multiple",
    "convexity_score",
    "crime_pump_score",
    "crime_exhaustion_score",
    "terminal_edge_score",
    "rave_lab_setup_score",
    "trade_bucket_score",
    "top10_holder_pct",
    "cex_deposit_flow_score",
    "mechanism_read",
    "mechanism_verdict",
    "scanner_lesson",
    "evidence_gap_severity",
    "next_data_action",
    "evidence_gaps",
    "price_path_status",
    "event_open",
    "event_high",
    "event_low",
    "event_close",
    "pre_1d_return_pct",
    "pre_3d_return_pct",
    "pre_7d_return_pct",
    "event_day_return_pct",
    "event_break_prior_20d_high",
    "post_7d_high_return_pct",
    "post_7d_low_drawdown_pct",
]


CASE_STUDY_METADATA = {
    "RAVEUSDT": {
        "event_date": "2026-04-18",
        "mechanism_hypothesis": "Hidden-float cap-table reflexivity / blowoff unwind",
    },
    "LABUSDT": {
        "event_date": "2026-05-11",
        "mechanism_hypothesis": "CEX inventory squeeze / low-float venue stress",
    },
    "VELVETUSDT": {
        "event_date": "recent/current",
        "mechanism_hypothesis": "Crowded-short uptrend continuation",
    },
    "RIVERUSDT": {
        "event_date": "scanner-observed",
        "mechanism_hypothesis": "Runway breakout reflexivity",
    },
    "SIRENUSDT": {
        "event_date": "scanner-observed",
        "mechanism_hypothesis": "Compression ignition / short-fuse pre-ignition",
    },
    "STOUSDT": {
        "event_date": "scanner-observed",
        "mechanism_hypothesis": "Target-venue squeeze / runway watch",
    },
}


@dataclass(frozen=True)
class SnapshotHit:
    symbol: str
    source_path: Path
    row: dict[str, Any]


@dataclass(frozen=True)
class ContractHintRow:
    symbol: str
    chain: str
    contract_address: str
    source_path: Path


class KlineClient(Protocol):
    def klines_1d(
        self,
        symbol: str,
        limit: int = 200,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[list[Any]]:
        ...


def _safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number if math.isfinite(number) else float("nan")


def _safe_bool(value: Any) -> bool | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _parse_event_date(value: str) -> datetime | None:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_snapshot_date(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H-%M", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _snapshot_time(path: Path, row: dict[str, Any]) -> str:
    for column in ("scanned_at_utc", "timestamp_utc", "flagged_at_utc", "created_at_utc"):
        value = str(row.get(column, "") or "").strip()
        if value:
            return value
    name = path.name
    if name.endswith("_export.csv"):
        return name.replace("_export.csv", "").replace("T", " ")
    return ""


def _short_account_pct(row: dict[str, Any]) -> float:
    direct = _safe_float(row.get("short_account_pct"))
    if math.isfinite(direct):
        return direct
    long_pct = _safe_float(row.get("long_account_pct"))
    if math.isfinite(long_pct):
        return 100.0 - long_pct
    return float("nan")


def _clean_contract(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1]
    return text


def _read_snapshot(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".jsonl":
            return pd.read_json(path, lines=True)
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def _kline_frame(rows: list[list[Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trade_count",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
            "ignore",
        ][: len(rows[0])],
    )
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["date"] = pd.to_datetime(pd.to_numeric(frame["open_time"], errors="coerce"), unit="ms", utc=True).dt.date
    return frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


def _return_pct(start: float, end: float) -> float:
    if not math.isfinite(start) or not math.isfinite(end) or abs(start) < 1e-12:
        return float("nan")
    return (end / start - 1.0) * 100.0


def _price_path_metrics(symbol: str, event_dt: datetime | None, client: KlineClient | None) -> dict[str, Any]:
    empty = {
        "price_path_status": "not requested" if client is None else "missing event date",
        "price_event_date": "",
        "price_event_date_source": "",
        "event_open": float("nan"),
        "event_high": float("nan"),
        "event_low": float("nan"),
        "event_close": float("nan"),
        "pre_1d_return_pct": float("nan"),
        "pre_3d_return_pct": float("nan"),
        "pre_7d_return_pct": float("nan"),
        "event_day_return_pct": float("nan"),
        "event_break_prior_20d_high": None,
        "post_7d_high_return_pct": float("nan"),
        "post_7d_low_drawdown_pct": float("nan"),
    }
    if client is None or event_dt is None:
        return empty
    start_ms = int((event_dt.timestamp() - 35 * 86400) * 1000)
    end_ms = int((event_dt.timestamp() + 15 * 86400) * 1000)
    try:
        rows = client.klines_1d(symbol, limit=80, start_time=start_ms, end_time=end_ms)
    except Exception as exc:
        output = dict(empty)
        output["price_path_status"] = f"kline fetch failed: {exc.__class__.__name__}"
        return output
    klines = _kline_frame(rows)
    if klines.empty:
        output = dict(empty)
        output["price_path_status"] = "no Binance kline rows"
        return output

    event_date = event_dt.date()
    exact = klines[klines["date"] == event_date]
    if exact.empty:
        output = dict(empty)
        output["price_path_status"] = "event date not in Binance klines"
        return output

    event_idx = int(exact.index[0])
    event_row = klines.loc[event_idx]
    event_open = float(event_row["open"])
    event_high = float(event_row["high"])
    event_low = float(event_row["low"])
    event_close = float(event_row["close"])

    prior = klines.iloc[:event_idx]
    post = klines.iloc[event_idx + 1 : event_idx + 8]
    output = dict(empty)
    output.update(
        {
            "price_path_status": "ok",
            "price_event_date": event_date.isoformat(),
            "price_event_date_source": "declared/snapshot",
            "event_open": event_open,
            "event_high": event_high,
            "event_low": event_low,
            "event_close": event_close,
            "event_day_return_pct": _return_pct(event_open, event_close),
            "event_break_prior_20d_high": bool(len(prior) >= 1 and event_high > float(prior.tail(20)["high"].max())),
        }
    )
    for days, column in ((1, "pre_1d_return_pct"), (3, "pre_3d_return_pct"), (7, "pre_7d_return_pct")):
        if event_idx >= days:
            start_close = float(klines.loc[event_idx - days, "close"])
            output[column] = _return_pct(start_close, event_close)
    if not post.empty:
        output["post_7d_high_return_pct"] = _return_pct(event_close, float(post["high"].max()))
        output["post_7d_low_drawdown_pct"] = _return_pct(event_close, float(post["low"].min()))
    return output


def _infer_event_date_from_klines(symbol: str, client: KlineClient | None) -> dict[str, Any]:
    empty = _price_path_metrics(symbol, None, client)
    if client is None:
        return empty
    try:
        rows = client.klines_1d(symbol, limit=160)
    except Exception as exc:
        output = dict(empty)
        output["price_path_status"] = f"kline fetch failed: {exc.__class__.__name__}"
        return output
    klines = _kline_frame(rows)
    if len(klines) < 8:
        output = dict(empty)
        output["price_path_status"] = "not enough Binance kline rows to infer"
        return output
    frame = klines.copy()
    prior_close = frame["close"].shift(1)
    frame["_close_return_pct"] = (frame["close"] / prior_close - 1.0) * 100.0
    frame["_high_return_pct"] = (frame["high"] / prior_close - 1.0) * 100.0
    frame["_impulse_score"] = frame[["_close_return_pct", "_high_return_pct"]].max(axis=1)
    frame = frame.dropna(subset=["_impulse_score"])
    if frame.empty:
        output = dict(empty)
        output["price_path_status"] = "could not infer impulse date"
        return output
    event_date = frame.sort_values(["_impulse_score", "date"], ascending=[False, False]).iloc[0]["date"]
    event_dt = datetime.combine(event_date, datetime.min.time(), tzinfo=timezone.utc)
    output = _price_path_metrics(symbol, event_dt, client)
    if output.get("price_path_status") == "ok":
        output["price_event_date_source"] = "inferred_largest_daily_impulse"
    return output


def collect_case_study_hits(
    *,
    root: Path | str = ".",
    symbols: Iterable[str] = CASE_STUDY_SYMBOLS,
    snapshot_files: Iterable[Path] = LOCAL_SNAPSHOT_FILES,
) -> list[SnapshotHit]:
    root_path = Path(root)
    wanted = {str(symbol).upper() for symbol in symbols}
    hits: list[SnapshotHit] = []
    for relative in snapshot_files:
        path = root_path / relative
        frame = _read_snapshot(path)
        if frame.empty or "symbol" not in frame.columns:
            continue
        matches = frame[frame["symbol"].astype(str).str.upper().isin(wanted)].copy()
        for _, row in matches.iterrows():
            hits.append(SnapshotHit(symbol=str(row.get("symbol", "")).upper(), source_path=relative, row=row.to_dict()))
    return hits


def collect_contract_hints(
    *,
    root: Path | str = ".",
    symbols: Iterable[str] = CASE_STUDY_SYMBOLS,
    hint_files: Iterable[Path] = CONTRACT_HINT_FILES,
) -> dict[str, ContractHintRow]:
    root_path = Path(root)
    wanted = {str(symbol).upper() for symbol in symbols}
    wanted_bases = {symbol.replace("USDT", "") for symbol in wanted}
    hints: dict[str, ContractHintRow] = {}
    for relative in hint_files:
        path = root_path / relative
        frame = _read_snapshot(path)
        if frame.empty or "symbol" not in frame.columns:
            continue
        for _, row in frame.iterrows():
            raw_symbol = str(row.get("symbol", "") or "").upper().strip()
            symbol = raw_symbol if raw_symbol in wanted else f"{raw_symbol}USDT"
            if raw_symbol not in wanted and raw_symbol not in wanted_bases:
                continue
            if symbol not in wanted or symbol in hints:
                continue
            chain = str(row.get("chain", "") or row.get("token_platform", "") or "").strip().lower()
            contract = _clean_contract(row.get("contract_address") or row.get("token_contract") or row.get("contract") or "")
            if not chain or not contract:
                continue
            hints[symbol] = ContractHintRow(symbol=symbol, chain=chain, contract_address=contract, source_path=relative)
    return hints


def _score_snapshot(hit: SnapshotHit) -> float:
    row = hit.row
    score = 0.0
    for column, weight in (
        ("mechanism_score", 1.5),
        ("terminal_edge_score", 1.2),
        ("rave_lab_setup_score", 1.2),
        ("convexity_score", 1.0),
        ("crime_pump_score", 0.8),
        ("trade_bucket_score", 0.8),
        ("short_account_pct", 0.4),
        ("top10_holder_pct", 0.4),
        ("cex_deposit_flow_score", 0.8),
    ):
        value = _safe_float(row.get(column))
        if math.isfinite(value):
            score += value * weight
    exhaustion = _safe_float(row.get("crime_exhaustion_score"))
    if math.isfinite(exhaustion):
        score += exhaustion * 0.3
    return score


def _best_hit(hits: list[SnapshotHit]) -> SnapshotHit | None:
    if not hits:
        return None
    return sorted(hits, key=_score_snapshot, reverse=True)[0]


def _phase(row: dict[str, Any]) -> str:
    exhaustion = _safe_float(row.get("crime_exhaustion_score"))
    day_return = _safe_float(row.get("day_return_pct"))
    high_5d = _safe_bool(row.get("broke_high_5d"))
    high_20d = _safe_bool(row.get("broke_high_20d"))
    setup_ready = _safe_bool(row.get("setup_ready_flag"))
    active_squeeze = _safe_bool(row.get("active_squeeze_flag"))
    if math.isfinite(exhaustion) and exhaustion >= 70:
        return "post-blowoff / exhaustion"
    if active_squeeze:
        return "active squeeze"
    if high_5d or high_20d:
        return "breakout/watch"
    if setup_ready:
        return "setup-ready watch"
    if math.isfinite(day_return) and abs(day_return) >= 20:
        return "volatile aftermath"
    return "watch / incomplete local evidence"


def _read_mechanism(row: dict[str, Any], mechanism_hypothesis: str) -> str:
    bits: list[str] = [mechanism_hypothesis]
    short_pct = _short_account_pct(row)
    funding = max(_safe_float(row.get("carry_funding_pct")), _safe_float(row.get("predicted_funding_pct")))
    oi_delta = _safe_float(row.get("oi_delta_pct"))
    top10 = _safe_float(row.get("top10_holder_pct"))
    cex = _safe_float(row.get("cex_deposit_flow_score"))
    if math.isfinite(short_pct):
        bits.append(f"shorts {short_pct:.1f}%")
    if math.isfinite(funding):
        bits.append(f"funding {funding:.4f}%")
    if math.isfinite(oi_delta):
        bits.append(f"OI {oi_delta:+.1f}%")
    if math.isfinite(top10):
        bits.append(f"top10 {top10:.1f}%")
    if math.isfinite(cex):
        bits.append(f"CEX flow {cex:.0f}")
    return " | ".join(bits)


def _gaps(row: dict[str, Any], count: int) -> str:
    gaps: list[str] = []
    if count == 0:
        return "no local snapshot row found"
    if not math.isfinite(_safe_float(row.get("top10_holder_pct"))):
        gaps.append("holder snapshot missing")
    if not math.isfinite(_safe_float(row.get("cex_deposit_flow_score"))):
        gaps.append("CEX-flow score missing")
    if not math.isfinite(_short_account_pct(row)):
        gaps.append("short-account snapshot missing")
    if not any(_safe_bool(row.get(column)) for column in ("broke_high_5d", "broke_high_20d", "broke_high_90d")):
        gaps.append("no high-break flag in local row")
    return "; ".join(gaps) if gaps else "local row has core market-structure fields"


def _mechanism_verdict(symbol: str, row: dict[str, Any]) -> str:
    status = str(row.get("price_path_status", "") or "")
    event_return = _safe_float(row.get("event_day_return_pct"))
    post_high = _safe_float(row.get("post_7d_high_return_pct"))
    drawdown = _safe_float(row.get("post_7d_low_drawdown_pct"))
    broke_20d = _safe_bool(row.get("event_break_prior_20d_high"))
    if status != "ok":
        return "needs exact event/date evidence"
    if symbol == "RAVEUSDT" or (math.isfinite(event_return) and event_return <= -50.0 and broke_20d):
        return "blowoff/unwind after prior-high break"
    if math.isfinite(post_high) and post_high >= 25.0 and math.isfinite(drawdown) and drawdown <= -25.0:
        return "violent continuation with large drawdown risk"
    if math.isfinite(event_return) and event_return >= 100.0 and math.isfinite(post_high) and post_high >= 25.0:
        return "impulse day can still have continuation fuel"
    if math.isfinite(post_high) and post_high >= 10.0 and (broke_20d or event_return >= 0.0):
        return "watchable continuation, not confirmed blowoff"
    return "weak or incomplete event-study confirmation"


def _scanner_lesson(symbol: str, row: dict[str, Any]) -> str:
    verdict = str(row.get("mechanism_verdict", "") or "")
    hypothesis = str(row.get("mechanism_hypothesis", "") or "")
    if "blowoff/unwind" in verdict:
        return "Do not chase vertical prior-high breaks when exhaustion/late-risk is high; treat post-spike bounces as unstable until structure resets."
    if "violent continuation" in verdict:
        if "CEX inventory" in hypothesis:
            return "LAB-like rows need CEX/holder proof plus breakout confirmation; expect continuation upside and deep pullbacks at the same time."
        return "Continuation rows can keep paying after the trigger, but position logic must survive 25-40% drawdowns."
    if "impulse day" in verdict:
        return "Largest impulse day is often not the terminal high; monitor short rebuild, OI, and high-break persistence before declaring exhaustion."
    if "Crowded-short" in hypothesis:
        return "Prioritize positive funding plus high/rising shorts only when price keeps making higher structural highs."
    if "Runway" in hypothesis or "Target-venue" in hypothesis:
        return "Runway/watch rows need a stronger trigger: high-break stack, short fuel, and venue/holder proof before promotion."
    return "Keep as research context until local holder, CEX-flow, short, and breakout evidence align."


def _gap_severity(row: dict[str, Any]) -> str:
    status = str(row.get("price_path_status", "") or "")
    gaps = str(row.get("evidence_gaps", "") or "")
    if "no local snapshot row found" in gaps:
        return "critical"
    missing_count = sum(
        token in gaps
        for token in (
            "holder snapshot missing",
            "CEX-flow score missing",
            "short-account snapshot missing",
            "no high-break flag",
        )
    )
    if status != "ok":
        missing_count += 1
    if missing_count >= 3:
        return "high"
    if missing_count >= 1:
        return "medium"
    return "low"


def _next_data_action(row: dict[str, Any]) -> str:
    status = str(row.get("price_path_status", "") or "")
    gaps = str(row.get("evidence_gaps", "") or "")
    contract_status = str(row.get("contract_hint_status", "") or "")
    if "no local snapshot row found" in gaps:
        return "Backfill or import a local scan row for this symbol/event before using it as an anchor."
    if status != "ok":
        return "Add an exact event date or fetch Binance daily klines so pre/post path can be measured."
    if "holder snapshot missing" in gaps:
        if contract_status == "available":
            return "Rerun holder composition/concentration using the existing contract hint for the event window."
        return "Resolve token contract and rerun holder composition/concentration for the event window."
    if "CEX-flow score missing" in gaps:
        return "Rerun labelled CEX-flow scan with contract hints and explorer API coverage."
    if "short-account snapshot missing" in gaps:
        return "Backfill Binance global long/short account history around the event."
    if "no high-break flag" in gaps:
        return "Compute custom high/low breakout windows for the event date."
    return "Evidence stack is usable; compare against live rows with the same mechanism label."


def build_case_study_event_frame(*, root: Path | str = ".", kline_client: KlineClient | None = None) -> pd.DataFrame:
    hits = collect_case_study_hits(root=root)
    contract_hints = collect_contract_hints(root=root)
    by_symbol: dict[str, list[SnapshotHit]] = {symbol: [] for symbol in CASE_STUDY_SYMBOLS}
    for hit in hits:
        by_symbol.setdefault(hit.symbol, []).append(hit)

    rows: list[dict[str, Any]] = []
    for symbol in CASE_STUDY_SYMBOLS:
        metadata = CASE_STUDY_METADATA[symbol]
        contract_hint = contract_hints.get(symbol)
        symbol_hits = by_symbol.get(symbol, [])
        best = _best_hit(symbol_hits)
        declared_event_dt = _parse_event_date(metadata["event_date"])
        if best is None:
            empty_row = {
                "symbol": symbol,
                "event_date": metadata["event_date"],
                "mechanism_hypothesis": metadata["mechanism_hypothesis"],
                "local_snapshot_count": 0,
                "best_snapshot_file": "",
                "best_snapshot_time": "",
                "local_evidence_status": "missing local row",
                "observed_phase": "not observed locally",
                "contract_hint_status": "available" if contract_hint is not None else "missing",
                "contract_hint_chain": contract_hint.chain if contract_hint is not None else "",
                "contract_hint_address": contract_hint.contract_address if contract_hint is not None else "",
                "mechanism_read": metadata["mechanism_hypothesis"],
                "evidence_gaps": "no local snapshot row found",
            }
            empty_row.update(
                _price_path_metrics(symbol, declared_event_dt, kline_client)
                if declared_event_dt is not None
                else _infer_event_date_from_klines(symbol, kline_client)
            )
            empty_row["mechanism_verdict"] = _mechanism_verdict(symbol, empty_row)
            empty_row["scanner_lesson"] = _scanner_lesson(symbol, empty_row)
            empty_row["evidence_gap_severity"] = _gap_severity(empty_row)
            empty_row["next_data_action"] = _next_data_action(empty_row)
            rows.append(empty_row)
            continue
        source = best.row
        snapshot_dt = _parse_snapshot_date(_snapshot_time(best.source_path, source))
        event_dt = declared_event_dt or snapshot_dt
        output = {
            "symbol": symbol,
            "event_date": metadata["event_date"],
            "mechanism_hypothesis": metadata["mechanism_hypothesis"],
            "local_snapshot_count": len(symbol_hits),
            "best_snapshot_file": str(best.source_path).replace("\\", "/"),
            "best_snapshot_time": _snapshot_time(best.source_path, source),
            "local_evidence_status": "observed locally",
            "observed_phase": _phase(source),
            "contract_hint_status": "available" if contract_hint is not None else "missing",
            "contract_hint_chain": contract_hint.chain if contract_hint is not None else "",
            "contract_hint_address": contract_hint.contract_address if contract_hint is not None else "",
            "mechanism_read": _read_mechanism(source, metadata["mechanism_hypothesis"]),
            "evidence_gaps": _gaps(source, len(symbol_hits)),
        }
        output.update(
            _price_path_metrics(symbol, event_dt, kline_client)
            if event_dt is not None
            else _infer_event_date_from_klines(symbol, kline_client)
        )
        output["mechanism_verdict"] = _mechanism_verdict(symbol, output)
        output["scanner_lesson"] = _scanner_lesson(symbol, output)
        output["evidence_gap_severity"] = _gap_severity(output)
        output["next_data_action"] = _next_data_action(output)
        for column in EVENT_STUDY_COLUMNS:
            if column in output:
                continue
            if column == "short_account_pct":
                output[column] = _short_account_pct(source)
                continue
            value = source.get(column)
            if column.startswith("broke_high_"):
                output[column] = _safe_bool(value)
            else:
                parsed = _safe_float(value)
                output[column] = parsed if math.isfinite(parsed) else value
        rows.append(output)
    return pd.DataFrame(rows, columns=EVENT_STUDY_COLUMNS)


def write_case_study_event_files(
    *,
    root: Path | str = ".",
    docs_path: Path | None = None,
    csv_path: Path | None = None,
    fetch_price_path: bool = False,
    kline_client: KlineClient | None = None,
) -> pd.DataFrame:
    root_path = Path(root)
    client = kline_client
    if fetch_price_path and client is None:
        client = BinanceFuturesPublic(requests_per_second=2.0, retries=2)
    frame = build_case_study_event_frame(root=root_path, kline_client=client)
    if csv_path is None:
        csv_path = root_path / "data" / "case_study_event_summary.csv"
    if docs_path is None:
        docs_path = root_path / "docs" / "case-study-event-summary.md"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False)

    visible = frame[
        [
            "symbol",
            "event_date",
            "mechanism_hypothesis",
            "local_snapshot_count",
            "best_snapshot_file",
            "observed_phase",
            "contract_hint_status",
            "contract_hint_chain",
            "contract_hint_address",
            "price_path_status",
            "price_event_date",
            "price_event_date_source",
            "event_day_return_pct",
            "event_break_prior_20d_high",
            "post_7d_high_return_pct",
            "post_7d_low_drawdown_pct",
            "mechanism_read",
            "mechanism_verdict",
            "scanner_lesson",
            "evidence_gap_severity",
            "next_data_action",
            "evidence_gaps",
        ]
    ].copy()
    for column in visible.columns:
        visible[column] = visible[column].map(lambda value: str(value).replace("|", ";") if pd.notna(value) else value)
    docs_path.write_text(
        "# Case-Study Event Summary\n\n"
        "Generated from local scanner/export snapshots. Missing rows mean the repo currently lacks a local snapshot for that named example, not that the market structure did not occur.\n\n"
        + visible.to_markdown(index=False)
        + "\n",
        encoding="utf-8",
    )
    return frame


def build_backfill_checklist(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["priority", "next_data_action", "symbols", "count", "why"])
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    working = frame.copy()
    working["evidence_gap_severity"] = working.get("evidence_gap_severity", pd.Series("", index=working.index)).fillna("").astype(str)
    working["next_data_action"] = working.get("next_data_action", pd.Series("", index=working.index)).fillna("").astype(str)
    working = working[working["next_data_action"].str.strip() != ""].copy()
    if working.empty:
        return pd.DataFrame(columns=["priority", "next_data_action", "symbols", "count", "why"])

    rows: list[dict[str, Any]] = []
    for action, group in working.groupby("next_data_action", sort=False):
        severities = group["evidence_gap_severity"].map(lambda value: severity_rank.get(str(value), 9))
        top_rank = int(severities.min()) if not severities.empty else 9
        priority = next((label for label, rank in severity_rank.items() if rank == top_rank), "unknown")
        symbols = ", ".join(group["symbol"].astype(str).tolist())
        gaps = "; ".join(sorted(set(group.get("evidence_gaps", pd.Series("", index=group.index)).fillna("").astype(str))))
        rows.append(
            {
                "priority": priority,
                "next_data_action": action,
                "symbols": symbols,
                "count": int(len(group)),
                "why": gaps,
            }
        )
    output = pd.DataFrame(rows)
    output["_rank"] = output["priority"].map(lambda value: severity_rank.get(str(value), 9))
    return output.sort_values(["_rank", "count", "next_data_action"], ascending=[True, False, True]).drop(columns=["_rank"]).reset_index(drop=True)


def write_backfill_checklist(*, frame: pd.DataFrame, docs_path: Path) -> pd.DataFrame:
    checklist = build_backfill_checklist(frame)
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(
        "# Case-Study Evidence Backfill Checklist\n\n"
        "Generated from `case_study_event_summary.csv`. Work top-to-bottom: critical/high rows block stronger conclusions about the mechanism.\n\n"
        + checklist.to_markdown(index=False)
        + "\n",
        encoding="utf-8",
    )
    return checklist


if __name__ == "__main__":
    generated = write_case_study_event_files(fetch_price_path=True)
    write_backfill_checklist(frame=generated, docs_path=Path("docs") / "case-study-backfill-checklist.md")
