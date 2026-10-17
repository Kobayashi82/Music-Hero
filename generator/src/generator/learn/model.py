"""Red que predice, por fotograma y dificultad, dónde pondría una persona una nota.

Entrada (B, T, 83): log-mel (80) + pulso/compás de Beat This (2) + estilo (1: chart
de Harmonix, más sobria; 0: de la comunidad). Los modelos v1 no tienen estilo (82).
Salida (B, T, 12): logits de inicio de nota (4), nota sostenida (4) y acorde (4),
en el orden Experto, Difícil, Medio, Fácil. Con botones (v4+), además 4 x 32 logits:
la combinación de botones de la nota por dificultad (clase = máscara de bits, verde = 1).

Convoluciones sobre el espectrograma (timbre y ataques locales) + GRU
bidireccional (contexto de frase: repeticiones, notas largas, dónde respira la
música).
"""

import torch
import torch.nn as nn

N_MELS = 80
N_EXTRA = 3  # pulso, compás, estilo
N_DIFFS = 4
N_COMBOS = 32  # combinaciones de 5 botones; la 0 (ninguno) no se usa


def combo(frets) -> int:
    return sum(1 << int(f) for f in frets)


def combo_frets(c: int) -> list[int]:
    return [f for f in range(5) if c >> f & 1]


class OnsetNet(nn.Module):
    def __init__(self, hidden: int = 256, layers: int = 2, dropout: float = 0.2, n_extra: int = N_EXTRA,
                 frets: bool = False):
        super().__init__()
        self.n_extra = n_extra
        self.frets = frets
        self.n_out = 3 * N_DIFFS + (N_DIFFS * N_COMBOS if frets else 0)
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, (3, 7), padding=(1, 3)), nn.BatchNorm2d(32), nn.GELU(), nn.MaxPool2d((1, 3)),
            nn.Conv2d(32, 64, (3, 3), padding=1), nn.BatchNorm2d(64), nn.GELU(), nn.MaxPool2d((1, 3)),
            nn.Conv2d(64, 64, (3, 3), padding=1), nn.BatchNorm2d(64), nn.GELU(), nn.MaxPool2d((1, 3)),
        )
        conv_out = 64 * (N_MELS // 27)
        self.proj = nn.Sequential(nn.Linear(conv_out + n_extra, hidden), nn.GELU(), nn.Dropout(dropout))
        self.rnn = nn.GRU(hidden, hidden, num_layers=layers, batch_first=True, bidirectional=True,
                          dropout=dropout if layers > 1 else 0)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(2 * hidden, self.n_out))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        mel, extra = x[..., :N_MELS], x[..., N_MELS:]
        b, t, _ = mel.shape
        h = self.conv(mel.unsqueeze(1))  # (B, C, T, F')
        h = h.permute(0, 2, 1, 3).reshape(b, t, -1)
        h = self.proj(torch.cat([h, extra], dim=-1))
        h, _ = self.rnn(h)
        return self.head(h)
