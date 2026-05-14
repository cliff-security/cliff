-- 019_posture_titles_issue_framed.sql
--
-- Migration 018 set posture titles to the "desired state" (e.g. "Secret
-- scanning enabled"). Those titles read as the *check name*, not the
-- problem — a row titled "Secret scanning enabled" sitting in the Todo
-- queue is genuinely confusing because the user has to mentally invert
-- the wording to understand what's wrong.
--
-- Re-title in-place to issue-framed language ("Secret scanning disabled").
-- Source of truth lives in opensec.assessment.posture.CHECK_DISPLAY_NAME;
-- keep them in sync.
--
-- Idempotent: only rewrites titles that still match the migration-018
-- "desired state" wording. Any row a user has manually retitled stays put.

UPDATE finding
SET title = CASE title
  WHEN 'Branch protection enabled'        THEN 'Branch protection not enabled on default branch'
  WHEN 'Force pushes blocked'             THEN 'Force pushes allowed on default branch'
  WHEN 'No committed secrets'             THEN 'Secrets committed in repository'
  WHEN 'SECURITY.md present'              THEN 'SECURITY.md missing'
  WHEN 'Lockfile present'                 THEN 'Lockfile missing'
  WHEN 'Dependabot/Renovate configured'   THEN 'Dependabot/Renovate not configured'
  WHEN 'Signed commits'                   THEN 'Commits not signed'
  WHEN 'Code owners file exists'          THEN 'CODEOWNERS file missing'
  WHEN 'Secret scanning enabled'          THEN 'Secret scanning disabled'
  WHEN 'Actions pinned to SHA'            THEN 'GitHub Actions not pinned to SHA'
  WHEN 'Trusted action sources'           THEN 'Untrusted GitHub Action sources'
  WHEN 'Workflow trigger scope'           THEN 'Workflow trigger scope too permissive'
  WHEN 'No stale collaborators'           THEN 'Stale collaborators with write access'
  WHEN 'Team permissions scoped'          THEN 'Team permissions too broad'
  WHEN 'Default branch permissions'       THEN 'Default branch permissions too broad'
  ELSE title
END
WHERE type = 'posture'
  AND title IN (
    'Branch protection enabled','Force pushes blocked','No committed secrets',
    'SECURITY.md present','Lockfile present','Dependabot/Renovate configured',
    'Signed commits','Code owners file exists','Secret scanning enabled',
    'Actions pinned to SHA','Trusted action sources','Workflow trigger scope',
    'No stale collaborators','Team permissions scoped','Default branch permissions'
  );
