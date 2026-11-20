"""Safe arithmetic for the model: numbers, + - * / // % ^, parentheses, pi, e and common math functions.

Parses with ast and evaluates only the allowed node types; nothing is ever passed to eval().
"""
from __future__ import annotations

import ast
import math
import operator
import re

_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCTIONS = {name: getattr(math, name) for name in (
    "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "log10", "log2", "exp", "floor", "ceil",
    "factorial", "radians", "degrees")}
_FUNCTIONS.update({"log": math.log, "ln": math.log, "abs": abs, "round": round})
_CONSTANTS = {"pi": math.pi, "e": math.e}


def calculate(expression: str) -> str:
    text = expression.replace("^", "**").replace("×", "*").replace("÷", "/").strip()
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,000 -> 1000, but round(x, 3) keeps its comma
    if not text or len(text) > 300:
        raise ValueError("give a math expression of at most 300 characters")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"could not read the expression: {exc.msg}") from None
    value = _evaluate(tree.body)
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def _evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        # Keeps 9^9^9-style input from freezing Nova.
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent is too large")
        return _OPERATORS[type(node.op)](left, right)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS
            and not node.keywords):
        arguments = [_evaluate(argument) for argument in node.args]
        if node.func.id == "factorial" and arguments and arguments[0] > 1000:
            raise ValueError("factorial input is too large")
        return _FUNCTIONS[node.func.id](*arguments)
    raise ValueError("only numbers, + - * / ^ %, parentheses, pi, e and math functions like sqrt or sin are allowed")
