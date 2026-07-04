"""Source adapters — one module per registered source (contracts §6).
Each fetches raw records and maps them toward the spine; no source may appear
in a provenance envelope without a matching entry in config.SOURCES."""
