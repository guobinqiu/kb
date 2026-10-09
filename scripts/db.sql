SELECT 'CREATE DATABASE rag OWNER rag'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag')\gexec

SELECT 'CREATE DATABASE rag_test OWNER rag'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag_test')\gexec

\connect rag

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;

DO $$
DECLARE
    business_tables CONSTANT TEXT[] := ARRAY[
        'apps',
        'orgs',
        'users',
        'workspaces',
        'workspace_user',
        'workspace_org',
        'files'
    ];
    table_name TEXT;
    legacy_table_count INTEGER := 0;
    public_table_count INTEGER := 0;
BEGIN
    FOREACH table_name IN ARRAY business_tables LOOP
        IF to_regclass(format('kb.%I', table_name)) IS NOT NULL THEN
            legacy_table_count := legacy_table_count + 1;
        END IF;

        IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            public_table_count := public_table_count + 1;
        END IF;

        IF to_regclass(format('kb.%I', table_name)) IS NOT NULL
           AND to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
            RAISE EXCEPTION
                'Schema migration conflict: both kb.% and public.% exist',
                table_name,
                table_name;
        END IF;
    END LOOP;

    IF legacy_table_count > 0 AND public_table_count > 0 THEN
        RAISE EXCEPTION
            'Schema migration conflict: business tables are split between kb and public schemas';
    END IF;

    IF legacy_table_count > 0 THEN
        FOREACH table_name IN ARRAY business_tables LOOP
            IF to_regclass(format('kb.%I', table_name)) IS NOT NULL THEN
                EXECUTE format('ALTER TABLE kb.%I SET SCHEMA public', table_name);
            END IF;
        END LOOP;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS apps (
    id UUID PRIMARY KEY,
    app_id VARCHAR(40) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    api_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE apps ALTER COLUMN app_id TYPE VARCHAR(40);

CREATE TABLE IF NOT EXISTS orgs (
    id UUID PRIMARY KEY,
    app_id UUID NOT NULL REFERENCES apps(id),
    parent_id UUID NULL REFERENCES orgs(id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS orgs_one_root_per_app
ON orgs(app_id)
WHERE parent_id IS NULL;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    org_id UUID REFERENCES orgs(id),
    name TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'member',
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT users_owner_org_check CHECK (
        (role = 'owner' AND org_id IS NULL) OR (role <> 'owner' AND org_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY,
    app_id UUID NOT NULL REFERENCES apps(id),
    name TEXT NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_user (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    user_id UUID NOT NULL REFERENCES users(id),
    role TEXT NOT NULL DEFAULT 'editor',
    CONSTRAINT workspace_user_workspace_user_key UNIQUE (workspace_id, user_id),
    CONSTRAINT workspace_user_role_check CHECK (role IN ('admin', 'editor', 'viewer'))
);

CREATE TABLE IF NOT EXISTS workspace_org (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    org_id UUID NOT NULL REFERENCES orgs(id),
    role TEXT NOT NULL DEFAULT 'viewer',
    CONSTRAINT workspace_org_workspace_org_key UNIQUE (workspace_id, org_id),
    CONSTRAINT workspace_org_role_check CHECK (role IN ('editor', 'viewer'))
);

CREATE TABLE IF NOT EXISTS files (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    filename TEXT NOT NULL,
    s3_url TEXT,
    mime_type TEXT,
    size_bytes BIGINT,
    checksum TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    indexed_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    index_task_id UUID,
    index_callback_token_hash TEXT,
    CONSTRAINT files_status_check CHECK (
        status IN ('uploaded', 'indexing', 'indexed', 'failed', 'deleting', 'delete_failed')
    )
);

ALTER TABLE files ADD COLUMN IF NOT EXISTS index_task_id UUID;
ALTER TABLE files ADD COLUMN IF NOT EXISTS index_callback_token_hash TEXT;

CREATE INDEX IF NOT EXISTS orgs_parent_id_idx ON orgs(parent_id);
CREATE INDEX IF NOT EXISTS orgs_app_id_idx ON orgs(app_id);
CREATE INDEX IF NOT EXISTS users_org_id_idx ON users(org_id);
CREATE INDEX IF NOT EXISTS workspaces_app_id_idx ON workspaces(app_id);
CREATE INDEX IF NOT EXISTS workspace_user_workspace_id_idx ON workspace_user(workspace_id);
CREATE INDEX IF NOT EXISTS workspace_org_workspace_id_idx ON workspace_org(workspace_id);
CREATE INDEX IF NOT EXISTS files_workspace_id_idx ON files(workspace_id);
