Apply a unified diff or codex-style `*** Begin Patch / *** End Patch` envelope. Multi-file capable; can add and delete files in the same patch.

A fuzzy hunk locator handles small line-number drift from the model, but for single-file targeted changes `edit_file` is more reliable.

If the patch fails to parse, the error includes both accepted formats — read it and try again.
