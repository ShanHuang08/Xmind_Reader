# XMind Reader

## 專案目的

本專案有四個資料整理流程：

1. `input_xmind/` -> `xmind_detail/`
   讀取已整理好的 XMind 測試案例知識庫，輸出給 Codex/AI 閱讀的 JSON、Markdown。

2. `new_vendor_source/` -> `new_vendor_detail/`
   讀取新 Vendor 的 Confluence 匯出 Word/HTML 文件，先整理成 Codex 好閱讀的中間格式，例如 API summary、endpoints、error codes、capability profile。

3. PDF -> `new_vendor_detail/<Vendor>/vendor_pdf/`
   讀取 Vendor 額外提供的 PDF API 文件，產生可供 Codex 補充查詢的 validation report、endpoint index、API section chunks 與 full text Markdown。PDF Reader 是次要參考來源，不是主要生成來源。

4. `new_vendor_detail/` -> `output/`
   根據已整理好的 Vendor 中間格式，產生 Codex 工作用的 draft JSON 鷹架，準備給後續 AI 生成測試案例使用。

根目錄的 `output/` 保留給 AI 產生完成的新 Vendor 測試案例，例如 `newvendor_test_case.xmind`，不再放 XMind reader 的知識庫輸出。

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
    vendor_master_checklist.json
    raw_doc.json
    source_meta.json
    vendor_pdf/
      manifest.json
      validation_report.json
      endpoint_index.json
      full_text.md
      sections/
xmind_detail/
  <Vendor>/
    summary/
    modules/
    tags/
    markdown/
    raw/
    source_meta/
output/
  <Vendor>/
    draft_test_cases.json
src/
  parser/
  extractor/
  chunker/
  exporters/
  doc_reader/
  pdf_reader/
  generator/
  xmind_reader_main.py
  doc_reader_main.py
  pdf_reader_main.py
  draft_main.py
