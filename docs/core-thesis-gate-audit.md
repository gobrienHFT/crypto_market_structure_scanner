# Core Thesis Gate Audit

This project is intentionally narrow: it tries to flag low-float, concentrated-holder market structures before a large pump, not after the move is already obvious. The live candidate path should only promote rows that satisfy the hard thesis gates below. Looser boards are diagnostics and must label themselves as such.

## Operator Path

Start in Discord with `/hunt` or `/thesis`. These are the clean hard-gated queues. If they are empty, use `/gates` to see which hard gate is blocking the current scan. Use `/coincheck` or `/dossier` for one-symbol evidence, `/flowproof` for transfer proof, and `/ravelab detail:true` only when row-level blocker evidence or RAVE/LAB analogue details are needed.

The older `/ravelab` surface is no longer the primary workflow. It remains a microscope for near misses, style filters, full evidence, and historical analogue language.

## Hard Gates

| Requirement | Enforcement | Evidence / tests |
| --- | --- | --- |
| Extreme centralized ownership, top10 >= 90% | `venue_gate.holder_concentration_mask`, `discord_convex_bot._strict_top10_thesis_holder_gate_mask`, and `discord_convex_bot._goal_score_frame` all hard-floor the requested threshold at 90%. Top100 concentration is context only. | `tests/test_venue_gate.py::test_thesis_alert_gate_requires_holder_evidence_and_binance_bitget`, `tests/test_discord_convex_bot.py::test_ravelab_whale_gate_requires_top10_control_not_top100_only` |
| Explorer-backed holder evidence on ETH/BNB/ARB | Holder gates require chain, contract, explorer holder-source text, and a holder snapshot. GoPlus-only, pct-only, missing contract, unsupported chain, and source-less rows fail candidate gates. | `tests/test_venue_gate.py::test_thesis_alert_gate_requires_holder_evidence_and_binance_bitget`, `tests/test_discord_convex_bot.py::test_strict_holder_evidence_requires_holder_source` |
| Custody/storage false positives filtered | When adjusted/manipulable holder metrics exist, exchange, bridge, treasury, vesting, wrapper, LP, burn, and protocol-storage concentration cannot pass as insider-controlled float. | `venue_gate.holder_storage_false_positive_mask`, `tests/test_venue_gate.py::test_thesis_alert_gate_rejects_storage_false_positive_when_filtered_top10_available`, `tests/test_discord_convex_bot.py::test_ravelab_holder_gate_uses_filtered_manipulable_top10` |
| Binance plus Bitget trading evidence | `venue_gate.binance_bitget_venue_mask` and Discord's explicit venue gate require Binance perp/share/top-venue evidence and Bitget trading evidence. Gate.io is optional/supporting only and transfer targets do not substitute for Bitget. | `tests/test_venue_gate.py::test_binance_bitget_venue_gate_rejects_gate_only_rows`, `tests/test_discord_convex_bot.py::test_ravelab_requires_explicit_binance_trading_evidence` |
| No large pump for roughly two months | `venue_gate.no_recent_pump_proof_mask` and `discord_convex_bot._no_recent_pump_proof_mask` require 60D pump-history coverage and either a clean numeric recent-pump read or a clean no-large-pump flag. Missing history fails closed. | `tests/test_venue_gate.py::test_thesis_alert_gate_requires_60d_no_pump_proof`, `tests/test_discord_convex_bot.py::test_ravelab_dormant_gate_allows_slow_high_break_without_large_pump` |
| Primed for squeeze, not just high short percentage | Core gates require short crowd plus squeeze fuel from build, OI, liquidation, funding-flip, forced-buying, or perp confluence signals. `/shorts` is labelled weak context only. | `scan_orchestrator.apply_core_setup_gate`, `discord_convex_bot._goal_score_frame`, `tests/test_discord_convex_bot.py::test_ravelab_squeeze_gate_requires_fuel_not_short_pct_alone` |
| Low-float / high-FDV reflexivity | Core setup requires low-float, float-trap, hidden-float, FDV/MC gap, locked supply, or related float evidence before a row can become a core candidate. | `scan_orchestrator.apply_core_setup_gate`, `discord_convex_bot._goal_score_frame`, `tests/test_discord_convex_bot.py::test_ravelab_core_gate_requires_float_fdv_evidence` |
| Early / no-chase structure | Core setup requires dormant/not-late structure and rejects late heat, large recent expansion, or exhaustion. | `terminal_engine.py`, `timing_engine.py`, `discord_convex_bot._goal_score_frame`, `tests/test_discord_convex_bot.py::test_ravelab_exhaustion_blocks_core_prime` |
| Breakout highs/lows after hard gates | `/high` and `/low` support arbitrary 1D-1499D windows. Their default `thesis_only:true` mode applies the full core gate before showing breakout rows. | `discord_convex_bot._load_breakout_list`, `tests/test_discord_convex_bot.py::test_load_breakout_list_computes_arbitrary_high_window`, `tests/test_discord_convex_bot.py::test_load_breakout_list_computes_arbitrary_low_window` |
| Massive whale/top-holder CEX transfers | CEX-flow rows are verified only with labelled destinations. The whale-CEX lane separately requires a scanned top-holder sender and its own token floor; the massive lane defaults to 10M tokens. | `cex_flow_scanner.py`, `discord_convex_bot._ravelab_apply_thesis_columns`, `tests/test_cex_flow_scanner.py`, `tests/test_discord_convex_bot.py::test_ravelab_massive_whale_flow_is_separate_trigger_lane` |

## Candidate Surfaces

The following surfaces are expected to apply the hard gate before promoting rows as candidates:

- Discord primary queues: `/hunt`, `/thesis`, `/radar`, `/prime`, `/crimepump`
- Legacy Discord candidate sample: `/convex`
- Discord strict brief: `/alpha`
- Discord breakout screens with default `thesis_only:true`: `/high`, `/low`
- Dashboard Convex Long cache and webhook alerts
- Background Discord watcher alerts
- Trade setup bot selection

The following surfaces are diagnostic and must not be read as candidate queues by themselves:

- `/shorts`, `/funding`, `/whales`, `/floattrap`, `/squeezeready`, `/cextargets`
- `/cexflow`, `/cexdiag`, `/earlyflow`, `/flowhealth`, `/flowblocked`, `/flowstress`
- Dashboard raw radar/watch tables outside the hard-gated Convex Long path

## Data-Coverage Failure Modes

The right response to an empty queue is usually not to weaken the gates. Use `/gates` first. Common blockers are:

- Missing ETH/BNB/ARB contract hints or explorer holder snapshots
- Missing Bitget venue evidence even when Binance or Gate is present
- Missing 60D pump-history proof
- Short crowd present without OI/liquidation/funding/build fuel
- Float/FDV evidence missing or storage-dominated holder concentration
- CEX-flow explorer/API blocked, unlabelled destination addresses, or no top-holder sender match

When CEX-flow is blocked by explorer coverage, use `/cexdiag`, `/flowhealth`, and `/flowblocked`. Rows with blocked transfer lookups are inconclusive, not clean tape.
