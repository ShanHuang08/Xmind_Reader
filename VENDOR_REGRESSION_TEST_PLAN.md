# All-Vendor Regression Test Plan

## 1. Purpose

每次完成程式修改後，必須針對 repository 中所有可執行的 vendor 逐一執行完整 new-vendor pipeline，確認既有 vendor 不會因共用 reader、generator、writer 或 validator 邏輯變更出現執行錯誤。

所有 vendor 都成功完成以下指令，且輸出驗證通過，該次變更才可判定為 regression passed：

```bash
python3 run_new_vendor.py <vendor_name>
```

任一 vendor 失敗、流程中斷、產生 traceback、缺少必要輸出或 XMind validation 不通過，整體 regression 一律判定為 failed。

### Implementation Status

此計畫已實作：

- Runner：`tests/run_vendor_regression.py`
- Discovery/output validation tests：`tests/test_regression_runner.py`
- Vendor error-source tests：`tests/test_generation_error_sources.py`
- Coverage implementation：`tests/regression/vendor_case_baseline.py`
- Version-controlled baseline：`tests/regression/vendor_case_count_baseline.json`
- Generated reports：`regression-results/summary.json`、`regression-results/summary.md`
- Coverage reports：`regression-results/case-count-comparison.json`、`regression-results/case-count-comparison.md`
- Per-vendor logs：`regression-results/logs/<Vendor>.log`
- Git ignore：`.gitignore` 已排除 `regression-results/`

2026-08-17 首次 forced-read baseline：動態發現 6 個 vendors，全部 wrapper command、forced document read、draft validation 與 XMind validation 通過。實際 case counts 與 duration 以每次重新產生的 `regression-results/summary.md` 為準。

## 2. Scope

一次 `run_new_vendor.py` 執行涵蓋：

1. 尋找並解析 `user_behavior_map.xmind`。
2. 尋找 `Vendor_<Vendor>.doc` 或 `.docx`。
3. 解析 vendor Confluence export。
4. 產生或更新 `new_vendor_detail/<Vendor>/`。
5. 建立 `draft_test_cases.json`。
6. 產生 API parameter validation 與 User Behavior test cases。
7. 輸出 MeterSphere-compatible XMind。
8. 回讀 XMind 並產生 validation report。
9. 產生 test case summary。

此計畫適用於會影響以下任一範圍的修改：

- `src/doc_reader/`
- `src/xmind_reader/`
- `src/generator/`
- `src/xmind_writer/`
- `src/pipeline/`
- `src/*_main.py`
- `main.py`
- `run_new_vendor.py`
- 共用 schema、validation、vendor discovery 或 reference selection 邏輯

## 3. Regression Runner Design

### Implementation Decision

Regression orchestration code 放在：

```text
tests/run_vendor_regression.py
```

不修改 `main.py`，也不另外增加 GitHub Action。理由如下：

- `main.py` 與 `run_new_vendor.py` 是正式功能入口，維持單一 vendor pipeline 的責任。
- All-vendor discovery、重複執行、artifact validation、log 與結果彙總屬於測試責任。
- Regression runner 應從外部呼叫正式入口，才能驗證真實使用路徑。
- 測試工具不應增加正式 CLI 的 public options 或 business logic branches。

不要將檔案命名為 `test_vendor_regression.py`，避免以下 unit-test discovery command 意外啟動耗時的完整 regression：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

### Runner Entry Point

預設執行所有動態發現的 vendors：

```bash
python3 tests/run_vendor_regression.py
```

測試 doc reader、parser 或 extractor 修改時，允許 runner 提供測試用途 option：

```bash
python3 tests/run_vendor_regression.py --force-doc-read
```

這個 option 屬於 regression runner，不加入 `main.py`。Runner 在正常 wrapper validation 之外，使用既有正式 command 補做 forced read：

```bash
python3 main.py new-vendor <vendor_name> --force
```

### Runner Responsibilities

