# Human Edited XMind Merge Plan

## 目標

目前 AI 會依據 doc / PDF / URL / `User_Behavior_map` 重新產生 XMind，但人工在產出 XMind 上做的小幅調整會在下次更新時被覆蓋。

目標是新增一個自動合併流程：

1. 先依照最新 doc / PDF / URL / `User_Behavior_map` 產生新版 draft cases。
2. 再讀取一份人工維護的 copy XMind。
3. 將人工 copy XMind 裡的調整套回新版 draft。
4. 最後輸出更新後的 final XMind，取代人工複製貼上的動作。

優先級固定為：

```text
our copy xmind > user_behavior_map > doc / PDF / URL generated content
```

也就是說，系統先完整抓最新文件與 `User_Behavior_map`，再用人工 copy XMind 覆蓋同一測項中已被人工調整的內容，並補上人工新增測項。

人工 copy XMind 的實際維護範圍以測項內容為主：

- 修改 test case title。
- 修改 `步骤描述` 底下的 `步骤` 內容。
- 增加或減少 `步骤`。
- 修改每個 `步骤` 底下的 `预期结果`。
- 刪除用不到的 cases。
- 新增全新的 cases。

## 可行性判斷

可以做到。

目前專案已有三個關鍵能力：

- `parser/xmind_reader.py` 可解析 `.xmind`，抽出 case title、前置條件、步驟、預期結果、備註、優先級、模組路徑。
- `generator/test_case_generator.py` 會把 doc / PDF / URL 與 `User_Behavior_map` 轉成 `draft_test_cases.json`。
- `xmind_writer/metersphere_xmind_writer.py` 只吃 `draft_test_cases.json`，因此只要在 write XMind 前把人工調整 merge 回 draft，就能產生最終版本。
- `xmind_writer/metersphere_xmind_writer.py` 已支援 case 有 `id` 時寫出 `ID：...`；merge 需要讓 generated cases 產生穩定 `id`，才能在人改 title 後仍找到同一個 case。

建議新增的流程位置：

```text
build_draft
  -> generate_test_cases_file
  -> merge_human_xmind_edits
  -> write_xmind_from_draft
  -> validate_generated_xmind
```

## 使用方式設計

新增一個可選參數：

```bash
python main.py generate --vendor <Vendor> --human-xmind our_copy/<Vendor>_test_cases.xmind
```

輸出仍維持：

```text
output/<Vendor>/
  draft_test_cases.json
  <Vendor>_test_cases.xmind
  <Vendor>_test_cases_validation_report.json
  <Vendor>_test_cases_summary.md
  <Vendor>_human_merge_report.json
  <Vendor>_human_merge_manifest.json
```

若未提供 `--human-xmind`，流程維持現況，不做人工覆蓋。

## 合併資料來源

### Base: 新版自動產生內容

來源：

- doc / HTML reader
- PDF reader
- URL reader
- `User_Behavior_map`
- deterministic API parameter generator

這份內容代表最新 vendor 文件與目前 generator 理解到的測項集合。

### Overlay: 人工 copy XMind

來源：

- 上一次人工已調整過的 XMind copy
- 人工新增測項
- 人工刪除後留下的測項集合
- 人工修改過的 test case title
- 人工修改過的 `步骤描述`，包含增加 / 減少 `步骤`
- 人工修改過的 `预期结果`

這份內容代表 human review 後的最終意圖，因此優先級最高。

## Case Matching 規則

合併要先判斷「新版自動測項」與「人工 copy 測項」是不是同一個測項。

建議使用多層 matching key，依序比對：

1. `case_id`
   - 如果人工 XMind 保留 `ID：...`，這是最穩定 key。
   - 第一版實作時，generated cases 應補上 deterministic `id`，例如：
     - API parameter：`param::<normalized endpoint>::<normalized parameter>`
     - User Behavior：`ub::<source_case_id or source_path hash>::<category>`
     - Human added：`human::<normalized module>::<normalized title hash>`
