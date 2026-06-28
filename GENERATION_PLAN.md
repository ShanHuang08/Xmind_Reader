# New Vendor Test Case Generation Plan

This project prepares source knowledge for Codex and can now generate API parameter validation XMind test cases automatically.

Current implemented generation flow:

```text
new_vendor_detail/<Vendor>/
  -> output/<Vendor>/draft_test_cases.json
  -> output/<Vendor>/<Vendor>_test_cases.xmind
  -> output/<Vendor>/<Vendor>_test_cases_validation_report.json
```

The public CLI keeps generation as one command:

```bash
python main.py generate --vendor <Vendor>
```

`generate` builds the draft JSON, generates deterministic API parameter validation cases, writes the XMind file, and re-reads the generated XMind for validation.

## Step 1: Draft JSON For Codex

Implemented scope:

- Read `new_vendor_detail/<Vendor>/capability_profile.json`
- Read `new_vendor_detail/<Vendor>/endpoints.json`
- Read `new_vendor_detail/<Vendor>/error_codes.json`
- Read `new_vendor_detail/<Vendor>/vendor_master_checklist.json`
- Read `new_vendor_detail/<Vendor>/game_codes.json` when present, or extract game-code tables from `raw_doc.json`
- Build `output/<Vendor>/draft_test_cases.json`

The draft JSON is a working context file for Codex. It contains:

- vendor capability profile
- vendor master checklist
- endpoint roles
- request and response parameter tables
- request / success response / error response examples where available
- endpoint-specific generation notes
- fixed precondition and remarks rules
- pending user questions
- generated `test_cases` array after `generate` runs

The draft remains the strict intermediate contract. The generator writes structured cases into `test_cases`; the XMind writer consumes only validated draft cases.

## Important Authoring Rules

Preconditions should follow this pattern:

1. Use `launch game <gameCode>`.
2. Use `/game/url` for launch-game fixed cases.
3. Use the actual vendor endpoint for endpoint cases, such as `/api/v1/esoterica/result`.
4. Use the default test account generated from the vendor's first three English letters plus `YYMMDD`, such as `eso260628` for Esoterica on 2026-06-28, unless the user confirms another account.
5. Paste the request parameters needed by that URL or endpoint, preferring request examples extracted from the vendor doc.

Remarks should contain the response structure for the same URL or endpoint, preferring success/error response examples extracted from the vendor doc.

Launch-game fixed cases may have different preconditions and remarks from endpoint API cases.

## Capability-Driven Expected Results

Expected results must depend on resolved vendor capability:

- If `multiple_bets=true`, same-round multiple bet scenarios should expect both bets to succeed.
- If `multiple_bets=false`, the second bet should expect failure or rejection.
- If `multiple_settlements=true`, multiple result/settlement expected results must also check whether the settlement endpoint has a round-end control parameter, such as `roundCompleted`, `isEndRound`, `roundEnd`, `endRound`, or an equivalent field.
- If `multiple_settlements=true` and the settlement endpoint has a round-end control parameter, Codex should use that parameter to decide whether the current round is still open or already closed. This changes whether a later settlement in the same round should succeed, fail, or be treated as idempotent.
- If `multiple_settlements=true` but the settlement endpoint has no round-end control parameter, the flow is closer to debit/credit behavior: debit deducts money and credit adds money. The vendor may not have a strict round concept, so expected results should focus on transfer posting, balance change, idempotency key, and duplicate credit behavior instead of round closure.
- If `multiple_settlements=false`, repeated settlement should expect failure or no duplicate effect.
- If `rollback_settlements=true`, settled-bet rollback cases should be included.
- If `rollback_settlements=false`, settled-bet rollback API cases must expect failure because the vendor does not support rolling back settled bets.
- If `cancel_bet=true`, refund/cancel unsettled bet cases should be included.
- If `modify_settlements_adjustment=true`, adjustment cases should be included.
- Idempotency support affects transaction/reference duplicate scenarios.

Error code selection rules:

