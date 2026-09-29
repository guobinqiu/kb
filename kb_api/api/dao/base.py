from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return str(uuid.uuid4())


class BaseDAO:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _record(row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        for key, value in result.items():
            if isinstance(value, (datetime, uuid.UUID)):
                result[key] = str(value)
        return result

    def close(self) -> None:
        pass

    def _one(self, query: str, params: tuple) -> dict | None:
        with self._connect() as connection:
            return self._record(connection.execute(query, params).fetchone())

    def _write_one(self, query: str, params: tuple, select: str, select_params: tuple) -> dict | None:
        with self._connect() as connection:
            connection.execute(query, params)
            return self._record(connection.execute(select, select_params).fetchone())

    def _execute(self, query: str, params: tuple) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            return cursor.rowcount > 0
