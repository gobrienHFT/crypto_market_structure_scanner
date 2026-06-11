import unittest

from binance_futures import FuturesSymbol
from breakout_monitor import (
    BREAKOUT_WINDOWS,
    active_signal_keys,
    alert_rows_for_signal_keys,
    build_discord_payload,
    build_monitor_row,
    flagged_frame,
)


def _kline(open_time: int, high: float, low: float, close: float) -> list[object]:
    return [
        open_time,
        str(close),
        str(high),
        str(low),
        str(close),
        "0",
        open_time + 86_399_999,
        "0",
        0,
        "0",
        "0",
        "0",
    ]


def _symbol() -> FuturesSymbol:
    return FuturesSymbol(symbol="TESTUSDT", base_asset="TEST", quote_asset="USDT", underlying_type="COIN")


class BreakoutMonitorTests(unittest.TestCase):
    def test_breakout_row_flags_all_requested_high_windows(self) -> None:
        klines = [_kline(i, high=100 + (i * 0.01), low=80 - (i * 0.001), close=90) for i in range(1300)]
        klines.append(_kline(1300, high=150, low=70, close=140))

        row = build_monitor_row(
            futures_symbol=_symbol(),
            klines=klines,
            ticker={"lastPrice": "140", "quoteVolume": "12345"},
        )

        for window in BREAKOUT_WINDOWS:
            self.assertIs(row[f"broke_high_{window}d"], True)
            self.assertIs(row[f"broke_low_{window}d"], False)

        self.assertEqual(row["history_days"], 1300)
        self.assertIn("1300D high breakout", row["flags"])

    def test_ma200_cross_above_uses_prior_closed_state(self) -> None:
        klines = [_kline(i, high=101, low=98, close=100) for i in range(199)]
        klines.append(_kline(199, high=101, low=98, close=99))
        klines.append(_kline(200, high=105, low=98, close=102))

        row = build_monitor_row(
            futures_symbol=_symbol(),
            klines=klines,
            ticker={"lastPrice": "102", "quoteVolume": "1000"},
        )

        self.assertIs(row["price_above_200d_ma"], True)
        self.assertIs(row["price_below_200d_ma"], False)
        self.assertIs(row["ma200_cross_above"], True)
        self.assertIs(row["ma200_cross_below"], False)

    def test_active_signal_keys_and_flagged_frame_only_include_true_alerts(self) -> None:
        klines = [_kline(i, high=100, low=80, close=90) for i in range(1300)]
        klines.append(_kline(1300, high=105, low=75, close=101))
        row = build_monitor_row(
            futures_symbol=_symbol(),
            klines=klines,
            ticker={"lastPrice": "101", "quoteVolume": "1000"},
        )

        import pandas as pd

        frame = pd.DataFrame([row])
        keys = active_signal_keys(frame)

        self.assertIn("TESTUSDT:broke_high_5d", keys)
        self.assertNotIn("TESTUSDT:price_above_200d_ma", keys)
        self.assertEqual(len(flagged_frame(frame)), 1)

    def test_signal_rows_build_discord_payload(self) -> None:
        klines = [_kline(i, high=100, low=80, close=90) for i in range(1300)]
        klines.append(_kline(1300, high=105, low=75, close=101))
        row = build_monitor_row(
            futures_symbol=_symbol(),
            klines=klines,
            ticker={"lastPrice": "101", "quoteVolume": "2500000"},
        )

        import pandas as pd

        frame = pd.DataFrame([row])
        alert_rows = alert_rows_for_signal_keys(frame, {"TESTUSDT:broke_high_20d"})
        payload = build_discord_payload(alert_rows, flagged_count=7)
        description = payload["embeds"][0]["description"]

        self.assertIn("New alert symbols: 1 | Active flagged snapshot: 7", description)
        self.assertIn("state-diff alerts only", description)
        self.assertIn("/TESTUSDT", description)
        self.assertIn("20D high breakout", description)
        self.assertIn("vol24 $2.50M", description)


if __name__ == "__main__":
    unittest.main()
