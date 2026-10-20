"""Canonical form for factor expressions — diagnostics only, never identity.

The authoritative identity of a factor is its value fingerprint
(:mod:`alphaledger.identity.value_fp`). This module exists for two narrower jobs:

1. Cheap de-duplication *before* data is loaded, so a repeated expression does not
   even get evaluated.
2. Detecting nondeterminism: if the same expression produces a different value
   fingerprint on the same panel, something in the factor is random or the data
   moved underneath it. That is a ``NONDETERMINISTIC_FACTOR`` warning, and it is
   the cheapest look-ahead detector you get for free.

The normalisation is deliberately conservative. It rewrites only what is provably
identical for *all* inputs:

* case and whitespace, operator aliases (``shift``/``lag``/``ref`` → ``delay``)
* numeric constant folding, and removal of identity elements (``+0``, ``*1``)
* associativity flattening and commutativity ordering for ``+`` and ``*``
* one deterministic printing convention

It does **not** expand ``a*(b+c)``, does not turn ``x/2`` into ``x*0.5``, and does
not touch anything that needs data to decide. Anything more aggressive would make
``canonical_expr`` disagree with reality, and a diagnostic that lies is worse than
no diagnostic.
"""

from __future__ import annotations

import hashlib
import re

__all__ = ["canonical_expr", "expr_fingerprint", "CanonicalizeError"]

_ALIASES = {
    "cs_rank": "rank",
    "rank_cs": "rank",
    "shift": "delay",
    "lag": "delay",
    "ref": "delay",
    "ts_mean": "ts_mean",
    "rolling_mean": "ts_mean",
    "ma": "ts_mean",
    "sma": "ts_mean",
    "ln": "log",
    "ts_std": "ts_std",
    "rolling_std": "ts_std",
    "stddev": "ts_std",
    "ts_sum": "ts_sum",
    "rolling_sum": "ts_sum",
}

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?|(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<op>[+\-*/(),]))"
)


class CanonicalizeError(ValueError):
    """Raised when the expression cannot be parsed. Callers should treat it as
    'no expression fingerprint' rather than failing the evaluation."""


