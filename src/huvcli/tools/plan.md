Replace the current task plan with a list of steps. Use for any multi-step task.

Each step: `{step: "human-readable description", status: "pending" | "in_progress" | "completed"}`.

At the start of a multi-step task, call this with each major step as `pending` plus the first as `in_progress`. As you finish a step, call again with that step marked `completed` and the next marked `in_progress`. Surfacing the plan keeps scope visible to the user — they can interrupt if you're going wrong.

For single-step tasks, skip the plan and just do the work.
