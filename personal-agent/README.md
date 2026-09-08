# Personal Skill Agent

A local agent for researching Claude-style "skills": it can load a skill's
instructions, run scripts a skill ships, create new skills, and download
skills from a git repository — all from a local web UI where you can see the
skill files, the chat, and the full invocation log (every tool call and its
result) as it happens.

## Setup

```bash
cd personal-agent
cp .env.example .env   # then edit .env and set ANTHROPIC_API_KEY
./run.sh
```

Open http://localhost:8008.

## Layout

```
personal-agent/
  app/
    main.py      FastAPI app: skill CRUD/download endpoints + streaming chat
    agent.py      Anthropic tool-use loop + tool definitions
    skills.py     skill discovery, file access, creation, git download
    static/       the web UI (vanilla HTML/CSS/JS)
  skills/         installed skills, one directory per skill
```

## How a skill is structured

Each skill is a directory under `skills/` with a `SKILL.md`:

```markdown
---
name: my-skill
description: One line describing when to use this skill.
---

Markdown instructions for the agent to follow, plus any supporting
files (scripts/, references/, templates/) alongside SKILL.md.
```

The agent only sees the name + description of every skill by default
(kept in its system prompt). When a request matches one, it calls
`load_skill` to pull in the full instructions before acting — the same
progressive-disclosure pattern Claude Code itself uses for skills.

## What the agent can do

- `list_skills` / `load_skill` / `read_skill_file` — discover and read skills
- `run_skill_script` — execute a script bundled in a skill's directory
- `create_skill` — write a new SKILL.md from a name/description/instructions
- `download_skill` — `git clone --sparse` a skill (or a subdirectory of a
  repo containing several skills) into `skills/`

All of this is also exposed directly as UI actions (the "+ New" and
"Download" buttons in the left panel), so you don't need to go through the
chat for basic skill management.

## Notes

- Single-user, local-only tool: conversation history and running skills all
  live in one process, no auth. Don't expose it beyond localhost.
- `run_skill_script` executes arbitrary scripts from skill directories with
  a 30s timeout and no other sandboxing — only load skills you trust.
