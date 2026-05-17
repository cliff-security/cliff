# Adapter Interfaces

Cliff connects to external systems through four adapter interfaces. Each interface has an abstract contract and at least one provider implementation. MVP ships with mock providers only.

See [ADR-0006](../adr/0006-mock-first-adapters.md) for the rationale.

## Interface Overview

| Interface | Purpose | Mock Provider | First Real Provider |
|-----------|---------|---------------|---------------------|
| FindingSource | Import vulnerability findings | Static JSON fixtures | Tenable or Wiz |
| OwnershipContext | Resolve asset owners and context | Static JSON fixtures | CMDB / cloud tags |
| Ticketing | Create and manage remediation tickets | In-app ticket simulator | Jira |
| Validation | Check if a finding is fixed | Static validation results | Re-scan API |

---

## 1. FindingSource

Provides vulnerability findings for the Queue and opens them into Workspaces.

### Methods

```
list_findings(filters: FindingFilters) -> list[FindingSummary]
get_finding(finding_id: str) -> FindingDetail
refresh_finding(finding_id: str) -> FindingDetail
```

### FindingSummary

| Field | Type | Description |
|-------|------|-------------|
| source_id | str | ID in the source system |
| title | str | Human-readable finding title |
| raw_severity | str | Severity as reported by scanner (critical/high/medium/low) |
| asset_id | str | Affected asset identifier |
| asset_label | str | Human-readable asset name |
| updated_at | datetime | Last update in source system |

### FindingDetail

Extends FindingSummary with:

| Field | Type | Description |
|-------|------|-------------|
| description | str | Full finding description |
| cve_ids | list[str] | Associated CVE identifiers |
| affected_package | str | Package name and version |
| remediation_hint | str | Scanner-provided fix suggestion |
| raw_payload | dict | Complete original payload |

---

## 2. OwnershipContext

Enriches findings with asset ownership and environment context.

### Methods

```
resolve_asset(asset_identifiers: AssetQuery) -> AssetContext
resolve_owner(asset_or_service: str) -> list[OwnerCandidate]
get_related_history(asset_or_service: str) -> list[HistoricalCase]
```

### AssetContext

| Field | Type | Description |
|-------|------|-------------|
| service_name | str | Logical service name |
| environment | str | prod / staging / dev |
| business_criticality | str | critical / high / medium / low |
| internet_facing | bool or None | Whether the asset is internet-exposed |
| cloud_account | str | Cloud account or subscription |
| tags | dict | Arbitrary metadata tags |

### OwnerCandidate

| Field | Type | Description |
|-------|------|-------------|
| team | str | Team name |
| person | str or None | Individual if identifiable |
| confidence | float | 0.0 - 1.0 |
| evidence | str | Why this candidate was selected |
| source | str | Where the evidence came from (CMDB, CODEOWNERS, git log, etc.) |

---

## 3. Ticketing

Creates and manages remediation tickets in external systems.

### Methods

```
preview_ticket(plan: RemediationPlan) -> TicketPreview
create_ticket(plan: RemediationPlan) -> TicketReference
update_ticket(ticket_id: str, update: TicketUpdate) -> TicketReference
get_ticket(ticket_id: str) -> TicketStatus
```

### TicketPreview

| Field | Type | Description |
|-------|------|-------------|
| title | str | Proposed ticket title |
| body_markdown | str | Proposed ticket body |
| assignee | str | Proposed assignee |
| priority | str | Proposed priority |
| labels | list[str] | Proposed labels |

### TicketReference

| Field | Type | Description |
|-------|------|-------------|
| provider | str | System name (jira, github, etc.) |
| external_key | str | Ticket key (e.g., SEC-1234) |
| url | str | Deep link to ticket |
| status | str | Current ticket status |

---

## 4. Validation

Checks whether a vulnerability finding has been fixed.

### Methods

```
request_validation(finding_id: str, workspace_id: str) -> ValidationRequest
get_validation_result(validation_id: str) -> ValidationOutcome
```

### ValidationOutcome

| Field | Type | Description |
|-------|------|-------------|
| state | str | fixed / still_active / uncertain |
| details_markdown | str | Human-readable explanation |
| evidence | dict | Supporting data |
| checked_at | datetime | When validation ran |
| recommendation | str | close / reopen / recheck_later |

---

## Adding a New Adapter

See [docs/guides/adding-an-adapter.md](../guides/adding-an-adapter.md) for a step-by-step guide.

In short:

1. Choose which interface your adapter implements
2. Create a new provider class in `backend/adapters/<interface>/<provider>.py`
3. Implement all required methods
4. Register the provider in the adapter registry
5. Add configuration schema to IntegrationConfig
6. Write tests using fixture data
