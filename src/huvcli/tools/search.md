Search file contents by regex. Uses `ripgrep` when available, otherwise falls back to a Python walk that skips binaries and large files (>2 MB).

Prefer this over reading whole files for any "where is X used?" question. Combine `pattern` with `glob` to narrow the search (e.g. `glob="*.tsx"`).

Returns matches in `path:line:content` form, capped at `max_matches`.
