-- 004_integration_action_tier.sql
-- Phase I-1: Add action tier to integration_config for permission model.
-- Tier 0 = read-only (default), 1 = enrichment, 2 = mutation (opt-in).

ALTER TABLE integration_config ADD COLUMN action_tier INTEGER NOT NULL DEFAULT 0;
