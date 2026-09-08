"""The agent loop: talks to the Anthropic API, exposes skill-management
tools, and reports every step (assistant text, tool calls, tool results)
through a callback so the caller can stream the invocation process live.
"""
from __future__ import annotations

import os
import time
from typing import Callable

import anthropic

from . import skills

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_TURNS = 10

LogFn = Callable[[dict], None]

TOOLS = [
    {
        "name": "list_skills",
        "description": "List all installed skills with their name and one-line description.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "load_skill",
        "description": (
            "Load the full SKILL.md instructions for one skill, plus the list "
            "of supporting files it ships (scripts, references, templates). "
            "Call this before following a skill's instructions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "skill name"}},
            "required": ["name"],
        },
    },
    {
        "name": "read_skill_file",
        "description": "Read one supporting file inside a skill's directory (e.g. a reference doc).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "skill name"},
                "path": {"type": "string", "description": "file path relative to the skill directory"},
            },
            "required": ["name", "path"],
        },
    },
    {
        "name": "run_skill_script",
        "description": (
            "Execute a script bundled inside a skill's directory (python/bash) "
            "and return its stdout, stderr and exit code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "skill name"},
                "script_path": {"type": "string", "description": "script path relative to the skill directory"},
                "args": {"type": "array", "items": {"type": "string"}, "description": "command-line arguments"},
            },
            "required": ["name", "script_path"],
        },
    },
    {
        "name": "create_skill",
        "description": "Create a new skill: writes a SKILL.md with the given description and instructions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "slug, e.g. 'pdf-merge'"},
                "description": {"type": "string", "description": "one-line description of when to use this skill"},
                "content": {"type": "string", "description": "markdown body: the skill's instructions"},
            },
            "required": ["name", "description", "content"],
        },
    },
    {
        "name": "download_skill",
        "description": (
            "Download a skill from a git repository (e.g. a GitHub URL) into the local skills "
            "directory. If the repo holds multiple skills, pass skill_path pointing at the "
            "subdirectory that contains that skill's SKILL.md."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_url": {"type": "string"},
                "skill_path": {"type": "string", "description": "subdirectory within the repo, if any"},
                "rename": {"type": "string", "description": "local name to install the skill under"},
            },
            "required": ["repo_url"],
        },
    },
]


def _dispatch(tool_name: str, tool_input: dict) -> dict:
    try:
        if tool_name == "list_skills":
            return {"skills": [{"name": s.name, "description": s.description} for s in skills.discover_skills()]}
        if tool_name == "load_skill":
            s = skills.get_skill(tool_input["name"])
            if s is None:
                return {"error": f"no such skill: {tool_input['name']}"}
            return {"name": s.name, "description": s.description, "instructions": s.body, "files": s.files}
        if tool_name == "read_skill_file":
            return {"content": skills.read_skill_file(tool_input["name"], tool_input["path"])}
        if tool_name == "run_skill_script":
            return skills.run_skill_script(
                tool_input["name"], tool_input["script_path"], tool_input.get("args") or []
            )
        if tool_name == "create_skill":
            s = skills.create_skill(tool_input["name"], tool_input["description"], tool_input["content"])
            return {"created": s.name, "files": s.files}
        if tool_name == "download_skill":
            s = skills.download_skill(
                tool_input["repo_url"], tool_input.get("skill_path"), tool_input.get("rename")
            )
            return {"installed": s.name, "description": s.description, "files": s.files}
        return {"error": f"unknown tool: {tool_name}"}
    except skills.SkillError as e:
        return {"error": str(e)}


def _system_prompt() -> str:
    return (
        "You are a personal research assistant for exploring, using and building "
        "Claude-style skills.\n\n"
        "Available skills (name: description):\n"
        f"{skills.manifest_text()}\n\n"
        "When a skill looks relevant to the user's request, call load_skill first "
        "to read its full instructions before acting on them. Use run_skill_script "
        "to execute any scripts a skill provides. Use create_skill or download_skill "
        "when the user asks you to add a new skill. Be concise in your final answers."
    )


def run_agent(history: list[dict], user_message: str, log: LogFn) -> list[dict]:
    """Runs the agent loop to completion, calling log(event) for every step.
    Returns the updated message history (including this turn)."""
    client = anthropic.Anthropic()
    messages = list(history) + [{"role": "user", "content": user_message}]

    for turn in range(MAX_TURNS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=_system_prompt(),
            tools=TOOLS,
            messages=messages,
        )

        text_parts = [b.text for b in response.content if b.type == "text"]
        if text_parts:
            log({"type": "assistant_text", "text": "\n".join(text_parts), "turn": turn})

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            log({"type": "tool_call", "tool": block.name, "input": block.input, "turn": turn})
            t0 = time.time()
            result = _dispatch(block.name, block.input)
            log({
                "type": "tool_result",
                "tool": block.name,
                "output": result,
                "ms": int((time.time() - t0) * 1000),
                "turn": turn,
            })
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": _stringify(result)}
            )
        messages.append({"role": "user", "content": tool_results})
    else:
        log({"type": "error", "text": f"stopped after {MAX_TURNS} turns without a final answer"})

    return messages


def _stringify(result: dict) -> str:
    import json

    return json.dumps(result, ensure_ascii=False)[:8000]