2. stable generated key
   - API parameter case：`category=parameter_validation + endpoint + parameter`
   - User Behavior case：`source_reference.source_case_id` 或 `source_reference.source_path`
   - 這些 key 主要用來產 deterministic `id`，或在舊資料沒有 `ID：...` 時做 fallback。
3. normalized `output_section + module + scenario`
   - 去掉 `case：` / `case:` prefix。
   - 大小寫不敏感。
   - 多空白合併。
   - 全形 / 半形冒號視為相同。
4. normalized `module + steps signature`
   - 當 title 被人工改過，且沒有穩定系統 key 時，用步驟內容摘要輔助判斷。
   - 只列為 possible match，第一版不自動覆蓋，避免錯配。

如果仍無法判定，就視為人工新增測項。

## 欄位覆蓋規則

當 matching 成功時，以人工 copy XMind 覆蓋新版自動測項的可人工調整欄位：

```text
scenario
steps
```

保留新版自動測項的系統欄位：

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

理由：

- 人工通常只改 test case title、`步骤` 內容、`步骤` 數量，以及 `预期结果`。
- 前置條件與備註通常應跟著最新 doc / PDF / URL 重新產生，避免 endpoint example 或 request / response structure 舊掉。
- endpoint / parameter / category 代表新版文件解析結果，應保留最新系統語意，避免文件更新後仍綁在舊 endpoint。

若之後確認人工也會調整前置條件、備註、優先級、標籤或分類，再把這些欄位加入可覆蓋白名單；第一版先收窄，降低誤覆蓋風險。

`steps` 覆蓋採整組覆蓋：

- human copy 有 3 個步驟、base 有 5 個步驟，最後保留 human copy 的 3 個步驟。
- human copy 有新增步驟，最後保留新增後的完整步驟列表。
- 每個 step 的 `step` 與 `expected` 都以 human copy 為準。

## 人工新增測項規則

人工 copy XMind 中找不到 base match 的測項，一律新增到新版 draft。

新增時補上 metadata：

```json
{
  "source_reference": {
    "generated_by": "human-xmind-overlay/v1",
    "source_xmind": "<human xmind path>",
    "merge_action": "added_from_human_copy"
  }
}
```

如果人工新增測項缺少系統欄位，使用可驗證的 fallback：

- `category`: `human_added`
- `output_section`: 從 XMind module path 推回；無法推回時放在原 module path 最接近的 section。
- `module`: 使用 XMind 的 `所属模块`，沒有則使用 module path 最後一層。
- `tags`: 從 `标签：` 解析，沒有則空陣列。
- `priority`: 沒有則 `P2`。

## 刪除與停用策略

人工 copy XMind 刪掉的 case 應該被視為「不要出現在 final XMind」。

但要避免誤刪本次 doc / PDF / URL 或 `User_Behavior_map` 新增出來的 case，所以刪除判斷需要多一份上一版狀態。

建議新增 merge manifest：

```text
output/<Vendor>/<Vendor>_human_merge_manifest.json
```

manifest 記錄上一次 final XMind 的 stable case keys：

```json
{
  "vendor": "<Vendor>",
  "final_case_keys": ["..."],
  "generated_at": "..."
}
```

刪除規則：

- base case 在上一版 manifest 出現過。
- 這次 human copy XMind 找不到同一個 stable key。
- 則視為人工刪除，從 final draft 移除。

保留規則：

- base case 沒在上一版 manifest 出現過，代表這次文件或 template 新增的測項。
- 即使 human copy XMind 還沒有這個 case，也要保留在 final XMind。
- report 標記為 `new_from_base`，方便 reviewer 下次決定是否保留。

如果沒有 manifest，例如第一次導入 `--human-xmind`：

- 不自動刪除 base-only cases。
- 只在 report 中列出 `base_only_without_manifest`。
- 從第二次 merge 開始才啟用刪除語意。

