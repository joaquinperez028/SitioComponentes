-- Fase 1: CPU, GPU y portátiles. Una tabla por categoría con columnas tipadas (D-29).

CREATE TABLE cpu (
    id                INTEGER PRIMARY KEY,
    nombre            TEXT NOT NULL UNIQUE,          -- nombre canónico
    fabricante        TEXT NOT NULL,
    plataforma        TEXT NOT NULL CHECK (plataforma IN ('escritorio', 'movil')),
    nucleos           INTEGER,
    hilos             INTEGER,
    relojBaseGhz      REAL,
    relojBoostGhz     REAL,
    tdpW              INTEGER,
    cacheL3Mb         REAL,
    socket            TEXT,
    fechaLanzamiento  TEXT,
    urlFuente         TEXT,
    creadoEn          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_cpu_filtros ON cpu (fabricante, plataforma, nucleos, tdpW);

CREATE TABLE gpu (
    id                INTEGER PRIMARY KEY,
    nombre            TEXT NOT NULL UNIQUE,
    fabricante        TEXT NOT NULL,
    plataforma        TEXT NOT NULL CHECK (plataforma IN ('escritorio', 'movil')),
    vramGb            REAL,
    tipoVram          TEXT,
    anchoBusBits      INTEGER,
    unidadesShader    INTEGER,
    relojBoostMhz     INTEGER,
    tdpW              INTEGER,                        -- escritorio: TBP. Móvil: TGP máximo de referencia
    fechaLanzamiento  TEXT,
    urlFuente         TEXT,
    creadoEn          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_gpu_filtros ON gpu (fabricante, plataforma, vramGb, tdpW);

-- Portátiles: modelo padre + configuraciones hijas (D-09)
CREATE TABLE modelo_portatil (
    id                 INTEGER PRIMARY KEY,
    nombre             TEXT NOT NULL UNIQUE,
    fabricante         TEXT NOT NULL,
    pantallaPulgadas   REAL,
    resolucionPantalla TEXT,
    tasaRefrescoHz     INTEGER,
    tipoPanel          TEXT,
    pesoKg             REAL,
    refrigeracion      TEXT,
    bateriaWh          REAL,
    urlFuente          TEXT,
    creadoEn           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- El TGP y los límites de potencia van por configuración, no por GPU (D-10)
CREATE TABLE configuracion_portatil (
    id                INTEGER PRIMARY KEY,
    modeloId          INTEGER NOT NULL REFERENCES modelo_portatil (id) ON DELETE CASCADE,
    nombre            TEXT NOT NULL UNIQUE,           -- p. ej. "Legion 5 16IRX9 (i7-14650HX / RTX 4060)"
    cpuId             INTEGER REFERENCES cpu (id),
    gpuId             INTEGER REFERENCES gpu (id),     -- NULL si solo hay gráfica integrada
    cpuNombreOriginal TEXT,                           -- texto tal cual en la fuente, por si no se pudo enlazar
    gpuNombreOriginal TEXT,
    tgpW              INTEGER,
    pl1W              INTEGER,
    pl2W              INTEGER,
    ramGb             INTEGER,
    almacenamientoGb  INTEGER,
    urlFuente         TEXT,
    creadoEn          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_config_filtros ON configuracion_portatil (cpuId, gpuId, tgpW, ramGb);

-- Normalización de nombres: alias -> producto canónico (D-21)
CREATE TABLE alias (
    id          INTEGER PRIMARY KEY,
    categoria   TEXT NOT NULL,
    alias       TEXT NOT NULL,
    clave       TEXT NOT NULL,                        -- alias normalizado por reglas
    productoId  INTEGER NOT NULL,
    origen      TEXT NOT NULL CHECK (origen IN ('reglas', 'claude', 'manual')),
    creadoEn    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (categoria, clave)
);

-- Alias propuestos por Claude con baja confianza: requieren confirmación manual
CREATE TABLE alias_pendiente (
    id                   INTEGER PRIMARY KEY,
    categoria            TEXT NOT NULL,
    alias                TEXT NOT NULL,
    productoIdPropuesto  INTEGER,
    confianza            REAL NOT NULL,
    motivo               TEXT,
    estado               TEXT NOT NULL DEFAULT 'pendiente'
                         CHECK (estado IN ('pendiente', 'confirmado', 'rechazado')),
    creadoEn             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Cada spec guarda fuente, fragmento de origen y estado de verificación (D-25)
CREATE TABLE dato_verificable (
    id                   INTEGER PRIMARY KEY,
    categoria            TEXT NOT NULL,              -- cpu, gpu, modelo_portatil, configuracion_portatil
    productoId           INTEGER NOT NULL,
    campo                TEXT NOT NULL,
    valor                TEXT,
    urlFuente            TEXT,
    fragmento            TEXT,
    fragmentoEncontrado  INTEGER NOT NULL DEFAULT 0, -- 1 si el fragmento aparece literalmente en la página
    estado               TEXT NOT NULL DEFAULT 'sin_verificar'
                         CHECK (estado IN ('sin_verificar', 'verificado')),
    UNIQUE (categoria, productoId, campo)
);

-- Benchmarks comparables solo con la misma prueba, resolución y preset (D-24)
CREATE TABLE benchmark (
    id            INTEGER PRIMARY KEY,
    categoria     TEXT NOT NULL,
    productoId    INTEGER NOT NULL,
    prueba        TEXT NOT NULL,
    resolucion    TEXT NOT NULL DEFAULT '',
    preset        TEXT NOT NULL DEFAULT '',
    valor         REAL NOT NULL,
    unidad        TEXT NOT NULL,
    mayorEsMejor  INTEGER NOT NULL DEFAULT 1,
    nombreFuente  TEXT NOT NULL,
    urlFuente     TEXT NOT NULL,
    fecha         TEXT,
    fragmento     TEXT,
    estado        TEXT NOT NULL DEFAULT 'sin_verificar'
                  CHECK (estado IN ('sin_verificar', 'verificado'))
);
CREATE INDEX idx_benchmark_producto ON benchmark (categoria, productoId);

-- Lista blanca editable de fuentes de rendimiento (D-15)
CREATE TABLE fuente_lista_blanca (
    id             INTEGER PRIMARY KEY,
    nombre         TEXT NOT NULL UNIQUE,
    tipo           TEXT NOT NULL CHECK (tipo IN ('web', 'reddit', 'youtube')),
    identificador  TEXT NOT NULL,                    -- dominio, subreddit o canal
    activa         INTEGER NOT NULL DEFAULT 1
);

INSERT INTO fuente_lista_blanca (nombre, tipo, identificador) VALUES
    ('Notebookcheck',     'web',     'notebookcheck.net'),
    ('TechPowerUp',       'web',     'techpowerup.com'),
    ('Phoronix',          'web',     'phoronix.com'),
    ('Gamers Nexus',      'youtube', 'GamersNexus'),
    ('Hardware Unboxed',  'youtube', 'Hardwareunboxed'),
    ('r/hardware',        'reddit',  'hardware'),
    ('r/GamingLaptops',   'reddit',  'GamingLaptops');

-- Resúmenes de rendimiento generados por Claude, con revisión del usuario (D-22, D-23)
CREATE TABLE resumen_rendimiento (
    id          INTEGER PRIMARY KEY,
    categoria   TEXT NOT NULL,
    productoId  INTEGER NOT NULL,
    texto       TEXT NOT NULL,
    citas       TEXT NOT NULL DEFAULT '[]',          -- JSON: [{"numero", "nombreFuente", "url"}]
    estado      TEXT NOT NULL DEFAULT 'sin_verificar'
                CHECK (estado IN ('sin_verificar', 'verificado')),
    creadoEn    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Cola de trabajos en segundo plano (D-31)
CREATE TABLE trabajo (
    id             INTEGER PRIMARY KEY,
    tipo           TEXT NOT NULL,
    parametros     TEXT NOT NULL DEFAULT '{}',
    estado         TEXT NOT NULL DEFAULT 'pendiente'
                   CHECK (estado IN ('pendiente', 'en_curso', 'completado', 'error')),
    mensaje        TEXT,
    resultado      TEXT,
    creadoEn       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizadoEn  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_trabajo_estado ON trabajo (estado, id);
