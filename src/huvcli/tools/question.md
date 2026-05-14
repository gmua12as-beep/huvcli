Ask the user a clarifying question and wait for their answer.

**Use ONLY when the task is genuinely ambiguous** and continuing would risk wasted work. Do not use this to:
- Confirm obvious things ("should I edit the file you asked me to edit?")
- Ask permission for routine edits
- Stall mid-task because you're unsure

Provide `options` if there's a clear small set of answers — the user can pick by number. In non-interactive contexts (no TTY, or `--yes`) the tool returns a deferred message; proceed with reasonable defaults and explain the assumption in your final answer.
