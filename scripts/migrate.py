#!/usr/bin/env python3
"""Apply and report ordered PostgreSQL schema migrations."""
from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg2

from sefaria_config import database_url

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_RE = re.compile(r"^(?P<version>\d{3})_(?P<name>[a-z0-9_]+)\.sql$")
LOCK_KEY = 730125001


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sql: str
    checksum: str


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_RE.match(path.name)
        if not match:
            raise ValueError(f"Invalid migration filename: {path.name}")
        sql = path.read_text(encoding="utf-8")
        if not sql.strip():
            raise ValueError(f"Empty migration: {path.name}")
        migrations.append(Migration(
            version=match.group("version"),
            name=match.group("name"),
            path=path,
            sql=sql,
            checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        ))
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("Duplicate migration version")
    return migrations


def ensure_tracking_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            version text PRIMARY KEY,
            name text NOT NULL,
            checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    # The MCP service only needs to read the tracking table; migrations run as
    # the database administrator because some DDL requires elevated privileges.
    cur.execute("GRANT SELECT ON public.schema_migrations TO sefaria_context")


def applied_migrations(cur) -> dict[str, tuple[str, str]]:
    cur.execute("SELECT version, name, checksum FROM public.schema_migrations ORDER BY version")
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def apply_migrations(db_url: str, *, status_only: bool = False, dry_run: bool = False) -> list[str]:
    migrations = discover_migrations()
    with psycopg2.connect(db_url) as conn:
        conn.set_client_encoding("UTF8")
        with conn.cursor() as cur:
            ensure_tracking_table(cur)
            conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            applied = applied_migrations(cur)
            pending = []
            for migration in migrations:
                previous = applied.get(migration.version)
                if previous:
                    if previous[1] != migration.checksum:
                        raise RuntimeError(
                            f"Migration {migration.version} checksum changed: "
                            f"database={previous[1]} file={migration.checksum}"
                        )
                    continue
                pending.append(migration)

            if status_only:
                return [
                    f"{migration.version} {migration.name} "
                    f"({'applied' if migration.version in applied else 'pending'})"
                    for migration in migrations
                ]
            if dry_run:
                return [f"would apply {migration.version} {migration.name}" for migration in pending]
            conn.commit()

        applied_now = []
        for migration in pending:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
                    # Re-check after acquiring the transaction lock in case another
                    # process committed while this runner was starting.
                    cur.execute("SELECT checksum FROM public.schema_migrations WHERE version=%s", (migration.version,))
                    row = cur.fetchone()
                    if row:
                        if row[0] != migration.checksum:
                            raise RuntimeError(f"Migration {migration.version} checksum changed during apply")
                    else:
                        cur.execute(migration.sql)
                        cur.execute(
                            "INSERT INTO public.schema_migrations(version, name, checksum) VALUES (%s, %s, %s)",
                            (migration.version, migration.name, migration.checksum),
                        )
                        applied_now.append(migration.version)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return [f"applied {version}" for version in applied_now]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="PostgreSQL DSN; defaults to MIDRASH_DATABASE_URL")
    parser.add_argument("--status", action="store_true", help="Show applied and pending migrations")
    parser.add_argument("--dry-run", action="store_true", help="Show pending migrations without applying them")
    args = parser.parse_args()
    for line in apply_migrations(database_url(args.db), status_only=args.status, dry_run=args.dry_run):
        print(line)


if __name__ == "__main__":
    main()
