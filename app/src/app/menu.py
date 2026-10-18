"""Menús del overlay: lista de opciones que se recorre con el strum. Sin Qt (la vista solo pinta view()).

- Strum arriba/abajo: mover. Verde, + o Intro: elegir. Rojo, − o Esc: volver.
- Una opción con valor (change) se elige para editarla: el strum la cambia (arriba sube) y elegir o
  volver deja de editar. Los cambios se aplican en el momento.
- Las listas largas se ven por páginas de WINDOW opciones: la página se queda quieta y se mueve la selección;
  al pasar de la última fila se pasa a la página siguiente (con la selección arriba) y, tras la última
  página, a la primera. Amarillo / azul pasan página entera.
- SearchMenu: buscador. Con el teclado se escribe directamente; con la guitarra, en «Escribir» el strum
  elige la letra y verde la añade.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape

WINDOW = 11
LETTERS = "abcdefghijklmnñopqrstuvwxyz0123456789 "


@dataclass
class Option:
    label: str
    action: Callable[[], None] | None = None  # al elegirla
    value: Callable[[], str] | str | None = None  # texto del valor (fijo o calculado al pintar)
    change: Callable[[int], None] | None = None  # +1 sube, -1 baja

    @property
    def editable(self) -> bool:
        return self.change is not None


class Menu:
    edit_hint = ""  # ayuda al editar (vacío: la de siempre)

    def __init__(self, title: str, options: list[Option], body: Callable[[], str] | str = "",
                 on_back: Callable[[], None] | None = None):
        self.title, self.options = title, options
        self._body = body
        self.on_back = on_back
        self.sel = 0
        self.editing = False

    @property
    def body(self) -> str:
        return self._body() if callable(self._body) else self._body

    def move(self, direction: int) -> None:
        """direction: -1 strum arriba, 1 strum abajo."""
        if self.editing:
            self.options[self.sel].change(-direction)
        elif self.options:
            self.sel = (self.sel + direction) % len(self.options)

    def page(self, direction: int) -> None:
        """Página siguiente o anterior, en la misma fila (o la última, si la página es más corta); da la vuelta."""
        if not self.editing and self.options:
            n = len(self.options)
            pages = -(-n // WINDOW)
            p = (self.sel // WINDOW + direction) % pages
            self.sel = min(p * WINDOW + self.sel % WINDOW, n - 1)

    @property
    def long(self) -> bool:
        return len(self.options) > WINDOW

    def select(self) -> None:
        if not self.options:
            return
        opt = self.options[self.sel]
        if opt.editable:
            self.editing = not self.editing
        elif opt.action:
            opt.action()

    def back(self) -> bool:
        """True si lo ha resuelto el propio menú (dejar de editar); si no, toca cerrarlo."""
        if self.editing:
            self.editing = False
            return True
        return False

    def view(self) -> dict:
        """Lo que pinta QML: la página de la elegida. En las largas, la última página se rellena con filas vacías
        (rows -1) para que el menú no cambie de alto."""
        n = len(self.options)
        start = self.sel // WINDOW * WINDOW if self.long else 0
        idx = list(range(start, min(n, start + WINDOW)))
        shown = [self.options[i] for i in idx]
        pad = WINDOW - len(idx) if self.long else 0
        items = [o.label for o in shown] + [""] * pad
        values = [o.value() if callable(o.value) else (o.value or "") for o in shown] + [""] * pad
        pages = -(-n // WINDOW)
        return {"title": self.title, "body": self.body, "sel": self.sel - start, "editing": self.editing,
                "items": items, "values": values, "rows": idx + [-1] * pad,
                "above": start > 0, "below": start + WINDOW < n, "editHint": self.edit_hint,
                "position": f"{self.sel + 1} / {n} · página {start // WINDOW + 1} de {pages}" if self.long else ""}


class SearchMenu(Menu):
    """Buscador: «Escribir» (con la guitarra: strum elige la letra, verde la añade), «Borrar» y debajo los
    resultados de search(texto). Con el teclado, type() y backspace()."""

    edit_hint = "Strum: letra · Verde / +: añadirla · Rojo / −: listo"
    FIXED = 2  # opciones antes de los resultados

    def __init__(self, title: str, search: Callable[[str], list[Option]], on_back: Callable[[], None] | None = None):
        super().__init__(title, [], body=self._describe, on_back=on_back)
        self.query = ""
        self.letter = 0
        self._search = search
        self._results: list[Option] = []
        self._refresh()

    def _describe(self) -> str:
        if not self.query.strip():
            return "Escribe con el teclado, o con la guitarra en «Escribir».<br>Buscar: <b>_</b>"
        n = len(self._results)
        found = "nada" if n == 0 else "1 canción" if n == 1 else f"{n} canciones"
        return f"Buscar: <b>{escape(self.query)}_</b> · {found}"

    def _change_letter(self, d: int) -> None:
        self.letter = (self.letter + d) % len(LETTERS)

    def _letter_value(self) -> str:
        c = LETTERS[self.letter]
        return "espacio" if c == " " else c.upper()

    def _refresh(self) -> None:
        self._results = self._search(self.query) if self.query.strip() else []
        self.options = [Option("Escribir", value=self._letter_value, change=self._change_letter),
                        Option("Borrar letra", self.backspace)] + self._results
        self.sel = min(self.sel, len(self.options) - 1)

    def type(self, text: str) -> None:
        """Teclado: añade y deja elegido el primer resultado (Intro lo pone)."""
        self.query += text
        self.editing = False
        self._refresh()
        self.sel = self.FIXED if self._results else 0

    def backspace(self) -> None:
        self.query = self.query[:-1]
        self._refresh()

    def select(self) -> None:
        if self.sel == 0 and self.editing:  # guitarra: verde añade la letra y se sigue escribiendo
            self.query += LETTERS[self.letter]
            self._refresh()
            return
        super().select()


def stepper(get: Callable[[], float], set_: Callable[[float], None], step: float, lo: float, hi: float
            ) -> Callable[[int], None]:
    """change() para un valor numérico con paso y límites."""
    def change(d: int) -> None:
        set_(round(min(hi, max(lo, get() + d * step)), 6))
    return change


def cycler(values: list, get: Callable[[], object], set_: Callable[[object], None]) -> Callable[[int], None]:
    """change() que recorre una lista dando la vuelta (Sí -> No -> Sí...)."""
    def change(d: int) -> None:
        cur = get()
        i = values.index(cur) if cur in values else 0
        set_(values[(i + d) % len(values)])
    return change
