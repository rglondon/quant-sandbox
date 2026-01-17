# src/quant_sandbox/expressions.py

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


# Canonical token pattern in expressions:
#   EQ:SPY
#   EQ:SAP.GY
#   EQ:700.HK
#   EQ:SAP@IBIS
#   FX:EURUSD
#   IX:DAX
#   IX:DAX.1
#   IX:DAX.A
#   IX:DAX@EUREX
#   IX:ESTX50@EUREX
#   IX:N225@OSE.JPN
#   IX:HHI.HK
#   BTC:BTCUSD
_CANONICAL_TOKEN_RE = re.compile(
    r"\b(?P<asset>EQ|FI|FX|IX|BTC)\:(?P<body>[A-Za-z0-9]+(?:[@\.][A-Za-z0-9]+)*)\b"
)

_REGION_RE = re.compile(r"^[A-Za-z]{2}$")

# Futures aliases:
#   ES1, MNQ2, CL3  -> positional selector (front=1, second=2, ...)
#   ESU25, NQH26    -> month-code selector (U=Sep, H=Mar, etc.)
_FUT_POS_RE = re.compile(r"^(?P<root>[A-Za-z0-9]+?)(?P<n>[0-9]+)$")
_FUT_CODE_RE = re.compile(r"^(?P<root>[A-Za-z0-9]+)(?P<code>[FGHJKMNQUVXZ])(?P<yy>[0-9]{2})$")

# Exchange override forms for IX:
#  - IX:SYMBOL@EXCHANGE
#  - IX:SYMBOL@OSE.JPN
# Futures selector with exchange override (venue may contain dots):
#  - IX:DAX@EUREX.1
#  - IX:N225@OSE.JPN.1
_IX_AT_WITH_SEL_RE = re.compile(r"^(?P<sym>[A-Za-z0-9]+)@(?P<venue>[A-Za-z0-9\.]+)\.(?P<sel>A|\d+)$")

# Cash index aliases (user-facing -> IB cash symbol)
_IX_ALIASES = {
    "ESTX50": "SX5E",
    "HSCEI": "HHI",
    "HSCEI.HK": "HHI",
    "HHI.HK": "HHI",
    "RTY": "RUT",
}


@dataclass(frozen=True)
class CanonicalSymbol:
    asset: str
    body: str

    @property
    def raw(self) -> str:
        return f"{self.asset}:{self.body}"


class SymbolNormalizationError(ValueError):
    pass


def extract_canonical_symbols(expr: str) -> List[CanonicalSymbol]:
    out: List[CanonicalSymbol] = []
    for m in _CANONICAL_TOKEN_RE.finditer(expr):
        out.append(CanonicalSymbol(asset=m.group("asset").upper(), body=m.group("body")))
    return out


def normalize_expr_symbols(expr: str) -> Tuple[str, List[str]]:
    """
    Replace canonical symbols in an expression with placeholder identifiers (s0, s1, ...),
    returning (rewritten_expr, symbols_in_order).
    """
    symbols: List[str] = []

    def _repl(m: re.Match) -> str:
        raw = f"{m.group('asset').upper()}:{m.group('body')}"
        symbols.append(raw)
        return f"s{len(symbols) - 1}"

    rewritten = _CANONICAL_TOKEN_RE.sub(_repl, expr)
    return rewritten, symbols


