"""GitHub plugin for FiestaBoard.

Shows the open pull requests waiting for your review, your own open pull
requests, and the CI status and star count of one repository.

Sign-in uses FiestaBoard's platform OAuth with the device flow (the
manifest's ``oauth`` block): the user's own GitHub App, no client secret.
The platform stores the user access token (8 hours) and refreshes it; this
plugin only calls ``self.get_oauth_token()`` and sends it as a bearer token.

Endpoints (GitHub REST API):

* ``GET /search/issues?q=is:pr is:open review-requested:@me``  review requests
* ``GET /search/issues?q=is:pr is:open author:@me``            your pull requests
* ``GET /repos/{owner}/{repo}``                                stars, default branch
* ``GET /repos/{owner}/{repo}/commits/{ref}/check-runs``       CI status

TODO(shared client ID): FiestaBoard's own GitHub App is pending. When it
exists, ship its Client ID as ``oauth.client_id`` in manifest.json and keep
the ``client_id`` setting, so a user's own app still wins when one is saved
(see "Whose App?" in FiestaBoard's docs/development/plugin-oauth.md).

The notifications endpoint is deliberately not used: it does not accept
GitHub App user access tokens.
"""

import logging
import re
import threading
import time
import unicodedata
from typing import Any
from urllib.parse import quote

import requests
from src.board_chars import BoardChars
from src.plugins.base import PluginBase, PluginResult
from src.text_to_board import take_tiles

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
# The REST API version this plugin was written against. 2022-11-28 is
# GitHub's default and is supported until March 2028.
API_VERSION = "2022-11-28"
USER_AGENT = "FiestaBoard GitHub Plugin (https://github.com/Fiestaboard/fiestaboard-plugin--github)"
REQUEST_TIMEOUT_SECONDS = 10

# Every board shape fetches separately; one snapshot serves them all.
SNAPSHOT_TTL_SECONDS = 30
LIST_SIZE = 5
CHECK_RUNS_PER_PAGE = 100

TRANSIENT_COOLDOWN_SECONDS = 30
AUTH_COOLDOWN_SECONDS = 60
DEFAULT_RETRY_AFTER_SECONDS = 60
MAX_RETRY_AFTER_SECONDS = 3600
STALE_DATA_LIMIT_SECONDS = 600

DEFAULT_COLS = 22
DEFAULT_ROWS = 6

TILE_PASSING = "{66}"  # green
TILE_RUNNING = "{65}"  # yellow
TILE_FAILING = "{63}"  # red

FAILED_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}

REVIEW_QUERY = "is:pr is:open review-requested:@me archived:false"
MINE_QUERY = "is:pr is:open author:@me archived:false"

NOT_CONNECTED_ERROR = "Not signed in to GitHub. Open this plugin's settings and sign in."
PLATFORM_TOO_OLD_ERROR = "This FiestaBoard version cannot sign in to GitHub. Update FiestaBoard to use this plugin."
UNAUTHORIZED_ERROR = "GitHub rejected the sign-in (401). Open this plugin's settings and press Reconnect."
FORBIDDEN_ERROR = (
    "GitHub refused access (403). Check your GitHub App's permissions (Pull requests: Read, Checks: Read) "
    "and that it is installed on the repositories you want to see."
)
CHECKS_FORBIDDEN_ERROR = (
    "GitHub refused to show the checks (403). Give your GitHub App the Checks: Read permission "
    "and install it on {repo}."
)
REPO_NOT_FOUND_ERROR = (
    "GitHub could not find the repository {repo}. Check the Repository setting; for a private "
    "repository, install your GitHub App on it."
)
BRANCH_NOT_FOUND_ERROR = "GitHub could not find the branch {branch} in {repo}. Check the Branch setting."
BAD_REPOSITORY_ERROR = "Repository should be owner/name, for example octo-org/fiestaboard"

_REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


class GitHubError(Exception):
    """A GitHub request failed; the message is shown to the user."""

    def __init__(self, message: str, *, transient: bool, cooldown: float):
        super().__init__(message)
        self.transient = transient
        self.cooldown = cooldown


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


def _monotonic() -> float:
    return time.monotonic()


def _epoch() -> float:
    return time.time()


