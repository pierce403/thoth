# Thoth Agent Notes

Project: Thoth - an agentic assistant that monitors public community chats and stores data for later RAG/pgvector workflows.

## Project expectations
- Use **Python + Playwright** for all scraping.
- Run **headful** (browser visible) at all times.
- **Slow scraping**: prioritize recent messages, then backfill older history.
- **No secrets** in code or env. If auth is required, navigate to login and pause for the user to authenticate.
- Data is stored in a **Postgres-compatible SQLite schema** for easy migration.
- `sync.sh` is expected to run in a continuous loop.
- `agent.sh` communicates with the user as "Thoth" over **XMTP**.

## Key paths
- Config: `config/thoth.toml`
- Database: `data/thoth.db`
- Sync loop: `sync.sh`
- Agent loop: `agent.sh`
- Python package: `thoth/`

## Operational guidance
- Keep scraping gentle (small scroll steps + delays).
- Prefer selectors defined in config; avoid hardcoding per-platform DOM unless required.
- Record edits, reactions, and threading in universal tables where possible.

## Self-improvement protocol
Keep this file current with anything learned while working in the repo. Add/update:
- Commands that work to build/run/test.
- Common pitfalls, missing deps, or platform quirks.
- Selector tips or known DOM changes per source.
- Any conventions discovered while editing.
- Process rule: always commit and push after every edit.

## Commands (verified)
- Create venv + install deps: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Install Playwright browsers: `python -m playwright install`
- Run one sync pass: `python -m thoth.sync --config config/thoth.toml`
- Run sync loop: `./sync.sh --config config/thoth.toml`
- Run agent (stdio): `./agent.sh --config config/thoth.toml --stdio`

## Known pitfalls / notes
- Playwright may require system deps; if the browser fails to launch, run `sudo playwright install-deps`.
- Browser is forced headful; config `headless=true` is ignored with a warning.
- Slack/Telegram sources are enabled, but sample channels are disabled until you fill in URLs.
- Persistent browser profile is stored under `data/profiles/default`.

## Codex skill usage (from local instructions)
These are copied from the local AGENTS instructions so future agents follow the same rules.

<INSTRUCTIONS>
## Skills
These skills are discovered at startup from multiple local sources. Each entry includes a name, description, and file path so you can open the source for full instructions.
- skill-creator: Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Codex's capabilities with specialized knowledge, workflows, or tool integrations. (file: /home/pierce/.codex/skills/.system/skill-creator/SKILL.md)
- skill-installer: Install Codex skills into $CODEX_HOME/skills from a curated list or a GitHub repo path. Use when a user asks to list installable skills, install a curated skill, or install a skill from another repo (including private repos). (file: /home/pierce/.codex/skills/.system/skill-installer/SKILL.md)
- Discovery: Available skills are listed in project docs and may also appear in a runtime "## Skills" section (name + description + file path). These are the sources of truth; skill bodies live on disk at the listed paths.
- Trigger rules: If the user names a skill (with `$SkillName` or plain text) OR the task clearly matches a skill's description, you must use that skill for that turn. Multiple mentions mean use them all. Do not carry skills across turns unless re-mentioned.
- Missing/blocked: If a named skill isn't in the list or the path can't be read, say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1) After deciding to use a skill, open its `SKILL.md`. Read only enough to follow the workflow.
  2) If `SKILL.md` points to extra folders such as `references/`, load only the specific files needed for the request; don't bulk-load everything.
  3) If `scripts/` exist, prefer running or patching them instead of retyping large code blocks.
  4) If `assets/` or templates exist, reuse them instead of recreating from scratch.
- Description as trigger: The YAML `description` in `SKILL.md` is the primary trigger signal; rely on it to decide applicability. If unsure, ask a brief clarification before proceeding.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request and state the order you'll use them.
  - Announce which skill(s) you're using and why (one short line). If you skip an obvious skill, say why.
- Context hygiene:
  - Keep context small: summarize long sections instead of pasting them; only load extra files when needed.
  - Avoid deeply nested references; prefer one-hop files explicitly linked from `SKILL.md`.
  - When variants exist (frameworks, providers, domains), pick only the relevant reference file(s) and note that choice.
- Safety and fallback: If a skill can't be applied cleanly (missing files, unclear instructions), state the issue, pick the next-best approach, and continue.
</INSTRUCTIONS>
