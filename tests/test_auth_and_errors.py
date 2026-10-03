"""How the GitHub plugin handles GitHub's error answers."""

import requests

from .conftest import FakeResponse


def test_401_asks_to_reconnect_and_cools_down(github_api, plugin, clock):
    github_api.fail("reviews", status=401)
    result = plugin.fetch_data()
    assert not result.available
    assert "401" in result.error and "Reconnect" in result.error
    calls = len(github_api.calls)
    plugin.fetch_data()
    assert len(github_api.calls) == calls  # not asked again straight away
    clock.advance(61)
    assert plugin.fetch_data().available


def test_new_token_skips_auth_cooldown(github_api, plugin, token):
    github_api.fail("reviews", status=401)
    plugin.fetch_data()
    token.value = "test_new_token"
    assert plugin.fetch_data().available


def test_403_rate_limit_waits_for_reset(github_api, plugin, clock):
    with_reset = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"}
    github_api.fail("reviews", status=403, headers=with_reset)
    result = plugin.fetch_data()
    assert "rate limit" in result.error.lower()


def test_403_rate_limit_reset_time(github_api, plugin, clock, monkeypatch):
    import plugins.github as mod

    monkeypatch.setattr(mod, "_epoch", lambda: 1_000_000)
    github_api.fail("reviews", status=403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1000300"})
    result = plugin.fetch_data()
    assert "300s" in result.error
    clock.advance(200)
    calls = len(github_api.calls)
    plugin.fetch_data()
    assert len(github_api.calls) == calls


def test_secondary_rate_limit_retry_after(github_api, plugin):
    github_api.fail("reviews", status=403, headers={"Retry-After": "90"})
    assert "90s" in plugin.fetch_data().error


def test_429_retry_after(github_api, plugin):
    github_api.fail("reviews", status=429, headers={"Retry-After": "nonsense"})
    result = plugin.fetch_data()
    assert "rate limit" in result.error.lower()


def test_403_without_rate_limit_is_access(github_api, plugin):
    github_api.fail("reviews", status=403)
    result = plugin.fetch_data()
    assert "403" in result.error and "permission" in result.error.lower()


def test_unknown_repository(github_api, make_plugin):
    result = make_plugin(repository="octo-org/missing").fetch_data()
    assert not result.available
    assert "OCTO-ORG/MISSING" in result.error.upper() and "install" in result.error.lower()


def test_invalid_repository_setting(github_api, make_plugin):
    result = make_plugin(repository="not a repo").fetch_data()
    assert not result.available
    assert "owner/name" in result.error
    assert github_api.calls == []


def test_checks_403_on_private_repo_explains_permission(github_api, plugin):
    github_api.fail("checks", status=403)
    result = plugin.fetch_data()
    assert "Checks" in result.error


def test_server_error_then_stale_data(github_api, plugin, clock):
    assert plugin.fetch_data().available
    clock.advance(31)
    github_api.fail("reviews", status=502)
    result = plugin.fetch_data()
    assert result.available  # last good data
    assert result.data["review_count"] == 3


def test_timeout_without_stale_data(github_api, plugin):
    github_api.fail("reviews", requests.exceptions.Timeout("slow"))
    result = plugin.fetch_data()
    assert not result.available and "Timed out" in result.error


def test_connection_error(github_api, plugin):
    github_api.fail("reviews", requests.exceptions.ConnectionError("down"))
    result = plugin.fetch_data()
    assert "Could not reach GitHub" in result.error


def test_stale_data_expires(github_api, plugin, clock):
    plugin.fetch_data()
    clock.advance(1000)
    github_api.fail("reviews", status=503)
    assert not plugin.fetch_data().available


def test_unexpected_status(github_api, plugin):
    github_api.fail("mine", status=418)
    result = plugin.fetch_data()
    assert "HTTP 418" in result.error


def test_validation_failed_search(github_api, plugin):
    github_api.fail("reviews", status=422)
    assert "HTTP 422" in plugin.fetch_data().error


def test_non_json_body(github_api, plugin):
    github_api.fail("reviews", FakeResponse(None, 200))
    result = plugin.fetch_data()
    assert not result.available and "Unexpected response" in result.error


def test_unexpected_exception_never_raises(github_api, plugin, monkeypatch):
    monkeypatch.setattr(plugin, "_load_snapshot", lambda token: 1 / 0)
    result = plugin.fetch_data()
    assert not result.available
