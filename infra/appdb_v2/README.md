# AppDB v2 — BD Demo Sorpresa para PgPilot

**Universidad Anáhuac Querétaro — Proyecto Final BD Avanzadas**

Esta es la **versión 2 ("sorpresa")** de la base de datos demo de PgPilot,
la que se entrega el día del **Demo Day**. Contiene los mismos *tipos* de
anti-pattern que la v1 que los equipos ya conocían, pero:

- es **otro dominio**: un foro / comunidad tipo Reddit, no una red social tipo Twitter,
- los **nombres de las tablas son distintos**,
- los **datos son diferentes**,
- hay **anti-patterns nuevos no anunciados** (Q21 a Q24).

El objetivo es evaluar si el producto de cada equipo —PgPilot— es
**genuinamente extensible**: si detecta patrones en los planes de ejecución
y en pg_stat_statements, o si hardcodeó las queries de la v1.

> ⚠️ **No repartir** el archivo `init/02_plantar_queries.sql` ni el
> documento Word de la lista maestra a los alumnos. Son material cerrado
> del profesor.

---

## Cómo levantarla

Requisitos: Docker y Docker Compose. Necesitas al menos **2 GB de espacio
libre** en disco.

```bash
docker compose up -d
docker compose logs -f appdb_v2   # para ver el progreso
```

La primera vez tarda **5-8 minutos**: crea el schema, siembra ~5 millones
de filas y ejecuta las 24 queries problemáticas (varias son lentas a
propósito, por eso tarda). Cuando el log deje de moverse y el healthcheck
diga `healthy`, está lista.

La BD queda disponible en:

| Parámetro | Valor |
|---|---|
| Host | `localhost` |
| Puerto | `5444` |
| Base de datos | `appdb` |
| Usuario | `foro_user` |
| Contraseña | `foro_pass` |

Cadena de conexión para PgPilot:

```
postgresql://foro_user:foro_pass@localhost:5444/appdb
```

Para apagarla y borrar todo:

```bash
docker compose down -v
```

---

## Qué contiene

Schema de un foro / comunidad con 8 tablas base (más una tabla extra
plantada para el problema de estadísticas):

| Tabla | Filas aprox. | Rol |
|---|---|---|
| `miembros` | 50,000 | usuarios del foro |
| `hilos` | 500,000 | publicaciones / temas (la tabla más grande) |
| `respuestas` | 1,000,000 | respuestas a los hilos |
| `votos` | 2,000,000 | votos a favor / en contra |
| `suscripciones` | 300,000 | relación de seguidores |
| `avisos` | 800,000 | notificaciones |
| `etiquetas` | 1,000 | hashtags / temas |
| `hilo_etiquetas` | ~500,000 | relación N:M |
| `hilos_recientes` | 60,000 | tabla con estadísticas viejas (plantada para Q10) |

Tamaño total: ~800 MB.

## Qué debe detectar el producto

**24 queries problemáticas** (Q01 a Q24), registradas en
`pg_stat_statements`. Cada una exhibe un anti-pattern específico que
PgPilot debe detectar a partir del análisis de `EXPLAIN` y del workload.

- **Q01 a Q20**: los mismos anti-patterns de la v1, disfrazados sobre el
  nuevo schema.
- **Q21 a Q24**: anti-patterns nuevos no anunciados.

El detalle completo —qué es cada anti-pattern, cómo detectarlo, qué query
de diagnóstico lo revela, qué muestra el plan EXPLAIN y cómo se ve una
buena recomendación— está en el documento:

**`AppDB_v2_Lista_Maestra_Hallazgos.docx`**

## Estructura de archivos

```
appdb_v2/
├── docker-compose.yml            # levanta Postgres 16 (puerto 5444)
├── postgresql.conf               # work_mem bajo intencional
├── README.md                     # este archivo
└── init/
    ├── 01_schema_seed.sql         # schema + datos (~5M filas)
    └── 02_plantar_queries.sql     # 24 queries problemáticas (CERRADO)
```

## Notas para el Demo Day

- La BD tarda en levantar porque varias queries plantadas son lentas a
  propósito (es lo que las hace buenos ejemplos de anti-pattern). Levántala
  con tiempo, antes de que empiecen las presentaciones.
- Las 3 BDs demo del curso usan puertos distintos (TiendaDB v2 en 5442,
  AppDB v2 en 5444), así que puedes tener varias levantadas a la vez.
- Si necesitas más volumen para estresar a los productos, puedes escalar
  los `generate_series` de `01_schema_seed.sql`; no es necesario para una
  demo normal.