def normalize_canonical_symbol(token: str) -> str:
    """
    Normalize a canonical symbol token into an internal spec string.

    Internal specs:
      - EQ:SPY            -> stock:SPY
      - EQ:SAP.GY         -> stock:SAP:GY
      - EQ:700.HK         -> stock:700:HK
      - EQ:SAP@IBIS       -> stock:SAP:IBIS

      - FX:EURUSD         -> fx:EURUSD

      - IX:DAX            -> index:DAX
      - IX:DAX@EUREX      -> index:DAX:EUREX
      - IX:N225@OSE.JPN   -> index:N225:OSE.JPN
      - IX:HHI.HK         -> index:HHI

      Futures selectors:
      - IX:DAX.1          -> futureSel:DAX:AUTO:1
      - IX:DAX.A          -> futureSel:DAX:AUTO:1
      - IX:DAX@EUREX.1    -> futureSel:DAX:EUREX:1

      Futures aliases:
      - IX:ES1            -> futureSel:ES:AUTO:1
      - IX:ESU25          -> futureCode:ES:AUTO:U25
    """
    token = token.strip()
    m = _CANONICAL_TOKEN_RE.fullmatch(token)
    if not m:
        raise SymbolNormalizationError(
            f"Bad symbol token '{token}'. Expected like EQ:SPY, EQ:SAP.GY, FX:EURUSD, IX:DAX, IX:DAX.1, IX:DAX@EUREX"
        )

    asset = m.group("asset").upper()
    body = m.group("body")

    # ---------------- EQ ----------------
    if asset == "EQ":
        body_u = body.upper().strip()

        # Exchange override: EQ:SAP@IBIS
        if "@" in body_u:
            sym, exch = body_u.split("@", 1)
            sym = sym.strip()
            exch = exch.strip()
            if not sym or not exch:
                raise SymbolNormalizationError(f"Bad EQ exchange override in '{token}'. Use EQ:SAP@IBIS")
            return f"stock:{sym}:{exch}"

        # Region suffix: EQ:SAP.GY or EQ:700.HK
        if "." in body_u:
            ticker, region = body_u.split(".", 1)
        else:
            ticker, region = body_u, "US"

        ticker = ticker.strip().upper()
        region = region.strip().upper()

        if not _REGION_RE.fullmatch(region):
            raise SymbolNormalizationError(
                f"Bad region suffix '{region}' in '{token}'. Use 2-letter suffix like .HK, .JP, .GY, .LN, .SW, .SP, .SK"
            )

        if region == "US":
            return f"stock:{ticker}"
        return f"stock:{ticker}:{region}"

    # ---------------- FX ----------------
    if asset == "FX":
        return f"fx:{body.upper()}"

    # ---------------- IX ----------------
    if asset == "IX":
        b = body.strip().upper()

        # Early cash-index aliases (prevents ESTX50 being parsed as futures alias)
        if b in _IX_ALIASES:
            return f"index:{_IX_ALIASES[b]}"

        # 1) Handle @VENUE with optional futures selector suffix (.1/.A)
        m_at_sel = _IX_AT_WITH_SEL_RE.fullmatch(b)
        if m_at_sel:
            sym = _IX_ALIASES.get(m_at_sel.group("sym").upper(), m_at_sel.group("sym").upper())
            venue = m_at_sel.group("venue").upper()
            sel = m_at_sel.group("sel").upper()
            if sel == "A":
                sel = "1"
            return f"futureSel:{sym}:{venue}:{int(sel)}"

        # 2) Handle simple @VENUE (venue may contain dots): IX:N225@OSE.JPN
        if "@" in b:
            sym, venue = b.split("@", 1)
            sym = _IX_ALIASES.get(sym.strip().upper(), sym.strip().upper())
            venue = venue.strip().upper()
            if not sym or not venue:
                raise SymbolNormalizationError(f"Bad IX exchange override in '{token}'. Use IX:DAX@EUREX")
            return f"index:{sym}:{venue}"

        # 3) Dot form might be futures selector, but ONLY if suffix is numeric or 'A'
        if "." in b:
            left, suffix = b.rsplit(".", 1)
            suf = suffix.upper().strip()
            if suf == "A" or suf.isdigit():
                sel = 1 if suf == "A" else int(suf)
                left2 = _IX_ALIASES.get(left.strip().upper(), left.strip().upper())
                return f"futureSel:{left2}:AUTO:{sel}"
            # otherwise dotted cash index / alias (e.g. HHI.HK)
            return f"index:{_IX_ALIASES.get(b, b)}"

        # 4) Futures aliases (ES1 / ESU25)
        m_code = _FUT_CODE_RE.fullmatch(b)
        if m_code:
            root = m_code.group("root").upper()
            code = m_code.group("code").upper()
            yy = m_code.group("yy")
            return f"futureCode:{root}:AUTO:{code}{yy}"

        m_pos = _FUT_POS_RE.fullmatch(b)
        if m_pos:
            root = m_pos.group("root").upper()
            n = int(m_pos.group("n"))
            if n < 1:
                raise SymbolNormalizationError(f"Invalid futures selector in '{token}'. Use ES1, ES2, ...")
            return f"futureSel:{root}:AUTO:{n}"

        # Default: cash index
        return f"index:{b}"

    # ---------------- BTC / FI ----------------
    if asset == "BTC":
        return f"crypto:{body.upper()}"

    if asset == "FI":
        return f"bond:{body.upper()}"

    raise SymbolNormalizationError(f"Unsupported asset prefix '{asset}' in '{token}'")
