import inspect
import os

import psycopg
from psycopg.rows import dict_row

from kb_api.repository import PostgresRepository


def _connect():
    return psycopg.connect(
        os.getenv("KB_TEST_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5432/rag_test"),
        row_factory=dict_row,
    )


def _columns(table: str) -> set[str]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'kb' AND table_name = %s",
            (table,),
        ).fetchall()
    return {row["column_name"] for row in rows}


def test_schema_has_workspace_tables_and_file_workspace_scope():
    with _connect() as connection:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'kb' AND table_type = 'BASE TABLE'",
        ).fetchall()
    tables = {row["table_name"] for row in rows}
    assert tables == {"apps", "orgs", "users", "workspaces", "workspace_user", "workspace_org", "files"}
    assert _columns("apps") == {"id", "app_id", "name", "api_key", "created_at", "updated_at"}
    assert _columns("orgs") == {"id", "app_id", "parent_id", "name", "created_at", "updated_at", "deleted_at"}
    assert _columns("users") == {"id", "org_id", "name", "password_hash", "role", "deleted_at", "created_at", "updated_at"}
    assert _columns("workspaces") == {"id", "app_id", "name", "created_at", "updated_at"}
    assert _columns("workspace_user") == {"id", "workspace_id", "user_id", "role"}
    assert _columns("workspace_org") == {"id", "workspace_id", "org_id", "role"}
    assert _columns("files") == {
        "id", "workspace_id", "filename", "object_key", "s3_url", "mime_type", "size_bytes",
        "checksum", "status", "error", "created_by", "created_at", "updated_at", "indexed_at", "deleted_at",
    }


def test_schema_enforces_unique_user_workspace_membership():
    with _connect() as connection:
        foreign_keys = connection.execute("""
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.table_schema = 'kb'
              AND tc.table_name = 'workspace_user'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'user_id'
              AND ccu.table_name = 'users'
              AND ccu.column_name = 'id'
        """).fetchone()
        unique_keys = connection.execute("""
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'kb'
              AND tc.table_name = 'workspace_user'
              AND tc.constraint_type = 'UNIQUE'
            GROUP BY tc.constraint_name
            HAVING array_agg(kcu.column_name::text ORDER BY kcu.ordinal_position) = ARRAY['workspace_id', 'user_id']
        """).fetchone()
    assert foreign_keys is not None
    assert unique_keys is not None


def test_schema_keeps_owner_outside_organization_tree():
    with _connect() as connection:
        nodes = connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'kb' AND table_name = 'nodes'",
        ).fetchone()
        owner_check = connection.execute("""
            SELECT 1
            FROM information_schema.check_constraints
            WHERE constraint_schema = 'kb'
              AND constraint_name = 'users_owner_org_check'
              AND check_clause ILIKE '%role%'
              AND check_clause ILIKE '%org_id%'
        """).fetchone()
        root_index = connection.execute("""
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'kb'
              AND tablename = 'orgs'
              AND indexname = 'orgs_one_root_per_app'
              AND indexdef ILIKE '%parent_id IS NULL%'
        """).fetchone()
    assert nodes is None
    assert owner_check is not None
    assert root_index is not None


def test_repository_org_listing_does_not_walk_ancestors():
    source = inspect.getsource(PostgresRepository)
    list_orgs_source = inspect.getsource(PostgresRepository.list_orgs)

    assert "def _ancestors_cte" not in source
    assert "ancestors" not in list_orgs_source
