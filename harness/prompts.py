"""The only text the harness ever sends to a solver, identical on both routes."""

SYSTEM = ("You are an autonomous investigator working alone inside a sandbox. Your only tools are the sandbox "
          "tools; there is no human to ask and no feedback on your answer.")

KICKOFF = "Read /evidence/TASK.md and begin. Keep /work/answer.json and /work/report.md current."

NUDGE = "No tool was called. Continue, or stop if /work/answer.json and /work/report.md are final."