`tests/run_vendor_regression.py` 必須負責：

1. 從 `new_vendor_source/` 動態發現所有 `Vendor_*.doc/.docx`。
2. 從檔名取得 vendor argument，並拒絕重複或無法識別的 source。
3. 每個 vendor 透過 subprocess 執行正式 wrapper：

```python
command = [sys.executable, "run_new_vendor.py", vendor]
completed = subprocess.run(
    command,
    cwd=repo_root,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)
```

4. 即使單一 vendor 失敗，仍繼續執行剩餘 vendors。
5. 保存每個 vendor 的 command、combined output、exit code 與 duration。
6. 驗證 draft JSON、XMind archive、validation report 與 summary。
7. 產生 machine-readable JSON 與 human-readable Markdown report。
8. 所有 vendors 通過時回傳 process exit code `0`；任一失敗時，全部跑完後回傳 `1`。

Runner 不應：

- import 並複製 `run_new_vendor.py` 的 pipeline 實作。
- 在測試中重新實作 reader、generator 或 writer business logic。
- 修改或回復現有使用者程式碼。
- 手動修正生成後的 XMind 再宣告通過。
- 將 regression result、log 或 generated output 寫進 `tests/` source tree。

### Suggested File Layout

目前 vendor 數量不多，先使用單一 runner 即可：

```text
tests/
├── test_doc_extractor.py
├── test_parameter_dependency.py
├── test_generation_error_sources.py
├── test_regression_runner.py
└── run_vendor_regression.py
```

若未來 validation 與 report logic 擴大，再拆成：

```text
tests/regression/
├── __init__.py
├── run_all_vendors.py
├── vendor_discovery.py
├── output_validator.py
└── report_writer.py
```

拆分後的執行方式為：

```bash
python3 -m tests.regression.run_all_vendors
```

Regression artifacts 建議輸出到 repository root 下的獨立 ignored directory：

```text
regression-results/
├── summary.json
├── summary.md
└── logs/
    ├── Alea.log
    └── <Vendor>.log
```

### Regression Artifact Git Policy

`regression-results/` 是每次執行產生的暫時報告與 logs，不可提交到 Git。實作 regression runner 時，必須同步在 repository `.gitignore` 加入：

```gitignore
# All-vendor regression generated reports and logs
regression-results/
```

此規則會忽略：

```text
regression-results/logs/
regression-results/summary.json
regression-results/summary.md
```

以下測試規格與程式碼不屬於 generated artifacts，必須保留在 Git：

```text
VENDOR_REGRESSION_TEST_PLAN.md
tests/run_vendor_regression.py
```

Runner 必須在需要時自行建立 `regression-results/` 與 `regression-results/logs/`，不可要求使用者事先建立，也不可因目錄被 Git 忽略而跳過報告輸出。

## 4. Vendor Discovery Rule

Regression vendor 清單必須從 repository 現有 source documents 取得，不可只依賴人工維護的固定清單。

合法來源檔名：

```text
Vendor_<Vendor>.doc
Vendor_<Vendor>.docx
```

可使用以下指令檢查目前所有 vendor source：

```bash
find new_vendor_source -type f \( -iname 'Vendor_*.doc' -o -iname 'Vendor_*.docx' \) -print | sort
```

Vendor argument 應由檔名移除 `Vendor_` prefix 與副檔名後取得。檔名比對不分大小寫，但報告中應保留 source filename 的 vendor spelling。

### Required Discovery Function

Runner 不可 hardcode vendor list。`tests/run_vendor_regression.py` 必須提供一個 discovery function，例如：

