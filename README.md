# XMind Reader

## 專案目的

本專案是 Vendor API 測試知識管理工具，解決一個核心問題：**如何把分散在 XMind 測試地圖、Confluence 文件、PDF、網頁 URL 中的 Vendor API 測試知識，整理成 AI（Codex）能高效讀取和使用的格式。**

專案包含五個資料整理流程：

1. **XMind 知識庫讀取** (`input_xmind/` → `xmind_detail/`)
   解析已整理好的 XMind 測試案例，抽出結構化欄位（ID、前置條件、步驟、預期結果），按模組和標籤切分為 JSON chunk，供 AI 按需讀取。

2. **Vendor 文件解析** (`new_vendor_source/` → `new_vendor_detail/`)
   讀取新 Vendor 的 Confluence 匯出文件，抽取 API endpoints、error codes、capability profile 等結構化知識。

3. **URL 補充讀取** (URL → `new_vendor_detail/<Vendor>/vendor_url/`)
   抓取 Vendor API 文件網頁，支援靜態 URL + Playwright browser fallback + OpenAPI JSON 自動偵測。

4. **PDF 補充讀取** (PDF → `new_vendor_detail/<Vendor>/vendor_pdf/`)
   解析 Vendor 額外提供的 PDF API 文件，產生 endpoint index 和 section chunks。

5. **測試案例生成** (`new_vendor_detail/` → `output/`)
   從 Vendor 中間格式建立 draft JSON、自動產生 parameter validation 測試案例、輸出 MeterSphere 相容的 XMind 檔，並回讀驗證。


## 安裝方式

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

主要依賴：`lxml`、`python-docx`、`beautifulsoup4`、`markdownify`、`pymupdf4llm`。


## 執行方式

統一透過 `main.py` 進入，支援五個子命令：

> macOS / Linux 若沒有 `python` 指令，請將以下範例中的 `python` 改為 `python3`，例如 `python3 main.py xmind`。

### XMind 知識庫讀取

```bash
# 掃描 input_xmind/ 列出可處理檔案
python main.py xmind

# 指定單一檔案
python main.py xmind --input EGTDigital_test_cases.xmind

# 指定 Vendor 名稱
python main.py xmind --input EGTDigital_test_cases.xmind --vendor EGTDigital
```

### Vendor 文件解析

```bash
python main.py doc --input Vendor_Esoterica.doc
python main.py doc --input Vendor_Esoterica.doc --vendor Esoterica
```

### URL 補充讀取

```bash
python main.py url --url https://vendor.example.com/api-docs --vendor NewVendor
python main.py url --url http://docs.gpk.asia/seamless-wallet --vendor GPK --username gpkdoc --password gpkdoc
python main.py url --html exported_vendor_doc.html --url https://vendor.example.com/api-docs --vendor NewVendor
```

### PDF 補充讀取

```bash
python main.py pdf --pdf Vendor_API_Spec.pdf --vendor Vendor
```

### 測試案例生成

```bash
python main.py generate --vendor Esoterica
```

一次執行：建立 draft JSON → 產生 parameter validation 案例 → 輸出 XMind → 回讀驗證。


## 核心設計概念

### 資料夾用途

| 資料夾 | 存放資料 | 設計原因 |
|---|---|---|
| `input_xmind/` | 原始 XMind 測試知識庫 | 人工維護的黃金參考來源，不動 |
| `new_vendor_source/` | 原始 Vendor API 文件（doc/html） | 保留原始文件，reader 可以重複執行 |
| `new_vendor_detail/` | Vendor 知識中間格式 | 結構化的 API 知識，供 Codex 和 generator 讀取 |
| `xmind_detail/` | XMind reader 輸出（chunk + Markdown） | AI 友好的知識切分結果 |
| `output/` | draft JSON + 生成的 XMind | AI 工作檔和最終產出 |

### 為什麼把 JSON 拆成 chunk

**目的：減少 AI token 消耗。**

