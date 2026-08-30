# Rovo MCP Confluence Phase 0 Runbook

This runbook executes the read-only hard gate described in
`ROVO_MCP_CONFLUENCE_SERVICE_DEVELOPMENT_PLAN.md`. It does not modify the production CLI,
Confluence pages, permissions, or existing vendor outputs.

## 1. Prepare the isolated runtime

Python 3.10 or newer is required. Install only the Phase 0 dependencies:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-phase0.txt
```

The MCP SDK is pinned to `mcp==2.1.1`; changing it invalidates the saved tool-schema contract and
requires a new Phase 0 run.

## 2. Create controlled Confluence fixtures

Copy `phase0/fixture_manifest.example.json` to a local manifest and replace every placeholder URL.
The nine fixture kinds are mandatory. The `long_content` page must exceed 20,000 characters and
contain unique begin, middle, and end markers. The negative-control page must exist but remain
invisible to both test identities.

Do not put credentials, customer data, or page bodies in the manifest.

## 3. Configure secrets outside the command line

Set environment variables through the approved secret store. Required names:

```text
ROVO_MCP_URL=https://mcp.atlassian.com/v1/mcp/authv2
ROVO_MCP_ALLOWED_SITES=company.atlassian.net
ROVO_MCP_EMAIL=...                 # personal run
ROVO_MCP_API_TOKEN=...             # personal run
ROVO_MCP_API_KEY=...               # service-account run
```

For the optional REST storage comparison:

```text
CONFLUENCE_REST_AUTH_MODE=basic|bearer
CONFLUENCE_REST_EMAIL=...           # Basic only
CONFLUENCE_REST_API_TOKEN=...       # Basic only
CONFLUENCE_REST_BEARER_TOKEN=...    # Bearer only
```

The program never accepts secrets as CLI arguments and never writes response bodies, page titles,
raw URLs with query strings, cloud IDs, cursors, or credentials to evidence.

## 4. Preflight

```powershell
.venv\Scripts\python.exe scripts\run_rovo_phase0.py `
  --manifest phase0\fixture_manifest.local.json `
  --admin-attestation phase0\admin_attestation.local.json `
  --failure-observations phase0\failure_observations.local.json `
  --include-rest `
  --preflight-only `
  --evidence phase0-evidence\preflight.json
```

Preflight intentionally exits with code 2 and writes `status: pending`; it performs no network call.

## 5. Live read-only spike

```powershell
.venv\Scripts\python.exe scripts\run_rovo_phase0.py `
  --manifest phase0\fixture_manifest.local.json `
  --auth-mode personal `
  --auth-mode service_account `
  --admin-attestation phase0\admin_attestation.local.json `
  --failure-observations phase0\failure_observations.local.json `
  --include-rest `
  --evidence phase0-evidence\phase0.json
```

Exit code 0 requires both auth modes, all required fixture checks, the completed admin checklist,
and every failure observation. Missing attestations produce `pending`; capability or fidelity failures
produce `fail`. Never change a failed observation to passed without a reproducible reference.

## 6. Offline contract tests

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m unittest tests.test_confluence_phase0 -v
.venv\Scripts\python.exe -m unittest discover -s tests
```

Synthetic fixtures contain no private page content. Real evidence belongs under `phase0-evidence/`,
which is gitignored.

## Hard Gate interpretation

- `pass`: Phase 0 technical checks and both attestations are complete. A human still signs the evidence.
- `pending`: implementation is usable, but live credentials, admin evidence, or failure observations are incomplete.
- `fail`: required tools/schema, site mapping, content fidelity, truncation, REST same-version check, or a required fixture failed.

Do not begin Phase 1 while the evidence is `pending` or `fail`.