## 衝突處理

### 人工 copy 與新版文件同時更新同一測項

處理方式：

1. 新版 generator 先產生最新 endpoint / parameter / expected error。
2. human overlay 覆蓋 title、完整 steps list、每個 step 的 expected result。
3. report 標記 `updated_by_human_overlay`。

### 人工 copy 中同 key 有多個測項

處理方式：

- 第一筆 merge。
- 後續同 key 測項列入 conflict report。
- 不靜默丟棄，避免人工重複 case 被吃掉。

### 新版自動測項 key 改變

例如文件中的 endpoint 或 parameter 名稱更新，導致 fallback key 對不上。

處理方式：

- 若 scenario 高相似度且 module path 相近，可列為 `possible_match`。
- 第一版不自動套用 fuzzy merge，只寫到 report，避免錯蓋。

## Merge Report

每次合併輸出：

```text
output/<Vendor>/<Vendor>_human_merge_report.json
```

內容包含：

- matched and overridden cases
- added human-only cases
- deleted by human cases
- new generated cases kept because they are not in previous manifest
- base-only cases skipped from deletion because manifest is missing
- duplicate human keys
- possible fuzzy matches
- validation warnings

範例：

```json
{
  "summary": {
    "base_cases": 120,
    "human_cases": 118,
    "overridden": 34,
    "added_from_human": 6,
    "deleted_by_human": 4,
    "new_from_base": 12,
    "conflicts": 1
  },
  "overridden": [
    {
      "key": "user behavior > bet and settle|case: multiple bet same round",
      "fields": ["scenario", "steps"]
    }
  ],
  "added_from_human": [],
  "deleted_by_human": [],
  "new_from_base": [],
  "conflicts": []
}
```

## 實作步驟

### Phase 1: 建立 merge module

新增：

```text
src/generator/human_xmind_merger.py
```

負責：

- 讀取 human `.xmind`
- 將 parsed source cases 轉成 draft case format
- 建立 base / human case index
- 套用 overlay
- 依 manifest 判斷人工刪除
- 輸出 merge report
- 寫入下一版 merge manifest

主要函式：

```python
def merge_human_xmind_edits(
    draft: dict[str, Any],
    human_xmind_path: Path,
    report_path: Path,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    ...
```

### Phase 2: 加入 CLI

修改：

```text
src/generator_main.py
```

新增參數：

```bash
--human-xmind <path>
```

流程改為：

```python
after = load_draft(draft_path)
if args.human_xmind:
    after = merge_human_xmind_edits(after, Path(args.human_xmind), merge_report_path, manifest_path)
write_xmind_from_draft(after, xmind_path)
```

### Phase 3: 補 stable case id

在 generated draft 寫出 XMind 前，每個 case 都應有穩定 `id`。

建議新增 helper：

```python
ensure_stable_case_ids(draft)
stable_case_key(case)
```

規則：

- API parameter cases 用 `endpoint + parameter` 產生 id。
- User Behavior cases 用 `source_reference.source_case_id`；沒有時用 `source_reference.source_path + category + scenario` hash。
- Human added cases 若沒有 id，用 module path + scenario hash 產生 id。
- 產出的 id 要穩定、短、可讀，不使用 random uuid。
- writer 會把 `id` 寫成 `ID：...`，下一次讀 human copy XMind 時就能靠 `case_id` match。

### Phase 4: Draft case conversion

將 `parser.xmind_reader.parse_xmind_file()` 的 source case 轉成 draft case：

```text
name -> scenario
preconditions -> preconditions
steps[].step / steps[].expected -> steps
remarks -> remarks
priority -> priority
labels -> tags
module_title -> module
module_path -> output_section inference
case_id -> id
```

需要注意：

