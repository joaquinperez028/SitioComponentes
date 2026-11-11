import time

import pytest

from app.db import abrirConexion
from app.trabajos import ColaTrabajos, TipoTrabajoDesconocido


def test_encolar_y_procesar(rutaBd):
    vistos = []
    cola = ColaTrabajos(rutaBd, {"sumar": lambda p, c: vistos.append(p) or {"total": p["a"] + p["b"], "mensaje": "ok"}})

    trabajoId = cola.encolar("sumar", {"a": 2, "b": 3})
    assert cola.obtener(trabajoId)["estado"] == "pendiente"

    assert cola.procesarPendientes() == 1
    trabajo = cola.obtener(trabajoId)
    assert trabajo["estado"] == "completado"
    assert trabajo["resultado"] == {"total": 5}
    assert trabajo["mensaje"] == "ok"
    assert vistos == [{"a": 2, "b": 3}]


def test_orden_de_llegada(rutaBd):
    orden = []
    cola = ColaTrabajos(rutaBd, {"t": lambda p, c: orden.append(p["n"])})
    for n in range(3):
        cola.encolar("t", {"n": n})
    cola.procesarPendientes()
    assert orden == [0, 1, 2]


def test_un_error_queda_registrado_y_no_frena_la_cola(rutaBd):
    def fallar(parametros, conexion):
        raise RuntimeError("la web no respondió")

    cola = ColaTrabajos(rutaBd, {"falla": fallar, "ok": lambda p, c: {}})
    idFallo = cola.encolar("falla", {})
    idBien = cola.encolar("ok", {})
    cola.procesarPendientes()
    fallo = cola.obtener(idFallo)
    assert fallo["estado"] == "error" and "la web no respondió" in fallo["mensaje"]
    assert cola.obtener(idBien)["estado"] == "completado"


def test_tipo_desconocido(rutaBd):
    with pytest.raises(TipoTrabajoDesconocido):
        ColaTrabajos(rutaBd, {}).encolar("nada", {})


def test_trabajos_interrumpidos_se_retoman_al_reiniciar(rutaBd):
    # Simula un cierre a mitad de trabajo: queda 'en_curso' en la BD
    conexion = abrirConexion(rutaBd)
    with conexion:
        conexion.execute("INSERT INTO trabajo (tipo, parametros, estado) VALUES ('t', '{\"n\": 1}', 'en_curso')")
    conexion.close()

    ejecutados = []
    cola = ColaTrabajos(rutaBd, {"t": lambda p, c: ejecutados.append(p["n"])})
    assert cola.reanudarInterrumpidos() == 1
    cola.procesarPendientes()
    assert ejecutados == [1]


def test_detecta_trabajo_activo_duplicado(rutaBd):
    cola = ColaTrabajos(rutaBd, {"t": lambda p, c: {}})
    trabajoId = cola.encolar("t", {"b": 1, "a": 2})
    assert cola.buscarActivo("t", {"a": 2, "b": 1})["id"] == trabajoId  # el orden de claves no importa
    cola.procesarPendientes()
    assert cola.buscarActivo("t", {"a": 2, "b": 1}) is None


def test_hilo_trabajador_procesa_en_segundo_plano(rutaBd):
    cola = ColaTrabajos(rutaBd, {"t": lambda p, c: {"hecho": True}}, intervaloSegundos=0.05)
    cola.iniciar()
    try:
        trabajoId = cola.encolar("t", {})
        limite = time.monotonic() + 5
        while cola.obtener(trabajoId)["estado"] != "completado" and time.monotonic() < limite:
            time.sleep(0.02)
        assert cola.obtener(trabajoId)["resultado"] == {"hecho": True}
    finally:
        cola.detener()
