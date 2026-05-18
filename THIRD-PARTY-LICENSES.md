# Third-party licenses

Cliff is licensed under the GNU Affero General Public License v3.0 only
(`AGPL-3.0-only`). See [`LICENSE`](LICENSE) for the full text.

This document inventories the third-party software that Cliff bundles,
links against, or fetches at install time, together with each project's
license terms and the obligation Cliff carries forward. Entries are
grouped by the surface where the dependency reaches Cliff.

The inventory below is current as of release-tagging time. For the live
state, see `backend/uv.lock`, `frontend/package.json` /
`frontend/node_modules/`, `.opencode-version`, and `.scanner-versions`.

---

## 1. Bundled binaries

These programs are downloaded by Cliff's installer scripts and baked into
the Docker image. Cliff invokes each one as a subprocess; nothing here is
linked into the Python application process.

### OpenCode

- **Project:** [anomalyco/opencode](https://github.com/anomalyco/opencode)
- **Version pinned:** see [`.opencode-version`](.opencode-version) (currently `1.3.2`)
- **License:** `MIT`
- **Installed by:** [`scripts/install-opencode.sh`](scripts/install-opencode.sh)
- **Bundle mechanism:** GitHub release archive extracted into `BIN_DIR`; the upstream `LICENSE` is preserved alongside the binary as `opencode.LICENSE`.
- **Cliff's obligation:** Reproduce the MIT copyright notice and license text alongside redistribution. Upstream text: <https://github.com/anomalyco/opencode/blob/dev/LICENSE>.

### Trivy

- **Project:** [aquasecurity/trivy](https://github.com/aquasecurity/trivy)
- **Version pinned:** see [`.scanner-versions`](.scanner-versions) (currently `0.70.0`)
- **License:** `Apache-2.0`
- **Installed by:** [`scripts/install-scanners.sh`](scripts/install-scanners.sh)
- **Bundle mechanism:** GitHub release tarball, checksum-verified against the upstream `trivy_<version>_checksums.txt`. `LICENSE` is extracted from the tarball alongside the binary as `trivy.LICENSE`. (Upstream does not ship a separate `NOTICE` file; if one is added in a future release, the installer also preserves it as `trivy.NOTICE`.)
- **Cliff's obligation:** Preserve `LICENSE` per Apache §4(d). Upstream text: <https://github.com/aquasecurity/trivy/blob/main/LICENSE>.
- **Note on the Trivy vulnerability database:** Trivy fetches its own DB at scan time. The DB content has its own license terms (mostly `CC-BY-4.0` / `Apache-2.0` / NVD public domain depending on source) and is the responsibility of Trivy, not Cliff. Cliff does not cache or redistribute Trivy DB snapshots.

### Semgrep CE engine

- **Project:** [semgrep/semgrep](https://github.com/semgrep/semgrep)
- **Version pinned:** see [`.scanner-versions`](.scanner-versions) (currently `1.70.0`)
- **License:** `LGPL-2.1` (the engine; the registry rule packs are licensed separately — see §2 below)
- **Installed by:** [`scripts/install-scanners.sh`](scripts/install-scanners.sh)
- **Bundle mechanism:** Installed via `pip` from PyPI into a private virtualenv. The package's `LICENSE` is preserved alongside `BIN_DIR` as `semgrep.LICENSE`.
- **Cliff's obligation:** Preserve the LGPL-2.1 license text. Cliff invokes Semgrep only as a subprocess via the wrapper script at `${BIN_DIR}/semgrep`, satisfying the LGPL §6 dynamic-coupling carve-out. Upstream text: <https://semgrep.dev/docs/licensing>.

---

## 2. Semgrep registry rule packs (not bundled)

`backend/cliff/assessment/scanners/runner.py` invokes the Semgrep CLI with
the following rule-pack identifiers:

```python
SEMGREP_CONFIGS = (
    "p/security-audit",
    "p/owasp-top-ten",
)
```

These `p/...` identifiers resolve at scan time against Semgrep's hosted
**rule registry**. The registry rule content is **not** redistributed by
Cliff and is **not** licensed under the LGPL-2.1 engine license.

- **License:** [Semgrep Rules License v1.0](https://semgrep.dev/legal/rules-license/) — source-available, non-SaaS, non-competing.
- **Permitted:** free internal business use (running these rules against your own code, on infrastructure you operate).
- **Prohibited without a commercial license from Semgrep, Inc.:** shipping these rules inside a commercial product; offering them as a SaaS or hosted service; using them inside a product that competes with Semgrep's offerings.
- **Cliff's posture:** Cliff ships open-source under AGPL-3.0-only. The Semgrep rule packs are fetched by the Semgrep CLI at scan time — the obligation to comply with the Semgrep Rules License v1.0 sits with the operator running Cliff. Teams considering paid, hosted, or otherwise commercial use of Cliff should consult counsel before relying on these rule packs; an LGPL-clean alternative such as [OpenGrep](https://github.com/opengrep/opengrep) is available as a near drop-in for the Semgrep CLI.

---

## 3. Python runtime dependencies

Source of truth: [`backend/uv.lock`](backend/uv.lock).

All Python production dependencies use AGPL-3.0-compatible licenses
(`MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `Apache-2.0`, `MPL-2.0`, `PSF-2.0`,
`Apache-2.0 OR BSD-3-Clause`, `MIT OR Apache-2.0`). No copyleft license
appears in the Linux production dependency set.

### Apache-2.0 packages requiring NOTICE preservation

Apache §4(d) requires that any upstream `NOTICE` file be preserved in
derivative works. For Cliff this applies to:

| Package | Upstream NOTICE |
|---|---|
| `cryptography` | <https://github.com/pyca/cryptography/blob/main/LICENSE> (Apache-2.0 OR BSD-3-Clause; no separate NOTICE file as of upstream main) |
| `importlib-metadata` | <https://pypi.org/project/importlib-metadata/> (Apache-2.0; upstream `python/importlib_metadata` does not ship a separate `LICENSE` or `NOTICE` file — license is declared via wheel metadata) |
| `packaging` | <https://github.com/pypa/packaging/blob/main/LICENSE> (Apache-2.0 OR BSD-2-Clause) |
| `uvloop` | <https://github.com/MagicStack/uvloop/blob/master/LICENSE-APACHE> (MIT OR Apache-2.0) |
| `pytest-asyncio` | <https://github.com/pytest-dev/pytest-asyncio/blob/main/LICENSE> *(dev only)* |
| `docker` (docker-py) | <https://github.com/docker/docker-py/blob/main/LICENSE> *(dev / install-time only)* |
| `requests` | <https://github.com/psf/requests/blob/main/LICENSE> *(transitive of docker-py)* |

### Aggregate Python license summary

| License | Count |
|---|---:|
| `MIT` / `MIT OR Apache-2.0` | ~30 |
| `BSD-2-Clause` / `BSD-3-Clause` | ~15 |
| `Apache-2.0` / `Apache-2.0 OR BSD-*` | ~7 |
| `MPL-2.0` | 1 (`certifi`) |
| `PSF-2.0` | 1 (`typing-extensions`) |
| `mixed (PSF-2.0 + LGPL-2.1 modules)` | 1 (`pywin32`, Windows-only, subprocess/dynamic-import boundary; not present in the Linux Docker image) |

The pywin32 LGPL-2.1 modules are loaded only on Windows and only via
Python's `ctypes` / dynamic import, which is the LGPL §6 carve-out
boundary; this is well-established compatibility with AGPL-3.0.

---

## 4. Node frontend dependencies

Source of truth: [`frontend/package.json`](frontend/package.json) and
`frontend/node_modules/`.

All 529 transitive Node packages use AGPL-3.0-compatible licenses. No
copyleft, source-available (SSPL / BUSL / Elastic / Commons Clause), or
unlicensed packages appear in the tree.

### Aggregate Node license summary

| License | Count |
|---|---:|
| `MIT` | 457 |
| `Apache-2.0` | 24 |
| `ISC` | 22 |
| `BSD-2-Clause` | 9 |
| `BSD-3-Clause` | 5 |
| `BlueOak-1.0.0` | 3 |
| `MPL-2.0` | 2 |
| `MIT-0` | 2 |
| `MIT OR CC0-1.0` | 1 |
| `0BSD` | 1 |
| `Python-2.0` | 1 |
| `CC0-1.0` | 1 |
| `CC-BY-4.0` | 1 |
| **Total** | **529** |

`CC-BY-4.0` is one-way GPLv3+-compatible per Creative Commons and FSF
guidance; `MPL-2.0` is GPL-compatible via its secondary-license clause.

---

## 5. In-repo plugins

The only plugin shipped inside this repository is
[`plugins/secure-repo/`](plugins/secure-repo/). Its
[`plugin.json`](plugins/secure-repo/.claude-plugin/plugin.json) declares
`"license": "AGPL-3.0-only"`, exactly matching the project's overall
SPDX identifier. Inbound = outbound.

---

## 6. Reference

This inventory was assembled with reference to:

- The FSF [list of GPL-compatible licenses](https://www.gnu.org/licenses/license-list.html)
- The SPDX license list (<https://spdx.org/licenses/>)
- The audit at `cliff-os/legal/LEGAL-READINESS.md` (2026-05-17), §§3-6
- Upstream `LICENSE` and `NOTICE` files of each listed dependency

Bug reports about any missing attribution are welcome — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).