- Every generated expected result must include the expected vendor error code for failure cases.
- If the vendor provides complete and specific error codes, Codex should use the documented code directly and should not infer a different code.
- If the vendor provides only a small or incomplete error code list, Codex must infer the most likely error code from the available list instead of leaving the expected result blank.
- Inferred error codes must be marked as inferred in the draft JSON, for example `error_code_source: "inferred_from_limited_vendor_codes"`.
- If several error codes could apply, choose the closest documented code and add a short `unresolved_questions` note for user/vendor confirmation.
- For vendors like EGT Digital, where endpoint error code choices are limited, Codex should still pick the most suitable documented code for the negative scenario. For example, if a settlement after `roundCompleted=true` is rejected but the exact error is not documented, choose the closest non-OK status from that endpoint's documented status codes and mark it as inferred.

## Endpoint Role Notes

Each endpoint must have a role before generation.

Example for Esoterica:

- `/api/v1/esoterica/bet`: bet
- `/api/v1/esoterica/result`: settlement
- `/api/v1/esoterica/refund`: cancel bet
- `/api/v1/esoterica/endRound`: balance confirmation only

`endRound` should not be used to close rounds in API integration test cases when the integration closes rounds through settlement/result.

## Test Case Map Category Standard

Future `test_case_map.xmind` files should be organized by test category and vendor capability, not by endpoint folders.

Endpoint data is still important, but it should be used as supporting context only:

- endpoint role
- request parameters
- response parameters
- parameter type differences
- endpoint-specific notes

The main purpose of the XMind knowledge base is to help Codex load the right reference cases for special vendor behavior. The better the XMind map is categorized, the more tokens can be saved during new vendor generation.

Recommended top-level categories:

1. `parameter_validation`
2. `user_behavior`

### parameter_validation

Scope:

- All supported endpoints
- Required field validation
- Missing field validation
- Invalid type validation
- Empty/null value validation
- Boundary value validation
- Error handling by endpoint

This category can still reference endpoint parameter types, such as `String`, `int`, `long`, `BigDecimal`, and amount precision rules.

### user_behavior

This category contains business-flow and vendor-capability cases.

Mandatory test cases:

- `launch_game`
- `balance`
- `bet`
- `settlement`
- `rollback`
- `amount_precision`

Capability-specific categories:

- `multiple_bets`
- `multiple_settlements`
- `modify_settlement_adjustment`
- `settle_by_round_or_settle_by_bet`
- `rollback_bet`
- `rollback_settled_bet`
- `rollback_by_round_or_rollback_by_bet`
- `bet_and_settle`
- `rollback_bet_and_settle`
- `idempotency`
- `freespin`
- `jackpot`

Codex should select category chunks based on `capability_profile.json` and `draft_test_cases.json`.

Examples:

- If `multiple_bets=true`, load `user_behavior/multiple_bets` reference cases.
- If `multiple_settlements=true`, load `user_behavior/multiple_settlements` reference cases.
- If `rollback_settlements=true`, load `user_behavior/rollback_settled_bet` reference cases.
- If adjustment is supported, load `user_behavior/modify_settlement_adjustment` reference cases.
- For all vendors, always load mandatory cases: launch game, balance, bet, settlement, rollback, and amount precision.

The generator should not decide reference cases by endpoint name alone. Endpoint names vary by vendor, while categories describe reusable test intent.

## Generated XMind Output Structure

The knowledge base can be category-based, but the generated XMind should still use the fixed QA-facing structure.

Current generated XMind structure:

```text
功能用例
  Regression
    Vendor_integration
      <Vendor>
        API parameter test
          <endpoint name>
            case：check the <parameter> validation

        User Behavior
          Launch Game
            launch URL and authenticate-related cases

          Get Player balance
            balance endpoint cases

          Bet and Settle
            bet
            settlement
            betAndSettle
            amount precision
            multiple bets
            multiple settlements
            freespin settlement
            jackpot settlement
            settlement idempotency

          Cancel Bet
            rollback
            rollback bet
            rollback settled bet
            rollback betAndSettle

          Game type
            Slots
            Arcade game
            Mini game
            Crash game
```

