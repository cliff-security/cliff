-- 018_posture_severity_backfill.sql
--
-- Backfill posture findings persisted by older builds (source_type='cliff-posture',
-- raw_severity=NULL, title=check_name, description=NULL) with the new metadata:
--   * source_type      → 'cliff'
--   * raw_severity     → calibrated per check
--   * normalized_priority → same value
--   * title            → human-readable display name (only when title still equals the raw check name)
--   * description      → static remediation guidance from posture/__init__.py CHECK_DESCRIPTION
--
-- Idempotent: re-running is a no-op because the WHERE clauses match only the legacy shape.
--
-- The mapping is duplicated here from Python because SQLite migrations are SQL-only;
-- the source of truth is cliff.assessment.posture.CHECK_SEVERITY / CHECK_DISPLAY_NAME /
-- CHECK_DESCRIPTION. Keep them in sync on changes.

UPDATE finding
SET source_type = 'cliff'
WHERE type = 'posture' AND source_type = 'cliff-posture';

-- Severity backfill — only fill rows where it's still NULL, so any later
-- manual edits aren't clobbered.
UPDATE finding
SET raw_severity = CASE title
  WHEN 'branch_protection'           THEN 'high'
  WHEN 'no_force_pushes'             THEN 'medium'
  WHEN 'no_secrets_in_code'          THEN 'high'
  WHEN 'security_md'                 THEN 'low'
  WHEN 'lockfile_present'            THEN 'medium'
  WHEN 'dependabot_config'           THEN 'medium'
  WHEN 'signed_commits'              THEN 'low'
  WHEN 'code_owners_exists'          THEN 'low'
  WHEN 'secret_scanning_enabled'     THEN 'high'
  WHEN 'actions_pinned_to_sha'       THEN 'medium'
  WHEN 'trusted_action_sources'      THEN 'medium'
  WHEN 'workflow_trigger_scope'      THEN 'low'
  WHEN 'stale_collaborators'         THEN 'medium'
  WHEN 'broad_team_permissions'      THEN 'medium'
  WHEN 'default_branch_permissions'  THEN 'medium'
  ELSE 'medium'
END
WHERE type = 'posture' AND raw_severity IS NULL;

UPDATE finding
SET normalized_priority = raw_severity
WHERE type = 'posture' AND normalized_priority IS NULL;

-- Description backfill.
UPDATE finding
SET description = CASE title
  WHEN 'branch_protection' THEN
    'The default branch has no protection rule, so anyone with push access can land code without review, CI, or status checks. Enable branch protection on the default branch and require at least one approving pull-request review plus passing status checks before merge.'
  WHEN 'no_force_pushes' THEN
    'Force pushes to the default branch are allowed, which means history can be rewritten and audited commits silently lost. Turn off force pushes in the default branch''s protection rule.'
  WHEN 'no_secrets_in_code' THEN
    'A static secret scan flagged credentials in the repository tree. Rotate the secret immediately, remove it from the codebase, and move it into the secrets manager. Add a pre-commit secret-scan hook to keep new ones out.'
  WHEN 'security_md' THEN
    'The repo has no SECURITY.md, so external researchers have no documented way to report vulnerabilities. Add a SECURITY.md at the repo root with a reporting contact and disclosure policy.'
  WHEN 'lockfile_present' THEN
    'A package manifest exists without a matching lockfile, so dependency resolution drifts between machines and CI. Commit the appropriate lockfile (package-lock.json, poetry.lock, Cargo.lock, etc.) so installs are reproducible and Dependabot can pin upgrades.'
  WHEN 'dependabot_config' THEN
    'No Dependabot or Renovate configuration is present, so the project gets no automatic alerts or PRs when its dependencies have known CVEs. Add .github/dependabot.yml (or renovate.json) covering every ecosystem in the repo.'
  WHEN 'signed_commits' THEN
    'Recent commits on the default branch are not GPG/SSH-signed, so commit authorship can''t be cryptographically verified. Encourage maintainers to sign commits and enable ''Require signed commits'' on the default branch''s protection rule.'
  WHEN 'code_owners_exists' THEN
    'There is no CODEOWNERS file, so reviewers aren''t auto-assigned on sensitive paths and no one is accountable for them. Add CODEOWNERS at .github/CODEOWNERS mapping the security-critical paths to the right team handles.'
  WHEN 'secret_scanning_enabled' THEN
    'GitHub''s secret-scanning feature is off for this repository, so any credential that lands on the default branch will not trigger an alert. Enable secret scanning (and push protection if available) in the repo''s Security settings.'
  WHEN 'actions_pinned_to_sha' THEN
    'GitHub Actions workflows reference third-party actions by tag (@v3) instead of by commit SHA, so a compromised tag silently pulls malicious code into CI. Pin every third-party action to a full 40-char commit SHA.'
  WHEN 'trusted_action_sources' THEN
    'CI workflows pull actions from publishers outside an allowlist of trusted vendors. Restrict the Actions allowlist (Settings → Actions → General) to GitHub-verified creators and your approved third parties.'
  WHEN 'workflow_trigger_scope' THEN
    'One or more workflows use a permissive trigger (e.g. pull_request_target or write-mode token on a fork PR) that an attacker can abuse from an untrusted fork. Audit each workflow''s triggers and token permissions; default to GITHUB_TOKEN: read-only.'
  WHEN 'stale_collaborators' THEN
    'Collaborators with write access haven''t shown activity in the last 90 days. Stale access is access an attacker can take over. Remove inactive collaborators or downgrade them to read.'
  WHEN 'broad_team_permissions' THEN
    'A team has admin or maintain on the repo when write or triage would suffice. Tighten the team''s permission to the least it needs for its actual workflow.'
  WHEN 'default_branch_permissions' THEN
    'Too many roles can push directly to the default branch. Restrict push to a small set of maintainers and enforce PRs for everyone else via branch protection.'
  ELSE description
END
WHERE type = 'posture' AND description IS NULL;

-- Title humanization — only rewrite rows whose title still equals the raw check name.
UPDATE finding
SET title = CASE title
  WHEN 'branch_protection'           THEN 'Branch protection enabled'
  WHEN 'no_force_pushes'             THEN 'Force pushes blocked'
  WHEN 'no_secrets_in_code'          THEN 'No committed secrets'
  WHEN 'security_md'                 THEN 'SECURITY.md present'
  WHEN 'lockfile_present'            THEN 'Lockfile present'
  WHEN 'dependabot_config'           THEN 'Dependabot/Renovate configured'
  WHEN 'signed_commits'              THEN 'Signed commits'
  WHEN 'code_owners_exists'          THEN 'Code owners file exists'
  WHEN 'secret_scanning_enabled'     THEN 'Secret scanning enabled'
  WHEN 'actions_pinned_to_sha'       THEN 'Actions pinned to SHA'
  WHEN 'trusted_action_sources'      THEN 'Trusted action sources'
  WHEN 'workflow_trigger_scope'      THEN 'Workflow trigger scope'
  WHEN 'stale_collaborators'         THEN 'No stale collaborators'
  WHEN 'broad_team_permissions'      THEN 'Team permissions scoped'
  WHEN 'default_branch_permissions'  THEN 'Default branch permissions'
  ELSE title
END
WHERE type = 'posture'
  AND title IN (
    'branch_protection','no_force_pushes','no_secrets_in_code','security_md',
    'lockfile_present','dependabot_config','signed_commits','code_owners_exists',
    'secret_scanning_enabled','actions_pinned_to_sha','trusted_action_sources',
    'workflow_trigger_scope','stale_collaborators','broad_team_permissions',
    'default_branch_permissions'
  );
