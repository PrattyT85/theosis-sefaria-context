SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE schema_migrations (
    version text PRIMARY KEY,
    name text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE works (
    id bigserial PRIMARY KEY,
    sefaria_title text NOT NULL UNIQUE,
    hebrew_title text,
    categories text[] NOT NULL DEFAULT '{}',
    role text NOT NULL DEFAULT 'context',
    description text,
    source_url text,
    metadata jsonb NOT NULL DEFAULT '{}',
    discovered_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE editions (
    id bigserial PRIMARY KEY,
    work_id bigint NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    language text NOT NULL,
    version_title text NOT NULL,
    version_source text,
    license text,
    is_source boolean NOT NULL DEFAULT false,
    is_primary boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}',
    UNIQUE (work_id, language, version_title)
);

CREATE TABLE segments (
    id bigserial PRIMARY KEY,
    work_id bigint NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    edition_id bigint NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    sefaria_ref text NOT NULL,
    section_path text[] NOT NULL DEFAULT '{}',
    segment_number integer,
    text text NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    UNIQUE (edition_id, sefaria_ref)
);

CREATE TABLE ingestion_manifest (
    id bigserial PRIMARY KEY,
    edition_id bigint NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    source_url text NOT NULL,
    export_generated_at timestamptz,
    segment_count integer NOT NULL DEFAULT 0,
    content_sha256 text,
    imported_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (edition_id, source_url)
);

CREATE TABLE source_links (
    id bigserial PRIMARY KEY,
    source_ref text NOT NULL,
    target_ref text NOT NULL,
    link_type text NOT NULL DEFAULT 'link',
    metadata jsonb NOT NULL DEFAULT '{}',
    UNIQUE (source_ref, target_ref, link_type)
);

CREATE TABLE cache_entries (
    id bigserial PRIMARY KEY,
    ref text NOT NULL,
    language text,
    version_title text,
    payload jsonb NOT NULL,
    source_url text NOT NULL,
    license text,
    retrieved_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    content_sha256 text NOT NULL,
    UNIQUE (ref, language, version_title)
);

CREATE INDEX cache_entries_lookup_idx ON cache_entries(ref, language, version_title);
CREATE INDEX segments_search_idx ON segments USING gin(search_vector);
CREATE INDEX segments_ref_idx ON segments(edition_id, sefaria_ref);
CREATE INDEX segments_work_idx ON segments(work_id, sefaria_ref);
CREATE INDEX source_links_lookup_idx ON source_links(source_ref, target_ref);
CREATE INDEX source_links_type_idx ON source_links(link_type);

CREATE OR REPLACE FUNCTION normalize_context_hebrew(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT regexp_replace(
        regexp_replace(translate(coalesce(value, ''), 'ךםןףץ', 'כמנפצ'),
                       '[' || chr(1425) || '-' || chr(1479) || ']', '', 'g'),
        '\s+', ' ', 'g')
$$;

CREATE INDEX segments_hebrew_trgm_idx
    ON segments USING gin (normalize_context_hebrew(text) gin_trgm_ops);

GRANT SELECT ON ALL TABLES IN SCHEMA public TO sefaria_context;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sefaria_context;
