from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import (
    ClassifiedHolder,
    ConcentrationMetrics,
    ContractControlStats,
    ManipulableWhaleMetrics,
    RepresentationStats,
    RiskFlags,
    RiskScores,
    ScannerStatus,
    ThinFloatStats,
    TokenMarketData,
    TokenScanResult,
    WalletCluster,
    WalletForensics,
    utc_now_iso,
)


class ScanCache:
    def __init__(self, path: str | Path = "concentration_scanner_cache.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_scan_results (
                    cache_key TEXT PRIMARY KEY,
                    coin_id TEXT,
                    token_name TEXT,
                    symbol TEXT,
                    chain TEXT,
                    contract_address TEXT,
                    risk_label TEXT,
                    risk_score REAL,
                    ravedao_score REAL,
                    scanner_status TEXT,
                    updated_at TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scanner_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def key(chain: str, contract_address: str, coin_id: str = "") -> str:
        if contract_address:
            return f"{chain.lower()}:{contract_address.lower()}"
        return f"coingecko:{coin_id.lower()}"

    def upsert_result(self, result: TokenScanResult) -> None:
        cache_key = self.key(result.chain, result.contract_address, result.token.coin_id)
        payload = json.dumps(result.to_dict(), sort_keys=True)
        updated = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO token_scan_results (
                    cache_key, coin_id, token_name, symbol, chain, contract_address, risk_label,
                    risk_score, ravedao_score, scanner_status, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    coin_id=excluded.coin_id,
                    token_name=excluded.token_name,
                    symbol=excluded.symbol,
                    chain=excluded.chain,
                    contract_address=excluded.contract_address,
                    risk_label=excluded.risk_label,
                    risk_score=excluded.risk_score,
                    ravedao_score=excluded.ravedao_score,
                    scanner_status=excluded.scanner_status,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    cache_key,
                    result.token.coin_id,
                    result.token.name,
                    result.token.symbol,
                    result.chain,
                    result.contract_address,
                    result.scores.risk_label,
                    result.scores.composite_structural_manipulation_risk_score,
                    result.scores.ravedao_archetype_score,
                    result.status.scanner_status,
                    updated,
                    payload,
                ),
            )

    def list_rows(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT cache_key, coin_id, token_name, symbol, chain, contract_address, risk_label,
                       risk_score, ravedao_score, scanner_status, updated_at, payload_json
                FROM token_scan_results
                ORDER BY risk_score DESC, ravedao_score DESC, updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def load_result(self, cache_key: str) -> TokenScanResult:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT payload_json FROM token_scan_results WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            raise KeyError(f"No cached concentration scan found for {cache_key}")
        payload = json.loads(row["payload_json"])
        return TokenScanResult(
            token=TokenMarketData(**payload.get("token", {})),
            chain=payload.get("chain", ""),
            contract_address=payload.get("contract_address", ""),
            holders=[ClassifiedHolder(**holder) for holder in payload.get("holders", [])],
            concentration=ConcentrationMetrics(**payload.get("concentration", {})),
            contract_control=ContractControlStats(**payload.get("contract_control", {})),
            representation=RepresentationStats(**payload.get("representation", {})),
            manipulable=ManipulableWhaleMetrics(**payload.get("manipulable", {})),
            wallet_forensics=[WalletForensics(**item) for item in payload.get("wallet_forensics", [])],
            wallet_clusters=[WalletCluster(**item) for item in payload.get("wallet_clusters", [])],
            thin_float=ThinFloatStats(**payload.get("thin_float", {})),
            scores=RiskScores(**payload.get("scores", {})),
            flags=RiskFlags(**payload.get("flags", {})),
            status=ScannerStatus(**payload.get("status", {})),
            summary=payload.get("summary", ""),
            key_flags=list(payload.get("key_flags", [])),
        )

    def enqueue(self, mode: str, payload: dict[str, Any]) -> int:
        now = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO scanner_queue (mode, payload_json, status, created_at, updated_at)
                VALUES (?, ?, 'queued', ?, ?)
                """,
                (mode, json.dumps(payload, sort_keys=True), now, now),
            )
            return int(cursor.lastrowid)

    def queue_rows(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM scanner_queue ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]
