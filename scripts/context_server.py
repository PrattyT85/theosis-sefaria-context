#!/usr/bin/env python3
"""Sefaria Context MCP server for selected Bible-study sources."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
from typing import Any

import asyncpg
from mcp.server.fastmcp import FastMCP

DB_URL = os.environ.get("SEFARIA_CONTEXT_DATABASE_URL", "postgresql://sefaria_context@/sefaria_context?host=/var/run/postgresql")
HOST = os.environ.get("SEFARIA_CONTEXT_HOST", "0.0.0.0")
PORT = int(os.environ.get("SEFARIA_CONTEXT_PORT", "8002"))
logger = logging.getLogger("sefaria-context-mcp")

mcp = FastMCP(
    "sefaria-context",
    instructions=(
        "Search selected Sefaria context for Bible study. Targum is an Aramaic "
        "interpretive translation, not the Hebrew biblical text. Always cite the "
        "exact work, Sefaria reference, edition, language, licence, source URL, "
        "and import metadata. Distinguish primary texts, commentary, rabbinic "
        "interpretation, and reference works."
    ),
    host=HOST,
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=8, command_timeout=30)
    return _pool


def metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def clean(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_hebrew(value: str) -> str:
    import unicodedata
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if not (0x0591 <= ord(ch) <= 0x05C7))
    value = value.translate(str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}))
    return re.sub(r"\s+", " ", value).strip()


async def schema_version(p: asyncpg.Pool) -> str:
    try:
        return await p.fetchval("SELECT coalesce(max(version), 'untracked') FROM schema_migrations")
    except asyncpg.UndefinedTableError:
        return "untracked"


def format_result(row: dict[str, Any], *, preview: bool = False) -> str:
    text = row.get("text") or ""
    length = row.get("text_length") or len(text)
    meta = metadata_dict(row.get("edition_metadata"))
    categories = ", ".join(row.get("categories") or []) or "not recorded"
    section = " › ".join(row.get("section_path") or []) or "not recorded"
    truncated = preview and length > len(text)
    lines = [
        f"**{row['sefaria_ref']}** — {row['work_title']}",
        f"Role: {row.get('role') or 'context'} | Categories: {categories}",
        f"Language: {row['language']} | Edition: {row['version_title']} (id {row['edition_id']})",
        f"Licence: {row.get('license') or 'not specified'}",
        f"Source: {row.get('source_url') or 'not recorded'}",
        f"Section: {section}",
    ]
    provenance = "; ".join(
        f"{key}={meta[key]}" for key in ("export_generated_at", "source_export_url", "content_sha256") if meta.get(key)
    )
    if provenance:
        lines.append("Import provenance: " + provenance)
    if truncated:
        lines.append(f"Text preview ({len(text):,} of {length:,} characters):")
    else:
        lines.append(f"Text ({length:,} characters):")
    lines.append(text)
    return "\n".join(lines)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    try:
        p = await pool()
        row = await p.fetchrow("""
            SELECT (SELECT count(*) FROM works) AS works,
                   (SELECT count(*) FROM editions) AS editions,
                   (SELECT count(*) FROM segments) AS segments,
                   (SELECT count(*) FROM ingestion_manifest) AS manifests,
                   (SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname=current_database()) AS encoding
        """)
        return JSONResponse({"status": "ok", "service": "sefaria-context-mcp", "schema_version": await schema_version(p), **dict(row)})
    except Exception:
        logger.exception("Health check failed")
        return JSONResponse({"status": "error", "service": "sefaria-context-mcp"}, status_code=503)


@mcp.tool()
async def list_context_works(category: str | None = None, language: str | None = None) -> str:
    """List locally imported context works and edition coverage."""
    p = await pool()
    filters = []
    params: list[Any] = []
    n = 1
    if category:
        filters.append(f"${n} = ANY(w.categories)"); params.append(category); n += 1
    if language:
        filters.append(f"e.language=${n}"); params.append(language); n += 1
    where = " AND ".join(filters) or "TRUE"
    rows = await p.fetch(f"""
        SELECT w.sefaria_title,w.hebrew_title,w.role,w.categories,e.language,e.version_title,
               e.license,count(s.id) AS segments
        FROM works w JOIN editions e ON e.work_id=w.id
        LEFT JOIN segments s ON s.edition_id=e.id
        WHERE {where}
        GROUP BY w.id,e.id ORDER BY w.sefaria_title,e.language,e.version_title
    """, *params)
    if not rows:
        return "No locally imported Context works match."
    lines = ["## Sefaria Context works", ""]
    for row in rows:
        lines.append(f"- **{row['sefaria_title']}** ({row['role']}; {row['language']}) — {row['version_title']} [{row['segments']} segments; {row['license'] or 'licence unspecified'}]")
    return "\n".join(lines)


async def fetch_text(ref: str, language: str, edition: str | None, preview: bool):
    p = await pool()
    columns = """
        s.sefaria_ref, {text}, length(s.text) AS text_length, s.section_path, s.segment_number,
        w.sefaria_title AS work_title, w.role, w.categories,
        e.id AS edition_id, e.language, e.version_title, e.license,
        e.version_source AS source_url, e.metadata AS edition_metadata
    """.format(text="left(s.text, 1200) AS text" if preview else "s.text")
    params: list[Any] = [ref, language]
    edition_filter = ""
    if edition:
        params.append(f"%{edition}%")
        edition_filter = "AND e.version_title ILIKE $3"
    return await p.fetchrow(f"""
        SELECT {columns}
        FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
        WHERE s.sefaria_ref=$1 AND e.language=$2 {edition_filter}
        ORDER BY e.is_primary DESC, e.version_title LIMIT 1
    """, *params)


@mcp.tool()
async def get_context_text(ref: str, language: str = "he", edition: str | None = None) -> str:
    """Retrieve a complete locally imported Context passage by exact Sefaria ref."""
    row = await fetch_text(ref, language, edition, preview=False)
    if not row:
        return f"Reference not found locally: {ref} ({language})."
    return format_result(dict(row))


@mcp.tool()
async def get_targum_text(ref: str, targum: str = "Onkelos", language: str = "he") -> str:
    """Retrieve a Targum passage and label it as an interpretive translation."""
    row = await fetch_text(ref, language, targum, preview=False)
    if not row:
        return f"Targum passage not found locally: {ref} ({targum}, {language})."
    return "## Targum — interpretive translation\n\n" + format_result(dict(row))


@mcp.tool()
async def search_context(query: str, work: str | None = None, language: str | None = None, limit: int = 10) -> str:
    """Search imported Context with bounded lexical/Hebrew-normalized retrieval."""
    p = await pool()
    query = query.strip()
    limit = max(1, min(limit, 50))
    if not query:
        return "Provide a search query."
    filters = []
    params: list[Any] = []
    n = 1
    if work:
        filters.append(f"w.sefaria_title ILIKE ${n}"); params.append(f"%{work}%"); n += 1
    if language:
        filters.append(f"e.language=${n}"); params.append(language); n += 1
    if re.search(r"[\u0590-\u05ff]", query):
        term = normalize_hebrew(query).replace("%", "\\%").replace("_", "\\_")
        filters.append(f"normalize_context_hebrew(s.text) LIKE '%' || ${n} || '%' ESCAPE '\\'"); params.append(term); n += 1
    else:
        filters.append(f"s.search_vector @@ plainto_tsquery('simple', ${n})"); params.append(query); n += 1
    params.append(limit)
    rows = await p.fetch(f"""
        SELECT s.sefaria_ref,left(s.text,1200) AS text,length(s.text) AS text_length,s.section_path,s.segment_number,
               w.sefaria_title AS work_title,w.role,w.categories,e.id AS edition_id,e.language,e.version_title,
               e.license,e.version_source AS source_url,e.metadata AS edition_metadata
        FROM segments s JOIN works w ON w.id=s.work_id JOIN editions e ON e.id=s.edition_id
        WHERE {' AND '.join(filters)}
        ORDER BY e.is_primary DESC,s.sefaria_ref LIMIT ${n}
    """, *params)
    if not rows:
        return f"No Context results found for '{query}'."
    return "## Context search results\n\n" + "\n\n---\n\n".join(format_result(dict(row), preview=True) for row in rows)


@mcp.tool()
async def get_context_corpus_summary(limit: int = 100) -> str:
    """Report local Context coverage, import health, and schema version."""
    p = await pool()
    limit = max(1, min(limit, 100))
    rows = await p.fetch("""
        SELECT w.sefaria_title,w.role,count(DISTINCT e.id) AS editions,count(DISTINCT s.id) AS segments,
               array_agg(DISTINCT e.language ORDER BY e.language) AS languages
        FROM works w LEFT JOIN editions e ON e.work_id=w.id LEFT JOIN segments s ON s.edition_id=e.id
        GROUP BY w.id ORDER BY w.sefaria_title LIMIT $1
    """, limit)
    if not rows:
        return "No Context data imported."
    lines = [f"## Sefaria Context summary (schema {await schema_version(p)})", ""]
    for row in rows:
        lines.append(f"- **{row['sefaria_title']}** ({row['role']}): {row['editions']} editions, {row['segments']} segments; languages={', '.join(row['languages'] or [])}")
    return "\n".join(lines)


@mcp.tool()
async def get_context_import_history(limit: int = 50) -> str:
    """List exact imported editions, licences, source URLs, and payload hashes."""
    p = await pool()
    rows = await p.fetch("""
        SELECT w.sefaria_title,e.language,e.version_title,e.license,m.source_url,m.segment_count,m.content_sha256,m.imported_at
        FROM ingestion_manifest m JOIN editions e ON e.id=m.edition_id JOIN works w ON w.id=e.work_id
        ORDER BY m.imported_at DESC LIMIT $1
    """, max(1, min(limit, 200)))
    if not rows:
        return "No Context import history recorded."
    return "## Context import history\n\n" + "\n".join(
        f"- {r['sefaria_title']} / {r['language']} / {r['version_title']}; {r['segment_count']} segments; "
        f"license={r['license'] or 'not specified'}; sha256={r['content_sha256']}; source={r['source_url']}"
        for r in rows
    )


if __name__ == "__main__":
    mcp.run("streamable-http")
