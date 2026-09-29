SELECT 'CREATE DATABASE rag OWNER rag'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag')\gexec

SELECT 'CREATE DATABASE rag_test OWNER rag'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag_test')\gexec

\connect rag

CREATE SCHEMA IF NOT EXISTS kb;

CREATE TABLE IF NOT EXISTS kb.apps (
    id UUID PRIMARY KEY,
    app_id VARCHAR(64) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    api_key TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS kb.orgs (
    id UUID PRIMARY KEY,
    app_id UUID NOT NULL REFERENCES kb.apps(id),
    parent_id UUID NULL REFERENCES kb.orgs(id),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS orgs_one_root_per_app
ON kb.orgs(app_id)
WHERE parent_id IS NULL;

CREATE TABLE IF NOT EXISTS kb.users (
    id UUID PRIMARY KEY,
    org_id UUID REFERENCES kb.orgs(id),
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

CREATE TABLE IF NOT EXISTS kb.workspaces (
    id UUID PRIMARY KEY,
    app_id UUID NOT NULL REFERENCES kb.apps(id),
    name TEXT NOT NULL,
    created_by UUID REFERENCES kb.users(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS kb.workspace_user (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES kb.workspaces(id),
    user_id UUID NOT NULL REFERENCES kb.users(id),
    role TEXT NOT NULL DEFAULT 'editor',
    CONSTRAINT workspace_user_workspace_user_key UNIQUE (workspace_id, user_id),
    CONSTRAINT workspace_user_role_check CHECK (role IN ('admin', 'editor', 'viewer'))
);

CREATE TABLE IF NOT EXISTS kb.workspace_org (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES kb.workspaces(id),
    org_id UUID NOT NULL REFERENCES kb.orgs(id),
    role TEXT NOT NULL DEFAULT 'viewer',
    CONSTRAINT workspace_org_workspace_org_key UNIQUE (workspace_id, org_id),
    CONSTRAINT workspace_org_role_check CHECK (role IN ('editor', 'viewer'))
);

CREATE TABLE IF NOT EXISTS kb.files (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES kb.workspaces(id),
    filename TEXT NOT NULL,
    s3_url TEXT,
    mime_type TEXT,
    size_bytes BIGINT,
    checksum TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_by UUID REFERENCES kb.users(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    indexed_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT files_status_check CHECK (
        status IN ('uploaded', 'indexing', 'indexed', 'failed', 'deleting', 'delete_failed')
    )
);

CREATE INDEX IF NOT EXISTS orgs_parent_id_idx ON kb.orgs(parent_id);
CREATE INDEX IF NOT EXISTS orgs_app_id_idx ON kb.orgs(app_id);
CREATE INDEX IF NOT EXISTS users_org_id_idx ON kb.users(org_id);
CREATE INDEX IF NOT EXISTS workspaces_app_id_idx ON kb.workspaces(app_id);
CREATE INDEX IF NOT EXISTS workspace_user_workspace_id_idx ON kb.workspace_user(workspace_id);
CREATE INDEX IF NOT EXISTS workspace_org_workspace_id_idx ON kb.workspace_org(workspace_id);
CREATE INDEX IF NOT EXISTS files_workspace_id_idx ON kb.files(workspace_id);
