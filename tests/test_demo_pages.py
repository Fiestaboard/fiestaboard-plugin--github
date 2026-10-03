"""Validates that demo page templates in manifest.json only use defined variables."""

import json
import re
from pathlib import Path

import pytest

_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "manifest.json"
_SYSTEM_PREFIXES = {"date_time"}


def _load_manifest():
    return json.loads(_MANIFEST_PATH.read_text())


def _valid_refs(plugin_id: str, manifest: dict) -> set:
    variables = manifest.get("variables", {})
    simple = variables.get("simple", {})
    arrays = variables.get("arrays", {})

    valid = set()
    for var in simple:
        valid.add(f"{plugin_id}.{var}")
        valid.add(var)
    for arr_name, arr_spec in arrays.items():
        fields = arr_spec.get("item_fields", [])
        sub_arrays = arr_spec.get("sub_arrays", {})
        for i in range(10):
            for field in fields:
                valid.add(f"{plugin_id}.{arr_name}.{i}.{field}")
                valid.add(f"{arr_name}.{i}.{field}")
            for sub_name, sub_spec in sub_arrays.items():
                for j in range(20):
                    for field in sub_spec.get("item_fields", []):
                        valid.add(f"{plugin_id}.{arr_name}.{i}.{sub_name}.{j}.{field}")
                        valid.add(f"{arr_name}.{i}.{sub_name}.{j}.{field}")
    return valid


def _demo_cases() -> list:
    manifest = _load_manifest()
    demo = manifest.get("demo", {})
    return [(device_type, entry.get("template", [])) for device_type, entry in demo.items()]


@pytest.mark.parametrize("device_type,template", _demo_cases())
def test_demo_variables_are_defined(device_type: str, template: list) -> None:
    """All {{variable}} references in each demo template must be declared in manifest variables."""
    manifest = _load_manifest()
    plugin_id = manifest.get("id", "")
    valid = _valid_refs(plugin_id, manifest)

    invalid = []
    for line in template:
        for m in re.finditer(r"\{\{([^}]+)\}\}", line):
            ref = m.group(1).strip()
            prefix = ref.split(".")[0]
            if prefix in _SYSTEM_PREFIXES:
                continue
            if ref not in valid:
                invalid.append(ref)

    assert not invalid, f"Demo '{device_type}' references undefined variables: {invalid}"


# ----------------------------------------------------------------------
# Previews show what the demo templates really render
# ----------------------------------------------------------------------


def _render(template: list, metadata: list, data: dict, width: int) -> list:
    """Substitute {{github.x}} / {{github.arr.i.f}} and align like core's TemplateEngine."""

    def value(ref: str) -> str:
        parts = ref.split(".")[1:]
        node = data
        for part in parts:
            node = node[int(part)] if part.isdigit() else node[part]
        return str(node)

    rows = []
    for line, meta in zip(template, metadata):
        text = re.sub(r"\{\{([^}]+)\}\}", lambda m: value(m.group(1).strip()), line)
        tiles = _tile_count(text)
        pad = max(width - tiles, 0)
        if meta.get("alignment") == "center":
            text = " " * (pad // 2) + text
        rows.append(text.rstrip())
    return rows


def _tile_count(text: str) -> int:
    return len(re.sub(r"\{\d+\}", "#", text))


def _preview_data(failing: bool) -> dict:
    from plugins.github import GitHubPlugin

    from .fixtures import check_run, check_runs, pull, repository, search

    runs = [check_run(f"JOB{i}") for i in range(12)]
    runs += (
        [check_run("LINT", conclusion="failure"), check_run("E2E", conclusion="failure")]
        if failing
        else [
            check_run("LINT"),
            check_run("E2E"),
        ]
    )
    snapshot = {
        "reviews": search([pull(412, "Fix login redirect"), pull(409, "Bump requests"), pull(401, "Docs")], total=3),
        "mine": search([pull(418, "Add dark mode"), pull(417, "Tidy")], total=2),
        "repo": (repository(stars=1234), check_runs(runs), "main"),
    }
    return GitHubPlugin._build_data(snapshot)


@pytest.mark.parametrize("label,failing", [(None, False), ("Failing build", True)])
def test_flagship_previews_match_the_demo_template(label, failing) -> None:
    manifest = _load_manifest()
    demo = manifest["demo"]["flagship"]
    preview = next(p for p in manifest["previews"] if p["device_type"] == "flagship" and p.get("label") == label)
    rendered = _render(demo["template"], demo["line_metadata"], _preview_data(failing), 22)
    # The board cuts a long row at 22 tiles (these rows have no colour markers past 22).
    rendered = [row if _tile_count(row) <= 22 else row[: len(row) - (_tile_count(row) - 22)] for row in rendered]
    assert preview["rows"] == rendered


def test_note_preview_matches_the_demo_template() -> None:
    manifest = _load_manifest()
    demo = manifest["demo"]["note"]
    preview = next(p for p in manifest["previews"] if p["device_type"] == "note")
    assert preview["rows"] == _render(demo["template"], demo["line_metadata"], _preview_data(False), 15)
