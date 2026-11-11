"""Cola de trabajos en segundo plano dentro del proceso, con el estado en SQLite (D-31).

- Un hilo trabajador procesa los trabajos de uno en uno, en orden de llegada.
- Al iniciar, los trabajos que quedaron `en_curso` (la app se cerró a mitad) vuelven a `pendiente`.
- Cada manejador recibe (parametros, conexion) y devuelve un dict con el resultado.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Callable

from app.db import abrirConexion

registro = logging.getLogger(__name__)

Manejador = Callable[[dict, sqlite3.Connection], dict | None]


class TipoTrabajoDesconocido(ValueError):
    pass


def _filaATrabajo(fila: sqlite3.Row | None) -> dict | None:
    if fila is None:
        return None
    trabajo = dict(fila)
    trabajo["parametros"] = json.loads(trabajo["parametros"] or "{}")
    trabajo["resultado"] = json.loads(trabajo["resultado"]) if trabajo["resultado"] else None
    return trabajo


class ColaTrabajos:
    def __init__(self, rutaBd: Path | str, manejadores: dict[str, Manejador], intervaloSegundos: float = 1.0):
        self.rutaBd = rutaBd
        self.manejadores = manejadores
        self.intervaloSegundos = intervaloSegundos
        self._hayTrabajo = threading.Event()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None

    # --- API pública --------------------------------------------------------------------------

    def encolar(self, tipo: str, parametros: dict) -> int:
        if tipo not in self.manejadores:
            raise TipoTrabajoDesconocido(tipo)
        conexion = abrirConexion(self.rutaBd)
        try:
            with conexion:
                cursor = conexion.execute(
                    "INSERT INTO trabajo (tipo, parametros) VALUES (?, ?)",
                    (tipo, json.dumps(parametros, ensure_ascii=False, sort_keys=True)),
                )
        finally:
            conexion.close()
        self._hayTrabajo.set()
        return cursor.lastrowid

    def buscarActivo(self, tipo: str, parametros: dict) -> dict | None:
        """Trabajo pendiente o en curso con los mismos parámetros, para no lanzar duplicados."""
        conexion = abrirConexion(self.rutaBd)
        try:
            fila = conexion.execute(
                "SELECT * FROM trabajo WHERE tipo = ? AND parametros = ? AND estado IN ('pendiente', 'en_curso') "
                "ORDER BY id LIMIT 1",
                (tipo, json.dumps(parametros, ensure_ascii=False, sort_keys=True)),
            ).fetchone()
            return _filaATrabajo(fila)
        finally:
            conexion.close()

    def obtener(self, trabajoId: int) -> dict | None:
        conexion = abrirConexion(self.rutaBd)
        try:
            return _filaATrabajo(conexion.execute("SELECT * FROM trabajo WHERE id = ?", (trabajoId,)).fetchone())
        finally:
            conexion.close()

    def reanudarInterrumpidos(self) -> int:
        conexion = abrirConexion(self.rutaBd)
        try:
            with conexion:
                cursor = conexion.execute(
                    "UPDATE trabajo SET estado = 'pendiente', mensaje = 'Reanudado tras reinicio', "
                    "actualizadoEn = CURRENT_TIMESTAMP WHERE estado = 'en_curso'"
                )
            return cursor.rowcount
        finally:
            conexion.close()

    def procesarSiguiente(self) -> bool:
        """Procesa un trabajo pendiente. Devuelve False si no había ninguno."""
        conexion = abrirConexion(self.rutaBd)
        try:
            with conexion:
                fila = conexion.execute(
                    "UPDATE trabajo SET estado = 'en_curso', actualizadoEn = CURRENT_TIMESTAMP "
                    "WHERE id = (SELECT id FROM trabajo WHERE estado = 'pendiente' ORDER BY id LIMIT 1) "
                    "RETURNING *"
                ).fetchone()
            trabajo = _filaATrabajo(fila)
            if trabajo is None:
                return False
            self._ejecutar(conexion, trabajo)
            return True
        finally:
            conexion.close()

    def procesarPendientes(self) -> int:
        procesados = 0
        while self.procesarSiguiente():
            procesados += 1
        return procesados

    def iniciar(self) -> None:
        if self._hilo and self._hilo.is_alive():
            return
        reanudados = self.reanudarInterrumpidos()
        if reanudados:
            registro.info("Reanudando %s trabajos interrumpidos", reanudados)
        self._parar.clear()
        self._hayTrabajo.set()
        self._hilo = threading.Thread(target=self._bucle, name="cola-trabajos", daemon=True)
        self._hilo.start()

    def detener(self, tiempoEspera: float = 5.0) -> None:
        self._parar.set()
        self._hayTrabajo.set()
        if self._hilo:
            self._hilo.join(tiempoEspera)
            self._hilo = None

    # --- Interno -------------------------------------------------------------------------------

    def _bucle(self) -> None:
        while not self._parar.is_set():
            self._hayTrabajo.wait(self.intervaloSegundos)
            self._hayTrabajo.clear()
            try:
                while not self._parar.is_set() and self.procesarSiguiente():
                    pass
            except Exception:  # noqa: BLE001 - el hilo no debe morir por un error de BD puntual
                registro.exception("Error en el bucle de la cola de trabajos")

    def _ejecutar(self, conexion: sqlite3.Connection, trabajo: dict) -> None:
        manejador = self.manejadores.get(trabajo["tipo"])
        try:
            if manejador is None:
                raise TipoTrabajoDesconocido(trabajo["tipo"])
            resultado = manejador(trabajo["parametros"], conexion) or {}
            estado, mensaje = "completado", resultado.pop("mensaje", None)
        except Exception as error:  # noqa: BLE001 - cualquier fallo se guarda en el trabajo
            registro.exception("Trabajo %s falló", trabajo["id"])
            estado, mensaje, resultado = "error", f"{type(error).__name__}: {error}", None
        with conexion:
            conexion.execute(
                "UPDATE trabajo SET estado = ?, mensaje = ?, resultado = ?, actualizadoEn = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (estado, mensaje, json.dumps(resultado, ensure_ascii=False) if resultado is not None else None, trabajo["id"]),
            )
