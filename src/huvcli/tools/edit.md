Exact-string replacement — the workhorse for code changes.

Replaces `old_string` with `new_string` in `path`. `old_string` must be unique in the file, or set `replace_all=true`. Include enough surrounding context in `old_string` to disambiguate (a few lines above and below the change).

**Refused if:**
- The file wasn't read this session (`read_file` it first).
- The file changed on disk since you read it (re-read first).
- `old_string` matches multiple places and `replace_all` is not set.
- The edit would touch more than ~120 lines in a single call (split into smaller edits, or use `write_file` for an explicit full rewrite).

Prefer many small `edit_file` calls over one large one. One concern per call.
