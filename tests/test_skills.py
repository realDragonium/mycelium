"""The shipped skills name only tools, parameters and routes the server has.

Skills under `skills/` are installed by people who run their own server, so a
renamed tool or parameter must fail here rather than in their session. The
scan follows `test_docgen_prompts.py`'s served-guidance test: a snake_case
name written as a call or in backticks counts as a tool when it starts with a
verb some registered tool starts with.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from mycelium import server
from mycelium.http import create_app
from mycelium.http.tool_routes import _path_for

_ROOT = Path(__file__).resolve().parents[1]
_SKILLS = _ROOT / "skills"
_SKILL_DIRS = sorted(p.parent for p in _SKILLS.glob("*/SKILL.md"))
# Claude Code truncates description plus when_to_use at this length.
_DESCRIPTION_LIMIT = 1536
# Response fields that start with a tool's verb.
_FIELDS = {"connect_error", "read_tools"}


def _parameters() -> dict[str, set[str]]:
    return {
        tool.__name__: set(inspect.signature(tool).parameters) for tool in server.TOOLS
    }


def _skill_texts() -> dict[str, str]:
    return {
        str(path.relative_to(_SKILLS)): path.read_text(encoding="utf-8")
        for path in sorted(_SKILLS.rglob("*.md"))
        if path != _SKILLS / "README.md"
    }


def _frontmatter(skill_dir: Path) -> dict[str, str]:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    block = text.split("---\n", 2)[1]
    return dict(line.split(": ", 1) for line in block.splitlines() if line)


def _api_route_patterns() -> list[re.Pattern[str]]:
    paths = {getattr(route, "path", "") for route in create_app().routes}
    return [
        re.compile(re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$")
        for path in paths
        if path.startswith("/api/")
    ]


def _expand(path: str) -> list[str]:
    """`/x/{a|b}` → `/x/a`, `/x/b`; any other `{placeholder}` stays a
    segment the route's own placeholder matches."""
    choice = re.search(r"\{([a-z]+(?:\|[a-z]+)+)\}", path)
    if choice is None:
        return [path]
    return [
        expanded
        for option in choice.group(1).split("|")
        for expanded in _expand(path[: choice.start()] + option + path[choice.end() :])
    ]


def test_every_skill_is_found():
    assert {p.name for p in _SKILL_DIRS} >= {
        "mycelium-agent-tasks",
        "mycelium-authoring",
        "mycelium-code-curation",
        "mycelium-curation",
        "mycelium-documentation",
        "mycelium-draft",
        "mycelium-draft-review",
        "mycelium-guide-authoring",
        "mycelium-knowledge-source",
        "mycelium-research",
    }


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=lambda p: p.name)
def test_skill_frontmatter_names_the_skill_and_says_when_to_use_it(skill_dir: Path):
    meta = _frontmatter(skill_dir)

    assert meta["name"] == skill_dir.name
    assert "Use " in meta["description"]
    assert len(meta["description"]) <= _DESCRIPTION_LIMIT


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=lambda p: p.name)
def test_the_repo_loads_each_skill_from_the_shared_folder(skill_dir: Path):
    link = _ROOT / ".claude" / "skills" / skill_dir.name

    assert link.is_symlink()
    assert link.resolve() == skill_dir.resolve()


def test_skills_name_only_registered_tools_and_parameters():
    parameters = _parameters()
    verbs = tuple({name.split("_", 1)[0] + "_" for name in parameters if "_" in name})
    problems = []
    for source, text in _skill_texts().items():
        for match in re.finditer(r"\b([a-z]+(?:_[a-z]+)+)\(([^)]*)\)?", text):
            name, arguments = match.group(1), match.group(2)
            if name not in parameters:
                if name.startswith(verbs):
                    problems.append(f"{source}: {name}() is not a tool")
                continue
            for parameter in re.findall(r"\b([a-z_]+)=", arguments):
                if parameter not in parameters[name]:
                    problems.append(f"{source}: {name}() has no {parameter!r}")
        for name in re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text):
            if name.startswith(verbs) and name not in {*parameters, *_FIELDS}:
                problems.append(f"{source}: `{name}` is not a tool")
    assert problems == []


def test_tool_routes_in_skills_exist_and_take_the_json_they_are_sent():
    by_path = {_path_for(name): name for name in _parameters()}
    parameters = _parameters()
    problems = []
    for source, text in _skill_texts().items():
        for match in re.finditer(
            r"(?:\$MYCELIUM_URL|[\s`\"])(/[a-z]+(?:-[a-z]+)+)\b(?![/-])", text
        ):
            path = match.group(1)
            name = by_path.get(path)
            if name is None:
                problems.append(f"{source}: {path} is not a tool route")
                continue
            following = text[match.end() :].split("\n\n", 1)[0][:200]
            body = re.search(r"\{[^{}]*\}", following)
            if body is None or "/" in following[: body.start()]:
                continue
            for key in re.findall(r'"([a-z_]+)"\s*:', body.group(0)):
                if key not in parameters[name]:
                    problems.append(f"{source}: {path} has no {key!r}")
    assert problems == []


def test_api_routes_in_skills_exist():
    patterns = _api_route_patterns()
    problems = []
    for source, text in _skill_texts().items():
        for path in re.findall(r"/api/[a-z0-9_{}|/-]+[a-z0-9_}]", text):
            for expanded in _expand(path):
                if not any(p.match(expanded) for p in patterns):
                    problems.append(f"{source}: {expanded} is not a route")
    assert problems == []


def test_plugin_manifests_point_at_the_skills_folder():
    plugin = json.loads((_SKILLS / ".claude-plugin" / "plugin.json").read_text())
    marketplace = json.loads(
        (_ROOT / ".claude-plugin" / "marketplace.json").read_text()
    )

    assert [p["source"] for p in marketplace["plugins"]] == ["./skills"]
    assert marketplace["plugins"][0]["name"] == plugin["name"]
