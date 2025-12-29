from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass(frozen=True)
class Series:
    values: pd.Series          # indexed by DatetimeIndex
    name: str                  # for chart legends
    unit: Optional[str] = None # "price", "%", "ratio", "index", etc.

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.values.index

    def dropna(self) -> "Series":
        return Series(self.values.dropna(), self.name, self.unit)

    def align(self, other: "Series") -> tuple["Series", "Series"]:
        v1, v2 = self.values.align(other.values, join="inner")
        return Series(v1, self.name, self.unit), Series(v2, other.name, other.unit)
