from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


# Canonical token pattern in expressions:
#   EQ:SPY
#   EQ:SAP.DE
#   FX:EURUSD
#   IX:DAX
#   IX:DAX.1
#   IX:DAX.A
#   IX:DAX@EUREX.1
#   IX:N225@SGX.2
#   IX:ES1
#   IX:ESU25
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

    Example:
        "(EQ:EEM * FX:EURUSD) / EQ:SPY"
      -> "(s0 * s1) / s2", ["EQ:EEM", "FX:EURUSD", "EQ:SPY"]
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

    Internal specs (this stage):
      - EQ:SPY        -> stock:SPY
      - EQ:SAP.DE     -> stock:SAP:DE      (region-qualified listing)
      - EQ:SAP        -> stock:SAP         (default US)
      - FX:EURUSD     -> fx:EURUSD

      - IX:DAX        -> index:DAX

      Existing futures selectors:
      - IX:DAX.1           -> futureSel:DAX:AUTO:1
      - IX:DAX.A           -> futureSel:DAX:AUTO:1
      - IX:DAX@EUREX.1     -> futureSel:DAX:EUREX:1
      - IX:N225@SGX.2      -> futureSel:N225:SGX:2

      New futures aliases (no dot):
      - IX:ES1             -> futureSel:ES:AUTO:1
      - IX:MNQ2            -> futureSel:MNQ:AUTO:2
      - IX:ESU25           -> futureCode:ES:AUTO:U25
      - IX:NQH26           -> futureCode:NQ:AUTO:H26

      - BTC:BTCUSD    -> crypto:BTCUSD    (placeholder)
      - FI:...        -> bond:...         (placeholder)

    NOTE: `futureSel:*` and `futureCode:*` are temporary internal forms.
    Next step will resolve them into `future:<product>:<exchange>:<YYYYMMDD>` using IBKR contract details.
    """
    token = token.strip()
    m = _CANONICAL_TOKEN_RE.fullmatch(token)
    if not m:
        raise SymbolNormalizationError(
            f"Bad symbol token '{token}'. Expected like EQ:SPY, EQ:SAP.DE, FX:EURUSD, IX:DAX.1, IX:DAX@EUREX.1"
        )

    asset = m.group("asset").upper()
    body = m.group("body")

    if asset == "EQ":
        # EQ:<TICKER>[.<REGION>]
        if "." in body:
            ticker, region = body.split(".", 1)
            ticker = ticker.upper()
            region = region.upper()
            if not _REGION_RE.fullmatch(region):
                raise SymbolNormalizationError(
                    f"Bad region suffix '{region}' in '{token}'. Use 2-letter region like .US, .DE, .GB"
                )
            if region == "US":
                return f"stock:{ticker}"
            return f"stock:{ticker}:{region}"
        return f"stock:{body.upper()}"

    if asset == "FX":
        return f"fx:{body.upper()}"

    if asset == "IX":
        # Spot: IX:DAX
        # Futures selectors:
        #   - IX:<UNDERLYING>[@<VENUE>].<SELECTOR>   (existing)
        #   - IX:<ROOT><N>                           (new, e.g. ES1)
        #   - IX:<ROOT><MONTHCODE><YY>               (new, e.g. ESU25)

        if "." not in body:
            base = body.upper()

            # If user writes IX:DAX@EUREX without a selector, treat it as an index (no futures selector implied)
            if "@" in base:
                return f"index:{base}"

                        # IMPORTANT: month-code forms like ESU25 must be checked BEFORE positional forms like ES1.
            m_code = _FUT_CODE_RE.fullmatch(base)
            if m_code:
                root = m_code.group("root").upper()
                code = m_code.group("code").upper()
                yy = m_code.group("yy")
                return f"futureCode:{root}:AUTO:{code}{yy}"

            m_pos = _FUT_POS_RE.fullmatch(base)
            if m_pos:
                root = m_pos.group("root").upper()
                n = int(m_pos.group("n"))
                if n < 1:
                    raise SymbolNormalizationError(f"Invalid futures selector in '{token}'. Use ES1, ES2, ...")
                return f"futureSel:{root}:AUTO:{n}"


            # Default: spot index
            return f"index:{base}"

        # Dot-form: IX:<UNDERLYING>[@<VENUE>].<SELECTOR>
        left, sel = body.rsplit(".", 1)
        sel = sel.upper()

        # Parse optional venue
        if "@" in left:
            underlying, venue = left.split("@", 1)
            venue = venue.upper()
            if not venue:
                raise SymbolNormalizationError(f"Bad venue in '{token}'. Use like IX:DAX@EUREX.1")
        else:
            underlying = left
            venue = "AUTO"

        underlying = underlying.upper()

        # Active alias = front month
        if sel == "A":
            sel = "1"

        if not sel.isdigit():
            raise SymbolNormalizationError(
                f"Unsupported IX selector '{sel}' in '{token}'. Supported today: .1, .2, .A"
            )

        n = int(sel)
        if n < 1:
            raise SymbolNormalizationError(f"Invalid futures selector '{sel}' in '{token}'. Use .1, .2, or .A")

        return f"futureSel:{underlying}:{venue}:{n}"

    if asset == "BTC":
        return f"crypto:{body.upper()}"

    if asset == "FI":
        return f"bond:{body.upper()}"

    raise SymbolNormalizationError(f"Unsupported asset prefix '{asset}' in '{token}'")
