"""Unit tests for repo URL canonicalization (ADR-0053 §1).

The app had no URL normalization, so the same repository spelled three ways was
three repos to the existing code. ``canonicalize_repo_url`` collapses the common
spellings to one ``https://<host>/<owner>/<repo>`` key.
"""

from __future__ import annotations

import pytest

from cliff.repos.identity import InvalidRepoUrlError, canonicalize_repo_url

CANONICAL = "https://github.com/acme/web"


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/acme/web",
        "https://github.com/acme/web.git",
        "https://github.com/acme/web/",
        "https://github.com/acme/web/.git",  # trailing slash + .git
        "http://github.com/acme/web",  # scheme normalised to https
        "https://GitHub.com/acme/web",  # host lowercased
        "https://github.com/acme/web ",  # surrounding whitespace
        "git@github.com:acme/web.git",  # scp-like
        "git@github.com:acme/web",
        "ssh://git@github.com/acme/web.git",  # ssh scheme
        "https://x-access-token:ghp_secret@github.com/acme/web.git",  # creds stripped
        "github.com/acme/web",  # bare, no scheme
    ],
)
def test_spellings_collapse_to_one_key(raw):
    assert canonicalize_repo_url(raw) == CANONICAL


def test_path_case_is_preserved():
    # GitHub is case-insensitive for access but other hosts are not; only the
    # host is lowercased, the path is left intact.
    assert canonicalize_repo_url("https://gitlab.com/Group/Sub/Repo") == (
        "https://gitlab.com/Group/Sub/Repo"
    )


def test_non_github_host_preserved():
    assert (
        canonicalize_repo_url("git@gitlab.example.com:team/svc.git")
        == "https://gitlab.example.com/team/svc"
    )


def test_token_never_survives_in_key():
    key = canonicalize_repo_url("https://x-access-token:ghp_secret@github.com/a/b")
    assert "ghp_secret" not in key
    assert "x-access-token" not in key


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "https://github.com", "https://github.com/", "not a url at all/"],
)
def test_rejects_unusable(bad):
    with pytest.raises(InvalidRepoUrlError):
        canonicalize_repo_url(bad)
