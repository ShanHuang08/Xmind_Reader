# Rovo MCP Confluence Phase 0 Runbook

This runbook executes the read-only hard gate described in
`ROVO_MCP_CONFLUENCE_SERVICE_DEVELOPMENT_PLAN.md`. It does not modify the production CLI,
Confluence pages, permissions, or existing vendor outputs.

This runbook targets the **Rovo MCP v2** contract only:

```text
Endpoint: https://mcp.atlassian.com/v2/mcp
Required tools: getAccessibleAtlassianResources, getConfluenceContent
Confluence scope: read:confluence:agent-interface
Content request: detail=full, content_format=markdown, include_metadata=true
Input/evidence schema version: 2
```

Rovo MCP v2 is separate from the optional Confluence REST API v2 storage fallback. The two paths
have independent endpoints, credentials, schemas, and evidence.

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
The local manifest, admin attestation, and failure observations must use `schema_version: 2`.
The nine fixture kinds are mandatory. The `long_content` page must exceed 20,000 characters and
contain unique begin, middle, and end markers. The negative-control page must exist but remain
invisible to both test identities.

Do not put credentials, customer data, or page bodies in the manifest.


## 3. Enable API token authentication and create a personal token

For Python or other non-interactive Phase 0 runs, enable API token authentication in the
Atlassian Rovo MCP server administration settings:

```text
Atlassian Administration
-> Rovo MCP server
-> Authentication
-> Allow API token authentication = Enabled
```

When API token authentication is used, no custom OAuth domain entry is required for the Python
script. The **Domains** allowlist is relevant to OAuth-based clients; this runbook uses API token
authentication for the personal run.

Create the personal token from the Atlassian account security page:

```text
Atlassian account
-> Security
-> API tokens
-> Create API token with scopes
```

Recommended token name:

```text
Rovo MCP Python - Confluence
```

Select the Rovo MCP v2 Confluence read permission. The minimum documented Phase 0 scope is:

```text
read:confluence:agent-interface
```

Do not grant write, delete, or search scopes for the direct page-read Phase 0 path. The token/session
must also contain the user-context claims required by `getAccessibleAtlassianResources`; Atlassian's
token UI and organization policy determine how those claims are issued, so the live call—not a legacy
v1 scope list—is the hard-gate evidence. If resource discovery reports a missing scope claim, recreate
the token with the account/resource identity access offered by the current Atlassian token UI and
record the exact approved selection in the admin attestation.

The token must still respect the permissions of the Atlassian user that created it. A token cannot
read a Confluence page that the underlying user account cannot access.

Store the generated token in the approved secret store. Do not commit it to the repository, write it
to the fixture manifest, or pass it as a command-line argument.

## 4. Configure secrets outside the command line

Set environment variables through the approved secret store. Required names:

```text
ROVO_MCP_URL=https://mcp.atlassian.com/v2/mcp
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

The Phase 0 runner rejects `/v1/sse`, `/v1/mcp/authv2`, query variants such as `?tools=all`, and any
other endpoint. `?tools=all` may be used only in a separate, explicitly reviewed diagnostic and must
not be placed in `.env.rovo` for this gate.

## 5. Preflight

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

## 6. Live read-only spike

### Read one page directly

For a development smoke test that prints one page's Markdown to stdout, no fixture manifest or
attestation files are required:

```bash
set -a
source .env.rovo
set +a

PYTHONPATH=src .venv/bin/python scripts/run_rovo_phase0.py \
  --read-url "https://ngvgs.atlassian.net/wiki/spaces/GA/pages/1471053840/Vendor_Alea" \
  --auth-mode personal
```

This mode still validates the v2 endpoint, required tools, allowed site, unique `cloudId`, canonical
URL, response content ID, Markdown envelope, and payload limits. It prints the page body to the
terminal, does not write evidence, and cannot count as a Phase 0 hard-gate pass.

### Run the full hard gate

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

Successful evidence must include:

```text
schema_version: 2
rovo_contract_version: v2
rovo_endpoint_path: /v2/mcp
```

## 7. Offline contract tests

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

The v1 tool `getConfluencePage`, v1 `pageId` arguments, or a v1 endpoint can never satisfy this gate.

Do not begin Phase 1 while the evidence is `pending` or `fail`.
