"""On-chain token concentration scanner backend.

The package keeps data fetching, chain adapters, holder classification,
concentration math, risk scoring, queueing, and cache persistence outside the
Streamlit UI. Generated language is deliberately framed as structural risk,
not as legal or criminal conclusions.
"""

from .cache import ScanCache
from .chains import ChainAdapter, ChainRegistry
from .classifier import HolderClassifier, ManualOverride
from .concentration import ConcentrationEngine
from .models import (
    ClassifiedHolder,
    ContractControlStats,
    HolderRecord,
    ManipulableWhaleMetrics,
    MasterSqueezeScore,
    PerpMarketContext,
    TokenMarketData,
    TokenScanResult,
    WalletCluster,
    WalletForensics,
)
from .risk import RiskScoringEngine
from .scanner import ScannerInput, TokenConcentrationScanner

__all__ = [
    "ChainAdapter",
    "ChainRegistry",
    "ClassifiedHolder",
    "ConcentrationEngine",
    "ContractControlStats",
    "HolderClassifier",
    "HolderRecord",
    "ManualOverride",
    "ManipulableWhaleMetrics",
    "MasterSqueezeScore",
    "PerpMarketContext",
    "RiskScoringEngine",
    "ScanCache",
    "ScannerInput",
    "TokenConcentrationScanner",
    "TokenMarketData",
    "TokenScanResult",
    "WalletCluster",
    "WalletForensics",
]