原始 XMind 的 raw JSON 可能很大（幾千個 topic、上千個測試案例），如果 AI 一次讀完整個檔案會浪費大量 token 在不相關的內容上。所以設計了分層讀取：

- `summary.json`：只有統計數字，幾百 token 就能了解全局
- `modules/*.json`：按模組切分，AI 只讀需要的模組
- `tags/*.json`：按標籤切分（positive / negative / boundary 等），AI 依測試意圖讀取
- `markdown/*.md`：更易讀的版本，適合快速瀏覽
- `raw/*.json`：完整原始資料，只在除錯時使用

**增量更新**：程式會比對 SHA256 和統計數字，只有檔案真正改變時才重建。如果只有少數 case 內容更新，只做 case-level 替換，不重建全部 chunk。


### 增量處理策略

- `topic_count`、`test_case_count` 與 SHA256 都相同 → 略過重建
- SHA256 不同但統計相同 → case-level update（用 `content_hash` 判斷替換）
- `test_case_count` 增加 → 只追加新案例
- `topic_count` 或 `test_case_count` 減少 → 保留既有知識，不刪除
- topic 數變動但 case 沒增加 → 只更新 raw JSON


## 專案架構

```text
input_xmind/                          XMind 來源
new_vendor_source/                    Vendor 文件來源
new_vendor_detail/
  <Vendor>/
    api_summary.md                    API 摘要（Codex 入口）
    endpoints.json                    結構化 endpoint 清單
    error_codes.json                  Error code 對照
    capability_profile.json           Vendor 支援能力
    vendor_master_checklist.json      Vendor 功能 checklist
    raw_doc.json                      解析後原始段落/表格
    source_meta.json                  來源檔 meta
    vendor_pdf/                       PDF reader 輸出
    vendor_url/                       URL reader 輸出
xmind_detail/
  <Vendor>/
    summary/                          統計與報告
    modules/                          按模組切分 JSON
    tags/                             按標籤切分 JSON
    markdown/                         AI 友好 Markdown
    raw/                              原始 parse 結果
    source_meta/                      來源檔 meta
output/
  <Vendor>/
    draft_test_cases.json             工作 draft（含生成案例）
    <Vendor>_test_cases.xmind         生成的 XMind
    <Vendor>_test_cases_validation_report.json
src/
  main.py                             CLI 統一入口
  xmind_reader_main.py                XMind 流程控制
  doc_reader_main.py                  Doc 流程控制
  pdf_reader_main.py                  PDF 流程控制
  url_reader_main.py                  URL 流程控制
  generator_main.py                   Generate 流程控制
  parser/                             XMind 解析
  extractor/                          知識抽取
  chunker/                            知識切分
  exporters/                          JSON/Markdown 匯出
  doc_reader/                         文件解析與抽取
  pdf_reader/                         PDF 解析
  url_reader/                         URL 抓取與解析
  generator/                          Draft 建立、Schema、驗證、案例生成
  xmind_writer/                       XMind 寫入與驗證
```


## 各檔案功能說明

### 統一入口

| 檔案 | 功能 |
|---|---|
| `main.py` | CLI 統一入口，提供 `xmind`、`doc`、`pdf`、`url`、`generate` 五個子命令，委派給對應的 `*_main.py` 執行。 |

### XMind 流程 (`python main.py xmind`)

| 檔案 | 功能 |
|---|---|
| `xmind_reader_main.py` | 流程主控制器。解析 CLI 引數，依序呼叫 parser → extractor → chunker → exporter，並做增量處理決策（skip / full / incremental / preserve / raw_only）。 |
| `parser/xmind_reader.py` | XMind 解析核心。解開 ZIP、自動偵測 `content.json` 或 `content.xml`，解析為 sheets → topics 樹狀結構，辨識 `case：` 開頭的測試用例並抽出結構化欄位。 |
| `extractor/knowledge_extractor.py` | 知識抽取。推斷 module / api_name，用 18 種關鍵字規則自動打 tags，抽取 validation_points / db_checks，計算 content_hash 供增量更新。 |
| `chunker/knowledge_chunker.py` | 知識切分。依 module 和 tags 切分為 chunk，用 SequenceMatcher 偵測 ≥92% 相似度的疑似重複 case。 |
| `exporters/json_exporter.py` | JSON 匯出。輸出 raw、source_meta、summary、extraction_report、duplicate_report、chunks。 |
| `exporters/markdown_exporter.py` | Markdown 匯出。每個模組一個 `.md`，依 primary tag 分組列出案例。 |

