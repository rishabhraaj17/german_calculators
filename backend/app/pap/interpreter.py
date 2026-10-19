"""Executes the official BMF Lohnsteuer "Programmablaufplan" (PAP) pseudocode.

The ITZBund publishes the PAP for every year as XML pseudocode
(https://www.bmf-steuerrechner.de/interface/pseudocode.xhtml). Instead of
re-typing tax formulas by hand (error prone), this module interprets that XML
directly. The XML uses a tiny Java subset (java.math.BigDecimal arithmetic,
if/else, method calls), which is mapped 1:1 onto Python's ``decimal`` module.

§ 2e Abs. 1 BEEG mandates exactly this program: taxes for Elterngeld are
computed with the PAP in force on 1 January of the calendar year before birth.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Context, Decimal, localcontext
from functools import lru_cache
from pathlib import Path
from typing import Any

_PAP_DIR = Path(__file__).parent
_RESULT_CACHE_SIZE = 4096  # per PAP year; bounded so a long-lived instance stays small
_CTX = Context(prec=80)  # wide enough that unscaled BigDecimal ops stay exact


class BigDecimal:
    """Minimal java.math.BigDecimal with the semantics the PAP relies on."""

    __slots__ = ("v",)
    ROUND_DOWN = ROUND_DOWN  # Java ROUND_DOWN: towards zero (same as Python)
    ROUND_UP = ROUND_UP  # Java ROUND_UP: away from zero (same as Python)
    ROUND_HALF_UP = ROUND_HALF_UP

    def __init__(self, v: Any) -> None:
        if isinstance(v, BigDecimal):
            self.v = v.v
        elif isinstance(v, float):
            # Java BigDecimal.valueOf(double) uses Double.toString -> shortest repr
            self.v = Decimal(repr(v))
        else:
            self.v = Decimal(v)

    @staticmethod
    def valueOf(v: Any) -> "BigDecimal":  # noqa: N802 (Java name)
        return BigDecimal(v)

    of = valueOf

    def add(self, o: "BigDecimal") -> "BigDecimal":
        return BigDecimal(_CTX.add(self.v, o.v))

    def subtract(self, o: "BigDecimal") -> "BigDecimal":
        return BigDecimal(_CTX.subtract(self.v, o.v))

    def multiply(self, o: "BigDecimal") -> "BigDecimal":
        return BigDecimal(_CTX.multiply(self.v, o.v))

    def divide(self, o: "BigDecimal", scale: int | None = None, mode: str | None = None) -> "BigDecimal":
        q = _CTX.divide(self.v, o.v)
        if scale is None:
            return BigDecimal(q)
        return BigDecimal(q).setScale(scale, mode)

    def setScale(self, scale: int, mode: str) -> "BigDecimal":  # noqa: N802
        with localcontext(_CTX):
            return BigDecimal(self.v.quantize(Decimal(1).scaleb(-scale), rounding=mode))

    def compareTo(self, o: "BigDecimal") -> int:  # noqa: N802
        return (self.v > o.v) - (self.v < o.v)

    def longValue(self) -> int:  # noqa: N802
        return int(self.v)  # truncates towards zero like Java

    def __repr__(self) -> str:
        return f"BigDecimal({self.v})"


BigDecimal.ZERO = BigDecimal(0)  # type: ignore[attr-defined]
BigDecimal.ONE = BigDecimal(1)  # type: ignore[attr-defined]
BigDecimal.TEN = BigDecimal(10)  # type: ignore[attr-defined]


def _to_python(expr: str) -> str:
    expr = re.sub(r"\bnew\s+BigDecimal\s*\(", "BigDecimal.of(", expr)
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = expr.strip()
    if expr.startswith("{") and expr.endswith("}"):  # Java array literal
        expr = "[" + expr[1:-1] + "]"
    return expr


class Programmablaufplan:
    """One parsed PAP year. Thread-safe: each run() gets its own variable scope."""

    def __init__(self, xml_path: Path) -> None:
        root = ET.parse(xml_path).getroot()
        self.name = root.get("name", "")
        self._defaults: dict[str, str] = {}
        self._types: dict[str, str] = {}
        self.inputs: list[str] = []
        self.outputs: list[str] = []
        for el in root.iter():
            if el.tag in ("INPUT", "OUTPUT", "INTERNAL"):
                name = el.get("name")
                assert name
                self._types[name] = el.get("type", "")
                self._defaults[name] = el.get("default") or el.get("defaul") or ""
                if el.tag == "INPUT":
                    self.inputs.append(name)
                elif el.tag == "OUTPUT":
                    self.outputs.append(name)
        self._constants = {
            c.get("name"): c.get("value") for c in root.iter("CONSTANT")
        }
        methods = root.find(".//METHODS")
        assert methods is not None
        self._main = methods.find("MAIN")
        self._methods = {m.get("name"): m for m in methods.findall("METHOD")}
        self._code_cache: dict[str, Any] = {}
        self._base: dict[str, Any] | None = None
        self._results: dict[tuple, dict[str, int]] = {}

    def _compile(self, src: str, mode: str) -> Any:
        key = mode + src
        code = self._code_cache.get(key)
        if code is None:
            code = compile(_to_python(src), self.name, mode)
            self._code_cache[key] = code
        return code

    def _base_scope(self) -> dict[str, Any]:
        """Constants and defaults, evaluated once; BigDecimal values are immutable, so runs can share them."""
        if self._base is None:
            scope: dict[str, Any] = {"BigDecimal": BigDecimal, "__builtins__": {}}
            for name, value in self._constants.items():
                scope[name] = eval(self._compile(value, "eval"), scope)
            for name, typ in self._types.items():
                default = self._defaults.get(name)
                if default:
                    scope[name] = eval(self._compile(default, "eval"), scope)
                else:
                    scope[name] = BigDecimal.ZERO if typ == "BigDecimal" else 0
                if typ == "double" and isinstance(scope[name], int):
                    scope[name] = float(scope[name])
            self._base = scope
        return self._base

    def _initial_scope(self, inputs: dict[str, Any]) -> dict[str, Any]:
        scope = dict(self._base_scope())
        for name, value in inputs.items():
            if name not in self._types:
                raise KeyError(f"{self.name}: unknown input {name}")
            typ = self._types[name]
            if typ == "BigDecimal":
                scope[name] = BigDecimal(str(value) if isinstance(value, float) else value)
            elif typ == "double":
                scope[name] = float(value)
            else:
                scope[name] = int(value)
        return scope

    def _exec_block(self, block: ET.Element, scope: dict[str, Any]) -> None:
        for stmt in block:
            tag = stmt.tag
            if tag == "EVAL":
                exec(self._compile(stmt.get("exec", ""), "exec"), scope)
            elif tag == "EXECUTE":
                self._exec_block(self._methods[stmt.get("method")], scope)
            elif tag == "IF":
                branch = "THEN" if eval(self._compile(stmt.get("expr", ""), "eval"), scope) else "ELSE"
                body = stmt.find(branch)
                if body is not None:
                    self._exec_block(body, scope)
            else:
                raise ValueError(f"{self.name}: unsupported statement <{tag}>")

    def run(self, **inputs: Any) -> dict[str, int]:
        """Runs the PAP. Monetary inputs/outputs are in cent, as in the PAP."""
        # a run depends only on its inputs, so identical calls (frequent within one analysis) reuse the result
        key = tuple(sorted((k, type(v).__name__, str(v)) for k, v in inputs.items()))
        hit = self._results.get(key)
        if hit is None:
            scope = self._initial_scope(inputs)
            assert self._main is not None
            self._exec_block(self._main, scope)
            hit = {name: int(scope[name].v) for name in self.outputs if isinstance(scope[name], BigDecimal)}
            if len(self._results) >= _RESULT_CACHE_SIZE:
                self._results.clear()
            self._results[key] = hit
        return dict(hit)

    def income_tax(self, zve: Decimal, joint: bool) -> int:
        """Annual income tax per § 32a EStG (splitting if `joint`), using the PAP's own tariff routine:
        MPARA sets the year's parameters, UPTABxx applies the tariff to X = zvE / KZTAB."""
        scope = self._initial_scope({})
        self._exec_block(self._methods["MPARA"], scope)
        kztab = 2 if joint else 1
        scope["KZTAB"] = kztab
        scope["X"] = BigDecimal(max(zve, Decimal(0)) / kztab).setScale(0, ROUND_DOWN)
        uptab = next(name for name in self._methods if name.startswith("UPTAB"))
        self._exec_block(self._methods[uptab], scope)
        return int(scope["ST"].v)


# Security note: compile()/eval() above only ever run expressions taken from
# these bundled, checksum-pinned BMF files (never user input; user values enter
# solely as typed numbers via run()). The XML is local and trusted, so stdlib
# ElementTree is acceptable (expat does not resolve external entities).
_PAP_SHA256 = {
    2025: "878ea4a0a1e0bb7122e44b02fe7f2e1d70b605768a2b42ec84f895365f4fb7e1",
    2026: "63d8981646d139eba2f4dd990c13b43c4fb3883b402a5a40cddf253aa7aa96b4",
}
SUPPORTED_YEARS = tuple(_PAP_SHA256)


@lru_cache(maxsize=None)
def load_pap(year: int) -> Programmablaufplan:
    if year not in _PAP_SHA256:
        raise ValueError(f"No official PAP bundled for {year}; supported: {SUPPORTED_YEARS}")
    path = _PAP_DIR / f"Lohnsteuer{year}.xml"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != _PAP_SHA256[year]:
        raise RuntimeError(f"{path.name} does not match the pinned official BMF file")
    return Programmablaufplan(path)
