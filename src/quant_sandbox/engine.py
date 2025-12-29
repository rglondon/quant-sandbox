from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict, Set, Tuple

import pandas as pd


ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


@dataclass(frozen=True)
class ExprResult:
    series: pd.Series
    symbols: Set[str]


class UnsafeExpression(ValueError):
    pass


def _extract_symbols(node: ast.AST, symbols: Set[str]) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return
        raise UnsafeExpression("Only numeric constants allowed.")
    if isinstance(node, ast.Num):  # py<3.8
        return
    if isinstance(node, ast.Name):
        symbols.add(node.id)
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, ALLOWED_BINOPS):
            raise UnsafeExpression("Only + - * / are allowed.")
        _extract_symbols(node.left, symbols)
        _extract_symbols(node.right, symbols)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ALLOWED_UNARYOPS):
            raise UnsafeExpression("Only unary + / - allowed.")
        _extract_symbols(node.operand, symbols)
        return
    if isinstance(node, ast.Expr):
        _extract_symbols(node.value, symbols)
        return

    raise UnsafeExpression(f"Unsupported syntax: {type(node).__name__}")


def _safe_parse(expr: str) -> Tuple[ast.AST, Set[str]]:
    """
    We map instrument specs to safe variable names first, then parse with AST.
    """
    tree = ast.parse(expr, mode="eval")
    symbols: Set[str] = set()
    _extract_symbols(tree.body, symbols)
    return tree.body, symbols


def _align_series(series_map: Dict[str, pd.Series]) -> Dict[str, pd.Series]:
    # Outer-join on time index and forward-fill where appropriate
    df = pd.DataFrame(series_map).sort_index()
    # Forward-fill only (common for cross-asset alignment)
    df = df.ffill()
    # Drop rows where everything is NaN
    df = df.dropna(how="all")
    return {c: df[c] for c in df.columns}


def _eval_node(node: ast.AST, env: Dict[str, pd.Series]) -> pd.Series:
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.Constant):
        return pd.Series(node.value, index=next(iter(env.values())).index)
    if isinstance(node, ast.Num):  # py<3.8
        return pd.Series(node.n, index=next(iter(env.values())).index)
    if isinstance(node, ast.UnaryOp):
        s = _eval_node(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -s
        if isinstance(node.op, ast.UAdd):
            return +s
        raise UnsafeExpression("Unsupported unary op.")
    if isinstance(node, ast.BinOp):
        a = _eval_node(node.left, env)
        b = _eval_node(node.right, env)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
        raise UnsafeExpression("Unsupported bin op.")
    raise UnsafeExpression("Unsupported node.")


def evaluate_expression(expr: str, series_map: Dict[str, pd.Series]) -> ExprResult:
    """
    expr: e.g. "S0 / S1" or "(S0 - S1) / S1"
    series_map: keys must match variable names in expr (S0, S1, etc)
    """
    node, symbols = _safe_parse(expr)

    aligned = _align_series(series_map)
    # Rebuild env with aligned indices
    env = {k: aligned[k].astype(float) for k in symbols}

    out = _eval_node(node, env)
    out = out.replace([pd.NA, pd.NaT], pd.NA)
    out = out.dropna()
    return ExprResult(series=out, symbols=symbols)
