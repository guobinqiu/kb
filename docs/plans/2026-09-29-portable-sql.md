# Portable Business SQL

## Scope

Replace PostgreSQL-specific business query syntax in `kb_api/dao.py` with basic SQL and Python orchestration. Preserve the PostgreSQL driver and deployment scripts; database installation commands and third-party LangGraph SQL are not application query code.

## Steps

1. Use existing repository and API tests as behavioral baselines. Add transaction rollback and concurrent write tests in `kb_api/tests/test_dao_transactions.py`; run against the manually initialized `rag_test` database.
2. Replace `RETURNING` with writes followed by `SELECT` on the same connection and transaction. Lock rows before read-modify-write updates.
3. Replace `ON CONFLICT` with `SELECT`, `INSERT` or `UPDATE`. Serialize workspace grant changes using the existing workspace lock; retain unique constraints.
4. Replace PostgreSQL functions with standard SQL: `CURRENT_TIMESTAMP`, aggregate counts, and `LOWER ... LIKE ... ESCAPE`. Use `ROW_NUMBER()` for server-side pagination rather than database-specific pagination syntax.
5. Preserve standard recursive CTEs, joins, unions, and row locks. Keep parent checks and related deletes within one transaction.
6. Run all KB API tests, relevant Indexer and Chat integration tests, and diff checks. Document the SQL-versus-driver portability boundary without claiming support for untested database engines.

## Verification

```sh
kb_api/.venv/bin/pytest kb_api/tests -q
git diff --check
```
