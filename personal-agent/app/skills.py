"""Skill discovery, file access, creation and download.

A "skill" is a directory under SKILLS_DIR containing a SKILL.md file with
YAML frontmatter (name, description) followed by markdown instructions,
plus any number of supporting files (scripts, references, templates) —
the same shape Claude Code uses for its own skills.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"
SKILLS_DIR.mkdir(exist_ok=True)

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class SkillError(Exception):
    pass


@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path
    body: str = ""
    files: list[str] = field(default_factory=list)


def _parse_skill_md(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    _, front, body = parts
    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, body.strip()


def _list_files(skill_dir: Path) -> list[str]:
    out = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            out.append(str(p.relative_to(skill_dir)))
    return out


def _skill_dir(name: str) -> Path:
    if not NAME_RE.match(name):
        raise SkillError(f"invalid skill name: {name!r}")
    d = (SKILLS_DIR / name).resolve()
    if SKILLS_DIR.resolve() not in d.parents:
        raise SkillError("invalid skill path")
    return d


def discover_skills() -> list[SkillMeta]:
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        skill_md = d / "SKILL.md"
        if not d.is_dir() or not skill_md.exists():
            continue
        meta, body = _parse_skill_md(skill_md.read_text(encoding="utf-8"))
        skills.append(
            SkillMeta(
                name=meta.get("name", d.name),
                description=meta.get("description", ""),
                path=d,
                body=body,
                files=_list_files(d),
            )
        )
    return skills


def get_skill(name: str) -> SkillMeta | None:
    d = _skill_dir(name)
    skill_md = d / "SKILL.md"
    if not skill_md.exists():
        return None
    meta, body = _parse_skill_md(skill_md.read_text(encoding="utf-8"))
    return SkillMeta(
        name=meta.get("name", d.name),
        description=meta.get("description", ""),
        path=d,
        body=body,
        files=_list_files(d),
    )


def manifest_text() -> str:
    skills = discover_skills()
    if not skills:
        return "(no skills installed yet)"
    return "\n".join(f"- {s.name}: {s.description}" for s in skills)


def _safe_file_path(name: str, rel_path: str) -> Path:
    skill_dir = _skill_dir(name)
    target = (skill_dir / rel_path).resolve()
    if skill_dir not in target.parents and target != skill_dir:
        raise SkillError("path escapes skill directory")
    return target


def read_skill_file(name: str, rel_path: str) -> str:
    target = _safe_file_path(name, rel_path)
    if not target.exists() or not target.is_file():
        raise SkillError(f"file not found: {rel_path}")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"<binary file, {target.stat().st_size} bytes>"


def run_skill_script(name: str, script_path: str, args: list[str] | None = None) -> dict:
    target = _safe_file_path(name, script_path)
    if not target.exists():
        raise SkillError(f"script not found: {script_path}")
    args = args or []
    if any(not isinstance(a, str) for a in args):
        raise SkillError("args must be strings")

    suffix = target.suffix
    if suffix == ".py":
        cmd = ["python3", str(target), *args]
    elif suffix in (".sh", ".bash"):
        cmd = ["bash", str(target), *args]
    else:
        cmd = [str(target), *args]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(target.parent),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": "timed out after 30s"}
    except OSError as e:
        raise SkillError(f"could not execute script: {e}")

    return {"exit_code": proc.returncode, "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-4000:]}


def create_skill(name: str, description: str, content: str) -> SkillMeta:
    d = _skill_dir(name)
    if d.exists():
        raise SkillError(f"skill already exists: {name}")
    d.mkdir(parents=True)
    front = yaml.safe_dump({"name": name, "description": description}, sort_keys=False).strip()
    (d / "SKILL.md").write_text(f"---\n{front}\n---\n\n{content.strip()}\n", encoding="utf-8")
    return get_skill(name)


def delete_skill(name: str) -> None:
    d = _skill_dir(name)
    if not d.exists():
        raise SkillError(f"skill not found: {name}")
    shutil.rmtree(d)


def download_skill(repo_url: str, skill_path: str | None = None, rename: str | None = None) -> SkillMeta:
    if not (repo_url.startswith("https://") or repo_url.startswith("git@")):
        raise SkillError("repo_url must use https:// or git@")
    if skill_path and ".." in Path(skill_path).parts:
        raise SkillError("invalid skill_path")

    tmp = Path(tempfile.mkdtemp(prefix="skill-dl-"))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", repo_url, str(tmp)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if skill_path:
            subprocess.run(
                ["git", "-C", str(tmp), "sparse-checkout", "set", skill_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            src = tmp / skill_path
        else:
            src = tmp

        if not (src / "SKILL.md").exists():
            raise SkillError(
                "no SKILL.md found at that location — pass skill_path pointing "
                "to the skill's subdirectory in the repo"
            )

        name = rename or src.name or repo_url.rstrip("/").rsplit("/", 1)[-1]
        name = re.sub(r"[^a-z0-9_-]", "-", name.lower())
        dest = _skill_dir(name)
        if dest.exists():
            raise SkillError(f"skill already exists locally: {name}")
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
        return get_skill(name)
    except subprocess.CalledProcessError as e:
        raise SkillError(f"git failed: {e.stderr.strip()[-500:]}")
    except subprocess.TimeoutExpired:
        raise SkillError("git operation timed out")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
