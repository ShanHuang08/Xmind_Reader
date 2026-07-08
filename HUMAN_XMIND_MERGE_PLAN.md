# Human Edited XMind Merge Plan

## Current Status

This document describes the currently adopted merge flow for preserving human edits in generated vendor XMind test cases.

The project now uses the previously debated visible-key approach as the practical production approach:

- Generated cases have deterministic `stable_case_id` values.
- The XMind writer writes those IDs into visible child topics named `merge_key:<stable_case_id>`.
- The XMind parser reads `merge_key:<stable_case_id>` back and treats it as the case identity.
- Human-edited XMind copies can then be merged back into newly generated drafts.

This is intentionally not hidden metadata. XMind does not reliably preserve hidden metadata across manual editing, copy, and save workflows. A visible `merge_key` topic is less pretty, but it survives normal XMind editing and gives the merge process a stable anchor.

For customer-facing or reviewer-facing delivery, a separate no-key XMind can be produced by removing `merge_key:` topics after generation. That no-key file is a delivery artifact only. It should not be used as the next round's human merge source unless we accept weaker title/path fallback matching.

## Goal

The generator should be able to refresh test cases from updated vendor docs while preserving useful human QA edits from an existing XMind copy.

The intended priority is:

```text
human-edited copy > User_Behavior_map templates > generated vendor doc/PDF/URL content
```

The human copy is treated as the reviewer's intent for case title and steps. The generator still owns technical fields that should follow the latest vendor document, such as endpoint examples, request/response remarks, parameter metadata, output section, category, and expected error.

## Main Flow

CLI:

```bash
python main.py generate --vendor <Vendor> --human-xmind input_xmind/<Vendor>_test_cases_copy.xmind
```

Pipeline:

```text
build_draft
  -> generate_test_cases_file
  -> ensure_stable_case_ids
  -> merge_human_xmind_edits
  -> write_xmind_from_draft
  -> validate_generated_xmind
  -> write summary and manifest
```

Outputs:

```text
output/<Vendor>/
  draft_test_cases.json
  <Vendor>_test_cases.xmind
  <Vendor>_test_cases_validation_report.json
  <Vendor>_test_cases_summary.md
  <Vendor>_human_merge_report.md
  <Vendor>_human_merge_manifest.json
```

## Stable Case Identity

Every generated or merged case should have a stable identity.

ID rules:

- API parameter cases:
  `param::<normalized endpoint>::<normalized parameter>`
- User Behavior cases with a source case id:
  `ub::<category>::<source_case_id>`
- User Behavior cases without a source case id:
  `ub::<category>::source_<hash(source_path|category|scenario)>`
- Human-added cases:
  `human::<normalized output section/module>::<hash(module|scenario)>`
- Duplicate human cases with the same visible ID but a different title:
  regenerate as `human::<module>::<hash(original_id|module|scenario)>`

Writer behavior:

```text
stable_case_id
  -> visible topic: merge_key:<stable_case_id>
```

Parser behavior:

```text
visible merge_key:<stable_case_id>
  -> source_case.stable_case_id
```

The visible `merge_key` is the main matching key for future merges. It is acceptable in working XMind files. If a no-key XMind is required, generate it as a separate final artifact after validation.

## Merge Matching

Current matching is intentionally conservative:

1. Match base case to human case by `stable_case_id`.
2. Human cases with no valid ID are treated as human-added cases.
3. Duplicate human IDs:
   - Same ID and same title: skip duplicate and report it.
   - Same ID but different title: regenerate a `human::...` ID and keep it as a separate human-added case.

Planned low-cost improvement:

- Preserve human copy ordering after merge.
- Use the human copy order as the primary sort order for all matched cases.
- Append generator-new cases after the relevant section or at the end.
- Support both `stable_case_id` and `module path + title` as ordering anchors.

This ordering improvement is useful because human-added or changed cases can otherwise drift toward the bottom of the output XMind.

## What Human Edits Override

When a generated base case matches a human copy case, only these fields are overlaid from the human copy:

```text
scenario
steps
```

The entire steps list is replaced when it differs. The merge does not do step-level patching.

Fields that remain owned by the generator:

```text
preconditions
remarks
priority
tags
module
output_section
endpoint
endpoint_name
parameter
category
expected_error
source_reference
unresolved_questions
```

Reason:

- QA typically edits title and test steps.
- Preconditions and remarks should track the latest vendor endpoint and request/response examples.
- This avoids keeping stale API remarks from an older XMind copy.

## Step Merge Rule

Steps are compared by normalized `step` and `expected` text.

If the human copy has a non-empty steps list and it differs from the generated base steps, the human copy's full steps list replaces the base list.

If the human copy has an empty steps list but the generated base has steps, the base steps are kept and the merge report records a `human_steps_empty` warning.

Pseudo-code:

