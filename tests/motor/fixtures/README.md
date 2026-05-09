# Fixtures del parser de EXPLAIN

Cada `.json` aquí es output literal de
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` contra AppDB v1, con la
excepción de `13_materialize.json` que es sintético (Postgres no
elige Materialize con este data-set, pero el parser debe soportarlo
porque B8 requiere los 16 tipos de nodo).

| Archivo | Query (resumen) | Tipos de nodo destacados |
|---------|-----------------|--------------------------|
| 01_index_scan.json | `SELECT * FROM users WHERE email = $1` | Index Scan |
| 02_aggregate_seq_scan.json | `SELECT count(*) FROM tags WHERE name LIKE $1` | Aggregate, Seq Scan |
| 03_limit_nested_loop.json | join users-posts con `WHERE u.id = $1 LIMIT 10` | Limit, Nested Loop, Index Scan, Gather, Seq Scan |
| 04_hash_join_aggregate_sort.json | left join + group by + order by + limit | Limit, Aggregate, Gather Merge, Sort, Hash Join, Hash, Index Only Scan, Seq Scan |
| 05_hash_join_groupby.json | CTE inlineada + group by | Aggregate, Gather Merge, Sort, Hash Join, Hash, Seq Scan |
| 06_aggregate_hash_join.json | `count(*) WHERE author_id IN (subquery)` | Aggregate, Gather, Hash Join, Hash, Index Only Scan, Seq Scan |
| 07_gather_sort_seq.json | `SELECT id FROM posts WHERE author_id BETWEEN ... ORDER BY id` | Gather Merge, Sort, Seq Scan |
| 08_bitmap_scan.json | `count(*)` con `OR` sobre columnas indexadas (forzando bitmap) | Aggregate, Bitmap Heap Scan, BitmapOr, Bitmap Index Scan |
| 09_recursive_cte.json | `WITH RECURSIVE chain AS (...)` | CTE Scan, Recursive Union, WorkTable Scan, Nested Loop, Index Only Scan |
| 10_merge_join.json | join users-posts forzando merge join | Gather, Merge Join, Sort, Index Only Scan, Seq Scan |
| 11_nested_loop_index.json | join users-posts con subquery donde PG hace doble Index Scan | Nested Loop, Index Scan |
| 12_subquery_scan.json | `SELECT id FROM (SELECT id FROM users LIMIT 5) sub` | Subquery Scan, Limit, Seq Scan |
| 13_materialize.json | sintético: nested loop con materialize en el lado interno | Nested Loop, Materialize, Seq Scan |

## Cómo regenerar

Levanta AppDB (`docker compose up appdb`) y para cada query corre:

```bash
docker exec appdb psql -U app_user -d appdb -tAq \
  -c "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>;" \
  > tests/motor/fixtures/<archivo>.json
```

`13_materialize.json` se mantiene a mano hasta que aparezca un caso
real en AppDB v2.
