#!/usr/bin/env python3
"""
Quant Sandbox – local endpoint test runner + plotter (cases.json driven)

- Define test cases in tools/cases.json
- Runs cases, saves JSON outputs to ./out/<case>.json
- Plotting + saving plots (defaults ON):
  - series/points -> line plot
  - tables.matrix + tables.monthly_summary -> table heatmap with summary rows

Usage:
  python3 tools/qs_run.py list
  python3 tools/qs_run.py run all
  python3 tools/qs_run.py run compare_spy_2007_vs_2025
  python3 tools/qs_run.py run seasonality_heatmap_spy_month_since_2010
  python3 tools/qs_run.py run seasonality_heatmap_spy_month_since_2010 --no-plot
  python3 tools/qs_run.py run seasonality_heatmap_spy_month_since_2010 --no-save-plot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8010"
HERE = os.path.dirname(__file__)
CASES_PATH = os.path.join(HERE, "cases.json")
OUT_DIR = os.path.join(HERE, "..", "out")


# ----------------------------
# Utilities
# ----------------------------

def ensure_out_dir() -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    return OUT_DIR


def iso_to_dt(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1])
        raise


def save_json(case_name: str, data: Any) -> str:
    ensure_out_dir()
    path = os.path.join(OUT_DIR, f"{case_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return path


def pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)


def extract_plot_series(resp_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Standard: {"series":[{label, points}, ...]}
    if isinstance(resp_json, dict) and "series" in resp_json and isinstance(resp_json["series"], list):
        out = []
        for s in resp_json["series"]:
            if isinstance(s, dict) and "points" in s and isinstance(s["points"], list):
                out.append(s)
        return out

    # Single: {"points":[...], "label":"..."}
    if isinstance(resp_json, dict) and "points" in resp_json and isinstance(resp_json["points"], list):
        return [{"label": resp_json.get("label", "series"), "points": resp_json["points"]}]

    return []


def basic_sanity_checks(resp_json: Dict[str, Any], expect: Dict[str, Any]) -> List[str]:
    problems: List[str] = []

    req_keys = expect.get("required_keys", [])
    for k in req_keys:
        if k not in resp_json:
            problems.append(f"Missing required key: {k}")

    if expect.get("require_non_empty_series", False):
        series = extract_plot_series(resp_json)
        if not series:
            problems.append("Expected series/points in response but found none.")
        else:
            total_points = sum(len(s.get("points", [])) for s in series)
            if total_points == 0:
                problems.append("Series present but has zero total points.")

    return problems


# ----------------------------
# Plotting helpers
# ----------------------------

def _savefig(fig, path: str):
    ensure_out_dir()
    fig.savefig(path, dpi=150)
    print(f"[plot] saved png: {path}")


def plot_line_response(case_name: str, resp_json: Dict[str, Any], save_png_path: Optional[str], show: bool) -> None:
    import matplotlib.pyplot as plt

    series = extract_plot_series(resp_json)
    if not series:
        print(f"[plot] {case_name}: no plottable series found (needs 'series' or 'points').")
        return

    meta = resp_json.get("meta", {}) if isinstance(resp_json, dict) else {}
    use_day_index = isinstance(meta, dict) and meta.get("x_axis") == "synthetic_days"

    fig = plt.figure()

    max_len = 0
    for s in series:
        pts = s.get("points", [])
        if not pts:
            continue

        ys = [p["value"] for p in pts]
        label = s.get("label", "series")
        max_len = max(max_len, len(ys))

        if use_day_index:
            xs = list(range(len(ys)))
            plt.plot(xs, ys, label=label)
        else:
            xs = [iso_to_dt(p["time"]) for p in pts]
            plt.plot(xs, ys, label=label)

    plt.title(case_name)
    plt.legend()
    plt.tight_layout()

    if use_day_index and max_len > 0:
        plt.xlim(0, max_len - 1)
        plt.xlabel("Day index")

    if save_png_path:
        _savefig(fig, save_png_path)

    if show:
        plt.show()
    else:
        plt.close(fig)


def has_heatmap_tables(resp_json: Dict[str, Any]) -> bool:
    """
    Detect our seasonality monthly heatmap response.
    We expect:
      tables.matrix: list[{"year":..., "m01":..., ... "m12":...}]
      tables.monthly_summary: list[{period:1..12, mean, median, min, max, hit_rate, stdev, ...}]
    """
    if not isinstance(resp_json, dict):
        return False
    tables = resp_json.get("tables")
    if not isinstance(tables, dict):
        return False
    return isinstance(tables.get("matrix"), list) and isinstance(tables.get("monthly_summary"), list)


def plot_heatmap_table(
    case_name: str,
    resp_json: Dict[str, Any],
    save_png_path: Optional[str],
    show: bool,
) -> None:
    """
    Render a "table heatmap" with summary stats rows at bottom:
      Mean / Median / Min / Max / Hit% / StdDev

    Fixes:
      - Title aligned to the left border of the table (not axes gutter)
      - 0.0 maps to WHITE (no yellow midpoint)
      - Softer pastel hues
      - Subtitle line (Returns in %, YYYY–YYYY)
      - Bold header + row labels
      - Spacer row above Mean (quarter height)
      - Heatmap applies to summary rows too (with separate scaling for Hit% + StdDev)
    """
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    # ----------------------------
    # Load data
    # ----------------------------
    tables = resp_json["tables"]
    matrix_rows = tables["matrix"]
    monthly_summary = tables.get("monthly_summary", [])

    df = pd.DataFrame(matrix_rows).sort_values("year").set_index("year")
    month_cols = [f"m{m:02d}" for m in range(1, 13)]
    df = df[month_cols].astype("float64")

    ms = pd.DataFrame(monthly_summary).copy()
    if not ms.empty:
        ms = ms.sort_values("period")
        ms["col"] = ms["period"].apply(lambda p: f"m{int(p):02d}")
        ms = ms.set_index("col")

    # meta -> for title/subtitle
    meta = resp_json.get("meta", {}) if isinstance(resp_json, dict) else {}
    years = meta.get("years_filter") or []
    start_year = min(years) if years else None
    end_year = max(years) if years else None
    bucket = str(meta.get("bucket", "month")).lower()
    period_txt = "monthly" if bucket.startswith("month") else bucket

    expr = meta.get("expr") or resp_json.get("expr") or ""
    inst = str(expr) if expr else "Instrument"

    # ----------------------------
    # Helpers
    # ----------------------------
    def fmt(x):
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return ""
        return f"{x:.1f}"

    def fmt_hit(x):
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return ""
        return f"{100*x:.0f}%"

    # If monthly_summary missing, compute from df
    def get_stat(col: str, key: str):
        if not ms.empty and col in ms.index and key in ms.columns:
            return ms.loc[col, key]
        s = pd.Series(df[col].values).dropna()
        if s.empty:
            return np.nan
        if key == "mean":
            return float(s.mean())
        if key == "median":
            return float(s.median())
        if key == "min":
            return float(s.min())
        if key == "max":
            return float(s.max())
        if key == "hit_rate":
            return float((s > 0).mean())
        if key == "stdev":
            return float(s.std(ddof=1)) if len(s) >= 2 else 0.0
        return np.nan

    summary_specs = [
        ("Mean",   "mean",     "return"),
        ("Median", "median",   "return"),
        ("Min",    "min",      "return"),
        ("Max",    "max",      "return"),
        ("Hit%",   "hit_rate", "hit"),
        ("StdDev", "stdev",    "vol"),
    ]

    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    # ----------------------------
    # Build table text
    # ----------------------------
    row_labels = [str(y) for y in df.index.tolist()] + [""] + [name for name, _, _ in summary_specs]

    cell_text: list[list[str]] = []
    # year rows
    for y in df.index:
        row = []
        for c in month_cols:
            v = df.loc[y, c]
            row.append("" if (not np.isfinite(v)) else f"{v:.1f}")
        cell_text.append(row)

    # spacer row
    cell_text.append([""] * 12)

    # summary rows
    for _, key, kind in summary_specs:
        row = []
        for c in month_cols:
            val = get_stat(c, key)
            row.append(fmt_hit(val) if kind == "hit" else fmt(val))
        cell_text.append(row)

    # ----------------------------
    # Numeric matrix for coloring
    # ----------------------------
    n_years = df.shape[0]
    n_total = n_years + 1 + len(summary_specs)
    color_vals = np.full((n_total, 12), np.nan, dtype="float64")

    # year rows
    color_vals[:n_years, :] = df.values

    # summary rows numeric
    summary_start = n_years + 1
    for i, (_, key, _) in enumerate(summary_specs):
        r_ix = summary_start + i
        for j, c in enumerate(month_cols):
            val = get_stat(c, key)
            color_vals[r_ix, j] = float(val) if np.isfinite(val) else np.nan

    # ----------------------------
    # Colormaps (white at 0, no yellow)
    # ----------------------------
    def _soft_diverging_white_center(soften: float = 0.55) -> LinearSegmentedColormap:
        """
        Custom diverging cmap:
          red (neg) -> WHITE at 0 -> green (pos)
        Pastel via blending endpoints toward white.
        """
        # base endpoints (pastel-ish)
        red = np.array([0.90, 0.55, 0.55])    # soft red
        green = np.array([0.55, 0.80, 0.65])  # soft green
        white = np.array([1.00, 1.00, 1.00])

        # optional extra softening (push endpoints closer to white)
        red = red * (1 - soften) + white * soften
        green = green * (1 - soften) + white * soften

        colors = [
            (0.0,  (*red, 1.0)),
            (0.5,  (*white, 1.0)),
            (1.0,  (*green, 1.0)),
        ]
        return LinearSegmentedColormap.from_list("soft_red_white_green", colors)

    def _soft_blues(soften: float = 0.75) -> LinearSegmentedColormap:
        """Pastel blue scale for StdDev."""
        base = plt.cm.Blues(np.linspace(0, 1, 256))
        base[:, :3] = base[:, :3] * (1 - soften) + soften
        return LinearSegmentedColormap.from_list("soft_blues", base)

    cmap_ret = _soft_diverging_white_center(soften=0.30)  # keep some signal, but pastel
    cmap_hit = _soft_diverging_white_center(soften=0.45)
    cmap_vol = _soft_blues(soften=0.80)

    # ----------------------------
    # Scales
    # ----------------------------
    # return scale from year rows + Mean/Median/Min/Max
    ret_rows = np.concatenate([
        df.values.reshape(-1),
        color_vals[summary_start:summary_start+4, :].reshape(-1)
    ])
    ret_rows = ret_rows[np.isfinite(ret_rows)]
    vmax_ret = float(np.percentile(np.abs(ret_rows), 90)) if ret_rows.size else 5.0
    vmax_ret = max(vmax_ret, 1.0)
    vmin_ret = -vmax_ret

    # hit-rate scale centered at 0.5
    vmax_hit = 0.5

    # vol scale
    vol_row_ix = summary_start + 5
    vol_vals = color_vals[vol_row_ix, :]
    vol_vals = vol_vals[np.isfinite(vol_vals)]
    vmax_vol = float(np.percentile(vol_vals, 90)) if vol_vals.size else 5.0
    vmax_vol = max(vmax_vol, 0.1)
    vmin_vol = 0.0

    # ----------------------------
    # Build cell colours
    # ----------------------------
    cell_colours = []
    for i in range(n_total):
        row_colors = []
        for j in range(12):
            v = color_vals[i, j]

            # spacer row = white
            if i == n_years:
                row_colors.append((1, 1, 1, 1))
                continue

            if not np.isfinite(v):
                row_colors.append((1, 1, 1, 1))
                continue

            # Year rows => returns
            if i < n_years:
                t = (v - vmin_ret) / (vmax_ret - vmin_ret) if vmax_ret > vmin_ret else 0.5
                row_colors.append(cmap_ret(float(np.clip(t, 0, 1))))
                continue

            # Summary rows
            s_i = i - summary_start
            _, _, kind = summary_specs[s_i]

            if kind == "return":
                t = (v - vmin_ret) / (vmax_ret - vmin_ret) if vmax_ret > vmin_ret else 0.5
                row_colors.append(cmap_ret(float(np.clip(t, 0, 1))))
            elif kind == "hit":
                x = (v - 0.5) / vmax_hit   # -1..+1
                t = (x + 1.0) / 2.0        # 0..1
                row_colors.append(cmap_hit(float(np.clip(t, 0, 1))))
            elif kind == "vol":
                t = (v - vmin_vol) / (vmax_vol - vmin_vol) if vmax_vol > vmin_vol else 0.0
                row_colors.append(cmap_vol(float(np.clip(t, 0, 1))))
            else:
                row_colors.append((1, 1, 1, 1))

        cell_colours.append(row_colors)

    # ----------------------------
    # Draw figure + table
    # ----------------------------
    fig, ax = plt.subplots(figsize=(14, 0.45 * (len(row_labels) + 3)))
    ax.axis("off")

    table = ax.table(
        cellText=cell_text,
        rowLabels=row_labels,
        colLabels=month_labels,
        cellColours=cell_colours,
        loc="center",
    )

    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.2)

    # Spacer row shorter
    spacer_table_row = 1 + n_years  # +1 header
    for col in range(-1, 12):  # include row label col
        key = (spacer_table_row, col)
        if key in table._cells:
            cell = table._cells[key]
            cell.set_height(cell.get_height() * 0.25)
            cell.set_facecolor((1, 1, 1, 1))

    # Bold header row + row label column
    for (r, c), cell in table._cells.items():
        # header row is r=0 with col labels
        if r == 0:
            cell.get_text().set_fontweight("bold")
        # row label column is c=-1
        if c == -1:
            cell.get_text().set_fontweight("bold")

    # ----------------------------
    # Title placement aligned to table left border
    # ----------------------------
    # We need the table's bbox in Axes coords -> draw first, then read bbox.
    fig.canvas.draw()
    bbox = table.get_window_extent(fig.canvas.get_renderer())
    # convert bbox from display pixels -> axes coordinates
    inv = ax.transAxes.inverted()
    (x0, y0) = inv.transform((bbox.x0, bbox.y0))
    (x1, y1) = inv.transform((bbox.x1, bbox.y1))

    title = f"{inst} {period_txt} seasonality"
    subtitle = ""
    if start_year and end_year:
        subtitle = f"Returns in %, {start_year}–{end_year}"
    elif start_year:
        subtitle = f"Returns in %, since {start_year}"
    else:
        subtitle = "Returns in %"

    # Put them just above the table top edge (y1)
    title_y = min(0.98, y1 + 0.035)
    subtitle_y = min(0.98, y1 + 0.015)

    ax.text(
        x0, title_y, title,
        transform=ax.transAxes,
        ha="left", va="bottom",
        fontsize=14, fontweight="bold",
        color="#9a9a9a",
    )
    ax.text(
        x0, subtitle_y, subtitle,
        transform=ax.transAxes,
        ha="left", va="bottom",
        fontsize=10,
        color="#b0b0b0",
    )

    # Tight layout without pushing title to the very top
    plt.tight_layout(pad=0.8)

    if save_png_path:
        ensure_out_dir()
        fig.savefig(save_png_path, dpi=150)
        print(f"[plot] saved png: {save_png_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)




def maybe_plot(case_name: str, resp_json: Dict[str, Any], plot: bool, save_plot: bool) -> None:
    """
    Decide how to plot:
    - heatmap tables -> table heatmap
    - else if series exists -> line plot
    """
    show = bool(plot)
    if not (plot or save_plot):
        return

    if has_heatmap_tables(resp_json):
        png = os.path.join(OUT_DIR, f"{case_name}_heatmap.png") if save_plot else None
        plot_heatmap_table(case_name, resp_json, save_png_path=png, show=show)
        return

    if extract_plot_series(resp_json):
        png = os.path.join(OUT_DIR, f"{case_name}.png") if save_plot else None
        plot_line_response(case_name, resp_json, save_png_path=png, show=show)
        return

    print(f"[plot] {case_name}: nothing plottable found.")


# ----------------------------
# Case model + loading
# ----------------------------

@dataclass(frozen=True)
class Case:
    name: str
    method: str
    path: str
    payload: Dict[str, Any]
    expect: Dict[str, Any]
    tags: List[str]


def load_cases() -> Dict[str, Case]:
    if not os.path.exists(CASES_PATH):
        raise FileNotFoundError(f"cases.json not found at {CASES_PATH}")

    with open(CASES_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("cases.json must contain a top-level JSON object")

    out: Dict[str, Case] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"Case '{name}' must be an object")

        method = str(spec.get("method", "POST")).upper()
        path = str(spec.get("path", "")).strip()
        payload = spec.get("payload", {})
        expect = spec.get("expect", {})
        tags = spec.get("tags", [])

        if not path.startswith("/"):
            raise ValueError(f"Case '{name}': path must start with '/'")
        if not isinstance(payload, dict):
            raise ValueError(f"Case '{name}': payload must be an object")
        if not isinstance(expect, dict):
            raise ValueError(f"Case '{name}': expect must be an object")
        if not isinstance(tags, list):
            raise ValueError(f"Case '{name}': tags must be a list")

        out[name] = Case(
            name=name,
            method=method,
            path=path,
            payload=payload,
            expect=expect,
            tags=[str(t).lower() for t in tags],
        )

    return out


# ----------------------------
# HTTP + runner
# ----------------------------

def http_call(base_url: str, case: Case, timeout: int = 120) -> Tuple[int, Any]:
    url = base_url.rstrip("/") + case.path
    method = case.method.upper()

    if method == "POST":
        r = requests.post(url, json=case.payload, timeout=timeout)
    elif method == "GET":
        r = requests.get(url, params=case.payload, timeout=timeout)
    else:
        raise ValueError(f"Unsupported method: {case.method}")

    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def run_case(base_url: str, case: Case, plot: bool, save_plot: bool, timeout: int) -> int:
    print(f"\n== {case.name}  ({case.method} {case.path}) ==")

    status, data = http_call(base_url, case, timeout=timeout)

    if status != 200:
        print(f"[FAIL] HTTP {status}")
        print(pretty(data) if isinstance(data, (dict, list)) else str(data))
        save_json(case.name + "_FAIL", {"http_status": status, "data": data})
        return 1

    if not isinstance(data, dict):
        print("[FAIL] Response was not JSON object")
        print(str(data))
        save_json(case.name + "_FAIL", {"http_status": status, "data": data})
        return 1

    problems = basic_sanity_checks(data, case.expect)
    out_path = save_json(case.name, data)

    if problems:
        print("[FAIL] Sanity checks failed:")
        for p in problems:
            print("  -", p)
        print(f"[saved] {out_path}")
        return 1

    maybe_plot(case.name, data, plot=plot, save_plot=save_plot)

    extra = ""
    if "stats" in data and isinstance(data["stats"], dict) and "last" in data["stats"]:
        extra = f"  last={data['stats'].get('last')}"
    print(f"[OK] saved={out_path}{extra}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List available test cases")

    p_run = sub.add_parser("run", help="Run one case, all, or by tag")
    p_run.add_argument("name", nargs="?", default=None, help="Case name or 'all' (omit if using --tag)")
    p_run.add_argument("--tag", default=None, help="Run all cases matching tag (case-insensitive)")
    p_run.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Default: {DEFAULT_BASE_URL}")

    # Defaults ON: plot + save plot
    p_run.add_argument("--no-plot", action="store_true", help="Disable interactive plot window")
    p_run.add_argument("--no-save-plot", action="store_true", help="Disable saving plot PNG")
    p_run.add_argument("--timeout", type=int, default=120, help="HTTP timeout seconds")

    args = parser.parse_args()
    cases = load_cases()

    if args.cmd == "list":
        print(f"Loaded {len(cases)} cases from {CASES_PATH}\n")
        for k in sorted(cases.keys()):
            c = cases[k]
            tags = ",".join(c.tags) if c.tags else "-"
            print(f"  - {k:40s}  {c.method:4s} {c.path:28s}  tags={tags}")
        return 0

    if args.cmd == "run":
        selected: List[Case] = []

        if args.tag:
            tag = args.tag.strip().lower()
            selected = [c for c in cases.values() if tag in c.tags]
            if not selected:
                print(f"[error] No cases matched tag '{args.tag}'")
                return 2
            selected = sorted(selected, key=lambda c: c.name)
        else:
            if not args.name:
                print("[error] Provide a case name, 'all', or --tag <tag>")
                return 2
            if args.name == "all":
                selected = [cases[k] for k in sorted(cases.keys())]
            else:
                if args.name not in cases:
                    print(f"[error] Unknown case: {args.name}")
                    return 2
                selected = [cases[args.name]]

        plot = not bool(args.no_plot)
        save_plot = not bool(args.no_save_plot)

        rc = 0
        for c in selected:
            rc |= run_case(args.base_url, c, plot=plot, save_plot=save_plot, timeout=args.timeout)
        return rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
