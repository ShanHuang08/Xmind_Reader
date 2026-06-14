# New Vendor Test Case Generation Plan

This project currently prepares source knowledge for Codex. It does not yet generate final new vendor XMind test cases automatically.

## Step 1: Draft JSON For Codex

Implemented scope:

- Read `new_vendor_detail/<Vendor>/capability_profile.json`
- Read `new_vendor_detail/<Vendor>/endpoints.json`
- Read `new_vendor_detail/<Vendor>/error_codes.json`
- Read `new_vendor_detail/<Vendor>/vendor_master_checklist.json`
- Build `output/<Vendor>/draft_test_cases.json`

The draft JSON is a working context file for Codex. It contains:

- vendor capability profile
- vendor master checklist
- endpoint roles
- request and response parameter tables
- endpoint-specific generation notes
- fixed precondition and remarks rules
- pending user questions
- empty `test_cases` array

No generated test cases are created in Step 1.

## Important Authoring Rules

Preconditions should follow this pattern:

1. Launch this vendor's gameCode.
2. Use `/game/url` for launch-game fixed cases.
3. Use the actual vendor endpoint for endpoint cases, such as `/api/v1/esoterica/result`.
4. Use `egt260514` as the default test account unless the user confirms another account.
5. Paste the request parameters needed by that URL or endpoint.

Remarks should contain the response structure for the same URL or endpoint.

Launch-game fixed cases may have different preconditions and remarks from endpoint API cases.

## Capability-Driven Expected Results

Expected results must depend on resolved vendor capability:

- If `multiple_bets=true`, same-round multiple bet scenarios should expect both bets to succeed.
- If `multiple_bets=false`, the second bet should expect failure or rejection.
- If `multiple_settlements=true`, multiple result/settlement cases can expect repeated settlement success.
- If `multiple_settlements=false`, repeated settlement should expect failure or no duplicate effect.
- If `rollback_settlements=true`, settled-bet rollback cases should be included.
- If `rollback_settlements=false`, settled-bet rollback cases should be skipped or expected to fail.
- If `cancel_bet=true`, refund/cancel unsettled bet cases should be included.
- If `modify_settlements_adjustment=true`, adjustment cases should be included.
- Idempotency support affects transaction/reference duplicate scenarios.

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
API parameter test
  <endpoint>
    <parameter>

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

Recommended generated case routing fields:

```json
{
  "category": "multiple_bets",
  "output_section": "User Behavior > Bet and Settle",
  "endpoint_group": "bet",
  "endpoints": ["/api/v1/vendor/bet"]
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

Future direction, not implemented yet.

The generator should let Codex read:

- `output/<Vendor>/draft_test_cases.json`
- selected `xmind_detail/<KnowledgeVendor or test_case_map>/modules/*.json`
- selected `xmind_detail/<KnowledgeVendor or test_case_map>/tags/*.json`
- selected category-based Markdown/JSON knowledge files
- supplementary PDF files only when DOC/HTML details are insufficient:
  - `new_vendor_detail/<Vendor>/vendor_pdf/manifest.json`
  - `new_vendor_detail/<Vendor>/vendor_pdf/endpoint_index.json`
  - selected `new_vendor_detail/<Vendor>/vendor_pdf/sections/*.json`

Codex should then write generated cases back into the draft JSON under `test_cases`.

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

## Supplementary PDF Reader

PDF Reader is a secondary reference source for vendor API details. It must not replace DOC/HTML reader output as the main source for generation.

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

Reader rules:

- Use `pymupdf4llm` to convert readable PDFs into Markdown.
- Validate the PDF before extraction.
- If the PDF is image-based or scanned, generate `validation_report.json` and `manifest.json` only.
- OCR is out of scope.
- Do not generate page-level JSON files such as `page_001.json`.
- Split content by API endpoint/section, not by page.
- `full_text.md` is for debugging or fallback only.
- Detect wallet-style endpoints such as `{baseUri}/withdraw`, `{baseUri}/reverse/withdraw`, and `{baseUri}/deposit`, not only `/api/...` URLs.

Wallet endpoint role aliases:

| PDF endpoint | Generation role |
|---|---|
| `{baseUri}/balance` | `balance` |
| `{baseUri}/debit` or `debit` keyword | `bet` |
| `{baseUri}/withdraw` | `bet` |
| `{baseUri}/credit` or `credit` keyword | `settlement` |
| `{baseUri}/reverse/withdraw` | `rollback` |
| `{baseUri}/deposit` | `settlement` |

Codex reading order for PDF details:

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
6. PDF supplementary index/sections only when DOC/HTML output is not enough

## Step 3: XMind Writer

Future direction, not implemented yet.

Once `draft_test_cases.json` is reviewed and validated, a Python XMind writer can convert it into:

```text
output/<Vendor>/<Vendor>_test_cases.xmind
```

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

## Recommended Operating Modes

Run Mode:

- Do not modify Python code.
- Execute existing readers and builders.
- Read generated JSON/Markdown.
- Produce or update draft JSON.

Improve Mode:

- Modify Python code only when parsing, mapping, validation, or export behavior is wrong.
- Re-run readers to regenerate intermediate files.
