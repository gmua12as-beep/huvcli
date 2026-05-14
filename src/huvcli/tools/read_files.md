Read several files in one call. Strongly prefer this when you need to inspect 2+ files in a row — N separate `read_file` calls take N round-trips and bloat the context with stale tool results.

Same `offset` / `limit` applies to every path in the batch. Errors on individual paths are inlined (the rest of the batch still comes through).
