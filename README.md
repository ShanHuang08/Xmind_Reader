# XMind Reader

## 專案目的

本專案有兩個資料整理流程：

1. `input_xmind/` -> `xmind_detail/`
   讀取已整理好的 XMind 測試案例知識庫，輸出給 Codex/AI 閱讀的 JSON、Markdown，以及給 QA 人員看的 Excel。

2. `new_vendor_source/` -> `new_vendor_detail/`
   讀取新 Vendor 的 Confluence 匯出 Word/HTML 文件，先整理成 Codex 好閱讀的中間格式，例如 API summary、endpoints、error codes、capability profile。

根目錄的 `output/` 之後保留給 AI 產生完成的新 Vendor 測試案例，例如 `newvendor_test_case.xmind`，不再放 XMind reader 的知識庫輸出。

本專案目前仍不是 AI 測試案例產生器。它只負責抽取、正規化、分類、切分與輸出知識。

## 專案架構

```text
input_xmind/
new_vendor_source/
new_vendor_detail/
  <Vendor>/
    api_summary.md
    endpoints.json
    error_codes.json
    capability_profile.json
    raw_doc.json
xmind_detail/
  <Vendor>/
    excel/
    summary/
    modules/
    tags/
    markdown/
    raw/
output/
src/
  parser/
  extractor/
  chunker/
  exporters/
  doc_reader/
  xmind_reader_main.py
  doc_reader_main.py
```

## 各檔案功能說明

### 統一入口

| 檔案 | 功能 |
|---|---|
| `main.py` | **CLI 統一入口**。提供 `xmind` 和 `doc` 兩個子命令，根據使用者選擇分別委派給 `xmind_reader_main.py` 或 `doc_reader_main.py` 執行。負責 `sys.path` 設定與引數轉發。 |

### XMind 流程 (`python main.py xmind`)

| 檔案 | 功能 |
|---|---|
| `src/xmind_reader_main.py` | **XMind 流程主控制器**。負責：(1) 解析 CLI 引數、解析輸入檔案路徑；(2) 呼叫 `xmind_reader` 解析 → `knowledge_extractor` 抽取知識 → `knowledge_chunker` 切分 → 各 exporter 輸出；(3) 增量處理決策（比對 SHA256、topic/case 數量決定 skip / full / incremental / preserve / raw_only）；(4) 新舊 case 合併（用 `topic_id` 識別同一個 case，`content_hash` 判斷是否需替換）。 |
| `src/parser/xmind_reader.py` | **XMind 檔案解析核心**。把 `.xmind`（ZIP 檔）解開，自動偵測 `content.json`（新版）或 `content.xml`（舊版）並解析為 sheets → topics 樹狀結構。提取每個 topic 的標題、ID、路徑、markers、notes、labels、超連結。辨識 `case：` 開頭的 topic 為測試用例，從子節點抽出結構化欄位（ID、前置條件、步驟、預期結果等）。 |
| `src/extractor/knowledge_extractor.py` | **知識抽取與正規化**。把 parser 輸出的 raw source cases 轉換為精簡的 knowledge cases：推斷 `module`、`api_name`，用關鍵字規則自動打 `tags`（positive / negative / boundary / validation / idempotency 等 18 種），抽取 `validation_points`、`db_checks`，並計算 `content_hash`（SHA256）供增量更新使用。 |
| `src/chunker/knowledge_chunker.py` | **知識切分與重複偵測**。將 knowledge cases 依 `module` 切分為 module chunks、依 `tags` 切分為 tag chunks，方便 AI 按需讀取。同時用 `SequenceMatcher` 偵測相似度 ≥ 92% 的疑似重複 case（只標記不移除）。 |
| `src/exporters/json_exporter.py` | **JSON 匯出模組**。提供多個函式：`export_raw`（raw JSON）、`export_source_meta`（來源檔 meta）、`export_summary`（摘要）、`export_extraction_report`（抽取報告）、`export_duplicate_report`（重複報告）、`export_chunks`（module / tag 切分 JSON）。 |
| `src/exporters/excel_exporter.py` | **Excel 匯出模組**。用 openpyxl 建立新的 Excel 檔案（非模板），包含 11 個欄位：ID、Module、Path、Scenario、Tags、Precondition、Steps、Expected Result、DB Check、Source XMind File、Source Sheet。附帶表頭樣式、欄寬、凍結首行、自動篩選。 |
| `src/exporters/markdown_exporter.py` | **Markdown 匯出模組**。把 module chunks 轉為 AI 友善的 `.md` 檔案。每個模組一個檔，內部依 primary tag 分組，列出 case ID、scenario、validation points、db checks。 |