def board_safe(text: Any) -> str:
    """Uppercase *text* and keep only characters the board can show."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    kept = []
    for ch in folded.upper():
        if ch.isspace():
            kept.append(" ")
        elif ch not in "{}" and BoardChars.get_char_code(ch) is not None:
            kept.append(ch)
    return re.sub(r" {2,}", " ", "".join(kept)).strip()


def normalize_repository(raw: Any) -> str | None:
    """``https://github.com/o/r.git`` -> ``o/r``. ``""`` when empty, ``None`` when invalid."""
    text = str(raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^(www\.)?github\.com/", "", text, flags=re.IGNORECASE)
    text = text.rstrip("/")
    text = text.removesuffix(".git")
    return text if _REPO_RE.match(text) else None


def short_count(n: int) -> str:
    """``1234`` -> ``1.2K``; at most five characters."""
    for size, suffix in ((1_000_000, "M"), (1_000, "K")):
        if n >= size:
            value = n / size
            if value < 10:
                text = f"{int(value * 10) / 10:.1f}".rstrip("0").rstrip(".")
            else:
                text = str(int(value))
            return f"{text}{suffix}"
    return str(n)


def summarize_checks(body: dict[str, Any] | None) -> dict[str, Any]:
    """Count check runs into passed, failed and running, and name the overall state."""
    runs = [run for run in ((body or {}).get("check_runs") or []) if isinstance(run, dict)]
    passed = failed = running = 0
    failing_name = ""
    for run in runs:
        if run.get("status") != "completed":
            running += 1
        elif run.get("conclusion") in FAILED_CONCLUSIONS:
            failed += 1
            failing_name = failing_name or board_safe(run.get("name"))
        else:
            passed += 1
    total = len(runs)
    if total == 0:
        status, tile, summary = "NO CHECKS", "", "NO CHECKS"
    elif failed:
        status, tile, summary = "FAILING", TILE_FAILING, f"{failed} OF {total} FAILED"
    elif running:
        status, tile, summary = "RUNNING", TILE_RUNNING, f"{running} OF {total} RUNNING"
    else:
        status, tile, summary = "PASSING", TILE_PASSING, f"{passed}/{total} PASSED"
    return {
        "status": status,
        "tile": tile,
        "summary": summary,
        "passed": passed,
        "failed": failed,
        "running": running,
        "total": total,
        "failing_name": failing_name,
    }


def fit(text: str, width: int) -> str:
    """Truncate *text* to *width* tiles (colour markers count as one)."""
    return take_tiles(text, width)[0]


def _join(*parts: str, sep: str = " ") -> str:
    return sep.join(part for part in parts if part)


def _pull_entry(item: dict[str, Any]) -> dict[str, str]:
    number = str(item.get("number") or "")
    title = board_safe(item.get("title"))
    repo_url = str(item.get("repository_url") or "")
    return {
        "title": title,
        "repo": board_safe(repo_url.rsplit("/", 1)[-1]),
        "number": number,
        "author": board_safe((item.get("user") or {}).get("login")),
        "line": _join(f"#{number}" if number else "", title),
    }


# ----------------------------------------------------------------------
# Plugin
# ----------------------------------------------------------------------


class GitHubPlugin(PluginBase):
    """Pull requests and CI from the user's own GitHub account."""

    def __init__(self, manifest: dict[str, Any]):
        super().__init__(manifest)
        self._lock = threading.RLock()
        self._reset_state()

    def _reset_state(self) -> None:
        self._snapshot: dict[str, Any] | None = None
        self._snapshot_at = 0.0
        self._last_good: dict[str, Any] | None = None
        self._last_good_at = 0.0
        self._cooldown_until = 0.0
        self._cooldown_error: GitHubError | None = None
        self._cooldown_token: str | None = None

    @property
    def plugin_id(self) -> str:
        return "github"

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        client_id = str(config.get("client_id") or "").strip()
        if client_id and re.search(r"\s", client_id):
            errors.append("Client ID should be the code from your GitHub App's General page, without spaces")
        if normalize_repository(config.get("repository")) is None:
            errors.append(BAD_REPOSITORY_ERROR)
        if re.search(r"\s", str(config.get("branch") or "").strip()):
            errors.append("Branch names cannot contain spaces")
        errors.extend(self._validate_refresh_seconds(config))
        return errors

    def on_config_change(self, old_config: dict[str, Any], new_config: dict[str, Any]) -> None:
        super().on_config_change(old_config, new_config)
        with self._lock:
            self._reset_state()

    # ------------------------------------------------------------------
    # GitHub requests
    # ------------------------------------------------------------------

    def _get(self, token: str, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
        """GET an API path. Returns ``(status, body)`` for 200 and 403/404; raises otherwise."""
        try:
            response = requests.get(
                f"{API_BASE}{path}",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": API_VERSION,
                    "User-Agent": USER_AGENT,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout:
            raise GitHubError("Timed out contacting GitHub", transient=True, cooldown=TRANSIENT_COOLDOWN_SECONDS)
        except requests.exceptions.RequestException as exc:
            raise GitHubError(
                f"Could not reach GitHub: {type(exc).__name__}", transient=True, cooldown=TRANSIENT_COOLDOWN_SECONDS
            )

        status = response.status_code
        headers = {str(k).lower(): str(v) for k, v in (response.headers or {}).items()}
        if status == 200:
            try:
                return status, response.json()
            except ValueError:
                raise GitHubError(
                    "Unexpected response from GitHub", transient=True, cooldown=TRANSIENT_COOLDOWN_SECONDS
                )
        if status == 401:
            raise GitHubError(UNAUTHORIZED_ERROR, transient=False, cooldown=AUTH_COOLDOWN_SECONDS)
        if status == 429 or (
            status == 403 and ("retry-after" in headers or headers.get("x-ratelimit-remaining") == "0")
        ):
            wait = self._rate_limit_wait(headers)
            raise GitHubError(f"GitHub rate limit reached; trying again in {int(wait)}s", transient=True, cooldown=wait)
        if status in (403, 404):
            return status, None
        if 500 <= status < 600:
            raise GitHubError(
                f"GitHub is having trouble (HTTP {status})", transient=True, cooldown=TRANSIENT_COOLDOWN_SECONDS
            )
        raise GitHubError(
            f"Unexpected response from GitHub (HTTP {status})", transient=False, cooldown=TRANSIENT_COOLDOWN_SECONDS
        )

    @staticmethod
    def _rate_limit_wait(headers: dict[str, str]) -> float:
        try:
            if "retry-after" in headers:
                wait = float(headers["retry-after"])
            elif "x-ratelimit-reset" in headers:
                wait = float(headers["x-ratelimit-reset"]) - _epoch()
            else:
                wait = DEFAULT_RETRY_AFTER_SECONDS
        except ValueError:
            wait = DEFAULT_RETRY_AFTER_SECONDS
        return min(max(wait, 1.0), MAX_RETRY_AFTER_SECONDS)

    def _search(self, token: str, query: str) -> dict[str, Any]:
        status, body = self._get(
            token, "/search/issues", {"q": query, "sort": "updated", "order": "desc", "per_page": LIST_SIZE}
        )
        if status != 200:
            raise GitHubError(FORBIDDEN_ERROR, transient=False, cooldown=AUTH_COOLDOWN_SECONDS)
        return body or {}

    def _load_repository(self, token: str, repo: str) -> tuple[dict[str, Any], dict[str, Any], str]:
        status, body = self._get(token, f"/repos/{repo}")
        if status == 404:
            raise GitHubError(REPO_NOT_FOUND_ERROR.format(repo=repo), transient=False, cooldown=AUTH_COOLDOWN_SECONDS)
        if status != 200:
            raise GitHubError(FORBIDDEN_ERROR, transient=False, cooldown=AUTH_COOLDOWN_SECONDS)
        info = body or {}
        branch = str(self.config.get("branch") or "").strip() or str(info.get("default_branch") or "main")
        status, checks = self._get(
            token, f"/repos/{repo}/commits/{quote(branch, safe='')}/check-runs", {"per_page": CHECK_RUNS_PER_PAGE}
        )
        if status == 404:
            raise GitHubError(
                BRANCH_NOT_FOUND_ERROR.format(branch=branch, repo=repo), transient=False, cooldown=AUTH_COOLDOWN_SECONDS
            )
        if status != 200:
            raise GitHubError(CHECKS_FORBIDDEN_ERROR.format(repo=repo), transient=False, cooldown=AUTH_COOLDOWN_SECONDS)
        return info, checks or {}, branch

    def _start_cooldown(self, exc: GitHubError, token: str) -> None:
        self._cooldown_until = max(self._cooldown_until, _monotonic() + exc.cooldown)
        self._cooldown_error = exc
        # An auth error belongs to the token that caused it: a new sign-in
        # should be tried at once. An outage or rate limit holds for any token.
        self._cooldown_token = None if exc.transient else token

    def _in_cooldown(self, token: str) -> bool:
        if self._cooldown_error is None or _monotonic() >= self._cooldown_until:
            return False
        return self._cooldown_token is None or self._cooldown_token == token

    def _load_snapshot(self, token: str) -> dict[str, Any]:
        if self._snapshot is not None and _monotonic() - self._snapshot_at < SNAPSHOT_TTL_SECONDS:
            return self._snapshot
        if self._in_cooldown(token):
            raise self._cooldown_error  # type: ignore[misc]
        repo = normalize_repository(self.config.get("repository"))
        if repo is None:
            raise GitHubError(BAD_REPOSITORY_ERROR, transient=False, cooldown=0)
        try:
            snapshot: dict[str, Any] = {
                "reviews": self._search(token, REVIEW_QUERY),
                "mine": self._search(token, MINE_QUERY),
                "repo": None,
            }
            if repo:
                snapshot["repo"] = self._load_repository(token, repo)
        except GitHubError as exc:
            self._start_cooldown(exc, token)
            raise
        self._snapshot = snapshot
        self._snapshot_at = _monotonic()
        return snapshot

    def _stale_snapshot(self) -> dict[str, Any] | None:
        if self._last_good is not None and _monotonic() - self._last_good_at < STALE_DATA_LIMIT_SECONDS:
            return self._last_good
        return None

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _board_size(self) -> tuple[int, int]:
        board = self.board
        if board is None:
            return DEFAULT_COLS, DEFAULT_ROWS
        return board.cols, board.rows

    def fetch_data(self) -> PluginResult:
        try:
            get_token = getattr(self, "get_oauth_token", None)
            if get_token is None:
                return PluginResult(available=False, error=PLATFORM_TOO_OLD_ERROR)
            token = get_token()
            if not token:
                return PluginResult(available=False, error=NOT_CONNECTED_ERROR)

            cols, rows = self._board_size()
            with self._lock:
                try:
                    snapshot = self._load_snapshot(token)
                except GitHubError as exc:
                    stale = self._stale_snapshot()
                    if exc.transient and stale is not None:
                        logger.info("GitHub: %s; showing the last data", exc)
                        snapshot = stale
                    else:
                        logger.warning("GitHub: %s", exc)
                        return PluginResult(available=False, error=str(exc))
                else:
                    self._last_good = snapshot
                    self._last_good_at = _monotonic()
            data = self._build_data(snapshot)
            return PluginResult(available=True, data=data, formatted_lines=self._format_display(data, cols, rows))
        except Exception as exc:  # fetch_data must never raise
            logger.exception("GitHub plugin failed")
            return PluginResult(available=False, error=str(exc))

    @staticmethod
    def _build_data(snapshot: dict[str, Any]) -> dict[str, Any]:
        reviews_body, mine_body = snapshot["reviews"], snapshot["mine"]
        reviews = [_pull_entry(item) for item in (reviews_body.get("items") or [])[:LIST_SIZE] if item]
        mine_items = [item for item in (mine_body.get("items") or []) if item]
        mine = [_pull_entry(item) for item in mine_items[:LIST_SIZE]]
        first_review = reviews[0] if reviews else {}
        first_mine = mine[0] if mine else {}
        data: dict[str, Any] = {
            "review_count": int(reviews_body.get("total_count") or len(reviews)),
            "review_title": first_review.get("title", ""),
            "review_repo": first_review.get("repo", ""),
            "review_number": first_review.get("number", ""),
            "review_author": first_review.get("author", ""),
            "review_line": first_review.get("line", ""),
            "reviews": reviews,
            "my_pr_count": int(mine_body.get("total_count") or len(mine)),
            "my_pr_title": first_mine.get("title", ""),
            "my_pr_repo": first_mine.get("repo", ""),
            "my_pr_number": first_mine.get("number", ""),
            "my_pr_line": first_mine.get("line", ""),
            "my_draft_count": sum(1 for item in mine_items if item.get("draft")),
            "my_prs": mine,
        }
        repo_part = snapshot.get("repo")
        if repo_part:
            info, checks, branch = repo_part
            stars = int(info.get("stargazers_count") or 0)
            ci = summarize_checks(checks)
            full = str(info.get("full_name") or "")
            data.update(
                repo=board_safe(full.rsplit("/", 1)[-1]),
                repo_full=board_safe(full),
                branch=board_safe(branch),
                stars=stars,
                stars_short=short_count(stars),
            )
        else:
            ci = {k: "" for k in ("status", "tile", "summary", "failing_name")}
            ci.update(passed=0, failed=0, running=0, total=0)
            data.update(repo="", repo_full="", branch="", stars=0, stars_short="")
        data.update({f"ci_{key}": value for key, value in ci.items()})
        return data

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    @staticmethod
    def _format_display(data: dict[str, Any], cols: int, rows: int) -> list[str]:
        """Fallback layout for a board *cols* x *rows* tiles when there is no template."""
        header = _join(data["ci_tile"], data["repo"]) or "GITHUB"
        stars = f"STARS {data['stars_short']}" if data["repo"] else ""
        reviews = data["reviews"]
        if rows < 6:
            lines = [
                header,
                f"REVIEW {data['review_count']} MINE {data['my_pr_count']}",
                stars or data["review_line"],
            ]
        else:
            lines = [
                header,
                data["ci_summary"],
                f"{data['review_count']} TO REVIEW",
                reviews[0]["line"] if reviews else "",
                reviews[1]["line"] if len(reviews) > 1 else "",
                _join(f"MY PRS {data['my_pr_count']}", stars),
            ]
        return [fit(line, cols) for line in lines[:rows]]

    def get_formatted_display(self) -> list[str] | None:
        result = self.get_data(self.board)
        if not result.available or not result.data:
            return None
        cols, rows = self._board_size()
        return self._format_display(result.data, cols, rows)


# Export hook: the loader looks for a module-level `Plugin`.
Plugin = GitHubPlugin