```python
from __future__ import annotations

import re
from pathlib import Path


VENDOR_DOCUMENT_RE = re.compile(
    r"^Vendor_(?P<vendor>.+)\.docx?$",
    re.IGNORECASE,
)


def discover_vendors(source_root: Path) -> list[str]:
    vendors: dict[str, tuple[str, Path]] = {}

    for path in source_root.rglob("*"):
        if not path.is_file():
            continue

        match = VENDOR_DOCUMENT_RE.match(path.name)
        if not match:
            continue

        vendor = match.group("vendor")
        key = vendor.casefold()

        if key in vendors:
            previous = vendors[key][1]
            raise RuntimeError(
                f"Duplicate vendor documents for {vendor}: "
                f"{previous} and {path}"
            )

        vendors[key] = (vendor, path)

    if not vendors:
        raise RuntimeError(
            f"No Vendor_*.doc or Vendor_*.docx found under {source_root}"
        )

    return sorted(
        (vendor for vendor, _ in vendors.values()),
        key=str.casefold,
    )
```

Runner 使用 discovery 結果產生 commands：

```python
vendors = discover_vendors(repo_root / "new_vendor_source")

for vendor in vendors:
    command = [sys.executable, "run_new_vendor.py", vendor]
```

Discovery requirements：

- 遞迴掃描 `new_vendor_source/`，包含 vendor 子資料夾。
- `.doc`、`.docx` 與 `Vendor_` prefix 比對不分大小寫。
- Vendor argument 保留 source filename 中的原始 spelling。
- 排序使用 `casefold()`，確保執行順序穩定。
- 相同 vendor 同時出現 `.doc`、`.docx` 或不同 casing 時必須 fail，不進入互動選擇。
- 找不到任何 vendor document 時必須 fail，不可產生空的 passing report。
- `.pdf`、`.html`、`.DS_Store` 與不符合 `Vendor_<Vendor>` 格式的檔案不可加入 vendor list。

建議為 discovery function 增加 unit tests，至少涵蓋：

1. Root 與 nested directory 都能發現。
2. `.doc` 與 `.docx` 都能發現。
3. 大小寫不影響偵測。
4. 重複 vendor 會拋出錯誤。
5. 非 vendor 文件會被忽略。
6. 零 vendor 時會拋出錯誤。

### Current Baseline Vendors

依目前 `new_vendor_source/`，`discover_vendors()` 的預期展開結果如下。這份表格是人工檢查用的目前 baseline，不是 runner 內的 hardcoded input：

| Order | Vendor argument | Source document |
|---:|---|---|
| 1 | `Alea` | `new_vendor_source/Vendor_Alea.doc` |
| 2 | `CasinoGate` | `new_vendor_source/Vendor_CasinoGate.doc` |
| 3 | `IDNPLAY` | `new_vendor_source/IDNPlay/Vendor_IDNPLAY.doc` |
| 4 | `MegaFair` | `new_vendor_source/Vendor_MegaFair.doc` |
| 5 | `SoftGaming` | `new_vendor_source/SoftGaming/Vendor_SoftGaming.doc` |
| 6 | `Veligames` | `new_vendor_source/Vendor_Veligames.doc` |

`new_vendor_detail/` 中只有中間資料、但沒有對應 `Vendor_<Vendor>.doc/.docx` 的資料夾，不可直接視為可執行的 regression vendor。應先確認 source document 與 `run_new_vendor.py` discovery 規則是否完整。

新增 vendor source document 後，下一次 regression 必須自動將該 vendor 加入清單。

## 5. Preconditions

執行前必須記錄：

```bash
git status --short --branch
git rev-parse HEAD
python3 --version
```

並確認：

- 從 repository root 執行。
- Python dependencies 已安裝。
- `user_behavior_map.xmind` 可被唯一識別；不可停在互動式檔案選擇。
- 每個 vendor 都有唯一可識別的 source document。
- 磁碟空間足以重新產生所有 output。
- 執行前記錄既有未提交修改，不得在 regression 過程中覆蓋或回復他人的修改。

## 6. Mandatory Execution

Runner 必須執行 `discover_vendors()` 回傳的所有 vendors，不可只抽樣，也不可在程式碼中固定六個名稱。

以目前 source documents 為例，動態 discovery 應展開成以下六個 commands：

