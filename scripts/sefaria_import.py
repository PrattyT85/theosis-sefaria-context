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


def metadata_for(title: str, version_title: str) -> dict[str, Any] | None:
    ref = f"{title} 1:1"
    try:
        data = fetch_json(API + urllib.parse.quote(ref, safe=""))
    except Exception as exc:
        print("SKIP", ref, version_title, type(exc).__name__, flush=True)
        return None
    matches = [v for v in data.get("available_versions", []) if v.get("versionTitle") == version_title]
    return matches[0] if matches else None


def flatten(text: dict[str, Any], title: str) -> list[tuple[str, tuple[str, ...], str]]:
    """Flatten cltk-flat text dict into (ref, path_tuple, text) records.

    Handles variable-depth section paths:
    - 2 parts: "Work 1:1" (chapter:verse for Targum/Mishnah)
    - 3 parts: "Work 1:1:1" (e.g. Philo chapter:paragraph)
    - 4 parts: "Work 1:1:1:1" (e.g. Josephus book:chapter:paragraph)
    """
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
        if len(numbers) < 2:
            raise ValueError(f"Expected at least 2 section parts for {title}: {raw_path}")
        # Build ref with colon-separated section numbers
        ref = f"{title} {':'.join(str(n) for n in numbers)}"
        records.append((ref, tuple(parts), value.strip()))
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


MISHNAH_WORKS = [
    "Mishnah Berakhot", "Mishnah Pesachim", "Mishnah Yoma", "Mishnah Sanhedrin", "Pirkei Avot"
]
JONATHAN_BOOKS = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]
JONATHAN_PROPHETS = {
    "Isaiah": "London Chaldee Paraphrase, 1871",
    "Jeremiah": None,
    "Ezekiel": None,
    "I Samuel": None,
    "II Samuel": None,
    "Jonah": "Sefaria Community Translation",
    "Hosea": None,
    "Micah": None,
    "Malachi": "Sefaria Community Translation",
    "Zechariah": None,
    "I Kings": None,
    "II Kings": None,
    "Amos": None,
    "Obadiah": None,
    "Joel": None,
    "Habakkuk": None,
    "Zephaniah": None,
    "Haggai": None,
}

# Exact versions verified through the Sefaria v3 metadata API.
JONATHAN_ENGLISH = "The Targum of Jonathan ben Uzziel, trans. J. W. Etheridge, London, 1862"

# Josephus works with approved licences (Public Domain or CC0/CC-BY only).
# "The Antiquities of the Jews" English is CC-BY-SA (not approved); only Hebrew PD is available.
# "Against Apion" is CC-BY-SA only (not approved).
JOSEPHUS_WORKS = [
    {
        "title": "The War of the Jews",
        "categories": ["Second Temple", "Josephus", "Historical"],
        "role": "historical_context",
        "editions": [
            ("en", "The War of the Jews, translated by William Whiston", "Public Domain"),
            ("he", "The Jewish Wars, trans. Y.N. Simhoni, Warsaw, 1923", "Public Domain"),
        ],
    },
    {
        "title": "The Antiquities of the Jews",
        "categories": ["Second Temple", "Josephus", "Historical"],
        "role": "historical_context",
        "editions": [
            ("he", "Yemei am olam, trans. Kalman Schulman. Vilna, 1886", "Public Domain"),
        ],
    },
]

# Philo works with approved licences (all Loeb Classical Library, Harvard University Press = Public Domain).
# Exact version titles verified through Sefaria Export catalog.
PHILO_WORKS = [
    ("Concerning Noah's Work as a Planter", "Loeb Classical Library, Harvard University Press, 1930"),
    ("Every Good Man is Free", "Loeb Classical Library, Harvard University Press, 1941"),
    ("On Abraham", "Loeb Classical Library, Harvard University Press, 1935"),
    ("On Joseph", "Loeb Classical Library, Harvard University Press, 1935"),
    ("On the Decalogue", "Loeb Classical Library, Harvard University Press, 1937"),
    ("On the Life of Moses", "Loeb Classical Library, Harvard University Press, 1935"),
    ("Allegorical Interpretation of Genesis", "Loeb Classical Library, Harvard University Press, 1929"),
    ("On the Special Laws", "Loeb Classical Library, Harvard University Press, 1937"),
    ("On Dreams", "Loeb Classical Library, Harvard University Press, 1934"),
    ("On the Confusion of Tongues", "Loeb Classical Library, Harvard University Press, 1932"),
    ("On the Migration of Abraham", "Loeb Classical Library, Harvard University Press, 1932"),
    ("On Flight and Finding", "Loeb Classical Library, Harvard University Press, 1934"),
    ("On Husbandry", "Loeb Classical Library, Harvard University Press, 1930"),
    ("On Drunkenness", "Loeb Classical Library, Harvard University Press, 1930"),
    ("On the Giants", "Loeb Classical Library, Harvard University Press, 1929"),
    ("On the Eternity of the World", "Loeb Classical Library, Harvard University Press, 1941"),
]