```python
def comparable_step(step):
    return {
        "step": normalize(step.get("step", "")),
        "expected": normalize(step.get("expected", "")),
    }


def steps_changed(base_steps, human_steps):
    if len(base_steps) != len(human_steps):
        return True
    for base_step, human_step in zip(base_steps, human_steps):
        if comparable_step(base_step) != comparable_step(human_step):
            return True
    return False
```

## Human-Added Cases

Human cases that do not match a generated base case are kept as `human_added`.

They receive metadata like:

```json
{
  "category": "human_added",
  "source_reference": {
    "generated_by": "human-xmind-overlay/v1",
    "source_xmind": "<human xmind path>",
    "merge_action": "added_from_human_copy"
  }
}
```

Human-added case IDs are deterministic:

```text
human::<normalized module/output section>::<title hash>
```

## Remarks Normalization

A bug was found in CasinoGate where non-launch User Behavior cases could inherit launch-game API request remarks.

Current fix:

- Endpoint role inference recognizes CasinoGate-style routes:
  - `/bet/place` -> `bet`
  - `/bet/win` -> `settlement`
  - `/bet/refund` -> `cancel_bet`
  - `/wallet` -> `balance_check`
- Non-launch cases no longer fall back to launch-game remarks when no endpoint is found.
- Human-added non-launch cases that already contain launch-game payload markers (`gameCode`, `lobbyUrl`, `ipAddress`) are normalized to target endpoint remarks when possible.

This means comparison reports may show many `Remarks` changes after the fix. That is expected and usually means stale launch payloads were replaced with the correct endpoint request examples.

## Human Deletion Semantics

The merge manifest records the previous final case keys:

```text
output/<Vendor>/<Vendor>_human_merge_manifest.json
```

Manifest shape:

```json
{
  "vendor": "<Vendor>",
  "generated_at": "...",
  "final_case_keys": ["..."],
  "case_index": {
    "ub::bet::tc_0017": {
      "scenario": "case: Place Bet twice using same transactionId",
      "output_section": "User Behavior > Bet and Settle",
      "module": "Bet and Settle"
    }
  }
}
```

Deletion rule:

- If a base case existed in the previous manifest but is missing from the current human copy, it is treated as deleted by human and excluded from final output.
- If a base case is new and did not exist in the previous manifest, it is kept and reported as `new_from_base`.
- If no previous manifest exists, base-only cases are kept and report includes `manifest_missing`.

## Merge Report

The merge report is written to:

```text
output/<Vendor>/<Vendor>_human_merge_report.md
```

It includes:

- base case count
- human copy case count
- overridden count
- added-from-human count
- deleted-by-human count
- new-from-base count
- base-only-without-manifest count
- regenerated human IDs
- duplicate same-title skips
- warnings
- conflicts

Example:

```markdown
# CasinoGate Human XMind Merge Report

Status: success

## Summary

| Item | Count |
|---|---:|
| Base cases | 117 |
| Human copy cases | 117 |
| Overridden by human | 97 |
| Added from human | 16 |
| Deleted by human | 15 |
| New from base | 1 |
| Base-only kept because manifest missing | 0 |
| Regenerated human IDs | 0 |
| Duplicate same title skipped | 0 |
| Warnings | 0 |
| Conflicts | 0 |
```

## No-Key Delivery XMind

Working XMind files should keep `merge_key:` topics because they are the robust merge anchors.

When a clean delivery file is required, produce a copy such as:

```text
output/<Vendor>/<Vendor>_test_cases_no_merge_key.xmind
```

Rules:

- Remove visible `merge_key:` topics from the copied XMind.
- Keep the original keyed XMind as the working artifact.
- Do not use the no-key file as the next `--human-xmind` source unless weaker fallback matching is acceptable.

## Validation

After generation:

```text
validate_generated_xmind(<Vendor>_test_cases.xmind, draft_test_cases.json)
```

Expected checks:

- parsed case count equals draft case count
- generated XMind is readable
- parser can extract steps, remarks, preconditions, priority, and stable IDs
- no unexpected validation errors

For no-key delivery copies, validate readability and confirm there are no `merge_key:` strings in `content.json` or `content.xml`.

## Current Known Tradeoffs

- Visible `merge_key:` topics are not pretty, but they are reliable for human edit round-trips.
- No-key delivery files are cleaner, but weaker as merge sources.
- Current merge only overlays `scenario` and `steps`; it intentionally does not overlay remarks.
- Human copy order preservation is not fully implemented yet and should be the next low-cost improvement.
- Step-level merge is intentionally deferred; full step-list replacement is simpler and easier to reason about.

## Recommended Next Improvements

1. Preserve human copy ordering in final XMind.
2. Add a formal CLI option for no-key export, for example `--hide-merge-key` or `--export-no-merge-key-copy`.
3. Add regression tests for CasinoGate endpoint role inference and remarks normalization.
4. Add comparison report fields that clearly distinguish content changes caused by intentional remarks normalization.
