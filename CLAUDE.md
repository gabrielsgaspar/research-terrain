# CLAUDE.md

Read `AGENTS.md` first; it is the rule set for every agent in this repository.

Local sessions: run Claude Code inside WSL2, not native Windows. The repo's
`.claude/settings.json` turns the Bash sandbox on with `failIfUnavailable`,
and the sandbox needs Linux (bubblewrap), so Bash commands fail on native
Windows.