def import_work(cur, catalog, title: str, categories: list[str], role: str,
                approved: list[tuple[str, str, str]], export_at: str) -> None:
    cur.execute("""INSERT INTO works(sefaria_title,hebrew_title,categories,role,source_url,metadata)
                   VALUES(%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(sefaria_title) DO UPDATE SET metadata=works.metadata || EXCLUDED.metadata
                   RETURNING id""",
                (title, None, categories, role, f"https://www.sefaria.org/{title.replace(' ', '_')}",
                 Json({"selection": "approved Sefaria Context editions"})))
    work_id = cur.fetchone()[0]
    imported_languages: set[str] = set()
    for language, version_title, expected_license in approved:
        if language in imported_languages:
            continue
        matches = [b for b in catalog if b.get("title") == title and b.get("language") == ("Hebrew" if language == "he" else "English") and b.get("versionTitle") == version_title]
        if not matches:
            print("SKIP", title, language, version_title, "not in export catalog", flush=True)
            continue
        meta = metadata_for(title, version_title)
        if not meta:
            print("SKIP", title, language, version_title, "exact API metadata unavailable", flush=True)
            continue
        actual_license = meta.get("license") or expected_license
        if actual_license != expected_license:
            raise RuntimeError(f"Licence mismatch for {title} / {version_title}: expected {expected_license}, got {actual_license}")
        count = import_edition(cur, work_id, title, language, version_title, actual_license, matches[0]["cltk_flat_url"], export_at)
        print("IMPORTED", title, language, version_title, count, actual_license, flush=True)
        imported_languages.add(language)
    if not imported_languages:
        print("NO APPROVED EDITION", title, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=database_url())
    parser.add_argument("--onkelos", action="store_true", help="Import approved Onkelos editions")
    parser.add_argument("--mishnah", action="store_true", help="Import selected Mishnah context works")
    parser.add_argument("--jonathan", action="store_true", help="Import Targum Jonathan on the Torah")
    parser.add_argument("--jonathan-prophets", action="store_true", help="Import selected Targum Jonathan prophetic books")
    parser.add_argument("--josephus", action="store_true", help="Import approved Josephus editions")
    parser.add_argument("--philo", action="store_true", help="Import approved Philo editions")
    args = parser.parse_args()
    if not any([args.onkelos, args.mishnah, args.jonathan, args.jonathan_prophets, args.josephus, args.philo]):
        parser.error("select an import set: --onkelos, --mishnah, --jonathan, --jonathan-prophets, --josephus, or --philo")
    catalog = fetch_json(BOOKS_JSON).get("books", [])
    export_at = datetime.now(timezone.utc).isoformat()
    with psycopg2.connect(args.db) as conn:
        conn.set_client_encoding("UTF8")
        with conn.cursor() as cur:
            if args.onkelos:
                for book in BOOKS:
                    title = f"Onkelos {book}"
                    import_work(cur, catalog, title, ["Tanakh", "Targum", "Onkelos", "Torah"], "primary_text", [
                        ("he", title, "Public Domain"),
                        ("en", "Sefaria Community Translation", "CC0"),
                    ], export_at)
            if args.mishnah:
                for title in MISHNAH_WORKS:
                    import_work(cur, catalog, title, ["Mishnah"], "rabbinic_context", [
                        ("he", "Torat Emet 357", "Public Domain"),
                        ("en", "Sefaria Community Translation", "CC0"),
                        ("en", "Mishnah Yomit by Dr. Joshua Kulp", "CC-BY"),
                    ], export_at)
            if args.jonathan:
                for book in JONATHAN_BOOKS:
                    title = f"Targum Jonathan on {book}"
                    import_work(cur, catalog, title, ["Tanakh", "Targum", "Targum Jonathan"], "primary_text", [
                        ("he", title, "Public Domain"),
                        ("en", JONATHAN_ENGLISH, "Public Domain"),
                    ], export_at)
            if args.jonathan_prophets:
                for book, english_version in JONATHAN_PROPHETS.items():
                    title = f"Targum Jonathan on {book}"
                    approved = [("he", "Mikraot Gedolot", "Public Domain")]
                    if english_version:
                        approved.append(("en", english_version, "Public Domain" if book == "Isaiah" else "CC0"))
                    import_work(cur, catalog, title, ["Tanakh", "Targum", "Targum Jonathan", "Prophets"], "primary_text", approved, export_at)
            if args.josephus:
                for work in JOSEPHUS_WORKS:
                    import_work(cur, catalog, work["title"], work["categories"], work["role"], work["editions"], export_at)
            if args.philo:
                for title, version_title in PHILO_WORKS:
                    import_work(cur, catalog, title, ["Second Temple", "Philo", "Philosophy"], "historical_context", [
                        ("en", version_title, "Public Domain"),
                    ], export_at)
        conn.commit()


if __name__ == "__main__":
    main()