```bash
python3 run_new_vendor.py Alea
python3 run_new_vendor.py CasinoGate
python3 run_new_vendor.py IDNPLAY
python3 run_new_vendor.py MegaFair
python3 run_new_vendor.py SoftGaming
python3 run_new_vendor.py Veligames
```

未來新增 `Vendor_NewVendor.doc` 後，不修改 runner code，也必須自動增加：

```bash
python3 run_new_vendor.py NewVendor
```

執行原則：

- 每個 vendor 使用獨立 log。
- 不使用 fail-fast；即使前一個 vendor 失敗，仍應執行剩餘 vendor，以取得完整 regression 結果。
- 保存每個 command 的 exit code。
- 不可因其他 vendor 通過而忽略單一 vendor 失敗。
- 不可只確認 command 啟動成功；必須確認 pipeline 執行到 XMind validation 完成。

## 7. Force-Read Requirement

`run_new_vendor.py` wrapper 目前只接受 vendor name，沒有 `--force` option。若 source metadata 判定文件沒有變更，doc reader 可能跳過重新解析。

因此測試 parser、extractor 或 Confluence parsing 相關修改時，除了 mandatory wrapper command，還必須補跑：

```bash
python3 main.py new-vendor <vendor_name> --force
```

判定原則：

- 一般 generator/writer 修改：mandatory wrapper commands 為主要 regression。
- doc reader/parser/extractor 修改：所有 vendor 必須再用 `--force` 完整重讀一次。
- log 必須能證明 source document 已重新解析，而不是只重用舊的 `new_vendor_detail`。

`--force` 是補充驗證，不取代 `python3 run_new_vendor.py <vendor_name>` 的相容入口測試。

## 8. Per-Vendor Pass Criteria

每個 vendor 必須同時滿足以下條件：

### Process

- Command exit code 為 `0`。
- 沒有未處理 exception 或 traceback。
- 沒有停在互動式 prompt。
- 沒有 error-level pipeline termination。

### Required Outputs

以下檔案必須存在且非空：

```text
output/<Vendor>/draft_test_cases.json
output/<Vendor>/<Vendor>_test_cases.xmind
output/<Vendor>/<Vendor>_test_cases_validation_report.json
output/<Vendor>/<Vendor>_test_cases_summary.md
```

實際 output folder casing 以 command 使用的 vendor argument 為準。

### Draft Validation

- `draft_test_cases.json` 是合法 JSON。
- `vendor` 欄位符合目標 vendor。
- `test_cases` 存在且為非空 list。
- 每個 generated case 通過 repository draft schema validation。
- 不得出現因共用邏輯變更造成的整批 cases 消失。

### XMind Validation

- `.xmind` 是合法 ZIP archive。
- XMind 可被 repository parser 回讀。
- validation report 是合法 JSON。
- validation report 的整體結果必須為 valid/pass。
- case count 與 draft 相符；若 validator 提供 mismatch/error 欄位，必須為空。

### Summary Validation

- Summary markdown 存在且非空。
- Summary 中的 total case count 不得為 `0`。
- Endpoint/API parameter/User Behavior 統計不可因錯誤解析而異常歸零。

## 9. Cross-Vendor Regression Checks

除了「可以跑完」，還要檢查共用邏輯沒有只對單一 vendor 正確：

| Area | Required check |
|---|---|
| Single-variant endpoints | 沒有 `operation_variants` 的 vendor 仍沿用原本 request example 與 case generation。 |
| Multi-variant endpoints | 有多 operations 或多 request examples 的 endpoint 能保留正確 variant data。 |
| Request examples | 不同 vendor 的 request pre 不可被其他 endpoint 或 variant 共用。 |
| Response examples | Success/error response 不可被 request example 誤判。 |
| Parameter tables | Request/response table 不可因 document order 而配對到錯誤 endpoint。 |
| Parameter dependencies | 沒有 dependency 的 endpoint 行為不變；有明確 dependency 的 endpoint 才啟用。 |
| Amount precision | Vendor-specific documented precision 正確；無法判斷時沿用 fallback。 |
| Encryption errors | 只有 encryption/signature parameters 使用對應 error。 |
| User Behavior | Reference selection 與 endpoint adaptation 不可整批消失。 |
| XMind writing | Remarks、steps、expected results 與 hierarchy 完整保留。 |

