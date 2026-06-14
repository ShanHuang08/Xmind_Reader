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

## Step 2: Test Case Generator

Future direction, not implemented yet.

The generator should let Codex read:

- `output/<Vendor>/draft_test_cases.json`
- selected `xmind_detail/<Vendor or capability knowledge>/modules/*.json`
- selected `xmind_detail/<Vendor or capability knowledge>/tags/*.json`

Codex should then write generated cases back into the draft JSON under `test_cases`.

Recommended generated case fields:

- id
- module
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
