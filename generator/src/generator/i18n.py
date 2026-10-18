"""Idioma de los avisos del generador (consola de generate y lyrics, motor, descarga de modelos): los textos van
en español en el código y t() los traduce (inglés en lang_en.py).

    t("notas: {n}", n=...)   -> el texto en el idioma de ahora, con los campos puestos (str.format)

El idioma: MUSICHERO_LANG ("es" o "en"; la app se lo pasa al motor con el que haya elegido) o, si no está, el de
Windows (español si lo es, si no inglés). tests/test_i18n.py comprueba que todo t("...") tiene su traducción.
"""

from __future__ import annotations

import ctypes
import os

from .lang_en import EN


def windows_lang() -> str:
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "en"
    return "es" if lid & 0x3FF == 0x0A else "en"


def lang() -> str:
    env = os.environ.get("MUSICHERO_LANG")
    return env if env in ("es", "en") else windows_lang()


def t(text: str, **fields) -> str:
    if lang() == "en":
        text = EN.get(text, text)
    return text.format(**fields) if fields else text