### Doc Reader 流程 (`python main.py doc`)

| 檔案 | 功能 |
|---|---|
| `doc_reader_main.py` | 流程主控制器。檢查 `source_meta.json` 判斷是否已處理，未變更則跳過。 |
| `doc_reader/doc_parser.py` | 文件解析。`.doc` 走 MIME/HTML 解碼，`.docx` 走 python-docx，`.html` 走 lxml。輸出段落、表格（含 checkbox）、連結。 |
| `doc_reader/doc_extractor.py` | Vendor API 知識抽取。提取 endpoints（regex）、error codes、vendor master checklist、capability profile（關鍵字規則 + checklist 優先）、request/response parameter tables 和 example。 |
| `doc_reader/doc_exporter.py` | 匯出 7 個檔案：api_summary.md、endpoints.json、error_codes.json、capability_profile.json、vendor_master_checklist.json、source_meta.json、raw_doc.json。 |

### PDF Reader 流程 (`python main.py pdf`)

| 檔案 | 功能 |
|---|---|
| `pdf_reader_main.py` | 流程主控制器。執行 validation → Markdown 轉換 → endpoint index → section chunking。 |
| `pdf_reader/pdf_validator.py` | PDF 可讀性驗證。檢查是否有可抽取文字；掃描版只輸出報告，不做 OCR。 |
| `pdf_reader/pdf_markdown_reader.py` | 用 `pymupdf4llm` 轉 Markdown，僅供除錯或 fallback。 |
| `pdf_reader/pdf_endpoint_indexer.py` | Endpoint index 建立器。偵測 GET/POST、`/api/xxx`、action-style 等格式，含 wallet endpoint role 對應。 |
| `pdf_reader/pdf_section_chunker.py` | 依 endpoint 切分 section，不產生 page-level JSON。 |
| `pdf_reader/pdf_exporter.py` | 輸出 manifest、validation_report、endpoint_index、sections/、full_text.md。 |

### URL Reader 流程 (`python main.py url`)

| 檔案 | 功能 |
|---|---|
| `url_reader_main.py` | 流程主控制器。抓取 URL 或讀取本地 HTML，自動偵測 OpenAPI JSON 或 HTML，合併 endpoint index + action index，切分 section chunks。 |
| `url_reader/url_fetcher.py` | URL 抓取。全平台優先用 `urllib`，Windows 補用 PowerShell fallback。靜態失敗時自動嘗試 Playwright Chromium。提供 `is_openapi_like()` 偵測 OpenAPI schema。 |
| `url_reader/html_markdown_reader.py` | HTML → Markdown。優先用 BeautifulSoup + markdownify，否則用內建 parser。自動清除 script/style/nav/footer。 |
| `url_reader/openapi_reader.py` | OpenAPI JSON → Markdown。將 `paths` 轉為 endpoint / method / parameters / responses 表格。 |
| `url_reader/action_indexer.py` | Wallet action index。偵測 `action: bet`、`action: win` 等格式，自動分類 role（balance / bet / settlement / rollback），補充 PDF endpoint indexer 漏抓的 wallet action。 |
| `url_reader/url_section_chunker.py` | 依 endpoint index 切分 section chunks。 |
| `url_reader/url_exporter.py` | 輸出 manifest、validation_report、endpoint_index、sections/、full_text.md。結構與 PDF reader 對齊。 |

### Generate 流程 (`python main.py generate`)

