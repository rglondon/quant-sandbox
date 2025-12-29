import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from quant_sandbox.config.settings import IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID
from quant_sandbox.data.ibkr import connect_ibkr, get_bars
from quant_sandbox.data.contracts import make_contract
from quant_sandbox.charts.line import plot_multi_axis

EU_FMT = "%d/%m/%Y"


def parse_eu_date(s: str) -> datetime:
    return datetime.strptime(s, EU_FMT)


@dataclass
class Window:
    duration: str


def month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def year_start(dt: datetime) -> datetime:
    return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def resolve_window(tf: str, date_from: Optional[str], date_to: Optional[str]) -> Window:
    if date_from and date_to:
        start = parse_eu_date(date_from)
        end = parse_eu_date(date_to)
        days = max(1, (end - start).days)
        if days <= 365:
            return Window(duration=f"{days} D")
        years = max(1, int(round(days / 365)))
        return Window(duration=f"{years} Y")

    if date_from and not date_to:
        start = parse_eu_date(date_from)
        end = datetime.now()
        days = max(1, (end - start).days)
        if days <= 365:
            return Window(duration=f"{days} D")
        years = max(1, int(round(days / 365)))
        return Window(duration=f"{years} Y")

    now = datetime.now()
    key = tf.strip().upper()

    if key == "INTRADAY":
        return Window(duration="1 D")
    if key == "MTD":
        days = max(1, (now - month_start(now)).days)
        return Window(duration=f"{days} D")
    if key == "YTD":
        days = max(1, (now - year_start(now)).days)
        return Window(duration=f"{days} D")

    allowed = {
        "1M": "1 M",
        "3M": "3 M",
        "6M": "6 M",
        "1Y": "1 Y",
        "3Y": "3 Y",
        "5Y": "5 Y",
        "10Y": "10 Y",
    }
    if key in allowed:
        return Window(duration=allowed[key])

    if len(key) >= 2 and key[:-1].isdigit() and key[-1] in ("D", "W", "M", "Y"):
        n = int(key[:-1])
        unit = key[-1]
        return Window(duration=f"{n} {unit}")

    raise ValueError(
        f"Unknown --tf '{tf}'. Use INTRADAY, MTD, YTD, 1m/3m/6m/1y/3y/5y/10y, or 10D/4W/2M/1Y. "
        f"Or use --from DD/MM/YYYY [--to DD/MM/YYYY]."
    )


def normalize_series(s: pd.Series) -> pd.Series:
    s = s.dropna()
    if s.empty:
        return s
    return 100.0 * (s / s.iloc[0])


def infer_what_to_show(instr_spec: str, midpoint_flag: bool) -> str:
    if midpoint_flag:
        return "MIDPOINT"
    if instr_spec.lower().startswith("fx:"):
        return "MIDPOINT"
    return "TRADES"


def build_arg_parser():
    p = argparse.ArgumentParser()

    p.add_argument("--left", action="append", default=[], help="Repeatable. e.g. stock:AAPL or index:DAX:EUREX")
    p.add_argument("--right", action="append", default=[], help="Repeatable. e.g. fx:EURUSD")

    p.add_argument("--tf", default="MTD", help="INTRADAY, MTD, YTD, 1m/3m/6m/1y/3y/5y/10y, or 10D/4W/2M/1Y")
    p.add_argument("--from", dest="date_from", default=None, help="EU date DD/MM/YYYY")
    p.add_argument("--to", dest="date_to", default=None, help="EU date DD/MM/YYYY")

    p.add_argument("--bar", default="daily", help="Bar size: '1 min', '5 mins', '1 hour', 'daily', 'weekly', 'monthly'")
    p.add_argument("--rth", action="store_true", help="Use Regular Trading Hours (stocks).")
    p.add_argument("--normalize", action="store_true", help="Normalize each series to start at 100.")
    p.add_argument("--invert-left", action="store_true")
    p.add_argument("--invert-right", action="store_true")

    p.add_argument("--midpoint", action="store_true", help="Force MIDPOINT for all instruments.")
    p.add_argument("--title", default=None)

    return p


def main():
    args = build_arg_parser().parse_args()

    if not args.left and not args.right:
        raise SystemExit("Provide at least one --left or --right instrument spec.")

    window = resolve_window(args.tf, args.date_from, args.date_to)

    bar_map = {"daily": "1 day", "weekly": "1 week", "monthly": "1 month"}
    bar_size = bar_map.get(args.bar.lower(), args.bar)

    ib = connect_ibkr(IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID)
    try:
        left_series = {}
        right_series = {}

        def fetch(spec: str):
            contract = make_contract(spec)
            what = infer_what_to_show(spec, args.midpoint)

            df = get_bars(
                ib=ib,
                contract=contract,
                duration=window.duration,
                bar_size=bar_size,
                what_to_show=what,
                use_rth=bool(args.rth),
                end_datetime="",
            )

            if df is None or df.empty:
                print(f"[WARN] No data for {spec} (whatToShow={what}, duration={window.duration}, bar={bar_size})")
                return None

            s = df["close"].dropna()
            if s.empty:
                print(f"[WARN] Empty close series for {spec}")
                return None

            return normalize_series(s) if args.normalize else s

        for spec in args.left:
            s = fetch(spec)
            if s is not None:
                left_series[spec] = s

        for spec in args.right:
            s = fetch(spec)
            if s is not None:
                right_series[spec] = s

        if not left_series and not right_series:
            raise SystemExit("No series returned. Check market data permissions and instrument specs.")

        title = args.title or f"Chart | tf={args.tf} bar={args.bar} duration={window.duration}"
        plot_multi_axis(
            series_left=left_series,
            series_right=right_series if right_series else None,
            title=title,
            invert_left=args.invert_left,
            invert_right=args.invert_right,
        )

    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