```

## 各檔案功能說明

### 統一入口

| 檔案 | 功能 |
|---|---|
| `main.py` | **CLI 統一入口**。提供 `xmind`、`doc`、`pdf`、`draft` 四個子命令，根據使用者選擇分別委派給對應的 `*_main.py` 執行。負責 `sys.path` 設定與引數轉發。 |

### XMind 流程 (`python main.py xmind`)

| 檔案 | 功能 |
|---|---|
| `src/xmind_reader_main.py` | **XMind 流程主控制器**。負責：(1) 解析 CLI 引數、解析輸入檔案路徑；(2) 呼叫 `xmind_reader` 解析 → `knowledge_extractor` 抽取知識 → `knowledge_chunker` 切分 → 各 exporter 輸出；(3) 增量處理決策（比對 SHA256、topic/case 數量決定 skip / full / incremental / preserve / raw_only）；(4) 新舊 case 合併（用 `topic_id` 識別同一個 case，`content_hash` 判斷是否需替換）。 |
| `src/parser/xmind_reader.py` | **XMind 檔案解析核心**。把 `.xmind`（ZIP 檔）解開，自動偵測 `content.json`（新版）或 `content.xml`（舊版）並解析為 sheets → topics 樹狀結構。提取每個 topic 的標題、ID、路徑、markers、notes、labels、超連結。辨識 `case：` 開頭的 topic 為測試用例，從子節點抽出結構化欄位（ID、前置條件、步驟、預期結果等）。 |
| `src/extractor/knowledge_extractor.py` | **知識抽取與正規化**。把 parser 輸出的 raw source cases 轉換為精簡的 knowledge cases：推斷 `module`、`api_name`，用關鍵字規則自動打 `tags`（positive / negative / boundary / validation / idempotency 等 18 種），抽取 `validation_points`、`db_checks`，並計算 `content_hash`（SHA256）供增量更新使用。 |
| `src/chunker/knowledge_chunker.py` | **知識切分與重複偵測**。將 knowledge cases 依 `module` 切分為 module chunks、依 `tags` 切分為 tag chunks，方便 AI 按需讀取。同時用 `SequenceMatcher` 偵測相似度 ≥ 92% 的疑似重複 case（只標記不移除）。 |
| `src/exporters/json_exporter.py` | **JSON 匯出模組**。提供多個函式：`export_raw`（raw JSON）、`export_source_meta`（來源檔 meta）、`export_summary`（摘要）、`export_extraction_report`（抽取報告）、`export_duplicate_report`（重複報告）、`export_chunks`（module / tag 切分 JSON）。 |
| `src/exporters/markdown_exporter.py` | **Markdown 匯出模組**。把 module chunks 轉為 AI 友善的 `.md` 檔案。每個模組一個檔，內部依 primary tag 分組，列出 case ID、scenario、validation points、db checks。 |

### Doc Reader 流程 (`python main.py doc`)

| 檔案 | 功能 |
|---|---|
| `src/doc_reader_main.py` | **Doc Reader 流程主控制器**。負責：(1) 解析 CLI 引數、解析輸入檔案路徑；(2) 檢查 `source_meta.json` 判斷來源是否已處理過，未變更則跳過；(3) 依序呼叫 `doc_parser` → `doc_extractor` → `doc_exporter`。 |
| `src/doc_reader/doc_parser.py` | **文件解析核心**。讀取 Confluence 匯出的 Word/HTML 文件。`.doc` 走 MIME/HTML 解碼，`.docx` 走 python-docx，`.html` 走 lxml。輸出結構化資料：標題、段落、表格（含 checkbox 狀態）、連結、純文字。 |
| `src/doc_reader/doc_extractor.py` | **Vendor API 知識抽取**。從 parsed 文件中提取：(1) API endpoints（用正則匹配 `/api/...`）；(2) error codes（從表格或文字中用正則匹配）；(3) vendor master checklist（從表格中識別 Name + Enable 欄位）；(4) capability profile（用關鍵字規則偵測 Vendor 支援的能力，如 multiple_bets、rollback、free_spin 等，並優先採用 checklist 結果）。 |
| `src/doc_reader/doc_exporter.py` | **Vendor Detail 匯出模組**。將抽取結果寫入 7 個檔案：`api_summary.md`（給 Codex 優先閱讀的 API 摘要）、`endpoints.json`、`error_codes.json`、`capability_profile.json`、`vendor_master_checklist.json`、`source_meta.json`、`raw_doc.json`。 |

### PDF Reader 流程 (`python main.py pdf`)

| 檔案 | 功能 |
|---|---|
| `src/pdf_reader_main.py` | **PDF Reader 流程主控制器**。負責解析 CLI 引數、執行 PDF validation、呼叫 `pymupdf4llm` 轉 Markdown、建立 endpoint index、切分 API section chunks，最後輸出到 `new_vendor_detail/<Vendor>/vendor_pdf/`。 |
| `src/pdf_reader/pdf_validator.py` | **PDF 可讀性驗證**。使用 PyMuPDF 檢查 PDF 是否有可抽取文字。如果是掃描或圖片型 PDF，只輸出 validation report，不做 OCR。 |
| `src/pdf_reader/pdf_markdown_reader.py` | **PDF Markdown 轉換**。使用 `pymupdf4llm` 將 PDF 轉成 `full_text.md`。此檔只做除錯或 fallback，不建議 Codex 優先讀取。 |
| `src/pdf_reader/pdf_endpoint_indexer.py` | **Endpoint Index 建立器**。用實用 regex 偵測 `GET /xxx`、`POST /xxx`、`/api/xxx`、`endpoint:`、`URL:`、`Path:` 等格式，產生 `endpoint_index.json`。 |
| `src/pdf_reader/pdf_section_chunker.py` | **API Section Chunker**。依 endpoint/API 區塊切分，不產生 `page_001.json` 這類 page-level JSON。 |
| `src/pdf_reader/pdf_exporter.py` | **PDF 輸出模組**。輸出 `manifest.json`、`validation_report.json`、`endpoint_index.json`、`sections/*.json`、`full_text.md`。 |

### Draft 流程 (`python main.py draft`)

| 檔案 | 功能 |
|---|---|
| `src/draft_main.py` | **Draft 流程主控制器**。接收 `--vendor` 必選引數，呼叫 `draft_builder` 從 `new_vendor_detail/<Vendor>/` 讀取已整理的中間格式，產生 draft JSON 到 `output/<Vendor>/draft_test_cases.json`。 |
| `src/generator/draft_builder.py` | **Draft JSON 鷹架建構器**。讀取 `capability_profile.json`、`endpoints.json`、`error_codes.json`、`vendor_master_checklist.json`，組合出 Codex 工作用的 draft 檔。包含：endpoint 角色推斷（authentication / bet / settlement / rollback 等）、前置條件撰寫模板、備註撰寫規則、`generation_mapping`（category → XMind section 對應表、mandatory / capability-specific categories、case routing fields）、pending user questions。`test_cases` 欄位留空，等後續 AI 生成填入。 |

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
- `xmind_detail/<Vendor>/source_meta/*_source_meta.json`：來源檔案 meta（檔名、大小、修改時間、SHA256）。

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

## PDF Reader 執行方式

PDF Reader 是 Vendor API 文件的補充讀取器。主要來源仍然是 DOC/HTML reader 產生的 `new_vendor_detail/<Vendor>/` 檔案。

PDF Reader 適合用在 Vendor 額外提供 API spec PDF，而且 Codex 需要補查 endpoint 細節時。

執行範例：

```bash
python main.py pdf --pdf EGT_Digital_Integration_API_Spec_v1.28.pdf --vendor EGT_Digital
```

也可以指定完整 PDF 路徑：

```bash
python main.py pdf --pdf C:\Users\Shan\Workspace2\Xmind_Reader\EGT_Digital_Integration_API_Spec_v1.28.pdf --vendor EGT_Digital
```

預設輸出：

```text
new_vendor_detail/<Vendor>/vendor_pdf/
```

如果 `--output` 指到 `vendor_pdf` 結尾，程式會直接使用該資料夾：

```bash
python main.py pdf --pdf Vendor_API.pdf --vendor NewVendor --output new_vendor_detail/NewVendor/vendor_pdf
```

## PDF Reader 輸出檔案說明

`new_vendor_detail/<Vendor>/vendor_pdf/validation_report.json`

PDF 讀取前的驗證報告，包含：

- readable
- ocr_required
- page_count
- total_text_length
- avg_text_length_per_page
- status

如果 PDF 是圖片或掃描檔：

- 不讀取 PDF 內容
- 不產生 `endpoint_index.json`
- 不產生 `sections/*.json`
- 只產生 validation report 與 manifest
- log 會明確提示 OCR required，但 OCR 不在目前範圍內

`new_vendor_detail/<Vendor>/vendor_pdf/manifest.json`

PDF reader 的入口檔案，讓 Codex 知道這份 PDF 是否可讀、總共有多少 endpoint / section，以及有哪些輸出檔。

`new_vendor_detail/<Vendor>/vendor_pdf/endpoint_index.json`

Codex 查 PDF 補充資料時應該先讀的索引。它會列出 endpoint、method、section file、keywords、confidence。Codex 應該依這個檔案決定要讀哪個 section JSON。

`new_vendor_detail/<Vendor>/vendor_pdf/sections/*.json`

依 API endpoint 切分的 section chunks。這裡不產生 `page_001.json`、`page_002.json`，避免 100 頁 PDF 變成 100 個碎檔。

`new_vendor_detail/<Vendor>/vendor_pdf/full_text.md`

完整 PDF Markdown，僅供除錯或 fallback。Codex 不應該優先讀它，除非 `endpoint_index.json` 或 section chunks 不足以判斷。

## Codex 閱讀順序

新 Vendor 產生測項時，建議 Codex 依序讀：

1. `output/<Vendor>/draft_test_cases.json`
2. `new_vendor_detail/<Vendor>/capability_profile.json`
3. `new_vendor_detail/<Vendor>/endpoints.json`
4. `new_vendor_detail/<Vendor>/error_codes.json`
5. 必要時才讀 `new_vendor_detail/<Vendor>/api_summary.md`
6. 如果 DOC/HTML 資訊不足，再讀 `new_vendor_detail/<Vendor>/vendor_pdf/manifest.json`
7. 再讀 `new_vendor_detail/<Vendor>/vendor_pdf/endpoint_index.json`
8. 依 `endpoint_index.json` 只讀需要的 `vendor_pdf/sections/*.json`
9. 除錯時才讀 `raw_doc.json`
10. 除錯或 fallback 時才讀 `vendor_pdf/full_text.md`

重點：PDF Reader 是補充來源。Codex 應以 DOC/HTML reader output 作為主要來源。

## Draft JSON 建立方式

當 `new_vendor_detail/<Vendor>/` 已經建立完成後，可以建立給 Codex 使用的新測項 draft JSON：

```bash
python main.py draft --vendor Esoterica
```

輸出：

```text
output/Esoterica/draft_test_cases.json
```

這份 draft JSON 不是最終測項，而是 Codex 後續產測項前要讀取的工作檔。內容包含：

- capability profile
- vendor master checklist
- endpoint roles
- request / response parameter tables
- error codes
- 前置條件與備註撰寫規則
- pending user questions
- 空的 `test_cases`

後續產生測項與 XMind writer 的方向記錄在：

```text
GENERATION_PLAN.md
```

## JSON Chunking 設計

AI 不應該一開始讀取完整 raw JSON。

建議 Codex 使用順序：

1. 讀 `xmind_detail/<Vendor>/summary/summary.json`
2. 根據需求讀 `modules/*.json` 或 `tags/*.json`
3. 需要更易讀時讀 `markdown/*.md`
4. 追查來源時才讀 raw JSON

New Vendor 流程建議：

1. 先讀 `output/<Vendor>/draft_test_cases.json`
2. 讀 `new_vendor_detail/<Vendor>/capability_profile.json`
3. 讀 `new_vendor_detail/<Vendor>/endpoints.json`
4. 讀 `new_vendor_detail/<Vendor>/error_codes.json`
5. 必要時才讀 `new_vendor_detail/<Vendor>/api_summary.md`
6. DOC/HTML 資訊不足時，才讀 `new_vendor_detail/<Vendor>/vendor_pdf/manifest.json` 與 `endpoint_index.json`
7. 依 `endpoint_index.json` 只讀必要的 `vendor_pdf/sections/*.json`
8. 再對照既有 `xmind_detail/<Vendor or capability knowledge>/modules/*.json`
9. 除錯時才讀 `raw_doc.json` 或 `vendor_pdf/full_text.md`

## AI Token 優化策略

- `xmind_detail` 存放既有測試知識庫。
- `new_vendor_detail` 存放新 Vendor API 文件的中間格式。
- `output` 保留給未來 AI 產生的新測試案例檔案。
- Summary / capability profile 作為入口，避免 Codex 一開始讀完整文件。
- Module / tag chunk 讓 Codex 只讀相關知識。
- Raw JSON 只作為除錯與追查來源使用。

## 未來擴充方向

詳細規格請參考 [GENERATION_PLAN.md](GENERATION_PLAN.md)。

- **Test Case Map 重新分類**：將現有知識庫改為依 `parameter_validation` 與 `user_behavior` 兩大類別組織，不以 endpoint 資料夾分類。
- **Capability 驅動的預期結果**：測試案例的 expected results 依 `capability_profile.json` 決定（如 multiple_bets、rollback_settlements 等）。
- **Test Case Generator（Step 2）**：讓 Codex 讀取 draft JSON + 現有知識 chunks，將產生的案例寫回 `test_cases` 陣列，不直接輸出 XMind。
- **XMind Writer（Step 3）**：將驗證過的 draft JSON 轉換為 `<Vendor>_test_cases.xmind`，保留現有 reader 可讀的結構。
- **Generation Mapping**：在 draft JSON 中寫入 category → XMind section 對應表，讓 Codex 產生前先知道每個案例該放哪裡。
- **Endpoint Role 分類**：每個 endpoint 必須有明確角色（authentication / bet / settlement / rollback 等）才能產生案例。
- **強化 doc reader**：改善 Confluence 表格的 endpoint request / response 欄位歸類。
- **Capability profile override**：增加人工可編輯的 override 機制。
- **更多文件來源**：例如 PDF OCR 後的 Markdown。

## 已知限制

- `.doc` 目前主要支援 Confluence 匯出的 MIME/HTML Word 檔；舊式二進位 Word 可能需要先轉成 `.docx`。
- capability profile 是規則式偵測，仍需要人工確認。
- endpoint method 如果文件沒有清楚標示，會顯示 `unknown`。
- Word 圖片、截圖、流程圖中的文字不會自動 OCR。
