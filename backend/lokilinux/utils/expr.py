"""
LokiLinux — restricted expression evaluator for `condition` workflow steps
(plan Partea I §12, §18 — the AST-whitelist evaluator promised there, never
implemented until now).

No `eval()` of arbitrary code. `ast.parse(..., mode="eval")` first, then a
full-tree walk against a strict node-type whitelist BEFORE anything is
executed — a disallowed construct (Call, Import, Lambda, comprehensions,
walrus, ...) is rejected outright, never partially evaluated. Attribute
access additionally rejects any name starting with `_` — `steps.__class__`
would otherwise resolve via normal attribute lookup (Python only falls back
to `__getattr__` for names that aren't already there) and reopen the classic
sandbox-escape chain (`__class__.__bases__[0].__subclasses__()...`) that the
node whitelist alone doesn't close, since Attribute nodes themselves have to
stay allowed for `steps.upgrade.status` to work at all.

Context shape (plan §12): `steps.<id>.{status, exit_code, duration_seconds}`,
`vars.<name>`, `targets.count`. Built and passed in by workflow_engine.py —
this module only evaluates, it never touches the database.
"""

import ast
from typing import Any

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.USub, ast.UAdd, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
    ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Name, ast.Load, ast.Attribute, ast.Constant, ast.Subscript,
)


class ExpressionError(ValueError):
    """Raised for a syntax error, a disallowed construct, an unknown name,
    or a runtime failure (e.g. comparing incompatible types) while
    evaluating a condition expression."""


def _validate(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"disallowed expression construct: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExpressionError(f"attribute '{node.attr}' is not accessible")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ExpressionError(f"name '{node.id}' is not accessible")


class _AttrDict:
    """Read-only dot-and-bracket access over a plain dict, recursing into
    nested dicts so `steps.upgrade.status` and `steps["upgrade"]["status"]`
    both work. Never exposes anything the underlying dict doesn't already
    hold — no methods, no dunder fallthrough beyond what _validate already
    blocks at the AST level (this class is defense in depth, not the only
    layer)."""

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        object.__setattr__(self, "_data", data)

    def _get(self, name: str) -> Any:
        if name.startswith("_"):
            raise ExpressionError(f"attribute '{name}' is not accessible")
        try:
            value = self._data[name]
        except KeyError:
            raise ExpressionError(f"unknown name '{name}'") from None
        return _AttrDict(value) if isinstance(value, dict) else value

    def __getattr__(self, name: str) -> Any:
        return self._get(name)

    def __getitem__(self, key: str) -> Any:
        return self._get(key)


def validate_expression(expression: str) -> str | None:
    """Publish-time check (workflow_compiler.py) — returns an error message
    string, or None if the expression is syntactically valid and stays
    within the whitelist. Never executes anything; safe to call on
    untrusted input during validation."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return f"invalid expression syntax: {exc.msg}"
    try:
        _validate(tree)
    except ExpressionError as exc:
        return str(exc)
    return None


def evaluate_condition(expression: str, context: dict[str, Any]) -> bool:
    """Evaluates a `condition` step's expression against the run context
    (workflow_engine.py builds `context` from step_runs/run.vars/target
    count). Raises ExpressionError on anything invalid — the caller decides
    whether that fails the step or the whole run; this function never
    silently returns a default."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression syntax: {exc.msg}") from None
    _validate(tree)

    compiled = compile(tree, "<condition>", "eval")
    scope = {k: (_AttrDict(v) if isinstance(v, dict) else v) for k, v in context.items()}
    try:
        result = eval(compiled, {"__builtins__": {}}, scope)  # noqa: S307 -- AST whitelisted above
    except ExpressionError:
        raise
    except Exception as exc:
        raise ExpressionError(f"expression evaluation failed: {exc}") from None
    return bool(result)
