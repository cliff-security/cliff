# Agent eval datasets — public synthetic samples

These JSONL files are the **public, synthetic sample** datasets for the agent
eval harness (ADR-0050). They exist so the eval is:

- **runnable in open source** (a contributor can run the live lane), and
- **deterministic in CI** (the harness tests load them).

They are intentionally small and contain **no proprietary or confidential
data** — only well-known public CVEs and hand-authored synthetic findings.

## The real datasets live elsewhere (private)

The proprietary / confidential golden sets — and any customer-derived data —
live in the **private `cliff-os/eval/`** project, never in this public repo
(ADR-0050 "harness public, data private").

The harness reads its dataset directory from `CLIFF_EVAL_DATASET_DIR`:

| Run | `CLIFF_EVAL_DATASET_DIR` | Dataset |
|-----|--------------------------|---------|
| public CI / OSS | _(unset)_ | this directory (synthetic sample) |
| private eval pipeline | `cliff-os/eval/datasets` | the real golden sets |

So the *scoring logic* is open and the *data* stays private. To add a public
sample case, append a line here; real/sensitive cases go in `cliff-os/eval`.
