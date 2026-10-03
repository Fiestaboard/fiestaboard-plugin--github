# GitHub Setup Guide

Connect FiestaBoard to your GitHub account to show pull requests waiting for your review, your own pull requests, and a repository's CI status and stars.

## Overview

**What it does:**

- Counts the open pull requests where your review is requested and lists the newest ones
- Counts and lists your own open pull requests, including drafts
- Shows whether the checks on a repository's latest commit pass, fail or are still running
- Shows the repository's star count

**Prerequisites:**

- A GitHub account. Nothing to create: the sign-in uses FiestaBoard's GitHub App, [FiestaBoard](https://github.com/apps/fiestaboard), which only has read-only permissions.
- FiestaBoard 9.8.0 or later (the plugin's settings have an **Account connection** section with guided setup).

FiestaBoard only reads. It can't comment, merge, approve, or change anything on GitHub.

## Quick Setup

### 1. Enable the Plugin

In the FiestaBoard web UI:

1. Go to **Integrations**
2. Find **GitHub** and toggle it **On**
3. Click **Configure**. The **Account connection** section at the top lists the steps below.

### 2. Sign in

1. In the plugin's **Account connection** section, press **Sign in with GitHub**. The settings show a code such as `WDJB-MJHT` and the address `github.com/login/device`
2. On any device, open [github.com/login/device](https://github.com/login/device), enter the code, and press **Authorize**. GitHub asks to let the FiestaBoard app read your pull requests and checks
3. The settings change to connected by themselves. The code is valid for 15 minutes; if it runs out, press the button again

Leave **Your own Client ID (optional)** blank: FiestaBoard's app is used. (To use an app of your own, see [Advanced: use your own GitHub App](#advanced-use-your-own-github-app).)

More about what you see while connecting: [Connecting Accounts](https://fiestaboard.app/docs/features/connecting-accounts).

### 3. Install the app for private repositories

Public repositories work with the sign-in alone. To see private ones (their pull requests, CI and stars):

1. Open [github.com/apps/fiestaboard](https://github.com/apps/fiestaboard) and press **Install** (or **Configure** if it is already installed)
2. Pick your account, or an organization whose private repositories you want to see. An organization may need an owner to approve it
3. Choose **All repositories** or **Only select repositories**, and press **Install**

The app only reads; you can change the repositories or uninstall it from the same page at any time.

### 4. Choose a repository

Set the optional settings and click **Save Changes**:

- **Repository:** the repository for the CI and star variables, as `owner/name` (for example `octo-org/fiestaboard`). You can paste its `github.com` link instead. Leave empty to show only pull requests.
- **Branch:** the branch whose checks are shown. Leave empty for the default branch.
- **Refresh Interval:** how often to check GitHub, 60 to 3600 seconds (default 120)

### 5. Create a Board Template

Create a page from the plugin's demo, or add variables to your own page:

```jinja
{{github.ci_tile}} {{github.repo}}
{{github.ci_summary}}
{{github.review_count}} TO REVIEW
{{github.reviews.0.line}}
{{github.reviews.1.line}}
MY PRS {{github.my_pr_count}}   STARS {{github.stars_short}}
```

On a Note, try:

```jinja
{{github.ci_tile}} {{github.repo}}
REVIEW {{github.review_count}} MINE {{github.my_pr_count}}
STARS {{github.stars_short}}
```

### 6. View on Your Board

The board updates on the next refresh (every 2 minutes by default).

## Template Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `{{github.review_count}}` | Open pull requests waiting for your review | `3` |
| `{{github.review_title}}` | Title of the most recently updated one | `FIX LOGIN REDIRECT` |
| `{{github.review_repo}}` | Its repository name | `FIESTABOARD` |
| `{{github.review_number}}` | Its pull request number | `412` |
| `{{github.review_author}}` | Who opened it | `OCTOCAT` |
| `{{github.review_line}}` | Number and title on one line | `#412 FIX LOGIN REDIRECT` |
| `{{github.reviews.0.title}}` | Pull request title, entry 0-4 | `FIX LOGIN REDIRECT` |
| `{{github.reviews.0.repo}}` | Repository name, entry 0-4 | `FIESTABOARD` |
| `{{github.reviews.0.number}}` | Pull request number, entry 0-4 | `412` |
| `{{github.reviews.0.author}}` | Who opened it, entry 0-4 | `MONA` |
| `{{github.reviews.0.line}}` | Number and title on one line, entry 0-4 | `#412 FIX LOGIN REDIRECT` |
| `{{github.my_pr_count}}` | Your own open pull requests | `2` |
| `{{github.my_pr_title}}` | Title of your most recently updated one | `ADD DARK MODE` |
| `{{github.my_pr_repo}}` | Its repository name | `FIESTABOARD` |
| `{{github.my_pr_number}}` | Its pull request number | `418` |
| `{{github.my_pr_line}}` | Number and title on one line | `#418 ADD DARK MODE` |
| `{{github.my_draft_count}}` | How many of your open pull requests are drafts | `1` |
| `{{github.my_prs.0.title}}` | Pull request title, entry 0-4 | `ADD DARK MODE` |
| `{{github.my_prs.0.repo}}` | Repository name, entry 0-4 | `FIESTABOARD` |
| `{{github.my_prs.0.number}}` | Pull request number, entry 0-4 | `418` |
| `{{github.my_prs.0.author}}` | Who opened it, entry 0-4 | `OCTOCAT` |
| `{{github.my_prs.0.line}}` | Number and title on one line, entry 0-4 | `#418 ADD DARK MODE` |
| `{{github.repo}}` | The configured repository's name | `FIESTABOARD` |
| `{{github.repo_full}}` | Owner and name | `OCTO-ORG/FIESTABOARD` |
| `{{github.branch}}` | Branch whose checks are shown (the default branch unless set) | `MAIN` |
| `{{github.stars}}` | Star count | `1234` |
| `{{github.stars_short}}` | Star count, shortened | `1.2K` |
| `{{github.ci_status}}` | PASSING, FAILING, RUNNING or NO CHECKS for the latest commit | `PASSING` |
| `{{github.ci_tile}}` | One colour tile: green passing, red failing, yellow running (empty with no checks) | `{66}` |
| `{{github.ci_summary}}` | Checks in a few words | `14/14 PASSED` |
| `{{github.ci_passed}}` | Checks that finished without failing (success, neutral or skipped) | `14` |
| `{{github.ci_failed}}` | Checks that failed, timed out, were cancelled or need action | `0` |
| `{{github.ci_running}}` | Checks still queued or running | `0` |
| `{{github.ci_total}}` | All checks on the latest commit | `14` |
| `{{github.ci_failing_name}}` | Name of the first failing check | `LINT` |

The `reviews` and `my_prs` lists hold entries 0 to 4, newest activity first.

## Configuration Reference

| Setting | Required | Default | Description |
|---------|----------|---------|-------------|
| Your own Client ID (optional) | No | FiestaBoard's app | Leave blank. Only for signing in through [your own GitHub App](#advanced-use-your-own-github-app) |
| Repository | No | | `owner/name` for the CI and star variables |
| Branch | No | Default branch | Branch whose checks are shown |
| Refresh Interval (seconds) | No | 120 | How often to check GitHub (60-3600) |

The connection itself is made with the **Sign in with GitHub** button, not a setting. The plugin asks for no scopes: what it can read is set by the GitHub App's permissions (all read-only) and the repositories it is installed on. FiestaBoard keeps the sign-in fresh: GitHub's sign-ins last 8 hours and are renewed automatically for up to 6 months of not using the board.

**Environment variables:** none.

## Advanced: use your own GitHub App

Optional. FiestaBoard's app is all most people need; use your own if you want an app you control.

1. On GitHub, click your profile picture, then **Settings** > **Developer settings** > **GitHub Apps** > **New GitHub App** (or open [github.com/settings/apps/new](https://github.com/settings/apps/new)).
2. Fill in:
   - **GitHub App name:** anything not already taken on GitHub, such as `FiestaBoard for yourname`
   - **Homepage URL:** anything, such as `https://fiestaboard.app`
   - **Callback URL:** leave empty. The board signs in with a code, so it needs no redirect URI.
   - **Expire user authorization tokens:** leave ticked
   - **Enable Device Flow:** **tick it.** Without it GitHub refuses the sign-in.
   - **Webhook:** untick **Active**
   - **Permissions** > **Repository permissions:** set **Checks** to **Read-only** and **Pull requests** to **Read-only**. **Metadata** is set to Read-only for you. Leave everything else at **No access**.
   - **Where can this GitHub App be installed?** **Only on this account** (pick **Any account** if you want to install it on an organization you don't own).
3. Press **Create GitHub App**.
4. On the app's **General** page, copy the **Client ID** (it starts with `Iv`). You don't need a client secret or a private key: don't generate either.
5. Paste it into **Your own Client ID (optional)** in the plugin's **Account connection** section, then press **Sign in with GitHub** (or **Reconnect** if you were signed in with FiestaBoard's app).
6. For private repositories, open your app's **Install App** page and install it instead of FiestaBoard's.

A saved Client ID always wins over FiestaBoard's. Clear it and reconnect to go back.

## Troubleshooting

**"Not signed in to GitHub"**

- Press **Sign in with GitHub** (or **Reconnect**) in the plugin's **Account connection** section.
- **Reconnect needed** means GitHub stopped accepting the saved sign-in: you revoked it under GitHub **Settings** > **Applications** > **Authorized GitHub Apps**, or the board was off for more than 6 months.

**The sign-in fails straight away, or GitHub says device flow is disabled**

- If **Your own Client ID (optional)** is filled in, clear it to use FiestaBoard's app, or fix your own app: on its **General** page tick **Enable Device Flow** and **Save changes**, and copy the Client ID again (it starts with `Iv`; don't paste the client secret).

**"GitHub rejected the sign-in (401)"**

- You revoked the app's access, or GitHub did. Press **Reconnect**.

**"GitHub refused access (403)"** or **"GitHub refused to show the checks (403)"**

- For a private repository, install the FiestaBoard app on the account or organization that owns it at [github.com/apps/fiestaboard](https://github.com/apps/fiestaboard). If you picked **Only select repositories**, add the repository there.
- Using your own GitHub App? Give it the **Checks: Read-only** and **Pull requests: Read-only** repository permissions (app **Permissions & events** page), then accept the changed permissions on the installation (**Install App** > the gear icon).

**"GitHub could not find the repository"**

- Check the **Repository** setting is `owner/name` and spelled as on GitHub. A private repository looks missing until the FiestaBoard app is installed on it: [github.com/apps/fiestaboard](https://github.com/apps/fiestaboard).

**"GitHub could not find the branch"**

- Check the **Branch** setting, or clear it to use the default branch.

**Review requests or pull requests from a private repository are missing**

- GitHub only shows a GitHub App what it is installed on. Install the app at [github.com/apps/fiestaboard](https://github.com/apps/fiestaboard) on that repository's account or organization. An organization may need an owner to approve the installation.

**CI shows NO CHECKS**

- The latest commit on that branch has no check runs. Checks from GitHub Actions and most CI apps are check runs; older services that only report commit statuses are not counted.

**"GitHub rate limit reached"**

- The plugin waits as long as GitHub asks and keeps showing the last data meanwhile (for up to ten minutes). Raise the refresh interval if it happens often.

**"This FiestaBoard version cannot sign in to GitHub"**

- Update FiestaBoard to 9.8.0 or later.

**Plugin shows "Not Available"**

- The error next to the plugin on the Integrations page says what went wrong. For more detail, check the logs: `docker compose logs -f`
