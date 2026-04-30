"""CI supply-chain posture checks (PRD-0003 v0.2).

All three checks are filesystem-only — they parse the repo's
``.github/workflows/*.yml`` files for ``uses:`` references. We deliberately
avoid pulling in PyYAML for this: the ``uses:`` lines we care about are simple
``key: value`` pairs, and a regex is sufficient to enumerate them. This keeps
the assessment fast and offline.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from opensec.assessment.posture import PostureCheckResult

if TYPE_CHECKING:
    from pathlib import Path

# Match `uses: <ref>` lines, capturing the ref (which may be quoted, indented,
# and followed by trailing comments). We only need the ref string itself.
_USES_RE = re.compile(
    r"""^\s*-?\s*uses:\s*['"]?([^\s'"#]+)['"]?""",
    re.MULTILINE,
)

# A 40-char hex SHA1 is the canonical pinned form; anything shorter (tag or
# branch name) is unpinned per the supply-chain advisory pattern.
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Action publishers GitHub considers "verified" for the purpose of this check.
# This is the narrow trusted set baked into PRD-0003 — the broader Marketplace
# verified-publisher list lives behind an API call we don't make here.
_TRUSTED_PUBLISHERS = frozenset(
    {
        "actions",
        "github",
        "docker",
        "aws-actions",
        "azure",
        "google-github-actions",
        "hashicorp",
    }
)

# Patterns that have led to repeated supply-chain incidents. The check is
# advisory — false positives are acceptable as long as the human reviewer can
# confirm each hit.
_DANGEROUS_TRIGGER_PATTERNS = (
    re.compile(r"pull_request_target", re.IGNORECASE),
    re.compile(r"workflow_run", re.IGNORECASE),
)
_CHECKOUT_REF_RE = re.compile(
    r"actions/checkout@[^\s]*\s*(?:\n.*?ref:\s*\${{.*github\.event\.pull_request)",
    re.DOTALL | re.IGNORECASE,
)


def _iter_workflow_files(repo_path: Path) -> list[Path]:
    workflows_dir = repo_path / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    return sorted(
        p for p in workflows_dir.iterdir() if p.suffix in {".yml", ".yaml"} and p.is_file()
    )


def _extract_uses_refs(file_path: Path) -> list[str]:
    text = file_path.read_text(encoding="utf-8", errors="replace")
    return [m.group(1) for m in _USES_RE.finditer(text)]


def check_actions_pinned_to_sha(repo_path: Path) -> PostureCheckResult:
    files = _iter_workflow_files(repo_path)
    if not files:
        # No workflows → nothing to fail. Treat as pass with detail.
        return PostureCheckResult(
            check_name="actions_pinned_to_sha",
            status="pass",
            detail={"reason": "no_workflows"},
        )

    unpinned: list[dict[str, str]] = []
    total_uses = 0
    for fp in files:
        for ref in _extract_uses_refs(fp):
            # Local actions are referenced as "./path/to/action" — skip them,
            # they live in the repo so SHA pinning isn't applicable.
            if ref.startswith("./") or "@" not in ref:
                continue
            total_uses += 1
            action, _, version = ref.partition("@")
            if not _FULL_SHA_RE.match(version):
                unpinned.append(
                    {
                        "file": str(fp.relative_to(repo_path)),
                        "action": action,
                        "version": version,
                    }
                )
    if not unpinned:
        return PostureCheckResult(
            check_name="actions_pinned_to_sha",
            status="pass",
            detail={"workflows": [str(f.relative_to(repo_path)) for f in files]},
        )
    return PostureCheckResult(
        check_name="actions_pinned_to_sha",
        status="fail",
        detail={
            "unpinned_count": len(unpinned),
            "total_uses": total_uses,
            "unpinned": unpinned[:20],  # cap detail size
        },
    )


def check_trusted_action_sources(repo_path: Path) -> PostureCheckResult:
    files = _iter_workflow_files(repo_path)
    if not files:
        return PostureCheckResult(
            check_name="trusted_action_sources",
            status="pass",
            detail={"reason": "no_workflows"},
        )

    untrusted: list[dict[str, str]] = []
    for fp in files:
        for ref in _extract_uses_refs(fp):
            if ref.startswith("./") or "@" not in ref:
                continue
            action = ref.split("@", 1)[0]
            owner = action.split("/", 1)[0] if "/" in action else action
            if owner.lower() in _TRUSTED_PUBLISHERS:
                continue
            untrusted.append(
                {"file": str(fp.relative_to(repo_path)), "action": action, "owner": owner}
            )
    if not untrusted:
        return PostureCheckResult(
            check_name="trusted_action_sources",
            status="pass",
            detail={"trusted_publishers": sorted(_TRUSTED_PUBLISHERS)},
        )
    return PostureCheckResult(
        check_name="trusted_action_sources",
        status="fail",
        detail={"untrusted_count": len(untrusted), "untrusted": untrusted[:20]},
    )


def check_workflow_trigger_scope(repo_path: Path) -> PostureCheckResult:
    """Surfaces workflows that combine `pull_request_target` with
    `actions/checkout` of the PR ref — the canonical pwn-request pattern.

    Per PRD-0003 this is an advisory-class check (never fails), but when there
    is nothing to advise on we emit ``pass`` so the row doesn't perpetually
    pollute the Issues page. The mapper still tags ``grade_impact='advisory'``
    based on the check name, so the grade math is unchanged either way.
    """
    files = _iter_workflow_files(repo_path)
    if not files:
        return PostureCheckResult(
            check_name="workflow_trigger_scope",
            status="pass",
            detail={"reason": "no_workflows"},
        )

    flagged: list[dict[str, str]] = []
    for fp in files:
        text = fp.read_text(encoding="utf-8", errors="replace")
        for pattern in _DANGEROUS_TRIGGER_PATTERNS:
            if pattern.search(text) and _CHECKOUT_REF_RE.search(text):
                flagged.append(
                    {
                        "file": str(fp.relative_to(repo_path)),
                        "pattern": pattern.pattern,
                    }
                )
                break
    return PostureCheckResult(
        check_name="workflow_trigger_scope",
        status="advisory" if flagged else "pass",
        detail={"flagged_count": len(flagged), "flagged": flagged[:20]},
    )
