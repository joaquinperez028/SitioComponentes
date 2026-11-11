"""Conexión a SQLite y migraciones versionadas (archivos NNN_nombre.sql)."""

import sqlite3
from pathlib import Path

DIRECTORIO_MIGRACIONES = Path(__file__).parent / "migraciones"


def abrirConexion(rutaBd: Path | str) -> sqlite3.Connection:
    rutaTexto = str(rutaBd)
    if rutaTexto != ":memory:":
        Path(rutaTexto).parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(rutaTexto, timeout=30, check_same_thread=False)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    if rutaTexto != ":memory:":
        conexion.execute("PRAGMA journal_mode = WAL")
    return conexion


def migrar(conexion: sqlite3.Connection) -> list[str]:
    """Aplica las migraciones pendientes en orden. Devuelve los nombres aplicados."""
    conexion.execute(
        "CREATE TABLE IF NOT EXISTS esquema_version ("
        " nombre TEXT PRIMARY KEY, aplicadaEn TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    aplicadas = {fila["nombre"] for fila in conexion.execute("SELECT nombre FROM esquema_version")}
    nuevas = []
    for archivo in sorted(DIRECTORIO_MIGRACIONES.glob("*.sql")):
        if archivo.name in aplicadas:
            continue
        with conexion:
            conexion.executescript(archivo.read_text(encoding="utf-8"))
            conexion.execute("INSERT INTO esquema_version (nombre) VALUES (?)", (archivo.name,))
        nuevas.append(archivo.name)
    return nuevas
