import pandas as pd
import matplotlib.pyplot as plt

def plot_normalized_intraday(prices: pd.DataFrame, title: str) -> None:
    prices = prices.dropna()
    if prices.empty or prices.shape[1] < 2:
        raise ValueError("Need at least two price series to plot.")

    norm = 100 * prices / prices.iloc[0]

    plt.figure(figsize=(12, 6))
    for col in norm.columns:
        plt.plot(norm.index, norm[col], label=col)

    plt.title(title)
    plt.xlabel("Time")
    plt.ylabel("Normalized (Start=100)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()
import pandas as pd
import matplotlib.pyplot as plt

def plot_normalized_intraday(prices: pd.DataFrame, title: str) -> None:
    """
    Plot normalized price series (each starts at 100).
    """
    prices = prices.dropna()

    if prices.empty or prices.shape[1] < 2:
        raise ValueError("Need at least two price series to plot.")

    normalized = 100 * prices / prices.iloc[0]

    plt.figure(figsize=(12, 6))

    for col in normalized.columns:
        plt.plot(normalized.index, normalized[col], label=col)

    plt.title(title)
    plt.xlabel("Time")
    plt.ylabel("Normalized (Start = 100)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

import matplotlib.pyplot as plt
import pandas as pd


def plot_multi_axis(
    series_left: dict[str, pd.Series],
    series_right: dict[str, pd.Series] | None,
    title: str,
    invert_left: bool = False,
    invert_right: bool = False,
) -> None:
    """
    Plot multiple time series with optional dual y-axes.
    """

    fig, ax_left = plt.subplots(figsize=(12, 6))

    # Left axis
    for label, s in series_left.items():
        ax_left.plot(s.index, s.values, label=label)

    # Right axis (optional)
    ax_right = None
    if series_right:
        ax_right = ax_left.twinx()
        for label, s in series_right.items():
            ax_right.plot(s.index, s.values, label=label)

    if invert_left:
        ax_left.invert_yaxis()
    if ax_right is not None and invert_right:
        ax_right.invert_yaxis()

    ax_left.set_title(title)
    ax_left.set_xlabel("Time")
    ax_left.grid(True)

    # Combined legend
    h1, l1 = ax_left.get_legend_handles_labels()
    if ax_right:
        h2, l2 = ax_right.get_legend_handles_labels()
        ax_left.legend(h1 + h2, l1 + l2, loc="best")
    else:
        ax_left.legend(loc="best")

    plt.tight_layout()
    plt.show()
