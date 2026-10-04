"""What the GitHub plugin shows, given what GitHub answers."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from src.oauth.provider import validate_provider_block

from plugins.github import (
    API_VERSION,
    GitHubPlugin,
    board_safe,
    normalize_repository,
    short_count,
    summarize_checks,
)

from .fixtures import check_run, check_runs, pull, search

ROOT = Path(__file__).parent.parent


# ----------------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------------


def test_oauth_block_is_valid_device_flow(manifest_data):
    oauth = manifest_data["oauth"]
    assert validate_provider_block(oauth) == []
    assert oauth["flows"] == ["device"]
    assert oauth["device_authorization_url"] == "https://github.com/login/device/code"
    assert oauth["token_url"] == "https://github.com/login/oauth/access_token"
    assert oauth["client_id_setting"] == "client_id"
    # GitHub Apps get their access from the app's permissions, not scopes.
    assert "scopes" not in oauth


def test_no_client_secret_anywhere():
    for path in ROOT.rglob("*"):
        if (
            path.is_file()
            and ".git" not in path.parts
            and path.name != "test_plugin.py"
            and path.suffix in {".json", ".py", ".md", ".yml"}
        ):
            text = path.read_text()
            assert "client_secret" not in text, path


def test_manifest_basics(manifest_data):
    assert manifest_data["id"] == "github"
    assert manifest_data["fiestaboard_version"] == ">=9.11.0"
    props = manifest_data["settings_schema"]["properties"]
    assert {"enabled", "client_id", "repository", "branch", "refresh_seconds"} <= set(props)
    assert "required" not in manifest_data["settings_schema"]
    assert manifest_data["category"] == "data"


def test_ci_pins_the_manifest_version():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "ref: v9.11.0" in ci


def test_every_declared_variable_is_produced(github_api, plugin, manifest_data):
    data = plugin.fetch_data().data
    for name in manifest_data["variables"]["simple"]:
        assert name in data, name
    for array, spec in manifest_data["variables"]["arrays"].items():
        assert data[array], array
        assert set(spec["item_fields"]) <= set(data[array][0])


def test_previews_fit_their_boards(manifest_data):
    from src.text_to_board import take_tiles

    widths = {"flagship": 22, "note": 15}
    for preview in manifest_data["previews"]:
        width = widths[preview["device_type"]]
        for row in preview["rows"]:
            assert take_tiles(row, width)[0] == row, row


# ----------------------------------------------------------------------
# Sign-in
# ----------------------------------------------------------------------


@pytest.mark.parametrize("missing", [None, ""])
def test_not_signed_in_makes_no_request(github_api, plugin, token, missing):
    token.value = missing
    result = plugin.fetch_data()
    assert not result.available
    assert "sign in" in result.error.lower()
    assert github_api.calls == []


def test_older_fiestaboard_without_oauth(github_api, manifest_data):
    p = GitHubPlugin(manifest_data)
    p.config = {"enabled": True}
    with patch.object(GitHubPlugin, "get_oauth_token", None, create=True):
        result = p.fetch_data()
    assert not result.available
    assert "Update FiestaBoard" in result.error


def test_requests_carry_token_and_api_headers(github_api, plugin):
    plugin.fetch_data()
    for _, call in github_api.calls:
        headers = call["headers"]
        assert headers["Authorization"] == "Bearer test_access_token"
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-GitHub-Api-Version"] == API_VERSION
        assert "FiestaBoard" in headers["User-Agent"]
        assert call["timeout"]


def test_searches_use_pull_request_qualifiers(github_api, plugin):
    plugin.fetch_data()
    queries = [call["params"]["q"] for key, call in github_api.calls if key in ("reviews", "mine")]
    review_q, mine_q = queries
    for q in queries:
        assert "is:pr" in q and "is:open" in q and "archived:false" in q
    assert "review-requested:@me" in review_q
    assert "author:@me" in mine_q
    params = github_api.calls[0][1]["params"]
    assert params["sort"] == "updated" and params["order"] == "desc"


def test_never_calls_notifications(github_api, plugin):
    plugin.fetch_data()
    assert not any("notifications" in call["url"] for _, call in github_api.calls)


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------


def test_review_requests(github_api, plugin):
    data = plugin.fetch_data().data
    assert data["review_count"] == 3
    assert data["review_title"] == "FIX LOGIN REDIRECT"
    assert data["review_repo"] == "FIESTABOARD"
    assert data["review_number"] == "412"
    assert data["review_author"] == "MONA"
    assert data["review_line"] == "#412 FIX LOGIN REDIRECT"
    assert data["reviews"][1] == {
        "title": "BUMP REQUESTS",
        "repo": "BOARD-TOOLS",
        "number": "409",
        "author": "DEPLOY-BOT",
        "line": "#409 BUMP REQUESTS",
    }


def test_review_count_uses_total_count(github_api, plugin):
    github_api.reviews = search([pull(1, "One")], total=42)
    assert plugin.fetch_data().data["review_count"] == 42


def test_my_pull_requests(github_api, plugin):
    data = plugin.fetch_data().data
    assert data["my_pr_count"] == 2
    assert data["my_pr_title"] == "ADD DARK MODE"
    assert data["my_pr_number"] == "418"
    assert data["my_pr_repo"] == "FIESTABOARD"
    assert data["my_pr_line"] == "#418 ADD DARK MODE"
    assert data["my_draft_count"] == 1
    assert len(data["my_prs"]) == 2


def test_nothing_open(github_api, plugin):
    github_api.reviews = search([])
    github_api.mine = search([])
    data = plugin.fetch_data().data
    assert data["review_count"] == 0
    assert data["review_title"] == "" and data["review_line"] == ""
    assert data["reviews"] == []
    assert data["my_pr_count"] == 0 and data["my_prs"] == []


def test_repository_and_ci(github_api, plugin):
    data = plugin.fetch_data().data
    assert data["repo"] == "FIESTABOARD"
    assert data["repo_full"] == "OCTO-ORG/FIESTABOARD"
    assert data["branch"] == "MAIN"
    assert data["stars"] == 1234
    assert data["stars_short"] == "1.2K"
    assert data["ci_status"] == "PASSING"
    assert data["ci_tile"] == "{66}"
    assert data["ci_summary"] == "14/14 PASSED"
    assert (data["ci_passed"], data["ci_failed"], data["ci_running"], data["ci_total"]) == (14, 0, 0, 14)
    assert data["ci_failing_name"] == ""
    checks = next(call for key, call in github_api.calls if key == "checks")
    assert checks["url"].endswith("/repos/octo-org/fiestaboard/commits/main/check-runs")
    assert checks["params"]["per_page"] == 100


def test_branch_setting_overrides_default(github_api, make_plugin):
    github_api.runs["release/1.0"] = check_runs([check_run("build")])
    data = make_plugin(branch="release/1.0").fetch_data().data
    assert data["branch"] == "RELEASE/1.0"
    url = next(call["url"] for key, call in github_api.calls if key == "checks")
    assert url.endswith("/commits/release%2F1.0/check-runs")


def test_no_repository_configured(github_api, make_plugin):
    data = make_plugin(repository="").fetch_data().data
    assert github_api.count("repo") == 0 and github_api.count("checks") == 0
    assert data["repo"] == "" and data["stars"] == 0 and data["stars_short"] == ""
    assert data["ci_status"] == "" and data["ci_tile"] == "" and data["ci_summary"] == ""


def test_repository_given_as_url(github_api, make_plugin):
    data = make_plugin(repository="https://github.com/Octo-Org/FiestaBoard.git").fetch_data().data
    assert data["repo_full"] == "OCTO-ORG/FIESTABOARD"


@pytest.mark.parametrize(
    "runs,status,tile,summary,failing",
    [
        (
            [check_run("build"), check_run("lint", conclusion="failure"), check_run("e2e", conclusion="timed_out")],
            "FAILING",
            "{63}",
            "2 OF 3 FAILED",
            "LINT",
        ),
        (
            [check_run("build"), check_run("deploy", status="in_progress", conclusion=None)],
            "RUNNING",
            "{65}",
            "1 OF 2 RUNNING",
            "",
        ),
        (
            [check_run("build", status="queued", conclusion=None), check_run("lint", conclusion="cancelled")],
            "FAILING",
            "{63}",
            "1 OF 2 FAILED",
            "LINT",
        ),
        ([], "NO CHECKS", "", "NO CHECKS", ""),
        (
            [check_run("a", conclusion="neutral"), check_run("b", conclusion="action_required")],
            "FAILING",
            "{63}",
            "1 OF 2 FAILED",
            "B",
        ),
    ],
)
def test_ci_states(github_api, plugin, runs, status, tile, summary, failing):
    github_api.runs["main"] = check_runs(runs)
    data = plugin.fetch_data().data
    assert (data["ci_status"], data["ci_tile"], data["ci_summary"], data["ci_failing_name"]) == (
        status,
        tile,
        summary,
        failing,
    )


def test_summarize_checks_ignores_junk():
    assert summarize_checks(None)["status"] == "NO CHECKS"
    assert summarize_checks({"check_runs": [None, {"status": "completed", "conclusion": "success"}]})["total"] == 1


@pytest.mark.parametrize(
    "n,text",
    [
        (0, "0"),
        (999, "999"),
        (1000, "1K"),
        (1234, "1.2K"),
        (9999, "9.9K"),
        (12345, "12K"),
        (999999, "999K"),
        (1200000, "1.2M"),
        (25000000, "25M"),
    ],
)
def test_short_count(n, text):
    assert short_count(n) == text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("octo-org/fiestaboard", "octo-org/fiestaboard"),
        (" octo-org/fiestaboard ", "octo-org/fiestaboard"),
        ("https://github.com/octo-org/fiestaboard", "octo-org/fiestaboard"),
        ("github.com/octo-org/fiestaboard/", "octo-org/fiestaboard"),
        ("https://github.com/octo-org/my.repo.git", "octo-org/my.repo"),
        ("", ""),
        (None, ""),
        ("not a repo", None),
        ("owner/", None),
        ("a/b/c", None),
    ],
)
def test_normalize_repository(raw, expected):
    assert normalize_repository(raw) == expected


def test_board_safe():
    assert board_safe("Café 🚀 {fix}") == "CAFE FIX"
    assert board_safe(None) == ""


# ----------------------------------------------------------------------
# Caching and display
# ----------------------------------------------------------------------


def test_one_snapshot_serves_every_board(github_api, plugin, clock):
    plugin.fetch_data()
    plugin.fetch_data()
    assert github_api.count("reviews") == 1
    clock.advance(31)
    plugin.fetch_data()
    assert github_api.count("reviews") == 2


def test_config_change_resets_snapshot(github_api, plugin):
    plugin.fetch_data()
    plugin.on_config_change(plugin.config, {**plugin.config, "repository": ""})
    plugin.fetch_data()
    assert github_api.count("reviews") == 2


def test_formatted_display_flagship(github_api, plugin):
    result = plugin.fetch_data()
    assert result.formatted_lines == [
        "{66} FIESTABOARD",
        "14/14 PASSED",
        "3 TO REVIEW",
        "#412 FIX LOGIN REDIREC",
        "#409 BUMP REQUESTS",
        "MY PRS 2 STARS 1.2K",
    ]


def test_formatted_display_note(github_api, plugin):
    class Board:
        cols, rows = 15, 3

    with patch.object(GitHubPlugin, "board", Board()):
        lines = plugin.fetch_data().formatted_lines
    assert lines == ["{66} FIESTABOARD", "REVIEW 3 MINE 2", "STARS 1.2K"]


def test_formatted_display_without_repository(github_api, make_plugin):
    lines = make_plugin(repository="").fetch_data().formatted_lines
    assert lines[0] == "GITHUB"


def test_get_formatted_display(github_api, plugin, token):
    assert plugin.get_formatted_display()[0] == "{66} FIESTABOARD"
    plugin.clear_cache()
    p2 = GitHubPlugin(plugin.manifest)
    p2.config = plugin.config
    p2.get_oauth_token = lambda: None
    assert p2.get_formatted_display() is None


# ----------------------------------------------------------------------
# Settings validation
# ----------------------------------------------------------------------


def test_validate_config(plugin):
    assert plugin.validate_config({"repository": "octo-org/fiestaboard", "refresh_seconds": 120}) == []
    assert plugin.validate_config({}) == []
    assert any("owner/name" in e for e in plugin.validate_config({"repository": "nope"}))
    assert any("Branch" in e for e in plugin.validate_config({"branch": "has space"}))
    assert any("Client ID" in e for e in plugin.validate_config({"client_id": "has space"}))
    assert plugin.validate_config({"refresh_seconds": 5})


def test_manifest_json_is_pretty():
    text = (ROOT / "manifest.json").read_text()
    assert json.loads(text)["id"] == "github"


def test_core_accepts_the_manifest():
    from src.plugins.manifest import load_manifest

    manifest, errors = load_manifest(ROOT / "manifest.json")
    assert manifest is not None, errors
    assert manifest.id == "github"


# ----------------------------------------------------------------------
# Shared FiestaBoard GitHub App
# ----------------------------------------------------------------------

SHARED_CLIENT_ID = "Iv23licsxgFjES7n3PnG"


def _provider(manifest_data):
    from src.oauth.provider import parse_provider_block

    return parse_provider_block(manifest_data["oauth"], "GitHub", manifest_data["settings_schema"])


def test_manifest_ships_fiestaboard_client_id(manifest_data):
    assert manifest_data["oauth"]["client_id"] == SHARED_CLIENT_ID


@pytest.mark.parametrize("config", [{}, {"client_id": ""}, {"client_id": "   "}, {"client_id": None}])
def test_shared_client_id_used_when_setting_blank(manifest_data, config):
    assert _provider(manifest_data).resolve_client_id(config) == SHARED_CLIENT_ID


def test_own_client_id_overrides_shared(manifest_data):
    assert _provider(manifest_data).resolve_client_id({"client_id": " Iv23liOWNAPP0000000 "}) == "Iv23liOWNAPP0000000"


def test_client_id_setting_is_optional_override(manifest_data):
    field = manifest_data["settings_schema"]["properties"]["client_id"]
    assert field["title"] == "Your own Client ID (optional)"
    assert "blank" in field["description"].lower() and "FiestaBoard" in field["description"]


@pytest.mark.parametrize("name", ["FORBIDDEN_ERROR", "CHECKS_FORBIDDEN_ERROR", "REPO_NOT_FOUND_ERROR"])
def test_access_errors_point_at_fiestaboard_app_install(name):
    import plugins.github as gh

    message = getattr(gh, name)
    assert "github.com/apps/fiestaboard" in message
    assert "your GitHub App" not in message


def test_no_pending_shared_client_notes():
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.suffix in {".json", ".py", ".md"}:
            if path.name == "test_plugin.py":
                continue
            text = path.read_text()
            assert "TODO(shared client ID)" not in text, path
            assert "does not have a shared GitHub App" not in text, path
            assert "Until FiestaBoard has its own GitHub App" not in text, path
