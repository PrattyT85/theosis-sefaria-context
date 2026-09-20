# Theosis Sefaria Context MCP

A separate, provenance-first MCP service for high-value Sefaria context used in Bible study. It is intentionally selective: the local tier starts with Targum Onkelos, while long-tail Sefaria works will be retrieved and cached on demand.

## Scope

- Separate from Theosis Bible and Theosis Midrash.
- UTF-8 PostgreSQL database: `sefaria_context`.
- Planned MCP endpoint: `http://192.168.1.130:8002/mcp`.
- Every edition records exact Sefaria reference/version, language, licence, source URL, retrieval/import timestamps, and SHA-256 payload hash.

## First local corpus

Targum Onkelos on Genesis, Exodus, Leviticus, Numbers, and Deuteronomy:

- Hebrew/Aramaic: prefer the Sefaria version explicitly marked `Public Domain`.
- English: use `Sefaria Community Translation` only where the API confirms coverage and `CC0`.
- Do not ingest the Metsudah 2009 edition into the default local corpus because Sefaria identifies it as `CC-BY-NC`.

All version choices are made from Sefaria API metadata at import time and saved in the ingestion manifest.

## Installation

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
sudo -u postgres env SEFARIA_CONTEXT_DATABASE_URL=postgresql:///sefaria_context?host=/var/run/postgresql python scripts/migrate.py
python scripts/sefaria_import.py --onkelos
```

## Import

The importer queries Sefaria metadata first, rejects unapproved licences, downloads the selected exact versions, records the payload hash, and validates reference uniqueness:

```bash
python scripts/sefaria_import.py --onkelos
```

## MCP tools

- `list_context_works`
- `get_context_text`
- `search_context`
- `get_targum_text`
- `get_context_corpus_summary`
- `get_context_import_history`

Results must label Targum as an Aramaic interpretive translation, not as the Hebrew biblical text.

## Licensing

Sefaria licences apply per edition and language. The importer stores licence and source metadata and does not silently treat an unknown or non-approved edition as reusable local data. See Sefaria's licence guidance and API metadata before adding editions.