### Doc Reader 流程 (`python main.py doc`)

| 檔案 | 功能 |
|---|---|
| `src/doc_reader_main.py` | **Doc Reader 流程主控制器**。負責：(1) 解析 CLI 引數、解析輸入檔案路徑；(2) 檢查 `source_meta.json` 判斷來源是否已處理過，未變更則跳過；(3) 依序呼叫 `doc_parser` → `doc_extractor` → `doc_exporter`。 |
| `src/doc_reader/doc_parser.py` | **文件解析核心**。讀取 Confluence 匯出的 Word/HTML 文件。`.doc` 走 MIME/HTML 解碼，`.docx` 走 python-docx，`.html` 走 lxml。輸出結構化資料：標題、段落、表格（含 checkbox 狀態）、連結、純文字。 |
| `src/doc_reader/doc_extractor.py` | **Vendor API 知識抽取**。從 parsed 文件中提取：(1) API endpoints（用正則匹配 `/api/...`）；(2) error codes（從表格或文字中用正則匹配）；(3) vendor master checklist（從表格中識別 Name + Enable 欄位）；(4) capability profile（用關鍵字規則偵測 Vendor 支援的能力，如 multiple_bets、rollback、free_spin 等，並優先採用 checklist 結果）。 |
| `src/doc_reader/doc_exporter.py` | **Vendor Detail 匯出模組**。將抽取結果寫入 7 個檔案：`api_summary.md`（給 Codex 優先閱讀的 API 摘要）、`endpoints.json`、`error_codes.json`、`capability_profile.json`、`vendor_master_checklist.json`、`source_meta.json`、`raw_doc.json`。 |

## 安裝方式

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## XMind 執行方式

將 `.xmind` 檔案放到 `input_xmind/`。

如果資料夾裡有多個 XMind，直接執行會先列出可處理檔案與狀態：

```bash
python main.py xmind
```

指定單一 XMind：

```bash
python main.py xmind --input EGTDigital_test_cases.xmind
```

輸出位置預設為：

```text
xmind_detail/<Vendor>/
```

例如：

```text
input_xmind/Vibra_Gaming_test_case.xmind -> xmind_detail/Vibra_Gaming/
input_xmind/EGTDigital_test_cases.xmind -> xmind_detail/EGTDigital/
```

也可以手動指定 Vendor：

```bash
python main.py xmind --input EGTDigital_test_cases.xmind --vendor EGTDigital
```

## XMind 輸出檔案說明

- `xmind_detail/<Vendor>/raw/*_raw.json`：完整 raw parse 結果，用於除錯與 parser 改良。
- `xmind_detail/<Vendor>/summary/summary.json`：AI 入口檔，包含案例數、模組統計、標籤統計。
- `xmind_detail/<Vendor>/summary/extraction_report.json`：抽取能力報告。
- `xmind_detail/<Vendor>/summary/duplicate_report.json`：疑似重複案例報告，只標記不刪除。
- `xmind_detail/<Vendor>/modules/*.json`：依模組切分的精簡 JSON。
- `xmind_detail/<Vendor>/tags/*.json`：依標籤切分的精簡 JSON。
- `xmind_detail/<Vendor>/markdown/*.md`：依模組產生的 AI 友善 Markdown。
- `xmind_detail/<Vendor>/excel/knowledge_base.xlsx`：給 QA 人員審查的人類友善 Excel。

## XMind 增量處理策略

程式會讀取既有 `xmind_detail/<Vendor>/raw/*_raw.json` 的統計資訊：