| 檔案 | 功能 |
|---|---|
| `generator_main.py` | 流程主控制器。依序：build_draft → generate_test_cases → write_xmind → validate。 |
| `generator/draft_builder.py` | Draft JSON 鷹架。讀取 capability_profile / endpoints / error_codes / checklist，組合 draft 檔。包含 endpoint 角色推斷、前置條件模板、generation_mapping（category → XMind section 對應表）。 |
| `generator/draft_schema.py` | Draft schema 常數。定義 `SCHEMA_VERSION`、XMind 欄位標籤、API parameter test 合約、allowed output sections、category → section mapping、required/optional 欄位、negative keywords。 |
| `generator/draft_validator.py` | Draft JSON 驗證器。檢查 required fields、output_section 合法性、category → section routing、scenario 格式、preconditions/remarks 標籤、steps 完整性、expected_error、id 唯一性。 |
| `generator/case_generation_context.py` | 生成上下文。從 draft 取出 generation context（capability_profile、endpoint_roles、endpoint_analysis、error_codes），選擇 parameter error code，產生預設測試帳號。 |
| `generator/endpoint_analyzer.py` | Endpoint topology / parameter semantics 分析器。從 endpoint role 和 request parameters 判斷 betAndSettle combined endpoint、multiple bets endpoint 形態、settlement 是否有 round-end control parameter / jackpot control parameter。 |
| `generator/reference_selector.py` | 參考知識選擇。依 capability_profile + endpoint_analysis 選擇 mandatory、conditional mandatory、capability-specific categories，並找出對應的 xmind_detail chunk 檔案作為參考。 |
| `generator/test_case_generator.py` | 測試案例生成器（第一版：parameter validation）。遍歷每個 endpoint 的 request parameters，自動產生「缺失 / 空值 / 錯誤值」等 negative case，含 request payload 和 expected error response。 |
| `xmind_writer/metersphere_profile_extractor.py` | MeterSphere profile 提取。從 golden XMind 參考檔抽出 case 欄位風格、topic 深度、writer guidance，供 writer 遵循。 |
| `xmind_writer/metersphere_xmind_writer.py` | XMind 寫入器。將驗證過的 draft 寫為 XMind ZIP（content.json + metadata.json + manifest.json），依 output_section 建立層級結構。 |
| `xmind_writer/xmind_validator.py` | XMind 回讀驗證。用 xmind_reader 讀回生成的 XMind，比對 case 數量、scenario、層級結構是否正確。 |


## Codex 閱讀順序

### XMind 知識庫

1. 讀 `xmind_detail/<Vendor>/summary/summary.json`
2. 根據需求讀 `modules/*.json` 或 `tags/*.json`
3. 需要更易讀時讀 `markdown/*.md`
4. 追查來源時才讀 raw JSON

### 新 Vendor 生成

1. `output/<Vendor>/draft_test_cases.json`
2. `new_vendor_detail/<Vendor>/capability_profile.json`
3. `new_vendor_detail/<Vendor>/endpoints.json`
4. `new_vendor_detail/<Vendor>/error_codes.json`
5. 必要時才讀 `api_summary.md`
6. DOC/HTML 不足時讀 `vendor_pdf/manifest.json` → `endpoint_index.json` → 需要的 `sections/*.json`
7. URL 補充時讀 `vendor_url/manifest.json` → `endpoint_index.json` → 需要的 `sections/*.json`
8. 對照既有 `xmind_detail/<Vendor>/modules/*.json`
9. 除錯才讀 `raw_doc.json`、`vendor_pdf/full_text.md` 或 `vendor_url/full_text.md`

重點：DOC/HTML reader output 是主要來源，PDF Reader 與 URL Reader 是補充來源。


## 已知限制

