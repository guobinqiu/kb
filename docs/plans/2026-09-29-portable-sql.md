# Simple Business SQL

## Scope

Keep business queries in `kb_api/api/dao` simple and move application orchestration to Python. The project still uses PostgreSQL through psycopg; this work reduces unnecessary SQL complexity rather than claiming compatibility with every database.

## Steps

1. Keep DAO modules grouped by App, org, user, workspace and file business ownership.
2. Use simple parameterized statements with explicit columns. Replace `RETURNING` and `ON CONFLICT` flows with ordinary writes and reads on the same connection when needed.
3. Merge query results, traverse org trees and coordinate conditional flows in Python instead of using `UNION`, recursive CTEs or deeply nested SQL.
4. Do not use `FOR UPDATE` for these management operations. Retain database uniqueness and foreign-key constraints and handle conflicts in application code.
5. Keep every multi-write business operation in one explicit transaction so partial failures roll back together.
6. Allow database-specific SQL only in schema initialization and vector providers where PostgreSQL, pgvector or ParadeDB capabilities are the implementation itself.
7. Optimize a query only after measurement identifies a real bottleneck, and verify the changed behavior and transaction boundary with tests.

## Verification

```sh
kb_api/.venv/bin/pytest kb_api/tests -q
git diff --check
```
