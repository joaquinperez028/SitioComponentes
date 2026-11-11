"""Benchmarks: solo se comparan filas con la misma prueba, resolución, preset y unidad (D-24)."""

import sqlite3
from dataclasses import dataclass, field
from statistics import mean

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.esquemas import Categoria


class Benchmark(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    prueba: str = Field(min_length=1)          # "Cyberpunk 2077", "Cinebench 2024 Multi"
    resolucion: str = ""                       # "1080p", "" si no aplica
    preset: str = ""                           # "Ultra", "RT Ultra"...
    valor: float
    unidad: str = Field(min_length=1)          # "fps", "pts"
    mayorEsMejor: bool = True
    nombreFuente: str = Field(min_length=1)
    urlFuente: HttpUrl
    fecha: str | None = None
    fragmento: str | None = None


def categoriaDatoBenchmark(categoria: Categoria) -> str:
    return "configuracion_portatil" if categoria == Categoria.portatil else categoria.value


def agregarBenchmark(conexion: sqlite3.Connection, categoria: Categoria, productoId: int, benchmark: Benchmark) -> int:
    with conexion:
        cursor = conexion.execute(
            "INSERT INTO benchmark (categoria, productoId, prueba, resolucion, preset, valor, unidad, mayorEsMejor, "
            "nombreFuente, urlFuente, fecha, fragmento) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                categoriaDatoBenchmark(categoria), productoId, benchmark.prueba, benchmark.resolucion,
                benchmark.preset, benchmark.valor, benchmark.unidad, int(benchmark.mayorEsMejor),
                benchmark.nombreFuente, str(benchmark.urlFuente), benchmark.fecha, benchmark.fragmento,
            ),
        )
    return cursor.lastrowid


def benchmarksDe(conexion, categoria: Categoria, productoId: int) -> list[dict]:
    return [
        dict(fila)
        for fila in conexion.execute(
            "SELECT * FROM benchmark WHERE categoria = ? AND productoId = ? ORDER BY prueba, resolucion, preset",
            (categoriaDatoBenchmark(categoria), productoId),
        )
    ]


def verificarBenchmark(conexion, benchmarkId: int) -> None:
    with conexion:
        conexion.execute("UPDATE benchmark SET estado = 'verificado' WHERE id = ?", (benchmarkId,))


def claveComparacion(fila: dict) -> tuple[str, str, str, str]:
    return tuple(str(fila[c]).strip().casefold() for c in ("prueba", "resolucion", "preset", "unidad"))


@dataclass
class GrupoBenchmark:
    prueba: str
    resolucion: str
    preset: str
    unidad: str
    mayorEsMejor: bool
    filasPorProducto: dict[int, list[dict]] = field(default_factory=dict)

    def media(self, productoId: int) -> float | None:
        filas = self.filasPorProducto.get(productoId)
        return mean(f["valor"] for f in filas) if filas else None

    @property
    def mejorProductoId(self) -> int | None:
        medias = {p: self.media(p) for p in self.filasPorProducto}
        if len(medias) < 2:
            return None
        elegir = max if self.mayorEsMejor else min
        return elegir(medias, key=medias.get)


def compararBenchmarks(conexion, categoria: Categoria, productoIds: list[int]) -> list[GrupoBenchmark]:
    """Agrupa benchmarks comparables. Solo devuelve grupos con datos de al menos dos productos."""
    grupos: dict[tuple, GrupoBenchmark] = {}
    for productoId in productoIds:
        for fila in benchmarksDe(conexion, categoria, productoId):
            clave = claveComparacion(fila) + (bool(fila["mayorEsMejor"]),)
            grupo = grupos.setdefault(
                clave,
                GrupoBenchmark(fila["prueba"], fila["resolucion"], fila["preset"], fila["unidad"], bool(fila["mayorEsMejor"])),
            )
            grupo.filasPorProducto.setdefault(productoId, []).append(fila)
    return [g for g in grupos.values() if len(g.filasPorProducto) >= 2]