## 10. Result Matrix

### Case Count And Coverage Baseline

Regression 不可只確認 XMind 能成功產生，也不可只比較 test case 總數。User Behavior 數量增加時，可能掩蓋 API parameter test 大量減少，因此 runner 應分層記錄並比較：

1. Vendor 總 test case 數。
2. `API parameter test` test case 數。
3. `User Behavior` test case 數。
4. 文件解析出的 endpoint 數量。
5. 每個 endpoint 的 request parameter 數量。
6. 每個 endpoint 實際產生的 API parameter test case 數量。
7. 每個 operation variant 的 request parameter 與 generated case 數量。

建議將人工確認過的基準提交到 Git：

```text
tests/regression/vendor_case_count_baseline.json
```

Baseline 格式範例：

```json
{
  "Alea": {
    "total_cases": 253,
    "sections": {
      "API parameter test": 121,
      "User Behavior": 132
    },
    "endpoints": {
      "BET": {
        "request_parameters": 12,
        "generated_parameter_cases": 12
      },
      "SETTLE": {
        "request_parameters": 14,
        "generated_parameter_cases": 14
      }
    }
  }
}
```

每次執行產生的比較結果屬於暫時 artifacts，寫入已被 Git ignore 的目錄：

```text
regression-results/case-count-comparison.json
regression-results/case-count-comparison.md
```

#### Required Failure Rules

以下任一情況必須讓該 vendor regression failed：

- 有 request parameters 的 endpoint 沒有產生任何 API parameter test case。
- 文件解析出的 endpoint 比 baseline 少。
- Baseline 中存在的 endpoint 或 operation variant 從 generated coverage 消失。
- `API parameter test` 數量比 baseline 減少超過 5%。
- Vendor 總 test case 數量比 baseline 減少超過 10%。
- Parsed request parameter count 與 generated parameter coverage 不符，且沒有明確的 skip reason。
- 單一 endpoint 原本有 parameter cases，本次變成 0 cases。

Endpoint coverage 必須另外列出 expected、generated 與 missing endpoints。例如：

```text
Expected parameter endpoints:
- BET
- SETTLE
- REFUND
- BALANCE

Generated parameter endpoints:
- BET

Missing endpoint coverage:
- SETTLE
- REFUND
- BALANCE
```

最基本的 coverage invariant：

```text
有 request_parameters 的 endpoint 數量
==
有 API parameter test cases 的 endpoint 數量
```

若 parameter 因 operation variant、dependency、unsupported type 或文件明確標記不適用而跳過，runner 必須記錄結構化 `skip_reason`，不可無聲忽略。

#### Baseline Update Policy

Runner 不可在一般 regression 執行時自動更新 baseline，避免錯誤輸出直接覆蓋正確基準。Baseline 只能透過明確 option 更新，例如：

```bash
python3 tests/run_vendor_regression.py --update-baseline
```

更新 baseline 後必須人工 review Git diff，確認 endpoint、operation variant、section 與 case count 的增減符合本次需求。Case count threshold 只負責偵測異常變化；endpoint 與 parameter coverage 才是判斷「是否只成功抓到部分 endpoint」的主要條件。

### Result Table

每次 regression 必須填寫完整結果：

