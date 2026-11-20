# ECC in Nova (for Claude Code sessions)

Nova's repository carries [ECC](https://github.com/affaan-m/ECC) 2.2.3 (MIT, by Affaan Mustafa), "the agent harness
operating system", in `.claude/`: its core rules, agents, commands and workflow skills. Any Claude Code session working
on Nova (in the terminal, the desktop app or the cloud) picks them up, e.g. the `code-reviewer`, `architect` and
`build-error-resolver` agents, the `/plan`, `/tdd` and `/code-review` commands, and the coding and testing rules.

It is ECC's **minimal profile without runtime hooks**: nothing runs by itself on your PC or in a session. ECC's
`includeCoAuthoredBy: false` setting was left out, so commits are credited as before. Nova itself (the app) doesn't use
these files; they're for building Nova.

- **Update or reinstall** (from the Nova folder): delete `.claude/agents`, `.claude/commands`, `.claude/rules`,
  `.claude/skills` and `.claude/scripts`, then run
  `npx ecc-universal@2.2.3 install --target claude-project --profile minimal --no-hooks` (Windows needs Node.js).
- **More of ECC**, e.g. Python skills: add `--with <component>`; see ECC's README, "Choose only the components you need".
- **Hooks** (optional, they run commands automatically): only with ECC's `--enable-hooks`, after reading what they do.
- **Remove it**: delete those folders and `.claude/AGENTS.md`, `README.md`, `plugin.json`, `marketplace.json`,
  `PLUGIN_SCHEMA_NOTES.md` and `mcp-configs`.
