"""Deterministic assessment engine (ADR-0025 + ADR-0028).

Given an HTTPS repo URL, ``run_assessment`` clones the repo and produces an
:class:`AssessmentResult` with vulnerability findings (from Trivy), code
findings (from Semgrep), and 15 repo posture checks. No LLM during the scan
itself; the API layer threads the LLM normalizer for ``plain_description``.
"""

from __future__ import annotations

from cliff.assessment.engine import (
    RepoCloner,
    derive_grade,
    run_assessment,
)

__all__ = ["RepoCloner", "derive_grade", "run_assessment"]
