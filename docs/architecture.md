# Sefaria Context architecture

The Sefaria Context service is the third research layer in the Theosis ecosystem.

```text
Hermes theosis_ai profile
  ├── Theosis Bible MCP       :8000
  ├── Theosis Midrash MCP     :8001
  └── Sefaria Context MCP     :8002
```

## Local tier

The local PostgreSQL database (`sefaria_context`) contains selected, high-value works:

- Targum Onkelos on the Torah
- Targum Jonathan on the Torah and selected Prophets
- Selected Mishnah tractates
- Selected Josephus and Philo editions with approved licences

Each `works` row has a role such as `primary_text`, `rabbinic_context`, or `historical_context`. Each `editions` row keeps the exact language, version title, source URL, licence, primary/source flags, and metadata. Segments preserve the exact Sefaria reference and structural path.

## On-demand tier

`lookup_sefaria_text` and the specialised lexicon/commentary tools fetch exact references outside the local corpus. Approved responses are stored in `cache_entries` with:

- exact reference and language
- selected version title
- raw selected payload
- source URL
- licence
- retrieval and expiry timestamps
- SHA-256 payload hash

Only Public Domain, CC0, and CC-BY editions are cached by default. CC-BY-NC, CC-BY-SA, unknown, and missing licences are rejected rather than silently reused.

## Why this is hybrid

A full Sefaria mirror would contain many overlapping editions and a very large Talmud/commentary surface. The local tier is reserved for recurring Bible-study sources. Rare works are retrieved on demand and cached after licence/provenance validation. This keeps MCP results focused and avoids feeding the model thousands of near-duplicate passages.

## Source-layer rules

- Tanakh: primary biblical text.
- Targum: Aramaic interpretive translation.
- Midrash/Mishnah/Talmud: rabbinic traditions, not plain biblical text.
- Rashi/Ibn Ezra: Jewish commentary, labelled by commentator and edition.
- Jastrow/BDB: reference works, not narrative or doctrinal authorities.
- Josephus/Philo: historical or Second Temple context.

The MCP instructions and the profile skill reinforce these distinctions in Hermes responses.
