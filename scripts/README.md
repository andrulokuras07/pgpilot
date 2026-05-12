# scripts

Scripts auxiliares del proyecto. No son código de producto: son
instrumentación, mediciones puntuales y utilidades operativas.

## Scripts disponibles

### `measure_c1_coverage.py`

Mide cobertura empírica del detector C1
(`detect_seq_scan_on_large_table`) contra las 20 queries plantadas en
AppDB v1.

**Qué hace:**

1. Conecta a AppDB con `conector.create_pool` (read-only forzado).
2. Extrae `SchemaSnapshot` (schema + sizes + stats).
3. Por cada query representativa Q01..Q20: corre
   `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, parsea con
   `motor.parse_explain`, llama el detector y el recomendador.
4. Compara contra un triage manual (`c1_target=True/False`) basado
   en el schema y en el código del detector.
5. Imprime tabla en Markdown con veredictos TP/FP/FN/TN y un resumen
   con recall + cobertura global respecto a la rúbrica.

**Uso:**

```bash
docker compose up appdb -d
source .venv/bin/activate
python -m scripts.measure_c1_coverage
```

Variables de entorno opcionales (defaults en `.env.example`):
`APPDB_HOST`, `APPDB_PORT`, `APPDB_DB`, `APPDB_USER`, `APPDB_PASSWORD`.

**Cuándo correrlo:** cuando se agregue/modifique un detector y se
quiera reverificar el número de cobertura para la rúbrica. Cada
detector nuevo debería sumar al script su propia función
`detect_*` y reportar su veredicto en la misma tabla.

**Resultado de la corrida del 2026-05-11:** ver `PROGRESS.md`
sección "Medición empírica de cobertura del detector C1".
