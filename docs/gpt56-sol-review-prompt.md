# Prompt for GPT-5.6 Sol

I am attaching `short-squeeze-low-float-strategy.md`, which describes a research system for finding early low-float perpetual short-squeeze structures. Treat it as a serious but unproven market-structure hypothesis, not as a request for encouragement or personalized financial advice.

Please act as a skeptical quantitative market-microstructure researcher and crypto derivatives risk reviewer. Read the entire document, then do all of the following:

1. Restate the strategy's causal model in your own words and identify every step where it relies on an assumption rather than a directly observed fact.
2. Separate the signals into: structural filters, entry/timing signals, continuation signals, exit signals, and operational/data-quality checks.
3. Critique the key claims about concentrated ownership, effective float, CEX deposits, market-maker inventory, Binance/Bitget/Gate venue selection, short-account ratios, OI, funding, breakouts, and forced-cover mechanics. Be precise about what each signal can and cannot establish.
4. Identify confounders and false-positive mechanisms for every major feature. In particular, explain why account-count long/short ratios can diverge from notional exposure, why a CEX deposit can be either bullish or bearish, and why OI/funding are not directionally self-explanatory.
5. Propose the strongest possible point-in-time backtest and walk-forward validation design. Include universe construction, delisted/listed-symbol bias, data timestamps, feature availability, missing-data handling, label definitions, baselines, transaction costs, funding, slippage, liquidity limits, multiple-hypothesis control, and out-of-sample criteria.
6. Recommend a feature set and model/ranking architecture that is interpretable and robust. Explain which features should be hard gates, soft scores, or merely annotations. Avoid black-box complexity unless it genuinely improves the research design.
7. Design a rigorous way to test whether the combined signal stack has incremental value beyond simple momentum, volatility, token age, and liquidity.
8. Analyze the current exit concept: closing/reducing a profitable long when one-hour short-account percentage drops by more than 2.5% relative. Discuss whether the additional 1 percentage-point fallback is sensible, how to avoid noisy one-sample exits, and propose alternative or complementary exits that can survive the large intratrend drawdowns characteristic of these assets.
9. Identify the highest-risk automation failures for an exchange-connected close monitor and provide a production safety checklist. Do not suggest placing orders; focus on validation, kill switches, logging, reconciliation, and simulation.
10. Recommend the three highest-leverage additions to the dashboard/Discord workflow that would improve early detection or reduce false positives.
11. Give a prioritized build plan with: immediate fixes, data acquisitions, backtests, paper-trading checks, and only then limited live-risk validation.
12. End with a concise verdict: which parts of the thesis are plausible, which are currently unsupported, what evidence would change your mind, and what would make the strategy untradeable even if the narrative is correct.

Constraints for your response:

- Do not assume manipulation or illegal conduct from concentration, CEX flows, or price behavior alone.
- Do not give personalized buy/sell/position-size advice.
- Prefer falsifiable statements, explicit caveats, equations/definitions where helpful, and a concrete experimental plan.
- Be direct. I want the strongest critique, not a flattering summary.
