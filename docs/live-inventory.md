# Live Sefaria Context inventory

Point-in-time snapshot recorded 2026-09-20. Query `/health` and `get_context_corpus_summary` for live values.

## Service

- systemd unit: `sefaria-context.service`
- endpoint: `192.168.1.130:8002/mcp`
- service account: `sefaria_context`
- database: `sefaria_context` (UTF-8)
- schema migrations: `001` and `002` applied

## Corpus snapshot

- 43 works
- 54 editions
- 28,689 segments
- 54 ingestion manifests
- Onkelos, Targum Jonathan, selected Mishnah, Josephus, and Philo
- Long-tail Jastrow/Rashi/Ibn Ezra available through the on-demand cache

## Verification

- Health endpoint: HTTP 200
- MCP initialize/tools-list: verified
- Targum Onkelos and Targum Jonathan retrieval: verified
- Mishnah Berakhot retrieval: verified
- Josephus War of the Jews retrieval: verified
- Jastrow lexicon lookup: verified
- Rashi and Ibn Ezra commentary lookup: verified
- Remote cache hit path: verified
