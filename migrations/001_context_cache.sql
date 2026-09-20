-- Cache exact Sefaria API responses for the long tail outside the local corpus.
CREATE TABLE IF NOT EXISTS cache_entries (
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
CREATE INDEX IF NOT EXISTS cache_entries_lookup_idx ON cache_entries(ref, language, version_title);
GRANT SELECT, INSERT, UPDATE ON cache_entries TO sefaria_context;
GRANT USAGE, SELECT ON SEQUENCE cache_entries_id_seq TO sefaria_context;
