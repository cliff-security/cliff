-- 012_phase2_columns.sql
-- PRD-0006 Phase 2 / IMPL-0007 §B1.
--
-- Adds two nullable columns to the unified ``finding`` table so the
-- side panel's "Reject" reason picker can persist its outcome:
--
--   exception_reason  TEXT  CHECK in {'false_positive','accepted_risk',
--                                     'wont_fix','deferred'}, NULL ok
--   exception_note    TEXT  free-form, NULL ok (≤ 280 chars enforced
--                            at the API layer to keep the DB schema dumb)
--
-- A finding's ``status='exception'`` does not by itself force a reason —
-- pre-Phase-2 rows continue to fall through to the "accepted" default in
-- ``issue_derivation``. Once the operator rejects via the new endpoint
-- (POST /findings/{id}/reject), both columns are populated and the
-- derivation reads them directly.
--
-- Per ADR-0033 this migration is forward-only; rollback is not supported.

BEGIN;

ALTER TABLE finding
    ADD COLUMN exception_reason TEXT
        CHECK (
            exception_reason IS NULL
            OR exception_reason IN (
                'false_positive',
                'accepted_risk',
                'wont_fix',
                'deferred'
            )
        );

ALTER TABLE finding
    ADD COLUMN exception_note TEXT;

COMMIT;
