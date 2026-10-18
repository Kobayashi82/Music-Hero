"""Menús del overlay: lista de opciones que se recorre con el strum. Sin Qt (la vista solo pinta view()).

- Strum arriba/abajo: mover. Verde, + o Intro: elegir. Rojo, − o Retroceso: volver.
- Una opción con valor (change) se elige para editarla: el strum la cambia (arriba sube) y elegir o
  volver deja de editar. Los cambios se aplican en el momento.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Option:
    label: str
    action: Callable[[], None] | None = None  # al elegirla
    value: Callable[[], str] | None = None  # texto del valor actual
    change: Callable[[int], None] | None = None  # +1 sube, -1 baja

    @property
    def editable(self) -> bool:
        return self.change is not None


class Menu:
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
        else:
            self.sel = (self.sel + direction) % len(self.options)

    def select(self) -> None:
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
        return {"title": self.title, "body": self.body, "sel": self.sel, "editing": self.editing,
                "items": [o.label for o in self.options],
                "values": [o.value() if o.value else "" for o in self.options]}


def stepper(get: Callable[[], float], set_: Callable[[float], None], step: float, lo: float, hi: float
            ) -> Callable[[int], None]:
    """change() para un valor numérico con paso y límites."""
    def change(d: int) -> None:
        set_(round(min(hi, max(lo, get() + d * step)), 6))
    return change


def cycler(values: list, get: Callable[[], object], set_: Callable[[object], None]) -> Callable[[int], None]:
    """change() que recorre una lista (sin dar la vuelta)."""
    def change(d: int) -> None:
        cur = get()
        i = values.index(cur) if cur in values else 0
        set_(values[min(len(values) - 1, max(0, i + d))])
    return change
