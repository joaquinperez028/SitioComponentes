import pytest

from app.normalizacion import Normalizador, claveNormalizada


@pytest.mark.parametrize(
    "variantes",
    [
        ["RTX 4060 Laptop", "GeForce RTX 4060 Mobile", "NVIDIA GeForce RTX 4060 Laptop GPU", "rtx-4060 notebook"],
        ["Intel® Core™ i7-13700H Processor", "Core i7 13700H", "intel core i7-13700h"],
        ["AMD Ryzen 7 7800X3D", "Ryzen 7 7800X3D", "ryzen 7  7800x3d"],
        ["AMD Ryzen 7 7840HS w/ Radeon 780M Graphics", "Ryzen 7 7840HS"],
        ["AMD Radeon RX 7900 XTX", "RX 7900 XTX"],
        ["Lenovo Legion 5 16IRX9", "Legion 5 16IRX9"],
    ],
)
def test_variantes_del_mismo_producto_dan_la_misma_clave(variantes):
    claves = {claveNormalizada(v) for v in variantes}
    assert len(claves) == 1, claves


@pytest.mark.parametrize(
    "nombreA, nombreB",
    [
        ("RTX 4060", "RTX 4060 Laptop"),          # escritorio frente a móvil
        ("RTX 4060", "RTX 4060 Ti"),
        ("RTX 4070", "RTX 4070 Super"),
        ("Ryzen 7 7800X3D", "Ryzen 7 7800X"),
        ("Core i7-13700H", "Core i7-13700HX"),
        ("RX 7900 XT", "RX 7900 XTX"),
    ],
)
def test_variantes_distintas_no_colisionan(nombreA, nombreB):
    assert claveNormalizada(nombreA) != claveNormalizada(nombreB)


def test_clave_de_texto_vacio_o_solo_marca():
    assert claveNormalizada("") == ""
    assert claveNormalizada("NVIDIA ®") == ""


def _insertarGpu(conexion, nombre, plataforma="movil"):
    cursor = conexion.execute(
        "INSERT INTO gpu (nombre, fabricante, plataforma) VALUES (?, 'NVIDIA', ?)", (nombre, plataforma)
    )
    conexion.commit()
    return cursor.lastrowid


def test_resuelve_por_reglas_y_guarda_alias(conexion):
    gpuId = _insertarGpu(conexion, "GeForce RTX 4060 Laptop GPU")
    normalizador = Normalizador(conexion)

    resultado = normalizador.resolver("gpu", "RTX 4060 Mobile")

    assert resultado.productoId == gpuId and resultado.metodo == "reglas"
    alias = conexion.execute("SELECT * FROM alias").fetchone()
    assert alias["origen"] == "reglas" and alias["productoId"] == gpuId

    # La segunda vez se resuelve directamente por la tabla de alias
    assert normalizador.resolver("gpu", "rtx 4060 mobile").metodo == "alias"


def test_no_confunde_escritorio_con_movil(conexion):
    _insertarGpu(conexion, "GeForce RTX 4060", plataforma="escritorio")
    resultado = Normalizador(conexion).resolver("gpu", "RTX 4060 Laptop")
    assert resultado.productoId is None


def test_sin_candidatos_parecidos_no_llama_a_claude(conexion, crearLlmFalso):
    _insertarGpu(conexion, "GeForce RTX 4060 Laptop GPU")
    llm = crearLlmFalso([])
    resultado = Normalizador(conexion, llm).resolver("gpu", "Radeon RX 7900 XTX")
    assert resultado.metodo == "no_encontrado" and llm.llamadas == []


def test_claude_con_confianza_alta_guarda_alias(conexion, crearLlmFalso):
    gpuId = _insertarGpu(conexion, "GeForce RTX 4060 Laptop GPU")
    llm = crearLlmFalso([{"productoId": gpuId, "confianza": 0.95, "motivo": "mismo chip AD107"}])

    resultado = Normalizador(conexion, llm).resolver("gpu", "RTX4060 Laptop 8GB GDDR6")

    assert resultado.metodo == "claude" and resultado.productoId == gpuId
    assert conexion.execute("SELECT origen FROM alias").fetchone()["origen"] == "claude"


def test_claude_con_confianza_baja_deja_pendiente(conexion, crearLlmFalso):
    gpuId = _insertarGpu(conexion, "GeForce RTX 4060 Laptop GPU")
    llm = crearLlmFalso([{"productoId": gpuId, "confianza": 0.5, "motivo": "dudoso"}])
    normalizador = Normalizador(conexion, llm)

    resultado = normalizador.resolver("gpu", "RTX 4060 Laptop 8GB GDDR6")

    assert resultado.requiereConfirmacion and resultado.metodo == "pendiente"
    assert conexion.execute("SELECT COUNT(*) FROM alias").fetchone()[0] == 0

    normalizador.confirmarPendiente(resultado.aliasPendienteId, gpuId)
    assert normalizador.resolver("gpu", "RTX 4060 Laptop 8GB GDDR6").metodo == "alias"
    estado = conexion.execute("SELECT estado FROM alias_pendiente").fetchone()["estado"]
    assert estado == "confirmado"


def test_claude_que_inventa_un_id_no_se_acepta(conexion, crearLlmFalso):
    _insertarGpu(conexion, "GeForce RTX 4060 Laptop GPU")
    llm = crearLlmFalso([{"productoId": 999, "confianza": 0.99}])
    resultado = Normalizador(conexion, llm).resolver("gpu", "RTX 4060 Laptop 8GB")
    assert resultado.productoId is None
    assert conexion.execute("SELECT COUNT(*) FROM alias").fetchone()[0] == 0


def test_respuesta_rota_de_claude_queda_pendiente(conexion, crearLlmFalso):
    _insertarGpu(conexion, "GeForce RTX 4060 Laptop GPU")
    llm = crearLlmFalso(["esto no es json"])
    resultado = Normalizador(conexion, llm).resolver("gpu", "RTX 4060 Laptop 8GB")
    assert resultado.requiereConfirmacion
