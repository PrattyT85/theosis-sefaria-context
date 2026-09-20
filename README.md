# Theosis Sefaria Context MCP

A separate, provenance-first MCP service for high-value Sefaria context used in Bible study. It is part of the Theosis ecosystem but is intentionally separate from both the Bible database and the Midrash database.

## Related repositories

- [theosis-mcp](https://github.com/PrattyT85/theosis-mcp) — Bible texts, translations, Christian commentaries, lexicons, and theology; MCP port 8000.
- [theosis-midrash](https://github.com/PrattyT85/theosis-midrash) — local Jewish Midrash corpus and source links; MCP port 8001.
- **theosis-sefaria-context** — this repository; selected Targumim, Mishnah, historical context, commentary lookup, lexicons, and Sefaria cache; MCP port 8002.

## Current live deployment

- Database: PostgreSQL `sefaria_context` on CT125
- MCP endpoint: `http://192.168.1.130:8002/mcp`
- Health: `http://192.168.1.130:8002/health`
- Service: `sefaria-context.service`
- Service account: `sefaria_context`
- Encoding: UTF-8
- Schema migration: `002`
- Snapshot: 43 works, 54 editions, 28,689 segments, 54 import manifests

Counts are operational snapshots; use `get_context_corpus_summary` or `/health` for current values.

## What is local

The local Context tier currently contains:

- Targum Onkelos on the Torah
- Targum Jonathan on the Torah and selected Prophets
- Selected Mishnah: Berakhot, Pesachim, Yoma, Sanhedrin, and Pirkei Avot
- Approved Public Domain Josephus and Philo editions where exact Sefaria metadata matched

The service also provides on-demand, licence-filtered cache lookup for long-tail Sefaria material such as Jastrow, Rashi, and Ibn Ezra. It does not attempt to mirror the whole Sefaria library.

## MCP tools

| Tool | Purpose | Main inputs |
|---|---|---|
| `list_context_works` | List locally imported Context works and edition coverage. | `category`, `language` |
| `get_context_text` | Retrieve a complete locally imported passage. | `ref`, `language`, optional `edition` |
| `get_targum_text` | Retrieve and label Targum as an interpretive translation. | `ref`, `targum`, `language` |
| `search_context` | Search local Context text with bounded lexical/Hebrew retrieval. | `query`, `work`, `language`, `limit` |
| `get_context_corpus_summary` | Report local coverage and schema version. | `limit` |
| `get_context_import_history` | Report imported editions, licences, hashes, and source URLs. | `limit` |
| `lookup_sefaria_text` | Fetch/cache an exact Sefaria passage outside the local corpus. | `ref`, `language`, optional `version_title`, `refresh` |
| `lookup_sefaria_lexicon` | Fetch/cache Jastrow or another dictionary entry. | `word`, `lexicon`, `refresh` |
| `lookup_sefaria_commentary` | Fetch/cache Jewish commentary such as Rashi or Ibn Ezra. | `commentator`, `work`, `section`, `language`, optional `version_title` |

Every result identifies work, reference, edition, language, licence, source URL, retrieval/import time, and SHA-256 hash where available.

## Requirements

- PostgreSQL 16+
- UTF-8 database
- Python 3.11+
- `asyncpg`, `psycopg2-binary`, MCP Python SDK
- `pg_trgm` PostgreSQL extension
- Network access to Sefaria API/export sources

Use `requirements.lock` for deployment and `requirements-dev.lock` for development/testing.

## Fresh installation

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE sefaria_context LOGIN;
CREATE DATABASE sefaria_context OWNER sefaria_context ENCODING 'UTF8' TEMPLATE template0;
SQL
sudo -u postgres psql -d sefaria_context -f schema.sql

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
export SEFARIA_CONTEXT_DATABASE_URL='postgresql://sefaria_context@/sefaria_context?host=/var/run/postgresql'

# Migrations require database-admin privileges for DDL.
sudo -u postgres env SEFARIA_CONTEXT_DATABASE_URL=postgresql:///sefaria_context?host=/var/run/postgresql python scripts/migrate.py --status
sudo -u postgres env SEFARIA_CONTEXT_DATABASE_URL=postgresql:///sefaria_context?host=/var/run/postgresql python scripts/migrate.py
```

## Import workflow

The importer queries Sefaria metadata before downloading, rejects unapproved licences, hashes payloads, validates reference uniqueness, and records exact source URLs.

```bash
python scripts/sefaria_import.py --onkelos
python scripts/sefaria_import.py --jonathan
python scripts/sefaria_import.py --jonathan-prophets
python scripts/sefaria_import.py --mishnah
python scripts/sefaria_import.py --josephus
python scripts/sefaria_import.py --philo
```

Approved editions are selected by exact Sefaria API metadata. Unknown, CC-BY-SA, and CC-BY-NC editions are not silently imported into the default local corpus.

## Deployment

Use [deploy/sefaria-context.service](deploy/sefaria-context.service) as the systemd template. It runs as the dedicated `sefaria_context` user, uses systemd sandboxing, and binds to the configured LAN address.

```bash
sudo cp deploy/sefaria-context.service /etc/systemd/system/sefaria-context.service
sudo systemctl daemon-reload
sudo systemctl enable --now sefaria-context.service
curl http://127.0.0.1:8002/health
```

The endpoint has no application authentication. It is intended for a secured home LAN and should use a firewall or authenticated reverse proxy if the network threat model changes.

## Hermes Desktop and other clients

Enable `theosis_sefaria_context` in the dedicated Hermes `theosis_ai` profile, alongside `theosis` and `theosis_midrash`. Start a new profile session after configuration changes.

For another MCP client, add:

```text
http://<host>:8002/mcp
```

## On-demand cache

`lookup_sefaria_text` retrieves exact Sefaria references outside the local corpus and caches only requested passages. Cache records include edition, licence, source URL, retrieval time, expiry, and SHA-256 hash. Only Public Domain, CC0, and CC-BY editions are cached. Public Domain entries may remain fresh for up to 365 days; CC0/CC-BY entries default to 90 days.

The cache is the preferred path for rare Jastrow, Rashi, Ibn Ezra, Josephus, Philo, and long-tail Sefaria queries. It avoids mirroring the entire library and keeps retrieval bounded.

## Schema and migrations

- [schema.sql](schema.sql) — UTF-8 baseline schema.
- [migrations/](migrations/) — numbered cache/schema migrations.
- [scripts/migrate.py](scripts/migrate.py) — ordered, checksum-tracked migration runner.

The `works.role` field distinguishes primary texts, rabbinic context, historical context, and other source roles. `cache_entries` stores remote passages separately from the local corpus.

## Licensing and source policy

Sefaria licensing applies to each edition and language independently. The importer records exact licence metadata and rejects unapproved editions. The repository contains code and import definitions, not a bundled database dump or downloaded source corpus. Check Sefaria’s licence guidance before redistributing any cached or imported text.

## Development and verification

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q scripts tests
```

GitHub Actions runs tests and compile checks on Python 3.11 and 3.13.
