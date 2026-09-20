#!/usr/bin/env python3
"""Import approved Sefaria Context editions from the structured export."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json

from sefaria_config import database_url

BOOKS_JSON = "https://raw.githubusercontent.com/Sefaria/Sefaria-Export/master/books.json"
API = "https://www.sefaria.org/api/v3/texts/"
BOOKS = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "theosis-sefaria-context/0.1", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "theosis-sefaria-context/0.1"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def metadata_for(title: str, version_title: str) -> dict[str, Any]:
    ref = f"{title} 1:1"
    data = fetch_json(API + urllib.parse.quote(ref, safe=""))
    matches = [v for v in data.get("available_versions", []) if v.get("versionTitle") == version_title]
    return matches[0] if matches else None


def flatten(text: dict[str, Any], title: str) -> list[tuple[str, tuple[str, ...], str]]:
    records = []
    for raw_path, value in text.items():
        if not isinstance(value, str) or not value.strip():
            continue
        parts = [part.strip() for part in raw_path.split(",")]
        numbers = []
        for part in parts:
            match = re.match(r"^(\d+)_", part)
            if not match:
                raise ValueError(f"Unexpected Sefaria path for {title}: {raw_path}")
            numbers.append(int(match.group(1)) + 1)
        if len(numbers) != 2:
            raise ValueError(f"Expected chapter/verse path for {title}: {raw_path}")
        records.append((f"{title} {numbers[0]}:{numbers[1]}", tuple(parts), value.strip()))
    refs = [row[0] for row in records]
    if len(refs) != len(set(refs)):
        raise ValueError(f"Reference collision in {title}")
    return records


def import_edition(cur, work_id: int, title: str, language: str, version_title: str, license_name: str, source_url: str, export_at: str) -> int:
    payload = fetch_bytes(source_url)
    digest = hashlib.sha256(payload).hexdigest()
    data = json.loads(payload)
    records = flatten(data.get("text") or {}, title)
    cur.execute("""SELECT id,metadata->>'content_sha256' FROM editions
                   WHERE work_id=%s AND language=%s AND version_title=%s""",
                (work_id, language, version_title))
    existing = cur.fetchone()
    if existing and existing[1] == digest:
        edition_id = existing[0]
        cur.execute("SELECT count(*) FROM segments WHERE edition_id=%s", (edition_id,))
        count = cur.fetchone()[0]
    else:
        metadata = {
            "format": "cltk-flat",
            "export_generated_at": export_at,
            "content_sha256": digest,
            "source_bytes": len(payload),
            "source_export_url": source_url,
        }
        cur.execute("""INSERT INTO editions(work_id,language,version_title,version_source,license,is_source,is_primary,metadata)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(work_id,language,version_title) DO UPDATE SET
                         version_source=EXCLUDED.version_source,license=EXCLUDED.license,metadata=EXCLUDED.metadata
                       RETURNING id""",
                    (work_id, language, version_title, source_url, license_name, language == "he", language == "he", Json(metadata)))
        edition_id = cur.fetchone()[0]
        cur.execute("DELETE FROM segments WHERE edition_id=%s", (edition_id,))
        for number, (ref, path, text) in enumerate(records, start=1):
            cur.execute("""INSERT INTO segments(work_id,edition_id,sefaria_ref,section_path,segment_number,text)
                           VALUES(%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(edition_id,sefaria_ref) DO UPDATE SET text=EXCLUDED.text,section_path=EXCLUDED.section_path,segment_number=EXCLUDED.segment_number""",
                        (work_id, edition_id, ref, list(path), number, text))
        count = len(records)
    cur.execute("""INSERT INTO ingestion_manifest(edition_id,source_url,export_generated_at,segment_count,content_sha256)
                   VALUES(%s,%s,%s,%s,%s)
                   ON CONFLICT(edition_id,source_url) DO UPDATE SET segment_count=EXCLUDED.segment_count,content_sha256=EXCLUDED.content_sha256,imported_at=now()""",
                (edition_id, source_url, export_at, count, digest))
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=database_url())
    parser.add_argument("--onkelos", action="store_true", help="Import approved Onkelos editions")
    args = parser.parse_args()
    if not args.onkelos:
        parser.error("select an import set, currently --onkelos")
    catalog = fetch_json(BOOKS_JSON).get("books", [])
    export_at = datetime.now(timezone.utc).isoformat()
    with psycopg2.connect(args.db) as conn:
        conn.set_client_encoding("UTF8")
        with conn.cursor() as cur:
            for book in BOOKS:
                title = f"Onkelos {book}"
                cur.execute("""INSERT INTO works(sefaria_title,hebrew_title,categories,role,source_url,metadata)
                               VALUES(%s,%s,%s,%s,%s,%s)
                               ON CONFLICT(sefaria_title) DO UPDATE SET metadata=works.metadata || EXCLUDED.metadata
                               RETURNING id""",
                            (title, None, ["Tanakh", "Targum", "Onkelos", "Torah"], "primary_text",
                             f"https://www.sefaria.org/{title.replace(' ', '_')}", Json({"selection": "approved Onkelos public-domain/CC0 editions"})))
                work_id = cur.fetchone()[0]
                approved = [
                    ("Hebrew", title, "Public Domain"),
                    ("English", "Sefaria Community Translation", "CC0"),
                ]
                for language_name, version_title, expected_license in approved:
                    language = "he" if language_name == "Hebrew" else "en"
                    matches = [b for b in catalog if b.get("title") == title and b.get("language") == language_name and b.get("versionTitle") == version_title]
                    if not matches:
                        print("SKIP", title, language_name, version_title, "not in export catalog", flush=True)
                        continue
                    meta = metadata_for(title, version_title)
                    if not meta:
                        print("SKIP", title, language_name, version_title, "exact API metadata unavailable", flush=True)
                        continue
                    actual_license = meta.get("license") or expected_license
                    if actual_license != expected_license:
                        raise RuntimeError(f"Licence mismatch for {title} / {version_title}: expected {expected_license}, got {actual_license}")
                    count = import_edition(cur, work_id, title, language, version_title, actual_license, matches[0]["cltk_flat_url"], export_at)
                    print("IMPORTED", title, language, version_title, count, actual_license, flush=True)
        conn.commit()


if __name__ == "__main__":
    main()
