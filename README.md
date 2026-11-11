# SitioComponentes

Comparador local y personal de especificaciones y rendimiento de componentes y equipos informáticos.
El plan está en `docs/PLAN.md` y las decisiones en `docs/decisiones.md` (Project de Claude).

**Estado:** primera versión de la fase 1 (CPU, GPU y portátiles).

## Puesta en marcha

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env          # completar ANTHROPIC_API_KEY
uvicorn app.main:app --reload # http://127.0.0.1:8000
```

## Pruebas

```bash
pytest
```

Todas las pruebas son deterministas y sin red (D-33): el HTML de fabricantes está en
`tests/fixtures/html/` y las respuestas de Claude en `tests/fixtures/respuestas_claude/`.
La API de Claude y Playwright se sustituyen por dobles.

> Las fixtures HTML actuales son **sintéticas** (imitan la estructura de Intel ARK, AMD, NVIDIA y PSREF).
> Conviene reemplazarlas por páginas reales guardadas desde el navegador; las pruebas no deberían cambiar.

## Cómo funciona

1. **Búsqueda** (`/buscar`): si el producto está en la BD se muestra al instante (clave normalizada + alias).
2. Si no está, se pega la URL de la ficha oficial y se lanza un **trabajo en segundo plano**
   (`importar_producto`). La página sondea su estado con HTMX cada 2 s.
3. El trabajo descarga la página con Playwright, Claude extrae las specs al esquema de la categoría
   con valor **y fragmento literal** de cada dato, Pydantic valida, y se comprueba que cada fragmento
   aparezca en la página. Lo que no aparece se marca "⚠ cita no encontrada".
4. Cada spec queda `sin_verificar` con su fuente y fragmento; se valida con un clic en la ficha.
5. **Catálogo** (`/catalogo/{cpu|gpu|portatil}`) con los filtros básicos de D-08 y casillas para
   **comparar** de 2 a 4 productos (`/comparar/...`). Se destaca el mejor valor por fila (no en TDP).
6. **Benchmarks**: solo se enfrentan filas con la misma prueba, resolución, preset y unidad.
7. **Portátiles**: `modelo_portatil` + `configuracion_portatil`; CPU y GPU se enlazan al catálogo con
   el normalizador; el TGP va por configuración.
8. **Normalización**: reglas → tabla de alias → Claude elige entre candidatos parecidos → si la
   confianza es baja, queda en `/alias-pendientes` para confirmar a mano.

## Estructura

```
app/
  config.py            .env → Configuracion
  db/                  conexión SQLite y migraciones versionadas (migraciones/NNN_*.sql)
  esquemas.py          Pydantic por categoría; etiquetas en inglés; qué valor es "mejor"
  normalizacion.py     claves por reglas, alias, respaldo con Claude, pendientes
  extraccion/          HTML → texto, descarga con Playwright, extractor con Claude
  repositorios.py      guardar/leer productos y datos verificables, búsqueda
  filtros.py           filtros básicos → SQL parametrizado
  benchmarks.py        alta, verificación y agrupación comparable
  comparador.py        tabla lado a lado de 2–4 productos
  rendimiento.py       lista blanca, resúmenes con citas, interfaz de recolectores
  trabajos.py          cola en proceso con estado en SQLite; reanuda al reiniciar
  servicios.py         casos de uso y manejadores de trabajos
  web/                 FastAPI + Jinja2 + HTMX
tests/                 pytest + fixtures
```

Convenciones (D-34): clases en español con mayúscula inicial; variables **y funciones** en camelCase y en español.

## Pendiente en la fase 1

- **Recolectores de reviews** (Reddit API, YouTube Data API + transcripciones, webs de la lista blanca).
  El botón "Buscar fuentes nuevas", el filtrado por lista blanca, el resumen con citas y su verificación
  ya funcionan; falta implementar los recolectores (`RecolectorFuentes` en `app/rendimiento.py`).
- **Extracción de benchmarks** desde las reviews (la tabla, la comparabilidad y la verificación ya existen).
- **Localizar la ficha oficial automáticamente**: por ahora la importación pide la URL.
- **Semilla del catálogo** desde Wikipedia/TechPowerUp (últimos ~5 años).
- Edición de la lista blanca desde la interfaz (hoy, en la tabla `fuente_lista_blanca`).
