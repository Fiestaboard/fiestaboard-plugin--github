"""Payloads shaped like the GitHub REST API's answers.

Field names follow docs.github.com (search issues, get a repository, list
check runs for a Git reference). All names and numbers are invented.
"""

API = "https://api.github.com"


def pull(number, title, repo="octo-org/fiestaboard", author="octocat", draft=False, updated="2026-09-30T10:00:00Z"):
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/{repo}/pull/{number}",
        "repository_url": f"{API}/repos/{repo}",
        "user": {"login": author},
        "state": "open",
        "draft": draft,
        "updated_at": updated,
        "pull_request": {"url": f"{API}/repos/{repo}/pulls/{number}"},
    }


def search(items, total=None):
    return {
        "total_count": len(items) if total is None else total,
        "incomplete_results": False,
        "items": items,
    }


def repository(full_name="octo-org/fiestaboard", stars=1234, default_branch="main"):
    return {
        "id": 1,
        "name": full_name.split("/")[1],
        "full_name": full_name,
        "default_branch": default_branch,
        "stargazers_count": stars,
        "private": False,
    }


def check_run(name, status="completed", conclusion="success"):
    return {"id": abs(hash(name)) % 10_000, "name": name, "status": status, "conclusion": conclusion}


def check_runs(runs):
    return {"total_count": len(runs), "check_runs": runs}
