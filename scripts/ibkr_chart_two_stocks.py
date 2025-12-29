import pandas as pd

from quant_sandbox.config.settings import IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID
from quant_sandbox.data.ibkr import connect_ibkr, get_stock_intraday_1min
from quant_sandbox.charts.line import plot_normalized_intraday

def main():
    symbols = ["AAPL", "MSFT"]

    ib = connect_ibkr(IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID)
    try:
        series = {}
        for sym in symbols:
            df = get_stock_intraday_1min(ib, sym)
            if df.empty:
                print(f"[WARN] No data returned for {sym}. Check IBKR market data permissions.")
                continue
            series[sym] = df["close"]

        prices = pd.DataFrame(series)

        if prices.shape[1] < 2:
            print("[ERROR] Not enough instruments with data to chart. Exiting.")
            return

        plot_normalized_intraday(prices, "IBKR Intraday 1-min (RTH) — Normalized Performance")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    main()

