"""Shared fixtures for the GitHub plugin tests.

``github_api`` patches ``requests.get`` with a fake GitHub REST API that
answers the endpoints this plugin uses (see ``fixtures.py``). Tests change
its state or queue raw responses to simulate errors. No test touches the
network.

``get_oauth_token`` is patched on the plugin instance: the platform's OAuth
service is not under test here, only how the plugin uses what it returns.
"""

import json
from collections import deque
from pathlib import Path
from unittest.mock import patch

import pytest

from plugins.github import GitHubPlugin

from .fixtures import API, check_run, check_runs, pull, repository, search

MANIFEST_PATH = Path(__file__).parent.parent / "manifest.json"
TEST_CLIENT_ID = "Iv23liEXAMPLE0000000"  # fake
TEST_TOKEN = "test_access_token"


class FakeResponse:
    def __init__(self, body=None, status_code=200, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeGitHub:
    """Answers requests.get the way the GitHub REST API would."""

    def __init__(self):
        self.reviews = search(
            [
                pull(412, "Fix login redirect", author="mona"),
                pull(409, "Bump requests", repo="octo-org/board-tools", author="deploy-bot"),
                pull(398, "Add Note layout", author="hubot"),
            ]
        )
        self.mine = search([pull(418, "Add dark mode", draft=True), pull(415, "Tidy settings")])
        self.repos = {"octo-org/fiestaboard": repository()}
        self.runs = {
            "main": check_runs([check_run(f"test-{i}") for i in range(13)] + [check_run("docs", conclusion="skipped")])
        }
        self.overrides = {}
        self.calls = []

    def fail(self, key, response=None, *, status=None, headers=None, times=1):
        """Make the next *times* calls to *key* (reviews, mine, repo, checks) return or raise *response*."""
        if response is None:
            response = FakeResponse({"message": "test"}, status, headers)
        self.overrides.setdefault(key, deque()).extend([response] * times)

    def count(self, key):
        return [k for k, _ in self.calls].count(key)

    @staticmethod
    def _key(path, params):
        if path == "/search/issues":
            q = params["q"]
            return "reviews" if "review-requested:@me" in q else "mine"
        if "/commits/" in path and path.endswith("/check-runs"):
            return "checks"
        return "repo"

    def __call__(self, url, params=None, headers=None, timeout=None):
        assert url.startswith(API), url
        path = url[len(API) :]
        key = self._key(path, params or {})
        self.calls.append((key, {"url": url, "params": params, "headers": headers, "timeout": timeout}))
        queued = self.overrides.get(key)
        if queued:
            response = queued.popleft()
            if isinstance(response, Exception):
                raise response
            return response
        if key == "reviews":
            return FakeResponse(self.reviews)
        if key == "mine":
            return FakeResponse(self.mine)
        parts = path.split("/")  # ['', 'repos', owner, name, ...]
        full = f"{parts[2]}/{parts[3]}".lower()  # GitHub ignores case
        if full not in self.repos:
            return FakeResponse({"message": "Not Found"}, 404)
        if key == "repo":
            return FakeResponse(self.repos[full])
        ref = parts[5]
        return FakeResponse(self.runs.get(ref, check_runs([])))


class Clock:
    """A controllable stand-in for time.monotonic()."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def manifest_data():
    with open(MANIFEST_PATH) as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def clock():
    c = Clock()
    with patch("plugins.github._monotonic", side_effect=c):
        yield c


@pytest.fixture
def github_api():
    fake = FakeGitHub()
    with patch("plugins.github.requests.get", side_effect=fake):
        yield fake


@pytest.fixture
def token():
    """The token get_oauth_token() hands out; tests may change ``token.value``."""

    class Token:
        value = TEST_TOKEN

    return Token


@pytest.fixture
def make_plugin(manifest_data, token):
    def factory(**config):
        p = GitHubPlugin(manifest_data)
        p.config = {"enabled": True, "client_id": TEST_CLIENT_ID, "repository": "octo-org/fiestaboard", **config}
        p.get_oauth_token = lambda: token.value
        return p

    return factory


@pytest.fixture
def plugin(make_plugin):
    return make_plugin()
