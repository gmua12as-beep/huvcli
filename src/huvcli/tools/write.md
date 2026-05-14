Create a new file or perform a full rewrite of an existing one.

**Use sparingly.** For changes to existing files, `edit_file` is almost always correct. Only use `write_file` when:
- The file does not exist yet, OR
- The user explicitly asked for a full rewrite.

The diff between old and new is shown (in verbose mode); confirmation is required in `suggest` mode.
