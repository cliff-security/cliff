-- 005_drop_audit_hash_chain.sql
-- Remove hash-chain columns from audit_log (no longer used).
ALTER TABLE audit_log DROP COLUMN prev_hash;
ALTER TABLE audit_log DROP COLUMN event_hash;
