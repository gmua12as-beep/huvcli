Run a shell command in the project directory. Used for build/test/lint runs the user explicitly asked for.

**Do not** use to verify tools work, write throwaway files, or "test" your edits without being asked. Trust the user to run their own checks.

Destructive commands (`rm -rf`, `git reset --hard`, `Remove-Item -Recurse`, etc.) are blocked unless `dangerous=true` is set explicitly. Even then, the user is asked to confirm in `suggest` and `auto-edit` modes.

Output is captured (stdout + stderr) and returned along with the exit code.
