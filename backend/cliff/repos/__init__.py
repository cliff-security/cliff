"""Repo knowledge base (ADR-0053).

A first-class git-repository entity plus the per-repo "Project profile" store
that the agentic triage Deep dive (ADR-0052) reads. Distinct from the
``cliff.db.repo_*`` modules, which are the data-access ("repository pattern")
layer for other entities — this package is the git-repository feature itself.
"""
