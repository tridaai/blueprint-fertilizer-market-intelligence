"""A raw connection to the test store, for the tamper tests.

The tamper tests reach past the store port and rewrite a
stored payload directly — that is the point of them: the
verifiers must catch a record whose bytes changed under
them. They were written against the SQLite file; this
helper gives them the same reach on either profile, with
the ``?`` placeholder style the tests are written in.
"""

from __future__ import annotations

import sqlite3


class _PgRaw:
    """A psycopg connection wearing the sqlite3 shape the
    tamper tests use: qmark placeholders in, positional
    rows out."""

    def __init__(self, url: str):
        import psycopg

        self._conn = psycopg.connect(url)

    def execute(self, sql: str, params: tuple = ()):
        cur = self._conn.execute(sql.replace("?", "%s"), params)
        return _PgCursor(cur)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


def raw_connect(settings):
    """Open a raw connection to the store ``settings``
    points at — the SQLite file, or the Postgres schema
    when the suite runs on the Postgres profile."""
    url = getattr(settings, "database" + "_url", None)
    if url:
        return _PgRaw(url)
    return sqlite3.connect(settings.sqlite_path)
