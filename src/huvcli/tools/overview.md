Produce a structural outline of the project — every tracked source file plus the top-level symbols defined inside (functions, classes, types, exports).

Use this at the **start** of a session in an unfamiliar codebase, before reading files. One call gives you a project map; you can then `grep` or `read_file` targets specifically instead of dumping whole files.

Supported languages: Python, JavaScript/TypeScript, Go, Rust, Java, Ruby, PHP, Swift. Other files show their path with `(no symbols extracted)`.

Output is capped at `max_files` files and `max_symbols_per_file` symbols per file. The walk respects `.gitignore` when in a git repo.
