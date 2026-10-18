"""Idioma: todo texto de t("...") / N_("...") del código y bridge.tr("...") del QML tiene traducción al inglés,
con los mismos campos. uv run --project app --with pytest pytest app/tests"""

import ast
import re
import string
from pathlib import Path

from app import i18n
from app.lang_en import EN

SRC = Path(__file__).resolve().parent.parent / "src" / "app"
TOOLS = [SRC.parents[2] / "tools" / f for f in ("wii_guitar_monitor.py", "wii_tilt_monitor.py",
                                                  "measure_aimp_latency.py")]  # los de tools/ que usan la app


def keys() -> dict[str, str]:
    """texto -> dónde aparece."""
    found = {}
    for path in [*SRC.glob("*.py"), *TOOLS]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("t", "N_") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found[node.args[0].value] = f"{path.name}:{node.lineno}"
    for path in (SRC / "qml").glob("*.qml"):
        for m in re.finditer(r'bridge\.tr\("((?:[^"\\]|\\.)*)"\)', path.read_text(encoding="utf-8")):
            found[m.group(1)] = path.name
    return found


def fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f} | set(re.findall(r"%\d", text))


def test_todo_traducido():
    missing = {k: where for k, where in keys().items() if k not in EN}
    assert not missing, "\n".join(f"{where}: {k!r}" for k, where in missing.items())


def test_mismos_campos():
    bad = [k for k in keys() if k in EN and fields(k) != fields(EN[k])]
    assert not bad, bad


def test_sin_traducciones_sobrantes():
    unused = set(EN) - set(keys())
    assert not unused, sorted(unused)


def test_t_no_queda_tapada():
    """Una variable local t (el tiempo, en muchos sitios) tapa la función t() en toda la función."""
    bad = []
    for path in [*SRC.glob("*.py"), *TOOLS]:
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(fn, (ast.FunctionDef, ast.Lambda)):
                local = any(isinstance(n, ast.Name) and n.id == "t" and isinstance(n.ctx, ast.Store)
                            for n in ast.walk(fn)) or any(a.arg == "t" for a in ast.walk(fn.args)
                                                          if isinstance(a, ast.arg))
                calls = any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "t" for n in ast.walk(fn))
                if local and calls:
                    bad.append(f"{path.name}:{fn.lineno}")
    assert not bad, bad


def test_t_traduce_y_rellena():
    old = i18n.lang()
    try:
        i18n.set_language("en")
        assert i18n.t("Dificultad: {name}", name="Hard") == "Difficulty: Hard"
        assert i18n.t("texto que no está") == "texto que no está"
        i18n.set_language("es")
        assert i18n.t("Dificultad: {name}", name="Difícil") == "Dificultad: Difícil"
    finally:
        i18n.set_language(old)