- `.doc` 主要支援 Confluence 匯出的 MIME/HTML Word 檔；舊式二進位 Word 需先轉 `.docx`。
- capability profile 是規則式偵測，仍需人工確認。
- endpoint method 如果文件沒有清楚標示，會顯示 `unknown`。
- Word 圖片、截圖、流程圖中的文字不會自動 OCR。
- PDF Reader 不做 OCR；掃描版或圖片型 PDF 只輸出 validation report。
- URL 靜態抓取不一定能處理 JavaScript render 的文件（Stoplight、Swagger UI、Redoc）。


## Vendor Doc Reader 目前限制與改進方向

目前限制：

- Confluence 匯出的 `.doc` 表格如果欄位跨列、換行或 section 標題包含多個 endpoint，request / response table 可能會配錯 endpoint。
- 文件中的 request URL example 不一定會被保留下來。
- response format 若只出現在文字段落或 code block 而非表格，目前不一定能完整抽取。
- optional parameter 是否放進 request example 仍依規則推斷。
- error response example 目前套用同一個 response shape，再把 code/message 替換。
- `game code` 表格欄位空白時使用 fallback。
- parameter normal value 是 heuristic，仍可能和 vendor 真實格式不同。

改進方向：

- 增加 code block / URL example extractor，保留原始 request URL、JSON body、success/error response。
- 將 request/response example 寫入 `endpoints.json` 並記錄 `example_source`。
- 增加 endpoint section parser profile，處理同一 heading 包含多個 endpoint 的情況。
- 建立 parameter value generator profile，依 type / description / enum / format 產生更接近 vendor 文件的值。
- 建立 error code selector，依 parameter name / endpoint role 選擇更準確的 error code。
- 在 validation report 中列出使用 heuristic 的欄位，方便人工 review。


## PDF / URL Reader 目前限制與改進方向

PDF Reader 限制：

- 依賴可抽取文字，不做 OCR。
- `pymupdf4llm` 不可用時 fallback 到 `pdfplumber`，品質較不穩定。
- 從網頁列印的 PDF 可能混入頁首、頁尾、導覽列。
- 章節標題若非 Markdown heading，需靠 regex 判斷，可能漏抓。
- 複雜表格只做基本 Markdown 化。

URL Reader 限制：

- 靜態抓取不一定能處理 JavaScript render 文件。
- Playwright fallback 需要可用的 Chromium binary。
- 企業網路、憑證、代理、Cloudflare 可能導致抓取失敗。
- 不處理複雜登入流程、SSO、MFA、cookie session。
- Stoplight 類文件尚未直接讀取底層 OpenAPI schema。
- 多 URL vendor 仍需逐頁處理。

PDF Reader 改進方向：

- 加入 OCR 選項。
- 強化表格解析，輸出 JSON schema。
- 增加 endpoint/action 偵測規則。
- 加入頁首頁尾清理。
- 建立 extraction report 標記抽取信心度。

URL Reader 改進方向：

- 優先偵測 OpenAPI / Swagger JSON schema。
- 支援多 URL 合併。
- 將 parameters / error codes 從 section text 結構化為 JSON。
- 增加 browser fallback 快取。
- 加入 source hash / fetched_at 跳過未變更文件。


## 未來擴充方向

詳細規格請參考 [GENERATION_PLAN.md](GENERATION_PLAN.md)。

### User Behavior 案例生成（下一階段重點）

目前 `test_case_generator.py` 只覆蓋 parameter validation（每個 endpoint 的每個 parameter 產生 negative cases）。User Behavior 需要覆蓋完整的業務流程測試。

**方案：Scenario Templates XMind**

手動維護一份 `scenario_templates.xmind`，以 category 驅動、配合 `capability_profile.supports`，透過現有 xmind_reader 管線分解成 JSON chunks 後供 generator 使用。

```
xmind_detail/scenario_templates/   ← 資料夾已建立，等待 XMind 完成
```

XMind 結構分為兩層：

