-- Harden on-demand cache identity, permissions, and expiry maintenance.

ALTER TABLE public.cache_entries
    ALTER COLUMN language SET NOT NULL,
    ALTER COLUMN version_title SET NOT NULL;

GRANT DELETE ON public.cache_entries TO sefaria_context;

CREATE INDEX IF NOT EXISTS cache_entries_expires_idx
    ON public.cache_entries (expires_at)
    WHERE expires_at IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS cache_entries_identity_idx
    ON public.cache_entries (ref, language, version_title);
