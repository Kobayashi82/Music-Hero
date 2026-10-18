"""Idioma del generador: todo t("...") tiene traducción al inglés con los mismos campos, y ninguna variable
local t tapa la función. uv run --project generator --with pytest --with jsonschema pytest tests"""

import ast
import re
import string
from pathlib import Path

from generator.lang_en import EN

SRC = Path(__file__).resolve().parent.parent / "generator" / "src" / "generator"


def sources():
    return [(p, ast.parse(p.read_text(encoding="utf-8"))) for p in SRC.rglob("*.py")]


def keys() -> dict[str, str]:
    found = {}
    for path, tree in sources():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "t" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found[node.args[0].value] = f"{path.name}:{node.lineno}"
    return found


def fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f} | set(re.findall(r"%\d", text))


def test_todo_traducido():
    missing = {k: where for k, where in keys().items() if k not in EN}
    assert not missing, "\n".join(f"{where}: {k!r}" for k, where in missing.items())


def test_mismos_campos_y_sin_sobrantes():
    ks = keys()
    assert not [k for k in ks if k in EN and fields(k) != fields(EN[k])]
    assert not set(EN) - set(ks), sorted(set(EN) - set(ks))


def test_t_no_queda_tapada():
    bad = []
    for path, tree in sources():
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.Lambda)):
                local = any(isinstance(n, ast.Name) and n.id == "t" and isinstance(n.ctx, ast.Store)
                            for n in ast.walk(fn)) or any(a.arg == "t" for a in ast.walk(fn.args)
                                                          if isinstance(a, ast.arg))
                calls = any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "t" for n in ast.walk(fn))
                if local and calls:
                    bad.append(f"{path.name}:{fn.lineno}")
    assert not bad, bad


def test_idioma_por_variable(monkeypatch):
    from generator.i18n import t

    monkeypatch.setenv("MUSICHERO_LANG", "en")
    assert t("no existe: {path}", path="x.mp3") == "doesn't exist: x.mp3"
    monkeypatch.setenv("MUSICHERO_LANG", "es")
    assert t("no existe: {path}", path="x.mp3") == "no existe: x.mp3"