- `case：` prefix 不應重複寫入。
- `标签：a, b` 要拆成 list。
- `步骤描述` 底下的 `步骤` / `预期结果` 已由 parser 抽出，可直接轉用。
- 人工主要改 title 與 steps，因此 conversion 必須保留完整 steps order，不能排序。
- 若某個 step 沒有 `预期结果`，保留空字串並在 validation warning 標記。

### Phase 5: Key normalization

建立 helper：

```python
normalize_case_title(value)
normalize_section(value)
case_match_keys(case)
```

規則：

- trim
- lower
- 移除 `case：` / `case:`
- 合併多空白
- 統一 `：` 與 `:`
- module path 用 `>` 切開後 trim 再重組

### Phase 6: Validation

合併完成後沿用現有：

```python
validate_draft(draft)
validate_generated_xmind(xmind_path, draft, report_path)
```

另外新增 unit tests：

- matching by `case_id`
- generated API parameter case gets deterministic id
- generated User Behavior case gets deterministic id
- API parameter fallback matching
- User Behavior stable source matching
- matching should still work when human changed scenario title
- matching by section + module + scenario
- human-only case added
- manifest-known base case missing in human copy is deleted
- manifest-unknown new base case is kept
- duplicate human key reported
- human scenario and steps override generated fields
- human step add / remove is preserved
- human expected result edits are preserved
- system fields remain from generated base

## 建議驗收案例

### Case 1: 修改 test case title

流程：

1. 產生 Vendor XMind。
2. 人工 copy 中修改某 case 的 title。
3. doc 更新後重新 generate + merge。

期望：

- 新 XMind 包含 doc 更新後的新測項。
- 該 case 的 title 維持人工版本。
- 該 case 的前置條件與備註仍使用新版 generator 依最新文件產生的內容。

### Case 2: 修改 steps 與 expected results

流程：

1. `User_Behavior_map` 產生 Bet and Settle 測項。
2. 人工 copy 改 `步骤` 文字。
3. 人工 copy 增加或減少 `步骤`。
4. 人工 copy 改 `预期结果`。
5. 重新 generate + merge。

期望：

- matching case 以人工 copy 的完整 steps list 為準。
- 新增的 step 被保留。
- 刪掉的 step 不會被新版 generator 補回來。
- `预期结果` 使用人工 copy 的版本。

### Case 3: 刪除用不到的 cases

流程：

1. 第一次 generate + merge 後產生 manifest。
2. 人工 copy 刪掉一個不需要的 case。
3. 重新 generate + merge。

期望：

- 如果該 case key 存在於上一版 manifest，且這次 human copy 找不到它，final XMind 不再輸出該 case。
- report 標記為 `deleted_by_human`。

### Case 4: 人工新增測項

流程：

1. 人工 copy 新增一個特殊測項。
2. 重新 generate + merge。

期望：

- 新測項出現在 final XMind。
- report 標記為 `added_from_human`。

### Case 5: 文件新增測項

流程：

1. doc / PDF 新增 endpoint 或 parameter。
2. 人工 copy 沒有此測項。
3. 重新 generate + merge。

期望：

- 新測項保留。
- report 標記為 `new_from_base`。
- 下一次如果人工 copy 刪除它，才會依 manifest 視為 `deleted_by_human`。

## 第一版不做的事

- 不自動 fuzzy merge 高相似案例，只列 report。
- 不嘗試把人工 XMind 的排版、markers、notes 完整保留。
- 不修改 `User_Behavior_map` 本身；人工 copy 只覆蓋當次 Vendor final output。
- 第一次沒有 manifest 時，不把 base-only cases 當成人工刪除。

## 後續可擴充

- 支援 `--human-xmind-dir`，依 Vendor 自動找 copy。
- 支援 `[human_merge] disabled=true` 來停用自動生成測項。
- 支援 merge preview，只產 report 不寫 final XMind。
- 支援 fuzzy match 人工確認清單。
- 支援將穩定人工新增測項反向整理回 `User_Behavior_map` 或 scenario templates。