This means generation needs two different classifications:

- `category`: how Codex selects reference knowledge
- `output_section`: where the final test case should be placed in the generated XMind

Generated case routing fields:

```json
{
  "category": "multiple_bets",
  "output_section": "User Behavior > Bet and Settle",
  "endpoint_group": "bet",
  "endpoint": "/api/v1/vendor/bet",
  "endpoint_name": "bet",
  "endpoints": ["/api/v1/vendor/bet"],
  "parameter": "amount"
}
```

Category to generated XMind section mapping:

| Knowledge category | Generated XMind section |
|---|---|
| `parameter_validation` | `API parameter test` |
| `launch_game` | `User Behavior > Launch Game` |
| `authenticate` | `User Behavior > Launch Game` |
| `balance` | `User Behavior > Get Player balance` |
| `bet` | `User Behavior > Bet and Settle` |
| `settlement` | `User Behavior > Bet and Settle` |
| `amount_precision` | `User Behavior > Bet and Settle` |
| `multiple_bets` | `User Behavior > Bet and Settle` |
| `multiple_settlements` | `User Behavior > Bet and Settle` |
| `modify_settlement_adjustment` | `User Behavior > Bet and Settle` |
| `settle_by_round_or_settle_by_bet` | `User Behavior > Bet and Settle` |
| `bet_and_settle` / `betandsettle` | `User Behavior > Bet and Settle` |
| `idempotency` | `User Behavior > Bet and Settle` |
| `rollback` | `User Behavior > Cancel Bet` |
| `rollback_bet` | `User Behavior > Cancel Bet` |
| `rollback_settled_bet` | `User Behavior > Cancel Bet` |
| `rollback_by_round_or_rollback_by_bet` | `User Behavior > Cancel Bet` |
| `rollback_bet_and_settle` / `rollback_betandsettle` | `User Behavior > Cancel Bet` |
| `freespin` | `User Behavior > Bet and Settle` |
| `jackpot` | `User Behavior > Bet and Settle` |
| `slots` | `User Behavior > Game type > Slots` |
| `arcade_game` | `User Behavior > Game type > Arcade game` |
| `mini_game` | `User Behavior > Game type > Mini game` |
| `crash_game` | `User Behavior > Game type > Crash game` |

This mapping should also be written into `draft_test_cases.json` as `generation_mapping`, so Codex can read it before generating any cases.

## Step 2: Test Case Generator

Implemented for API parameter validation.

Current implemented scope:

- `python main.py generate --vendor <Vendor>` builds the draft and writes generated cases back into `test_cases`.
- API parameter validation is deterministic and generated from `endpoint_roles[].request_parameters`.
- Generated API parameter cases are routed to `API parameter test > <endpoint_name>`.
- Each parameter case uses the scenario format `case：check the <parameter> validation`.
- Preconditions prefer `endpoint.request_example`; otherwise the generator derives normal values from parameter name, type, and description.
- Remarks prefer `endpoint.success_response_example` and `endpoint.error_response_example`.
- Step expected results include a parameter validation error message and an error response JSON block.
- User Behavior generation is still pending and should be driven by scenario templates/reference cases.

The generator should let Codex read:

- `output/<Vendor>/draft_test_cases.json`
- selected `xmind_detail/<KnowledgeVendor or test_case_map>/modules/*.json`
- selected `xmind_detail/<KnowledgeVendor or test_case_map>/tags/*.json`
- selected category-based Markdown/JSON knowledge files
- supplementary PDF files only when DOC/HTML details are insufficient:
  - `new_vendor_detail/<Vendor>/vendor_pdf/manifest.json`
  - `new_vendor_detail/<Vendor>/vendor_pdf/endpoint_index.json`
  - selected `new_vendor_detail/<Vendor>/vendor_pdf/sections/*.json`

Codex/generator should then write generated cases back into the draft JSON under `test_cases`.

Recommended generated case fields:

