# crypto_market_structure_scanner

Research and monitoring framework for identifying structurally unusual crypto assets using market microstructure, liquidity, and on-chain concentration analysis.

## Overview

The project combines:

- Binance perpetual market screening
- on-chain holder concentration analytics
- float and liquidity analysis
- Discord monitoring infrastructure
- Streamlit dashboards
- contract-resolution tooling
- persistent scan storage and ranking

The repository is designed for research, monitoring, and signal-discovery workflows.

## Core Features

### Market Structure Scanner

Evaluates Binance perpetual markets using structural and liquidity-based metrics, including:

- relative volume expansion
- open-interest acceleration
- volatility compression and expansion
- float-adjusted participation
- futures-versus-spot activity
- liquidity asymmetry
- concentration-adjusted turnover
- structural squeeze conditions

Results are surfaced through an interactive Streamlit dashboard and can be distributed through Discord integrations.

### On-Chain Concentration Analytics

Includes a concentration-analysis engine for evaluating token distribution quality and tradable-float characteristics across ERC-20 and BEP-20 assets.

Supported analysis includes:

- top-holder concentration
- linked-wallet clustering
- adjusted float estimation
- concentration scoring
- liquidity and custody filtering
- thin-float detection
- structural-risk ranking

The scanner stores outputs locally in:

```text
data/concentration_scanner.sqlite
