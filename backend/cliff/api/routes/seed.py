"""Seed demo data for development and testing."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from cliff.db.connection import get_db
from cliff.db.repo_finding import create_finding, list_findings
from cliff.models import Finding, FindingCreate

router = APIRouter(tags=["seed"])

DEMO_FINDINGS: list[dict] = [
    {
        "source_type": "tenable",
        "source_id": "CVE-2023-46589",
        "title": "Apache Tomcat vulnerable version on web-prod-17",
        "description": (
            "CVE-2023-46589 identified on web-prod-17. Apache Tomcat 9.0.82"
            " is vulnerable to HTTP request smuggling, allowing attackers"
            " to bypass security constraints."
        ),
        "raw_severity": "critical",
        "normalized_priority": "P1",
        "asset_id": "web-prod-17",
        "asset_label": "Web Server 17 (Production)",
        "status": "new",
        "likely_owner": "Web Platform Team",
        "why_this_matters": (
            "Internet-facing server with known exploit available."
            " Request smuggling can bypass WAF rules and access"
            " internal admin endpoints."
        ),
    },
    {
        "source_type": "cloudwatch",
        "source_id": "AWS-S3-PUBLIC-001",
        "title": "Publicly exposed S3 bucket with permissive policy",
        "description": (
            "S3 bucket data-archive-01 has a public access policy"
            " allowing unauthenticated reads. Contains archived"
            " customer reports from 2023."
        ),
        "raw_severity": "high",
        "normalized_priority": "P2",
        "asset_id": "data-archive-01",
        "asset_label": "Data Archive Bucket",
        "status": "triaged",
        "likely_owner": "Data Engineering",
        "why_this_matters": (
            "Public bucket may expose sensitive customer data."
            " Compliance risk under SOC 2 and GDPR."
        ),
    },
    {
        "source_type": "internal_scan",
        "source_id": "SSH-KEYS-EXPIRED-04",
        "title": "Outdated SSH keys detected on jump-host-04",
        "description": (
            "SSH key rotation policy violation. 3 keys on"
            " jump-host-04 have not been rotated in over 180 days."
        ),
        "raw_severity": "medium",
        "normalized_priority": "P3",
        "asset_id": "jump-host-04",
        "asset_label": "Jump Host 04",
        "status": "new",
        "likely_owner": "IT Security",
        "why_this_matters": (
            "Stale SSH keys increase risk of credential compromise"
            " if any key is leaked."
        ),
    },
    {
        "source_type": "snyk",
        "source_id": "SNYK-JS-LODASH-1234",
        "title": "Prototype pollution in lodash < 4.17.21",
        "description": (
            "The application uses lodash 4.17.19 which is vulnerable"
            " to prototype pollution via the merge and zipObjectDeep"
            " functions."
        ),
        "raw_severity": "medium",
        "normalized_priority": "P3",
        "asset_id": "frontend-app",
        "asset_label": "Customer Portal Frontend",
        "status": "in_progress",
        "likely_owner": "Frontend Team",
        "why_this_matters": (
            "Prototype pollution can lead to property injection,"
            " potentially enabling XSS or denial of service."
        ),
    },
    {
        "source_type": "wiz",
        "source_id": "WIZ-IAM-OVERPERM-01",
        "title": "Over-permissioned IAM role on lambda-processor",
        "description": (
            "Lambda function lambda-processor has AdministratorAccess"
            " policy attached. Function only requires S3 read and"
            " DynamoDB write."
        ),
        "raw_severity": "low",
        "normalized_priority": "P4",
        "asset_id": "lambda-processor",
        "asset_label": "Data Processor Lambda",
        "status": "new",
        "likely_owner": "Cloud Infrastructure",
        "why_this_matters": (
            "Over-permissioned roles violate least-privilege principle"
            " and expand blast radius if the function is compromised."
        ),
    },
]


@router.post("/seed", response_model=list[Finding], status_code=201)
async def seed_demo_data(db=Depends(get_db)):
    """Seed demo findings. Skips if findings already exist."""
    existing = await list_findings(db, limit=1)
    if existing:
        return existing

    results = []
    for data in DEMO_FINDINGS:
        finding = await create_finding(db, FindingCreate(**data))
        results.append(finding)
    return results