- id
- module
- category
- scenario
- source_capability
- reference_cases
- endpoint
- preconditions
- steps
- expected_results
- tags
- remarks
- priority
- unresolved_questions

The generator should not write XMind directly.

## User Behavior Test Case Generation

This section documents what is needed to move from the current parameter-validation-only generator to full User Behavior test case generation.

### Current State: Implemented vs Pending

| Item | Parameter Validation (Implemented) | User Behavior (Pending) |
|---|---|---|
| Source data | `endpoint_roles[].request_parameters` | `xmind_detail` reference cases + `capability_profile` + `endpoints` |
| Generation method | Fully deterministic (each param → doesn't set / blank / wrong value) | Needs **template + substitution** from reference cases |
| Case structure | Single endpoint, single parameter, pure negative | **Multi-step business flow** (bet → settle → check history) |
| Expected result | Fixed error code template | **Capability-dependent** (e.g. `multiple_bets=true` → both bets succeed) |
| Error code selection | One generic parameter error code | **Per-scenario error codes** (insufficient balance, duplicate request, etc.) |

### 6 Missing Requirements

#### Requirement 1: Scenario Templates (XMind-driven)

Instead of hardcoding scenario templates in Python, use a **manually maintained Scenario Templates XMind file** as the single source of truth.

**Workflow:**

```text
Manually write scenario_templates.xmind (category-driven, capability-aware)
    ↓  (xmind_reader pipeline - already implemented)
Decompose into JSON chunks + Markdown
    ↓  (stored in xmind_detail/scenario_templates/)
Generator reads chunks + capability_profile.supports
    ↓
Select mandatory cases + capability-specific cases
    ↓
Substitute new vendor's endpoint, gameCode, amount, etc.
    ↓
Write into draft_test_cases.json
```

**XMind structure design:**

```text
Scenario Templates
├── Mandatory                              ← always generated, regardless of capabilities
│   ├── Launch Game
│   │   ├── case：successful launch game
│   │   ├── case：wrong gameCode
│   │   └── case：unsupported currency
│   ├── Balance
│   │   └── case：check player balance
│   ├── Bet
│   │   ├── case：normal bet (win)
│   │   ├── case：normal bet (lose)
│   │   └── case：insufficient balance
│   ├── Settlement
│   │   └── ...
│   ├── Rollback
│   │   └── ...
│   └── Amount Precision
│       └── ...
├── Capability: multiple_bets              ← only selected when supports.multiple_bets=true
│   ├── case：two bets same round both succeed
│   └── case：two bets same round second rejected
├── Capability: multiple_settlements
│   └── ...
├── Capability: rollback_settlements
│   └── case：rollback settled bet
├── Capability: cancel_bet
│   └── case：cancel unsettled bet
├── Capability: bet_and_settle
│   └── case：full bet+settle flow
├── Capability: modify_settlements_adjustment
│   └── ...
├── Capability: free_spin
│   └── ...
├── Capability: jackpot
│   └── ...
```

**Output folder (already created, empty, waiting for XMind):**

```text
xmind_detail/scenario_templates/
  markdown/         ← decomposed markdown per module
  modules/          ← decomposed JSON chunks per module
  raw/              ← raw extraction output
  source_meta/      ← source metadata
  summary/          ← extraction report and summary
  tags/             ← tag-based JSON chunks
```

**Generator-side selection logic (to implement in a new `template_loader.py` or extend `reference_selector.py`):**

1. Read `xmind_detail/scenario_templates/modules/*.json`
2. Filter: all cases under `Mandatory` are always selected; cases under `Capability: xxx` are selected only when `capability_profile.supports[xxx] == true`
3. For each selected case, substitute placeholders with the new vendor's `endpoint_roles`, `game_codes`, `error_codes` values
4. Expected results are derived by logical inference from capability profile + error code mapping

**Benefits over hardcoding:**

- QA can edit templates directly in XMind without touching Python code
- Reuses the existing xmind_reader pipeline (no new parsing code)
- Mandatory vs capability-specific is expressed naturally through XMind hierarchy
- Adding a new category (e.g. `crash_game`) only requires adding XMind nodes
- Requirement 2 (Reference Case Loader) is naturally solved because templates are already abstracted reference cases

#### Requirement 2: Reference Case Loader

`reference_selector.py` currently does **filename matching only** (stem contains category term) and returns file paths. Missing:

- **Read** the selected JSON chunk content (`modules/*.json`, `tags/*.json`)
- **Abstract**: replace vendor-specific values (gameCode, endpoint, transactionId, amount) with placeholders
- **Deduplicate**: same category may have multiple vendor reference cases; select the most representative canonical cases (filter out `duplicate_of` entries)

For example, `bet_and_settle.json` contains 39 cases, but many are `duplicate_of` duplicates — only the canonical ones should be used as templates.

#### Requirement 3: Capability-Driven Error Code Selection

`case_generation_context.py` currently only extracts `parameter_error`. Business-logic error selection is missing:

```python
# Currently only this exists
"parameter_error": _select_parameter_error(error_codes)

# Still needed
"bet_not_allowed_error": _select_error(error_codes, "bet not allowed")
"insufficient_balance_error": _select_error(error_codes, "insufficient")
"duplicate_request_error": _select_error(error_codes, "duplicate")
"player_not_found_error": _select_error(error_codes, "player not found")
"game_not_found_error": _select_error(error_codes, "game not found")
```

Additionally, `GENERATION_PLAN.md` explicitly requires: expected results must depend on `capability_profile.supports` (e.g. `multiple_bets=true` → second bet succeeds, `false` → second bet fails).

#### Requirement 4: Multi-Step Flow Builder

Parameter validation steps are flat:

```text
step: "userId doesn't set\n//userId=xxx"
expected: "Error code is 7"
```

User Behavior requires **multi-step flows**, e.g. bet_and_settle:

```text
steps: [
  "the player betAmount 50",           # bet endpoint
  "Settle the bet, winAmount 100",     # settlement endpoint
  "check in Game Bet History",         # DB check
  "Check vendor requestBody of bet",   # API log check
  "Check vendor responseBody of bet",
  ...
]
```

This requires knowing:

- Which endpoints participate in the flow (resolved from `endpoint_roles` by role)
- How to compose request payloads for each endpoint
- Data flow between steps (bet `transactionId` → settlement `transactionId`)

#### Requirement 5: Category → Endpoint Reverse Mapping

`ENDPOINT_ROLE_RULES` maps `endpoint path → role`. User Behavior generation needs the **reverse**:

- `launch_game` category → needs `/game/url` (not in endpoint list; it is a front-end URL)
- `balance` category → find role=`balance_check` or role=`authentication` (authenticate also returns balance)
- `bet` category → find role=`bet` endpoint
- `settlement` category → find role=`settlement` or role=`combined_bet_settlement` endpoint
- `rollback` category → find role=`cancel_bet` or role=`rollback` endpoint
- `bet_and_settle` → needs bet endpoint + settlement endpoint together

This reverse lookup logic does not exist yet.

#### Requirement 6: Draft Validator Extension for User Behavior

`draft_validator.py` currently enforces strict scenario format for API parameter test (`"case：check the {parameter} validation"`), but User Behavior scenario formats are undefined:

- What should a launch_game scenario look like?
- What should a bet_and_settle scenario look like?
- How to validate step/expected correspondence in multi-step cases?

### Implementation Path

Recommended order:

```text
Requirement 1: Scenario Templates XMind (manually write, then decompose via xmind_reader)
    ↓
Requirement 5: Category → Endpoint reverse mapping (find the correct endpoints)
    ↓
Requirement 3: Capability-Driven Error Selection (decide success/failure + error codes by capability)
    ↓
Requirement 4: Multi-Step Flow Builder (compose endpoint payloads into multi-step flows)
    ↓
Requirement 6: Validator extension (add User Behavior validation rules)
```

Note: Requirement 2 (Reference Case Loader) is naturally resolved by Requirement 1 — the scenario templates XMind, once decomposed, already serves as the abstracted reference cases.

**Blocking dependency:** Python code changes (template_loader.py, reverse mapping, error selection, flow builder, validator) must wait until the scenario templates XMind is complete and decomposed into `xmind_detail/scenario_templates/`. No Python code should be written before the XMind template is ready.

## Supplementary PDF / URL Readers

PDF Reader and URL Reader are secondary reference sources for vendor API details. They must not replace DOC/HTML reader output as the main source for generation.

Some vendors provide API documents as PDFs, while others provide web URLs. Both readers should normalize their output into the same Codex-friendly retrieval pattern so Codex can read only the relevant endpoint sections instead of loading the whole document.

PDF Reader output:

```text
new_vendor_detail/<Vendor>/vendor_pdf/
  manifest.json
  validation_report.json
  endpoint_index.json
  sections/
    <api_section>.json
  full_text.md
```

URL Reader output:

```text
new_vendor_detail/<Vendor>/vendor_url/
  manifest.json
  validation_report.json
  endpoint_index.json
  sections/
    <api_section>.json
  full_text.md
```

Reader rules:

- Use `pymupdf4llm` to convert readable PDFs into Markdown.
- Validate the PDF before extraction.
- If the PDF is image-based or scanned, generate `validation_report.json` and `manifest.json` only.
- OCR is out of scope.
- Do not generate page-level JSON files such as `page_001.json`.
- Split content by API endpoint/section, not by page.
- `full_text.md` is for debugging or fallback only.
- Detect wallet-style endpoints such as `{baseUri}/withdraw`, `{baseUri}/reverse/withdraw`, and `{baseUri}/deposit`, not only `/api/...` URLs.

URL Reader rules:

- Support API documentation URLs as supplementary sources.
- Support HTTP Basic Auth through CLI arguments.
- Prefer static HTML extraction first.
- Convert HTML into Markdown before endpoint indexing.
- Detect OpenAPI/Swagger JSON URLs and convert them directly into endpoint Markdown.
- Store source URL, final URL, content type, and content hash in `manifest.json` / `validation_report.json`.
- Use the same endpoint role aliases and section chunking behavior as PDF Reader.
- `full_text.md` is for debugging or fallback only.

Wallet endpoint role aliases:

| PDF endpoint | Generation role |
|---|---|
| `{baseUri}/balance` | `balance` |
| `{baseUri}/debit` or `debit` keyword | `bet` |
| `{baseUri}/withdraw` | `bet` |
| `{baseUri}/credit` or `credit` keyword | `settlement` |
| `{baseUri}/reverse/withdraw` | `rollback` |
| `{baseUri}/deposit` | `settlement` |

Codex reading order for PDF/URL details:

1. Read `manifest.json`.
2. Read `endpoint_index.json`.
3. Select only relevant files under `sections/`.
4. Read `full_text.md` only when section chunks are insufficient.

The main Codex reading order remains:

1. `output/<Vendor>/draft_test_cases.json`
2. `new_vendor_detail/<Vendor>/capability_profile.json`
3. `new_vendor_detail/<Vendor>/endpoints.json`
4. `new_vendor_detail/<Vendor>/error_codes.json`
5. `new_vendor_detail/<Vendor>/api_summary.md` only when necessary
6. PDF/URL supplementary index/sections only when DOC/HTML output is not enough

## Step 3: XMind Writer

Implemented for generated draft cases.

Once `draft_test_cases.json` is generated and validated, the Python XMind writer converts it into:

```text
output/<Vendor>/<Vendor>_test_cases.xmind
```

MeterSphere compatibility must be treated as a hard requirement.

Current implemented scope:

- Writes XMind archives with `content.json`, `metadata.json`, and `manifest.json`.
- Uses metadata format compatible with the Xmind desktop app (`creator` is an object with `name` and `version`).
- Uses the fixed root path `功能用例 > Regression > Vendor_integration > <Vendor>`.
- Places API parameter cases under `API parameter test > <endpoint_name>`.
- Re-reads generated XMind files with this project's XMind reader.
- Writes `<Vendor>_test_cases_validation_report.json`.

Known importable XMind references:

- `input_xmind/metersphere_xmind_example.xmind`
- `input_xmind/EGTDigital_test_cases.xmind`
- `input_xmind/Vibra_Gaming_test_case.xmind`

All three files are known to import into MeterSphere successfully.

Writer format priority:

1. Follow `EGTDigital_test_cases.xmind` and `Vibra_Gaming_test_case.xmind` as the main production-style output references.
2. Use `metersphere_xmind_example.xmind` as the official MeterSphere template reference.
3. Do not invent a new XMind structure unless MeterSphere compatibility has been validated again.

The writer should preserve the same structure expected by the existing XMind reader:

- case topic
- ID
- preconditions
- module
- labels
- remarks
- priority
- steps
- expected results

Generated XMind validation should include:

- Re-read the generated XMind with this project's XMind reader.
- Compare generated case count with `draft_test_cases.json`.
- Verify case ID, scenario, preconditions, remarks, steps, and expected results are not lost.
- Verify hierarchy matches the fixed QA-facing output structure.
- Compare topic/field style against the known MeterSphere-importable reference files.
- Produce a validation report before the file is treated as ready for MeterSphere import.

### MeterSphere Format Knowledge

Before implementing the XMind writer, the project should extract and preserve MeterSphere-compatible format knowledge from the known importable XMind files.

Recommended output:

```text
xmind_detail/_metersphere_profile/
  metersphere_schema_profile.json
```

The profile should describe:

- supported sheet/root topic structure
- fixed QA-facing hierarchy
- case topic naming style
- where preconditions are stored
- where remarks are stored
- how steps and expected results are paired
- how labels, markers, and priority are represented
- maximum useful hierarchy depth
- example topic paths from the golden reference files

Purpose:

- The XMind writer should follow this profile instead of guessing MeterSphere's import format.
- The validator should compare generated files against this profile.
- If MeterSphere import behavior changes later, update the profile/validator rules before changing generation logic.

### Draft Schema Constraints

`draft_test_cases.json` is the strict input contract for the XMind writer.

Each generated test case should use structured fields, not only free text:

```json
{
  "id": "TC_001",
  "output_section": "User Behavior > Bet and Settle",
  "module": "Bet and Settle",
  "category": "multiple_bets",
  "scenario": "Place two bets in the same round",
  "preconditions": "前置条件：\n...",
  "steps": [
    {
      "step": "Call bet endpoint with transactionId A.",
      "expected": "Return success."
    }
  ],
  "remarks": "备注：\n...",
  "expected_error": {
    "code": "ERR_xxx",
    "source": "documented"
  },
  "source_reference": {
    "vendor_doc": [],
    "xmind_reference_cases": []
  },
  "unresolved_questions": []
}
```

Draft validation rules:

- `id` is optional before MeterSphere upload. If present, it must be unique.
- `output_section` must match the generated XMind mapping table.
- `scenario` must not be empty.
- `preconditions` must be present and keep the `前置条件：` label.
- `remarks` must be present and keep the `备注：` label.
- `steps` must not be empty.
- Each step must have a paired expected result.
- Failure/negative cases must include an expected error code.
- Inferred error codes must include their inference source.
- `source_reference` should preserve which vendor doc and XMind cases were used.
- Cases with unresolved questions should not be marked as final unless the uncertainty is intentionally accepted.

## Recommended Operating Modes

Run Mode:

- Execute existing readers, draft builder, generator, XMind writer, and validator.
- Read generated JSON/Markdown only when review or debugging is needed.
- Produce or update `draft_test_cases.json`, `<Vendor>_test_cases.xmind`, and the validation report.
- Do not change Python code unless the current vendor exposes a parsing, mapping, validation, or export defect.

Improve Mode:

- Modify Python code only when parsing, mapping, validation, or export behavior is wrong.
- Re-run readers to regenerate intermediate files.
- Re-run `python main.py generate --vendor <Vendor>` and confirm the XMind validator report is valid.