def _tokenize(src: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(src):
        m = _TOKEN_RE.match(src, pos)
        if not m or m.end() == pos:
            if src[pos:].strip() == "":
                break
            raise CanonicalizeError(f"cannot tokenize at {pos}: {src[pos:pos + 20]!r}")
        pos = m.end()
        if m.group("num") is not None:
            tokens.append(("num", m.group("num")))
        elif m.group("name") is not None:
            tokens.append(("name", m.group("name").lower()))
        else:
            tokens.append(("op", m.group("op")))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise CanonicalizeError("unexpected end of expression")
        self.i += 1
        return tok

    def expect(self, op: str) -> None:
        kind, value = self.take()
        if kind != "op" or value != op:
            raise CanonicalizeError(f"expected {op!r}, got {value!r}")

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise CanonicalizeError(f"trailing tokens at {self.i}")
        return node

    def expr(self):
        node = self.term()
        while (tok := self.peek()) and tok[0] == "op" and tok[1] in "+-":
            self.take()
            rhs = self.term()
            node = ("add", node, rhs) if tok[1] == "+" else ("sub", node, rhs)
        return node

    def term(self):
        node = self.unary()
        while (tok := self.peek()) and tok[0] == "op" and tok[1] in "*/":
            self.take()
            rhs = self.unary()
            node = ("mul", node, rhs) if tok[1] == "*" else ("div", node, rhs)
        return node

    def unary(self):
        tok = self.peek()
        if tok and tok[0] == "op" and tok[1] in "+-":
            self.take()
            operand = self.unary()
            return operand if tok[1] == "+" else ("neg", operand)
        return self.atom()

    def atom(self):
        kind, value = self.take()
        if kind == "num":
            return ("num", float(value))
        if kind == "name":
            name = _ALIASES.get(value, value)
            if self.peek() and self.peek() == ("op", "("):
                self.take()
                args = []
                if self.peek() != ("op", ")"):
                    args.append(self.expr())
                    while self.peek() == ("op", ","):
                        self.take()
                        args.append(self.expr())
                self.expect(")")
                return ("call", name, tuple(args))
            return ("var", name)
        if value == "(":
            node = self.expr()
            self.expect(")")
            return node
        raise CanonicalizeError(f"unexpected token {value!r}")


def _fmt_num(v: float) -> str:
    if v == int(v) and abs(v) < 1e16:
        return str(int(v))
    return format(v, ".12g")


def _sort_key(node) -> str:
    return _print(node)


def _canon(node):
    kind = node[0]
    if kind in ("num", "var"):
        return node
    if kind == "call":
        return ("call", node[1], tuple(_canon(a) for a in node[2]))
    if kind == "neg":
        inner = _canon(node[1])
        if inner[0] == "num":
            return ("num", -inner[1])
        return ("neg", inner)
    if kind == "sub":
        return _canon_add([_canon(node[1]), _canon_neg(_canon(node[2]))])
    if kind == "add":
        return _canon_add([_canon(node[1]), _canon(node[2])])
    if kind == "mul":
        return _canon_mul([_canon(node[1]), _canon(node[2])])
    if kind == "div":
        lhs, rhs = _canon(node[1]), _canon(node[2])
        if lhs[0] == "num" and rhs[0] == "num" and rhs[1] != 0:
            return ("num", lhs[1] / rhs[1])
        if rhs[0] == "num" and rhs[1] == 1:
            return lhs
        return ("div", lhs, rhs)
    raise CanonicalizeError(f"unknown node {kind}")


def _canon_neg(node):
    if node[0] == "num":
        return ("num", -node[1])
    if node[0] == "neg":
        return node[1]
    return ("neg", node)


def _canon_add(terms: list):
    flat: list = []
    total = 0.0
    stack = list(terms)
    while stack:
        node = stack.pop()
        if node[0] == "add":
            stack.extend([node[1], node[2]])
        elif node[0] == "num":
            total += node[1]
        elif node[0] == "neg" and node[1][0] == "num":
            total -= node[1][1]
        else:
            flat.append(node)
    if total:
        flat.append(("num", total))
    if not flat:
        return ("num", 0.0)
    if len(flat) == 1:
        return flat[0]
    flat.sort(key=_sort_key)
    node = flat[0]
    for nxt in flat[1:]:
        node = ("add", node, nxt)
    return node


def _canon_mul(factors: list):
    flat: list = []
    coef = 1.0
    stack = list(factors)
    while stack:
        node = stack.pop()
        if node[0] == "mul":
            stack.extend([node[1], node[2]])
        elif node[0] == "num":
            coef *= node[1]
        elif node[0] == "neg":
            coef *= -1.0
            stack.append(node[1])
        else:
            flat.append(node)
    if coef == 0.0:
        return ("num", 0.0)
    if not flat:
        return ("num", coef)
    flat.sort(key=_sort_key)
    node = flat[0]
    for nxt in flat[1:]:
        node = ("mul", node, nxt)
    if coef == 1.0:
        return node
    if coef == -1.0:
        return ("neg", node)
    return ("mul", ("num", coef), node)


def _print(node) -> str:
    kind = node[0]
    if kind == "num":
        return _fmt_num(node[1])
    if kind == "var":
        return node[1]
    if kind == "call":
        return f"{node[1]}({','.join(_print(a) for a in node[2])})"
    if kind == "neg":
        return f"(-{_print(node[1])})"
    if kind == "add":
        return f"({_print(node[1])}+{_print(node[2])})"
    if kind == "mul":
        return f"({_print(node[1])}*{_print(node[2])})"
    if kind == "div":
        return f"({_print(node[1])}/{_print(node[2])})"
    raise CanonicalizeError(f"unknown node {kind}")


def canonical_expr(src: str) -> str:
    """Canonical string form. Raises :class:`CanonicalizeError` on unparseable input."""
    if isinstance(src, str) and "#" in src:
        src = src.split("#", 1)[0]  # allow trailing comments in factor files
    tokens = _tokenize(src)
    if not tokens:
        raise CanonicalizeError("empty expression")
    return _print(_canon(_Parser(tokens).parse()))


def expr_fingerprint(src: str) -> str | None:
    """``"e1:<hex16>"``, or ``None`` when the expression cannot be parsed.

    Never raises: an unparseable expression costs you a diagnostic, not an
    evaluation.
    """
    try:
        canonical = canonical_expr(src)
    except CanonicalizeError:
        return None
    return "e1:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
