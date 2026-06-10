"""The agentic triage Deep dive (ADR-0052).

The escalation-gated pipeline that investigates uncertain / high-stakes findings
by reading real source — gather_facts -> rule_out -> trace_path -> plan_exploit
-> challenge — read-only and plan-don't-execute in V1.
"""