- 如果 `topic_count`、`test_case_count` 與 SHA256 都相同，略過重建。
- 如果 SHA256 不同但 `topic_count` 與 `test_case_count` 相同，會做 case-level update：用 `source.topic_id` 找到同一個 case，若 `content_hash` 不同就替換整個 case，再重建 chunks、Markdown 與 Excel。
- XMind reader 也會保存 `source_meta/<file>_source_meta.json`，包含來源檔案大小、修改時間與 SHA256。
- 如果 `test_case_count` 增加，只追加新測項。
- 如果 `topic_count` 或 `test_case_count` 減少，保留既有 JSON 與 Markdown，不刪除 Codex 可讀取的知識。
- 如果 topic 數變動但 test case 沒增加，只更新 raw JSON，不重建 AI-facing chunks。

## New Vendor Doc Reader 執行方式

將 Confluence 匯出的 Word/HTML 文件放到：

```text
new_vendor_source/
```

支援：

- `.doc`：Confluence 匯出的 MIME/HTML Word 檔
- `.docx`
- `.html`
- `.htm`

執行：

```bash
python main.py doc --input Vendor_Esoterica.doc
```

輸出位置：

```text
new_vendor_detail/Esoterica/
```

也可以指定 Vendor：

```bash
python main.py doc --input Vendor_Esoterica.doc --vendor Esoterica
```

## New Vendor 中間格式說明

`new_vendor_detail/<Vendor>/api_summary.md`

給 Codex 優先閱讀的 API 摘要，包含：

- source file
- capability profile
- endpoints
- error codes
- sections 摘要

`new_vendor_detail/<Vendor>/endpoints.json`

結構化 API endpoint 清單，讓 Codex 可以快速判斷要讀哪些 API。

`new_vendor_detail/<Vendor>/error_codes.json`

結構化 error code 與 message / exception 對照。

`new_vendor_detail/<Vendor>/capability_profile.json`

規則式偵測 Vendor 可能支援的能力，例如：

- multiple bets
- multiple settlements
- rollback settlements
- modify settlements / adjustment
- cancel bet
- free spin
- jackpot
- idempotency
- retry
- wallet

`new_vendor_detail/<Vendor>/raw_doc.json`

保留解析後的段落、表格與連結，方便之後改良 doc reader。

`new_vendor_detail/<Vendor>/source_meta.json`

保存來源檔案名稱、大小與修改時間。Doc reader 會用這個檔案判斷來源是否已處理過；如果來源檔沒有變更，重複執行時會略過重建。

## JSON Chunking 設計

AI 不應該一開始讀取完整 raw JSON。

建議 Codex 使用順序：

1. 讀 `xmind_detail/<Vendor>/summary/summary.json`
2. 根據需求讀 `modules/*.json` 或 `tags/*.json`
3. 需要更易讀時讀 `markdown/*.md`
4. 追查來源時才讀 raw JSON

New Vendor 流程建議：

1. 讀 `new_vendor_detail/<Vendor>/api_summary.md`
2. 讀 `endpoints.json`
3. 讀 `error_codes.json`
4. 讀 `capability_profile.json`
5. 再對照既有 `xmind_detail/<Vendor or capability knowledge>/modules/*.json`

## AI Token 優化策略

- `xmind_detail` 存放既有測試知識庫。
- `new_vendor_detail` 存放新 Vendor API 文件的中間格式。
- `output` 保留給未來 AI 產生的新測試案例檔案。
- Summary / capability profile 作為入口，避免 Codex 一開始讀完整文件。
- Module / tag chunk 讓 Codex 只讀相關知識。
- Raw JSON 只作為除錯與追查來源使用。

## 未來擴充方向

- 強化 doc reader 對 Confluence 表格的 endpoint request / response 欄位歸類。
- 增加人工可編輯的 capability profile override。
- 加入 new vendor test case generation，但必須明確讀取中間格式與既有 capability knowledge。
- 支援更多文件來源，例如 PDF OCR 後的 Markdown。

## 已知限制

- `.doc` 目前主要支援 Confluence 匯出的 MIME/HTML Word 檔；舊式二進位 Word 可能需要先轉成 `.docx`。
- capability profile 是規則式偵測，仍需要人工確認。
- endpoint method 如果文件沒有清楚標示，會顯示 `unknown`。
- Word 圖片、截圖、流程圖中的文字不會自動 OCR。
