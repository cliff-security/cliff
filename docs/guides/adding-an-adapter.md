# Adding an Adapter

> This guide will be updated when the adapter framework is built in Phase 2-3.

## Overview

Cliff connects to external systems through four adapter interfaces. Each interface defines a contract (abstract class) that providers implement.

See [docs/architecture/adapter-interfaces.md](../architecture/adapter-interfaces.md) for the full interface specs.

## Steps

### 1. Choose the interface

| Interface | Use when you want to... |
|-----------|------------------------|
| FindingSource | Import vulnerability findings from a scanner |
| OwnershipContext | Resolve asset owners from an external system |
| Ticketing | Create/manage tickets in a project management tool |
| Validation | Check fix status from a scanner or test runner |

### 2. Create the provider

```
backend/adapters/<interface>/<provider_name>.py
```

Implement all required methods from the interface.

### 3. Register the provider

Add your provider to the adapter registry so it appears in the Integrations page.

### 4. Add configuration schema

Define what settings your adapter needs (API URL, credentials, project key, etc.) as a Pydantic model.

### 5. Write tests

Use fixture data to test your adapter without hitting real APIs. Place fixtures in `fixtures/`.

### 6. Document

Add a section to the Integrations page docs describing your adapter's capabilities and configuration.