- **Mandatory**：不管 vendor capability 為何都要產生的必要測項（launch game、balance、bet、settlement、rollback、amount precision）
- **Conditional Mandatory**：屬於必要測項，但必須先由 API doc 形態判斷是否可套用。例如 `BetAndSettle` 只有在偵測到 combined bet-and-settlement endpoint 時才選入，最後仍放在 `User Behavior > Bet and Settle`。
- **Capability: xxx**：先依 `capability_profile.supports[xxx]` 決定是否選入，再依 `endpoint_analysis` 選擇正確分支（multiple_bets、multiple_settlements、rollback_settlements、cancel_bet、jackpot、idempotency 等）。`jackpot` 只有在 settlement/result endpoint 真的有 jackpot 相關 request parameters 時才抽；`free_spin` 則改看 bet 或 settlement/result endpoint 是否有 freespin 相關 request parameters。

`endpoint_analyzer.py` 會把完整 endpoint / parameter table 壓縮成小型摘要，讓後續 generator 不必反覆讀完整 vendor doc，也避免抽錯 User Behavior template：

```text
endpoint_roles + request_parameters
  -> endpoint_analysis.endpoint_topology
  -> endpoint_analysis.parameter_semantics
  -> selected User_Behavior_map branch
```

目前已定義的分支：

- `Authenticate`：conditional mandatory。只要 `endpoint_analysis.endpoint_topology.authenticate.mode = endpoint_present`，就抽 `Authenticate > Mandatory > test cases` 底下所有案例。
  - `Authentication is necessary`：只有 API doc 確認 authenticate 是必要的，且沒 call 會回 unauthenticated / unauthorized / invalid token / missing session 類錯誤時才抽。目前案例 title 是 `Bet without authenticate`，先強制放到 `User Behavior > Bet and Settle`。
- `BetAndSettle`：conditional mandatory。只有 `endpoint_analysis.endpoint_topology.bet_and_settle.mode = combined_endpoint` 時才抽。
  - `has_round_end_control_parameter`：combined endpoint 有 round-end control parameter。
  - `no_round_end_control_parameter`：目前用不到，先不抽。
- `multiple_bets`
  - `one_bet_endpoint`：同一個 bet endpoint，可能靠 action/method parameter 控制；User_Behavior_map 結構為 `Multiple Bets > one_bet_endpoint > test cases`。
  - `two_bet_endpoint`：兩個分開的 bet-like endpoints，例如 Bet / Rebet；User_Behavior_map 結構為 `Multiple Bets > two_bet_endpoint > test cases`。
- `multiple_settlements`
  - `has_round_end_control_parameter`：settlement/result endpoint 有 round-end control parameter。
  - `no_round_end_control_parameter`：沒有 round-end control parameter，測項重點改看 transfer posting、balance change、idempotency / duplicate behavior。
- `FreeSpin`：不同 vendor 可能把 freespin 欄位放在 bet 或 settlement/result endpoint；只要這些 endpoint 的 request parameters 有 freespin/free game/free bet/bonus/campaign 相關欄位，就抽 `freespin`。
- `Special test cases`：預留給未來擴充，目前 selector 會跳過，不會抽取或生成。

**實現路徑：**

1. 完成 Scenario Templates XMind 並用 xmind_reader 分解到 `xmind_detail/scenario_templates/`
2. Endpoint Analyzer + Category → Endpoint 反向映射（先判斷 topology / parameter semantics，再找對應 endpoint）
3. Capability-Driven Error Code Selection（依能力決定成功/失敗 + 選擇對應的錯誤碼）
4. Multi-Step Flow Builder（組合多 endpoint payload 成多步驟流程）
5. Draft Validator 擴展（加入 User Behavior scenario 格式驗證規則）

**Blocking dependency：** Python code 變更需等 Scenario Templates XMind 完成後才動工。

### 其他待做項目

- **Test Case Map 重新分類**：將現有知識庫改為依 `parameter_validation` 與 `user_behavior` 兩大類別組織。
- **Capability profile override**：增加人工可編輯的 override 機制。
- **強化 doc reader**：改善 Confluence 表格的 endpoint request / response 欄位歸類。
- **更多文件來源**：例如 PDF OCR 後的 Markdown。