| Vendor | Command | Exit code | Draft valid | XMind valid | Case count | Log | Result |
|---|---|---:|---|---|---:|---|---|
| Alea | `python3 run_new_vendor.py Alea` |  |  |  |  |  | Pending |
| CasinoGate | `python3 run_new_vendor.py CasinoGate` |  |  |  |  |  | Pending |
| IDNPLAY | `python3 run_new_vendor.py IDNPLAY` |  |  |  |  |  | Pending |
| MegaFair | `python3 run_new_vendor.py MegaFair` |  |  |  |  |  | Pending |
| SoftGaming | `python3 run_new_vendor.py SoftGaming` |  |  |  |  |  | Pending |
| Veligames | `python3 run_new_vendor.py Veligames` |  |  |  |  |  | Pending |

若執行時發現新的 `Vendor_<Vendor>.doc/.docx`，必須在表格新增一列。

## 11. Failure Handling

發生失敗時必須記錄：

- Vendor name。
- 完整 command。
- Exit code。
- Failure stage：discovery、XMind read、doc read、draft build、case generation、XMind write 或 validation。
- Error/traceback 的第一個實際 root cause。
- 失敗前最後成功產生的 artifact。
- 是否只影響單一 vendor，或所有 vendor 都能重現。

不得用以下方式把 regression 標記為通過：

- 手動修正生成後的 XMind。
- 忽略失敗 vendor。
- 使用先前已成功的 output 取代本次執行結果。
- 只確認 output 檔案存在，卻沒有確認本次 command 的 exit code 與 validation report。
- 將「已知問題」自動視為 passed；已知問題仍須列為 failed 或取得明確 waiver。

修復後必須：

1. 重新執行失敗 vendor。
2. 再執行完整 all-vendor regression。
3. 更新結果矩陣，不可只補單一 vendor 結果後直接宣告整體通過。

## 12. Overall Pass/Fail Rule

### Passed

只有在以下條件全部成立時才算通過：

- 動態發現的所有 vendor 都已執行。
- 每個 mandatory `run_new_vendor.py` command exit code 都是 `0`。
- 所有必要 artifacts 都存在且非空。
- 所有 draft 與 XMind validation 都通過。
- 沒有 unresolved traceback、missing output 或 case-count mismatch。
- parser/extractor 相關修改已完成全 vendor `--force` regression。
- 結果矩陣與 logs 完整保存。

### Failed

以下任一條件成立即為 failed：

- 少跑任何一個 vendor。
- 任一 command exit code 非 `0`。
- 任一 validation report 失敗。
- 任一必要 artifact 缺少或為空。
- pipeline 使用舊資料而未實際覆蓋本次修改範圍。
- 需要人工介入才能跑完。
- 新增 vendor source 後沒有納入 regression。

## 13. Regression Report Template

```markdown
# Vendor Regression Report

- Commit/working tree: `<commit hash or dirty>`
- Date:
- Python version:
- Change scope:
- Vendor discovery count:
- Overall result: PASS / FAIL

## Results

| Vendor | Exit code | Draft valid | XMind valid | Case count | Duration | Result |
|---|---:|---|---|---:|---:|---|
| ... | ... | ... | ... | ... | ... | ... |

## Failures

- Vendor:
- Stage:
- Root cause:
- Log path:
- Required fix:

## Verification Notes

- Mandatory wrapper commands completed:
- Forced doc re-read completed when required:
- Output validation completed:
- Known warnings:
- Not verified:
```

## 14. Definition of Done

程式修改只有在以下工作全部完成後才算完成：

1. Relevant unit tests passed。
2. 所有現存 vendor 執行 `python3 run_new_vendor.py <vendor_name>`。
3. Parser/extractor 修改時，所有 vendor 補跑 `--force`。
4. 每個 vendor 的 output 與 validation report 通過。
5. Regression report 完整記錄。
6. 沒有未處理 failure 或未說明的 skipped vendor。

在這些條件完成前，不應將修改標記為 regression passed，也不應以單一 vendor 成功作為合併依據。

## 15. Case-Count Protection 實作結果

原先列於本節的 P0 與 P1 項目已完成。Runner 現在會在正式 pipeline、draft validation 與 XMind validation 之外，再執行 baseline 與結構化 coverage validation。

