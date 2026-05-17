# Fixtures

Sample and demo data used across tests, local development, and the hosted demo.

## Files

| File | Purpose |
|------|---------|
| `sample_finding.json` | Single normalized Finding — used as the canonical example in tests |
| `sample_finding_minimal.json` | Minimal FindingCreate payload — used to exercise default-value handling |
| `sample-snyk-export.json` | Raw Snyk CLI JSON output — used by the Snyk adapter tests |
| `sample-wiz-export.json` | Raw Wiz export — used by the Wiz adapter tests |
| `demo-seed-findings.json` | **10 curated findings for the hosted demo** — see below |

## `demo-seed-findings.json` — demo seed

The demo seed is the dataset behind the public `demo.cliff.dev` environment (and the local demo when `CLIFF_DEMO=true` lands in Phase 9b). It's designed to make Cliff tell a complete story to a first-time visitor in under 3 minutes.

### What's in it

10 findings spread across:

| Axis | Spread |
|------|--------|
| Severity | 2 critical, 4 high, 3 medium, 1 low |
| Status | 3 `new`, 2 `triaged`, 2 `in_progress`, 1 `remediated`, 1 `validated`, 1 `closed` |
| Source | Snyk (5), Trivy (3), Gitleaks (1), GitHub Advanced Security (1) |
| Scenario | OSS dependency CVE, prototype pollution, cloud misconfig, leaked secret, base-image CVE, SSRF, regex DoS, missing security header, exception-closed finding |

Every finding has:
- A realistic `description` pulled from the actual vuln
- A `plain_description` written for a non-security reader (the jargon-free copy the finding-normalizer agent would emit)
- A `why_this_matters` line that contextualizes blast radius and reachability
- A `raw_payload` block preserving scanner-native fields (CVE, CVSS, version info) so adapters can round-trip

### Why this shape

A demo dataset should show someone:

1. **What fresh findings look like** — `new` + `triaged` items the visitor can click into and run an agent on
2. **What in-flight work looks like** — `in_progress` items with partial state in the sidebar
3. **What "done" looks like** — `validated` and `closed` items that demonstrate the full lifecycle, including an exception-closed case (demo-010) showing "risk accepted" is a valid outcome
4. **That the product handles real CVEs** — not synthetic `"Acme Vuln #1"` placeholders

### How to load it

Until `CLIFF_DEMO=true` ships in Phase 9b, the simplest path is the Queue page's JSON import:

```bash
# Start Cliff locally
docker compose -f docker/docker-compose.yml up

# In another terminal, POST the seed to the findings import endpoint
curl -X POST http://localhost:8000/api/findings/import \
  -H "Content-Type: application/json" \
  -d @fixtures/demo-seed-findings.json
```

Alternatively, copy the file into `data/demo/` on a fresh instance — the startup seeder (Phase 9b) will pick it up when `CLIFF_DEMO=true` is set.

### Editing guidelines

If you add or change findings, keep the distribution intact so the demo keeps its pedagogical shape:

- Keep at least one `new` item per severity tier so "what to work on next" is always clear
- Keep at least one `closed` item with `raw_payload.reachable: false` to show the exception path
- Keep dates recent (within the last 30 days of the repo's current timeline) so the demo feels live
- Don't invent CVEs — real CVE IDs give the demo credibility
