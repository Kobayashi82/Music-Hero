"""Menús del overlay: lista de opciones que se recorre con el strum. Sin Qt (la vista solo pinta view()).

- Strum arriba/abajo: mover. Verde, + o Intro: elegir. Rojo, − o Retroceso: volver.
- Una opción con valor (change) se elige para editarla: el strum la cambia (arriba sube) y elegir o
  volver deja de editar. Los cambios se aplican en el momento.
- Las listas largas son circulares: se ven por ventanas de WINDOW opciones con la elegida en el centro,
  y al pasar de la última sigue la primera; amarillo / azul saltan PAGE (también dando la vuelta).
- SearchMenu: buscador. Con el teclado se escribe directamente; con la guitarra, en «Escribir» el strum
  elige la letra y verde la añade.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape

WINDOW = 11
PAGE = 10
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
    circular = True  # las listas largas se ven como una rueda
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
        """Salto largo, para las listas largas (da la vuelta, como el strum)."""
        if not self.editing and self.options:
            self.sel = (self.sel + direction * PAGE) % len(self.options)

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
        """Lo que pinta QML: solo la ventana de opciones alrededor de la elegida. En las largas (circulares),
        la elegida va en el centro y wrap es la fila donde vuelve a empezar la lista (-1 si no se ve)."""
        n = len(self.options)
        wrap = -1
        if self.long and self.circular:
            idx = [(self.sel - WINDOW // 2 + i) % n for i in range(WINDOW)]
            sel = WINDOW // 2
            wrap = next((r for r in range(1, WINDOW) if idx[r] == 0), -1)
            above = below = True
        else:
            start = max(0, min(self.sel - WINDOW // 2, n - WINDOW))
            idx = list(range(start, min(n, start + WINDOW)))
            sel = self.sel - start
            above, below = start > 0, start + WINDOW < n
        shown = [self.options[i] for i in idx]
        return {"title": self.title, "body": self.body, "sel": sel, "editing": self.editing,
                "items": [o.label for o in shown], "values": [o.value() if callable(o.value) else (o.value or "") for o in shown],
                "above": above, "below": below, "wrap": wrap, "editHint": self.edit_hint,
                "position": f"{self.sel + 1} / {n}" if self.long else ""}


class SearchMenu(Menu):
    """Buscador: «Escribir» (con la guitarra: strum elige la letra, verde la añade), «Borrar» y debajo los
    resultados de search(texto). Con el teclado, type() y backspace()."""

    circular = False  # «Escribir» siempre arriba
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