| 原項目 | Status | 實作結果 |
|---|---|---|
| Version-controlled case-count baseline | Done | `tests/regression/vendor_case_count_baseline.json` 保存 6 個 vendors 的 total、section、category、endpoint、operation variant 與 parameter coverage。 |
| Section-level case count | Done | 分別記錄 API parameter、User Behavior、Other cases 與完整 `section_counts`。 |
| Endpoint parameter coverage | Done | 比對 parsed request parameters 與 generated API parameter cases，缺少 parameter 時直接 failed。 |
| Operation variant coverage | Done | 使用 `<endpoint>::<operation>` 作為獨立 coverage group，operation 消失時直接 failed。 |
| Count regression thresholds | Done | API parameter 減少超過 5%，或 total 減少超過 10% 時 failed。 |
| Missing coverage failure | Done | Endpoint/operation 消失、parameter count 減少、generated parameter 消失或 endpoint 產生 0 cases 均會 failed。 |
| Structured parameter skip reasons | Done | Draft 可透過 `parameter_coverage_skips` 提供 endpoint、operation、parameter 與非空 `skip_reason`；無理由的 missing parameter 仍會 failed。 |
| Baseline comparison reports | Done | 每次產生 ignored JSON 與 Markdown comparison reports。 |
| Explicit baseline update command | Done | `--update-baseline` 只在所有 vendors 通過 intrinsic validation 後寫入 deterministic baseline；一般執行唯讀。 |
| Summary content validation | Done | 驗證 summary total、API parameter 與 User Behavior count 和 draft profile 一致。 |
| Successful-command traceback scan | Done | Exit code 0 仍會掃描 traceback、error-level termination 與 unhandled exception。 |
| Structured failure diagnosis | Done | Result 保存 failure stage、第一個 root cause 與最後成功產生的 artifact。 |
| Complete result-matrix columns | Done | Summary 顯示 command、exit code、draft/XMind/coverage、case count、duration、log 與 result。 |
| Environment preflight | Done | 檢查正式入口、唯一的 User Behavior XMind、核心 Python dependencies、磁碟空間，並保存完整 Git status。 |
| Cross-vendor structural assertions | Done | Baseline 比對 category、amount-precision/dependency case count、encryption error mapping，以及 request/success/error example 是否消失。 |

### Baseline Commands

一般 regression：

```bash
python3 tests/run_vendor_regression.py --force-doc-read
```

只有在 test case、endpoint 或文件內容的預期變更已人工確認後，才更新 baseline：

```bash
python3 tests/run_vendor_regression.py --force-doc-read --update-baseline
```

Baseline 更新後仍必須 review `tests/regression/vendor_case_count_baseline.json` 的 Git diff，再執行一次不帶 `--update-baseline` 的 regression，確認唯讀 comparison 能通過。

### Remaining Limitations

以下內容仍不能只靠數量或結構化 baseline 自動證明，需保留 unit tests 或人工 review：

- Request/response example 的完整 payload value 是否符合最新 vendor 文件；目前會偵測 example 從有變無，但不鎖定所有 value。
- Amount precision 的實際小數位內容是否正確；目前會偵測 amount-precision cases 數量下降，不取代 payload assertion。
- 新增合法 parameter skip 時，generator/business logic 必須主動寫入 `parameter_coverage_skips`；runner 不會自行猜測 skip reason。
- Baseline 代表人工接受的 snapshot。錯誤輸出若被人工用 `--update-baseline` 接受，後續 comparison 無法辨識該人為錯誤，因此 baseline diff review 仍是必要流程。

### Verification Baseline

2026-08-17 實作驗證：

- Unit tests：28 passed。
- Dynamic vendors：6。
- Mandatory wrapper 與 forced doc read：全部通過。
- Draft、XMind、summary 與 coverage validation：全部通過。
- Baseline-read regression：全部通過，且一般執行未更新 baseline。
