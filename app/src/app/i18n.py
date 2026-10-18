"""Idioma de la app: los textos van en español en el código y t() los traduce (inglés en lang_en.py).

    t("Dificultad: {name}", name=...)   -> el texto en el idioma de ahora, con los campos puestos (str.format)
    N_("texto")                         -> marca un texto que se traduce más tarde, al usarlo (constantes)

El idioma sale de config.language: "auto" (el de Windows: español si lo es, si no inglés), "es" o "en". Se deja
en la variable MUSICHERO_LANG para que el motor de generación (otro proceso) hable igual. Los tests comprueban
que todo t("...") y N_("...") del código tiene su traducción (app/tests/test_i18n.py).
"""

from __future__ import annotations

import ctypes
import os

from .lang_en import EN

LANGS = {"auto": "Automático", "es": "Español", "en": "English"}  # Ajustes → Idioma (español e inglés, sin traducir)
LANG_ENV = "MUSICHERO_LANG"


def windows_lang() -> str:
    """El idioma de Windows del usuario: "es" si es español (cualquier país), si no "en"."""
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "en"
    return "es" if lid & 0x3FF == 0x0A else "en"


_lang = os.environ.get(LANG_ENV) if os.environ.get(LANG_ENV) in ("es", "en") else windows_lang()


def set_language(choice: str) -> str:
    """choice: "auto", "es" o "en". Devuelve el que queda."""
    global _lang
    _lang = choice if choice in ("es", "en") else windows_lang()
    os.environ[LANG_ENV] = _lang
    return _lang


def lang() -> str:
    return _lang


def t(text: str, **fields) -> str:
    if _lang == "en":
        text = EN.get(text, text)
    return text.format(**fields) if fields else text


def N_(text: str) -> str:  # noqa: N802 - el nombre de siempre (gettext) para «se traduce luego»
    return text


class TrDict(dict):
    """Diccionario de nombres para enseñar (dificultades, posiciones...): los valores salen traducidos."""

    def __getitem__(self, key):
        return t(super().__getitem__(key))

    def get(self, key, default=None):
        return t(super().__getitem__(key)) if key in self else default

    def values(self):
        return [t(v) for v in super().values()]

    def items(self):
        return [(k, t(v)) for k, v in super().items()]
