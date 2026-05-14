Read a single file with `cat -n` line numbers in the output. Use `offset` (0-based start line) and `limit` to read a window.

For files >300 lines, grep first to locate the section you actually need, then read with offset/limit. Don't dump the whole file unless you need the whole file.

`read_file` records mtime+size; `edit_file` / `apply_patch` refuse to touch a file you haven't read this session.
