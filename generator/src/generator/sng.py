"""Lectura de archivos .sng (paquete de charts de Chorus Encore / YARG).

Formato (SngFileFormat de Geomitron): cabecera "SNGPKG", versión, máscara XOR de
16 bytes, metadatos (pares clave/valor), índice de archivos y contenido. Cada
byte del contenido va enmascarado con mask[i % 16] ^ (i & 0xFF).
"""

import struct
from pathlib import Path


def read_sng(path: Path) -> tuple[dict[str, str], dict[str, bytes]]:
    data = path.read_bytes()
    if data[:6] != b"SNGPKG":
        raise ValueError(f"{path.name} no es un .sng")
    pos = 6
    (_version,) = struct.unpack_from("<I", data, pos); pos += 4
    mask = data[pos:pos + 16]; pos += 16

    (_meta_len, meta_count) = struct.unpack_from("<QQ", data, pos); pos += 16
    meta = {}
    for _ in range(meta_count):
        (klen,) = struct.unpack_from("<i", data, pos); pos += 4
        key = data[pos:pos + klen].decode("utf-8"); pos += klen
        (vlen,) = struct.unpack_from("<i", data, pos); pos += 4
        meta[key] = data[pos:pos + vlen].decode("utf-8"); pos += vlen

    (_index_len, file_count) = struct.unpack_from("<QQ", data, pos); pos += 16
    entries = []
    for _ in range(file_count):
        nlen = data[pos]; pos += 1
        name = data[pos:pos + nlen].decode("utf-8"); pos += nlen
        size, offset = struct.unpack_from("<QQ", data, pos); pos += 16
        entries.append((name, size, offset))

    files = {}
    for name, size, offset in entries:
        raw = bytearray(data[offset:offset + size])
        for i in range(len(raw)):
            raw[i] ^= mask[i % 16] ^ (i & 0xFF)
        files[name] = bytes(raw)
    return meta, files
