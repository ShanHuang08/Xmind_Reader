# Rovo MCP Confluence Service Development Plan

## 1. 目標

在 Xmind_Reader 新增一個**唯讀、可替換、明確 opt-in** 的 Confluence source service，讓 Python 接收 Confluence page URL 後，透過 Atlassian Rovo MCP 取得 Markdown 頁面內容，交給新增的 `MarkdownDocumentParser` 轉成現有 `doc_reader` 的 parsed document contract，再沿用既有 extractor 與 exporter 產生：

- `api_summary.md`
- `endpoints.json`
- `error_codes.json`
- `parameter_dependencies.json`
- `parameter_dependency_validation_report.json`
- `capability_profile.json`
- `vendor_master_checklist.json`
- `game_codes.json`
- `source_meta.json`
- `raw_doc.json`

預期使用方式：

```bash
python main.py doc \
  --confluence-url "https://ngvgs.atlassian.net/wiki/spaces/GA/pages/1471053840/Vendor_Alea" \
  --vendor Alea
```

此功能只改變明確提供 `--confluence-url` 的執行路徑。既有本機 `.doc`、`.docx`、`.html`、`.htm` 流程及 `url`、`pdf`、`xmind`、`generate`、`new-vendor` 預設行為都不得改變。

### 1.1 可行性與決策摘要

整體可行性評估為 **8/10（高可行）**。CLI opt-in、`cloudId` discovery、Rovo MCP v2 `getConfluenceContent`、service account authentication、既有流程隔離及 atomic publish 都有清楚的實作路徑。`getConfluenceContent` 可用 `detail="full"` 與 `content_format="markdown"` 要求完整 Markdown 正文；主要風險收斂為 **Markdown 是否完整保留原 Confluence 頁面的表格、code block、checkbox 與連結語意，以及 `MarkdownDocumentParser` 是否能正確建立現有 extractor 所需的結構**。

因此本計畫採以下決策：

- Phase 0 是**不可跳過的 hard gate**，不是可選的 research task。
- Phase 0 未證明資料等價性以前，不得開始 production `MarkdownDocumentParser`、CLI integration 或 `new-vendor` integration。
- 正常路徑仍以 Rovo Markdown 為唯一首選；但 Phase 0 必須同時驗證一條**受控的 Confluence REST API v2 storage-format 備援路徑**。只有 Rovo 已成功讀到同一 page、卻被完整性檢查判定為 Markdown fidelity loss 或 truncation 時，且部署明確啟用 `storage_rest` fallback，才可改讀 `/wiki/api/v2/pages/{id}?body-format=storage`。Authentication、authorization、site mismatch、not found、rate limit 或一般 transport error 一律不得觸發 fallback。
- MVP 只依賴兩個 required tools；其他 Confluence/search/user tools 一律視為 optional，不影響 MVP 啟動。
- 來源內容沒變不代表輸出可沿用；incremental cache key 必須包含 Markdown parser、extractor 與 exporter 的版本。
- Library API 採 async-first；`asyncio.run()` 只存在於同步 CLI entry point。GUI、Jupyter 或其他已有 event loop 的 caller 必須 `await` async facade，不得由 service 偷開或巢狀啟動 event loop。

### 1.2 風險排序

| 優先級 | 風險 | 影響 | 控制方式 |
|---|---|---|---|
| P0 | Rovo Markdown 不完整或被截斷 | parser 無法還原必要結構，或靜默遺失內容 | 明確 truncation evidence + Phase 0 fixture matrix + 受控 REST v2 storage fallback |
| P0 | Markdown parser 與原頁格式不等價 | endpoints、parameters、examples 或 checkbox 解析錯誤 | 與 Confluence 原頁及本機 export 做資料等價性驗收 |
| P0 | service account 實際不可見 page/tool | service 無法在 CI/CD 運作 | 部署權限 checklist + Basic/Bearer 實測 |
| P1 | tool/input schema 隨版本或 auth mode 改變 | runtime call 失敗 | required tool discovery + typed arguments + schema fixture |
| P1 | 只看 content hash 造成舊輸出未重建 | 修正 extractor 後仍使用過期產物 | pipeline fingerprint 納入 cache key |
| P1 | URL 形式過度嚴格 | short/display/viewpage URL 頻繁失敗，降低採用率 | allowlisted deterministic redirect/query resolver；無法唯一解析才報錯 |
| P1 | sync wrapper 在既有 event loop 中被呼叫 | GUI、Jupyter 或 async host 發生 `RuntimeError` | async-first public API + 僅 CLI 使用的 sync adapter + loop-state tests |

## 2. 已確認的外部條件

以下條件以 2026-09-02 的 Atlassian 官方文件、目前 organization admin 畫面與本機 live probe 為基準，開發時仍須先執行 Phase 0 capability spike，避免把會變動的遠端能力寫死：

- Rovo MCP 是 MCP-compatible client 到 Jira、Confluence 等 Atlassian Cloud app 的受控入口。
- `getAccessibleAtlassianResources` 用來列出可存取 site 與 `cloudId`；其他工具呼叫需要明確傳入 `cloudId`。
- Rovo MCP v2 的 `getConfluenceContent` 可依 `content_url` 或 `content_id` 讀取 Confluence content；本服務固定要求 `detail="full"`、`content_format="markdown"`，並以 `include_metadata=true` 取得可用 metadata。Confluence read permission group 所需 scope 為 `read:confluence:agent-interface`，API token authentication 可使用此 read tool。
- Non-interactive service 可使用 personal API token（Basic auth）或 service account API key（Bearer auth）。正式 service 優先採 service account，personal token 只供本機開發。
- API token 不受 OAuth domain allowlist 控制，但仍受 token scope、Rovo MCP Permissions、使用者／service account 的 Confluence 權限及 organization IP allowlist 控制。
- 本計畫的 Rovo contract baseline 是 v2 Streamable HTTP endpoint：`https://mcp.atlassian.com/v2/mcp`。舊 `/v1/sse` 已退役，`/v1/mcp/authv2` 與 v1 tool names 也不得作為本服務的 production contract。Phase 0 仍須以 Basic 與 Bearer 的實際 handshake 驗證核准 endpoint；endpoint 由設定提供，不在 business logic 散落 hard-coded URL。`?tools=all` 只供受控 capability/contract diagnostics，不是 production runtime 的預設 endpoint。
- 本文件中的 **Rovo MCP v2** 指 MCP endpoint/tool contract；**Confluence REST API v2** 只指 `/wiki/api/v2/...` storage fallback。兩者是獨立 transport、credential 與 contract，不得因同為「v2」而混用。
- 本功能不需要 Confluence Public Link。Rovo MCP 使用受驗證身分讀取 private page；是否可建立 public link 是另一個 write/sharing 功能，不在本計畫範圍。

官方參考：

- [Rovo MCP v2 supported tools](https://support.atlassian.com/atlassian-ai-gateway/docs/supported-tools/)
- [Rovo MCP v2 API token authentication](https://support.atlassian.com/atlassian-ai-gateway/docs/configure-authentication-via-api-token/)
- [Rovo MCP organization settings](https://support.atlassian.com/security-and-access-policies/docs/control-atlassian-rovo-mcp-server-settings/)
- [Rovo MCP permissions](https://support.atlassian.com/security-and-access-policies/docs/Configure-Atlassian-Rovo-MCP-server-permission/)
- [Official MCP Python SDK: client transports](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/transports.md)

## 3. 現有架構與不可破壞的邊界

### 3.1 現有主流程

```text
main.py doc
  -> src/doc_reader_main.py
  -> doc_reader.doc_parser.parse_vendor_doc(local_path)
  -> doc_reader.doc_extractor.extract_vendor_detail(parsed, vendor)
  -> doc_reader.doc_exporter.export_vendor_detail(detail, output_root)
  -> new_vendor_detail/<Vendor>/
  -> generator/draft_builder.py
```

`parse_vendor_doc()` 目前只負責本機 DOC/DOCX/HTML。它產出的 parsed document contract 包含 `source_file`、`source_path`、`format`、`title`、`paragraphs`、`tables`、`tables_detailed`、`links`、`plain_text`，後續 extractor 已依賴這個 contract。

`url_reader` 是 supplementary source，輸出到 `vendor_url/`，且具有 urllib/PowerShell/Playwright fallback。Private Confluence 的 Rovo authentication、MCP tool discovery、`cloudId` 與 page ID 都不是一般 HTTP fetch，因此不可把 Rovo token 或 MCP 邏輯塞入 `url_reader.url_fetcher`。

### 3.2 隔離原則

- `parse_vendor_doc(path)` 的 signature 與既有 branch 保持不變。
- `extract_vendor_detail()`、其內部 extraction functions、`export_vendor_detail()` 的程式與既有 public behavior 保持不變；Markdown parser 必須配合現有 contract，而不是讓 extractor 認識 MCP response 或 Markdown syntax。
- 如果 Markdown 內容無法對應既有 contract，修正責任在 `MarkdownDocumentParser` 或 validation layer；不得在 extractor 加入 Rovo/Markdown-specific conditional 或 fallback。
- Rovo service 只能使用 `read_confluence` 與必要的 shared discovery tools，不要求或呼叫任何 write tool。
- 不以 hostname 自動切換來源。只有 `--confluence-url` 才走 Rovo；既有 `--input`、`url --url` 不會被攔截。
- MCP SDK 僅存在於 Rovo adapter boundary；其 exception、async lifecycle、tool result schema 不可滲入 parser/extractor/generator。
- 遠端抓取或 Markdown parsing 失敗時不得覆寫既有 `new_vendor_detail/<Vendor>/` 成品。

## 4. 建議架構

```text
Confluence URL
  -> ConfluenceUrlResolver
       先純解析；short/display URL 必要時以受限 redirect resolver 正規化
  -> ConfluenceDocumentService
       -> RovoMcpClient（primary）
       -> ConfluenceRestStorageClient（只在 fidelity/truncation gate 失敗時的 opt-in fallback）
       回傳 ConfluencePageContent(content, content_format, title, page_id, source_url, version)
  -> MarkdownDocumentParser | StorageFormatDocumentParser
       ConfluencePageContent -> existing parsed document contract
  -> ConfluenceDocReaderOrchestrator
       parsing、錯誤轉換、metadata、incremental decision
  -> existing extract_vendor_detail()
  -> existing export_vendor_detail()
```

建議新增檔案：

```text
src/doc_reader/
  confluence_models.py          # dataclass/TypedDict 與 validation
  confluence_url.py             # URL allowlist、page reference parsing
  rovo_mcp_client.py            # 唯一接觸 MCP SDK 與 Authorization header 的模組
  confluence_rest_client.py     # REST API v2 storage-format 備援 adapter
  confluence_service.py         # primary/fallback policy 與 async facade
  markdown_document_parser.py   # Markdown -> existing parsed document contract
  storage_document_parser.py    # storage HTML -> existing parsed document contract
  confluence_orchestrator.py    # service/parser/extractor/exporter orchestration

tests/
  fixtures/confluence/          # 去識別化 MCP responses 與 expected parsed/detail JSON
  test_confluence_url.py
  test_rovo_mcp_client.py
  test_confluence_rest_client.py
  test_markdown_document_parser.py
  test_confluence_service.py
  test_confluence_orchestrator.py
  test_doc_reader_confluence_cli.py
```

### 4.1 URL resolver

本專案實際使用的 canonical Confluence page URL 規則為：

```text
https://ngvgs.atlassian.net/wiki/spaces/<space_key>/pages/<numeric_page_id>/<page_slug>
```

已確認的實際範例：

| Vendor | Canonical URL | Site host | Space key | Page ID | Page slug |
|---|---|---|---|---:|---|
| Alea | `https://ngvgs.atlassian.net/wiki/spaces/GA/pages/1471053840/Vendor_Alea` | `ngvgs.atlassian.net` | `GA` | `1471053840` | `Vendor_Alea` |
| MegaFair | `https://ngvgs.atlassian.net/wiki/spaces/GA/pages/1481113796/Vendor_MegaFair` | `ngvgs.atlassian.net` | `GA` | `1481113796` | `Vendor_MegaFair` |
| Groove | `https://ngvgs.atlassian.net/wiki/spaces/GA/pages/1391558758/Vendor_Groove` | `ngvgs.atlassian.net` | `GA` | `1391558758` | `Vendor_Groove` |

MVP 的 primary URL pattern 是：

- `/wiki/spaces/<spaceKey>/pages/<numericPageId>/<pageSlug>`

同一版也支援下列可 deterministic 正規化的常見形式：

- `/wiki/pages/viewpage.action?pageId=<numericPageId>`：直接從唯一的 `pageId` query parameter 解析。
- `/wiki/x/<shortCode>` 與 `/wiki/display/<spaceKey>/<title>`：只透過第 4.1.1 節的受限 redirect resolver 取得 canonical URL；不自行解碼 short code、不以 title 搜尋 page。

Resolver 的 typed output：

```python
ConfluencePageRef(
    source_url="https://ngvgs.atlassian.net/wiki/spaces/GA/pages/1471053840/Vendor_Alea",
    site_host="ngvgs.atlassian.net",
    space_key="GA",
    page_id="1471053840",
    page_slug="Vendor_Alea",
)
```

驗證規則：

- scheme 必須是 `https`。
- hostname 必須是設定允許的 Atlassian site；目前 deployment allowlist 至少需要明確包含 `ngvgs.atlassian.net`，不因 URL 輸入而自動接受任意 host。
- primary pattern 的 path segment 必須依序為 `wiki/spaces/<spaceKey>/pages/<numericPageId>/<pageSlug>`，不可只用模糊 substring matching；`viewpage.action` 必須恰有一個有效的正整數 `pageId`。
- `spaceKey` 必須非空；目前已知 production examples 使用 `GA`，但 resolver 不把 `GA` 寫死，是否允許其他 space 由設定決定。
- page ID 必須是正整數，解析後不得把 query、fragment 或標題當成 ID。
- `pageSlug` 需做一次 percent-decoding 並保留作 metadata/logging；slug 不作 page identity。送入 `getConfluenceContent.content_url` 前必須建立已驗證的 canonical HTTPS URL；即使 slug 與頁面新標題不同，仍以 numeric page ID 作 identity 與 response validation。
- trailing slash、query 或 fragment 不得改變已解析的 site/space/page ID；送入 `content_url` 前移除 query 與 fragment，禁止把未驗證的 URL 原字串直接交給 MCP tool。
- URL host 必須與 `getAccessibleAtlassianResources` 選到的 site URL 一致；0 個 match 或多個 match 都 fail closed。
- 純 resolver 不執行網路；只有 short/display URL 會明確進入受限 redirect resolver。

#### 4.1.1 受限 redirect resolver

short/display URL 的 resolution 必須符合以下全部條件：

- 初始 URL 與每一個 redirect target 都必須是 `https`、exact host allowlist 內，且 port 為預設 `443`；禁止跨 host、user-info、IP literal 與 scheme downgrade。
- 最多跟隨 5 次 redirect，設定 connect/read/overall timeout；每一跳重新驗證，credential 不得轉送到不同 origin。
- 最終 URL 必須可由 primary/viewpage parser 唯一取得 numeric page ID；只取得 space/title 或多個候選即 fail closed。
- Redirect resolution 使用與 REST adapter 相同、經 Phase 0 驗證的唯讀 authentication；不使用 browser cookie、Playwright 或自然語言/CQL 搜尋。
- Canonical URL、解析方式與 redirect count 可寫入 metadata；query value、page title 與 redirect response body 不得寫 log。

若無法唯一正規化，回傳明確錯誤：

```text
ConfluenceUrlResolutionError: The Confluence URL could not be resolved to one numeric page ID.
Please verify access or provide a canonical URL such as:
https://<site>.atlassian.net/wiki/spaces/<space>/pages/<page_id>/<title>
```

### 4.2 MCP client boundary

`RovoMcpClient` 對內只暴露與專案相關的 typed methods：

```python
class RovoMcpClient:
    async def list_tools(self) -> set[str]: ...
    async def list_accessible_sites(self) -> list[AtlassianSite]: ...
    async def get_confluence_content(
        self, *, cloud_id: str, content_url: str
    ) -> ConfluencePageContent: ...  # content_format="rovo_markdown"
```

必要行為：

- 使用官方 MCP Python SDK 的 Streamable HTTP client，不自行實作 JSON-RPC/SSE。
- SDK 版本要 pin 到 Phase 0 驗證過的版本；升級 SDK 必須重跑 contract tests。
- connection/session 由 async context manager 管理；`async def read(...)` 是 library 的 canonical API。同步 adapter 明確命名為 `read_sync(...)`，只供 CLI entry point 呼叫，且在建立 coroutine 前先檢查目前 thread 是否已有 running loop；若有則拋出可行動的 `ConfluenceAsyncContextError`，提示 caller 改用 `await read(...)`。不得使用 `nest_asyncio`、背景 thread 或 library 深層的 `asyncio.run()` 隱藏衝突。
- session initialize 後先 `list_tools()`，工具分級如下：

  ```text
  required（缺少即阻擋 MVP）：
  - getAccessibleAtlassianResources
  - getConfluenceContent

  optional（缺少不可阻擋 MVP）：
  - atlassianUserInfo
  - discover / executeRead
  - listConfluenceContent / listConfluenceSpaces
  - searchConfluence / search
  ```

  工具可能因 auth mode、token scope、organization permission 或 server 版本而不可見。錯誤需指出缺少哪個 required tool，但不可要求完整工具集合固定不變。
- 先取得 accessible sites，再以 URL host 選定唯一 `cloudId`，禁止使用「第一個 site」。
- MVP 對 Phase 0 已驗證的 `getConfluenceContent` schema 使用 typed arguments：`cloudId`、經驗證且移除 query/fragment 的 `content_url`、`detail="full"`、`content_format="markdown"`、`include_metadata=true`。runtime 只檢查 required tool 是否存在及已知 required fields/enum 是否相容，不動態遞迴組裝任意 arguments。Phase 0 將 tool schema 保存成去識別化 contract fixture；schema 不相容時 fail closed，透過更新 typed adapter 與 contract test 升級。
- `content_id` 是已驗證的相容替代輸入，但 MVP 不在 runtime 任意切換 `content_url`/`content_id`。若 Phase 0 決定改採 `content_id`，必須以 contract fixture 固定該選擇，並持續驗證 URL host、space 與 numeric page ID；不得因此放寬 URL allowlist。
- decoder 只負責從 Phase 0 驗證過的 MCP response envelope 取得 Markdown body 與 page metadata。Markdown 可能位於 `structuredContent` 或 text content block，但對外一律回傳 `content_format="rovo_markdown"` 的 typed `ConfluencePageContent`；兩者同時存在時必須使用 Phase 0 確認的 authoritative location，不能拼接或深層 recursive key guessing。
- Markdown body 缺失、不是 string、response envelope 不相容或具明確 truncation evidence 時，先回傳具體的 schema/fidelity/truncation error；只有第 4.2.2 節允許的情況可進入 REST storage fallback，不得改用一般 HTTP fetch、browser 或純文字猜測。
- 只對 idempotent discovery/read call 重試 `429`、暫時性 `5xx` 與 transport disconnect；尊重 `Retry-After`，採 bounded exponential backoff + jitter。`401`、`403`、tool error、schema error 不重試。
- 設定 connect/read/overall timeout，並將 MCP/HTTP error 轉成第 8 節的明確 domain errors；`ConfluenceReadError` 只可作共同 base class，不可吃掉具體錯誤類型。

#### 4.2.1 Pagination 與 truncation contract

「疑似截斷」不得只靠字數門檻或單一 Markdown heuristic 判定。判定優先序如下：

1. **Authoritative signals**：response/tool result 的 `truncated`、`hasMore`、`next`、`cursor`、`continuationToken`、`stopReason` 或 Phase 0 確認的同義欄位。
2. **Continuation completeness**：若 tool schema 支援續讀，必須依 server-defined cursor 逐頁讀完；驗證 cursor 不重複、page/order 穩定、最後一頁明確結束，並設定 `max_pages`、`max_total_bytes` 與 overall timeout。達上限不是成功，而是 `ConfluenceContentTruncatedError`。
3. **Controlled end markers**：Phase 0 長頁 fixture 在文件開頭、中段與末尾放唯一 marker；缺少末尾 marker直接證明截斷。fixture 必須涵蓋 >20,000 字與超過預期 tool payload 上限的頁面。
4. **Structural indicators**：未閉合 fenced code、明顯缺欄的 GFM table、JSON/XML example 在 EOF 未閉合只能作輔助 evidence；因合法 Markdown 可在 EOF 結束，不能單獨證明完整。
5. **Cross-source evidence**：REST storage response 的 version/size/結構 inventory 與 Rovo 結果不一致，可判定 fidelity/truncation；不得把兩份內容拼接。

若 response 沒有 continuation metadata，且 runtime 又無足夠證據證明完整性，必要結構頁面必須 fail closed 或走已啟用的 storage fallback，不可發布「看似成功」的部分文件。

#### 4.2.2 Confluence REST API v2 storage fallback

`ConfluenceRestStorageClient` 是獨立、唯讀、可關閉的 adapter，呼叫 `/wiki/api/v2/pages/{id}?body-format=storage`，並把回應建模為 `ConfluencePageContent(content_format="storage_html")`。`StorageFormatDocumentParser` 使用 `BeautifulSoup` 解析 storage HTML，直接建立既有 parsed document contract；避免先轉 Markdown 造成第二次格式損失。

Fallback policy 必須集中在 `ConfluenceDocumentService`，且符合：

- 預設 `fallback_mode=disabled`；只有 Phase 0 驗證 REST endpoint、service identity、最小 read scope、response schema 與資料等價性後，部署才可設為 `storage_rest`。
- 只捕捉 `ConfluenceContentFidelityError` 或 `ConfluenceContentTruncatedError`；不得捕捉共同 base exception 後一律 fallback。
- REST 回傳的 page ID 必須相同，page version 必須與 Rovo 一致；版本不一致時 bounded retry 整次 read，仍不一致即 fail，禁止混用不同版本。
- REST adapter 使用獨立設定與 credential provider；不得假設 Rovo Bearer key 可直接用於 Confluence REST。secret/redaction/allowlist 規則與 MCP 相同。
- Storage HTML 中 merged cell、nested table、expand/panel macro 必須有 deterministic mapping 與 inventory validation；BeautifulSoup 只負責 DOM parsing，不得以 `.get_text()` 壓平必要結構。
- `source_transport`、`content_format`、fallback reason 與兩端 page version 記入 metadata/metrics，但不得記錄正文。

### 4.3 Authentication 與設定

建議環境變數：

```text
ROVO_MCP_URL                  # 必填；部署環境核准的 Streamable HTTP endpoint
ROVO_MCP_AUTH_MODE            # service_account 或 personal；預設不猜測
ROVO_MCP_API_KEY              # service account Bearer key
ROVO_MCP_EMAIL                # personal Basic auth 才需要
ROVO_MCP_API_TOKEN            # personal Basic auth token
ROVO_MCP_ALLOWED_SITES        # 逗號分隔 exact host allowlist
ROVO_MCP_CONNECT_TIMEOUT      # optional
ROVO_MCP_READ_TIMEOUT         # optional
CONFLUENCE_FALLBACK_MODE      # disabled 或 storage_rest；預設 disabled
CONFLUENCE_REST_AUTH_MODE     # Phase 0 驗證過的 REST auth mode
CONFLUENCE_REST_EMAIL         # REST Basic auth 才需要
CONFLUENCE_REST_API_TOKEN     # REST token；不得假設與 Rovo secret 相同
CONFLUENCE_MAX_PAGES          # continuation safety limit
CONFLUENCE_MAX_TOTAL_BYTES    # total payload safety limit
```

安全要求：

- `ROVO_MCP_URL` 的 production baseline 為 `https://mcp.atlassian.com/v2/mcp`；設定若是 `/v1/sse`、`/v1/mcp/authv2` 或其他未核准 endpoint，啟動時必須 fail closed。
- 正式環境優先使用唯讀 service account。Rovo MCP v2 的 Confluence baseline scope 是 `read:confluence:agent-interface`；`getAccessibleAtlassianResources` 所需的 user-context claims/scopes 必須由 token 建立設定與 Phase 0 live call 實證，不得沿用 v1 的 `read:account`、`read:me`、`read:page:confluence` 作為已確認的 v2 contract。新增 scope 必須記錄原因。
- secret 只從 environment/secret manager 注入，不接受 CLI argument，不寫入 config file、`source_meta.json`、fixture、traceback 或 log。
- Basic header 只在記憶體組合；所有 logging filter 必須遮蔽 `Authorization`、token、API key 與 email/token base64 value。
- 啟動時驗證 URL、auth mode、required fields 與 allowed sites；不可在缺少設定時退回匿名 HTTP 或 Playwright。
- 啟用 `storage_rest` 時，啟動檢查必須同時驗證 REST credential/config；未啟用時不得建立 REST client 或要求額外 secret。

#### Deployment 權限 checklist

OAuth domain allowlist 與 API-token deployment controls 必須分開描述。API token 不走 OAuth redirect，因此**不受 OAuth domain allowlist 驗證**；這不表示不需要 Atlassian admin 設定。部署前必須逐項確認：

- [ ] Organization 已啟用 Rovo MCP API token authentication。
- [ ] Rovo MCP Permissions 已允許 Confluence Read；Write/Search 維持關閉，除非另一個獨立需求明確核准。
- [ ] Organization IP allowlist 已允許實際執行環境的 outbound IP。
- [ ] Service account 已加入正確 Atlassian site，具有必要 product access。
- [ ] Service account 是目標 space/page 的 viewer，且不可見不在 service scope 的敏感 space。
- [ ] Service account/API key 能呼叫 `getAccessibleAtlassianResources`，並取得預期 `cloudId`。
- [ ] Bearer auth 能看到並呼叫 `getConfluenceContent`，且以 `detail="full"`、`content_format="markdown"` 取得正文。
- [ ] Personal token 的 Basic auth 只用於 development verification，且不共用正式 service secret。
- [ ] Audit log 能辨識該 service identity 的 read activity。
- [ ] 若啟用 storage fallback，REST API v2 的唯讀 credential、page endpoint、storage response schema 與 audit activity 已獨立驗證。

上述設定只由管理員完成，本程式不得自動修改 permission、allowlist、product access 或 page sharing。

### 4.4 Content parsers

Service 對 parser 的共同 output 是 typed `ConfluencePageContent`；`content_format` 決定使用 Markdown 或 storage parser：

```python
@dataclass(frozen=True)
class ConfluencePageContent:
    content: str
    content_format: Literal["rovo_markdown", "storage_html"]
    title: str
    page_id: str
    source_url: str
    page_version: int | None
```

`MarkdownDocumentParser.parse(page)` 與 `StorageFormatDocumentParser.parse(page)` 只負責把來源內容轉成現有 extractor 所需的同一 parsed document contract，不直接抽 endpoint、error code、dependency 或 capability，也不寫檔。以下規則先定義 primary Markdown path：

```python
{
    "source_file": "confluence_<page_id>.md",
    "source_path": "<canonical Confluence URL>",
    "source_url": "<canonical Confluence URL>",
    "format": "confluence-rovo-markdown",
    "title": "...",
    "headings": [{"level": 1, "text": "..."}],
    "paragraphs": [{"style": "h1|h2|h3|h4|p|li|pre", "text": "..."}],
    "code_blocks": ["..."],
    "tables": [[...]],
    "tables_detailed": [[...]],
    "links": [{...}],
    "plain_text": "...",
}
```

Parser 必須使用能產生 AST/token stream 且支援 CommonMark + GFM tables/task lists 的 Markdown library；不可用一組跨行 regex 解析整份文件。實際 dependency 在 Phase 1 spike 後 pin 版本。

轉換規則需明確且可測試：

| Markdown node | Parsed document contract | 規則 |
|---|---|---|
| ATX/setext heading | `headings[]` + `paragraphs[{style: h1..h4}]` | level 1～4 直接對應；level 5/6 deterministic clamp 為 `h4` 並產生 warning，確保現有 `_sections()` 可辨識 |
| paragraph | `paragraphs[{style: p}]` | 保留可讀文字與 inline code 內容，不保留 Markdown marker |
| ordered/unordered list item | `paragraphs[{style: li}]` | 維持 document order；nested level 可存在 parser metadata，但不得把子項黏成父項 |
| fenced/indented code | `code_blocks[]` + `paragraphs[{style: pre}]` | 移除 fence/info string；JSON/XML/query 的內容、換行、縮排逐字保留 |
| GFM table | `tables[][]` + `tables_detailed[][]` | 移除 delimiter row；保留 header、row、cell 順序與原 cell text |
| task list | `tables_detailed` 可對應位置的 `tasks[{text, checked}]` | 只有 Markdown 明確提供 `[x]`/`[ ]` 時設定狀態；無法映射到既有 checklist table contract 時 warning，不猜測 |
| link/image | `links[]` | link text + href；relative href 以 canonical page URL resolve；image/attachment 不下載 |
| thematic break/HTML/macro marker | validation report | 不影響正文可忽略；可能承載必要結構時 warning 或 fail |

額外規則：

- `title` 優先使用 Rovo page metadata；缺少時才取第一個 h1，仍缺少則使用 `confluence_<page_id>`。
- `plain_text` 由解析後的 paragraphs 依 document order deterministic 組合，不直接把 raw Markdown 原文塞入。
- Markdown table 必須變成 `tables`；只存在 `plain_text` 不算成功，因現有 `_endpoint_parameter_tables()` 不會解析 Markdown table syntax。
- fenced code 必須變成 `pre` paragraph；不得把 fence、language tag 或 escaped JSON/XML 交給現有 example extractor。
- parser 不執行 endpoint/error/dependency regex，不複製 `doc_extractor.py` 邏輯。
- parser 不修改 `extract_vendor_detail()` 的 input expectations；所有相容處理都留在 parser boundary。
- unsupported macro、attachment、embedded page、whiteboard、expand block 要加入 parse warnings；必要正文遺失時視為 `MarkdownDocumentParseError` 或 `ConfluenceOutputValidationError`，不得輸出空的成功結果。

#### 4.4.1 Parser output validation

不得因 Markdown string 或 `plain_text` 非空就判定成功。Parser 完成後先驗證：

- raw Markdown 有 headings 時，parsed output 必須有對應 heading paragraphs。
- raw Markdown 有 GFM table delimiter 時，parsed output 必須有對應 `tables` entry。
- raw Markdown 有 fenced/indented code 時，parsed output 必須有對應 `pre` paragraph，且內容 hash 相同。
- `tables` 與 `tables_detailed` 的 table/row/cell index 必須對齊。
- parser output 必須能直接傳入現有 `extract_vendor_detail()`，不做 Rovo-specific pre-processing。

任一必要結構不一致時 fail closed。

#### 4.4.2 Phase 0 fixture matrix

至少保存下列九類去識別化 fixture；可用多個專用測試頁，避免單一 fixture 難以定位問題：

| Fixture | 必驗證內容 |
|---|---|
| basic content | heading levels、paragraph、ordered/unordered/nested list、inline code |
| parameter table | header、row/cell 順序、required/description/remark 欄位 |
| code examples | JSON、XML、URL query code block 的逐字內容與換行 |
| merged/nested table | Rovo Markdown 是否保留 row/col span 或 nested structure；無法表示時必須被偵測為 fidelity limitation，不可由 parser 猜測 |
| tasks | task/checkbox 文字與 checked state；無 state 時必須標記 unsupported |
| macro | expand、panel、code/macro 在 Rovo Markdown 中的實際表示與 warning |
| embedded content | attachment、embedded page、anchor/link；正文不可被假裝為完整 |
| empty/error | 真正空頁、無權限頁、not found、truncated/malformed payload 的區分 |
| long content | >20,000 字、跨越預期 payload 上限；開頭/中段/末尾 marker、continuation envelope、總 byte/page count |

Fixtures 不可含 production credential、真實客戶資料或完整 private vendor 文件。

#### 4.4.3 Storage-format parser contract

REST fallback 必須對同一 fixture matrix 建立 storage HTML fixtures 與 golden parsed output，至少覆蓋 `table` 的 `rowspan`/`colspan`、nested table、`ac:structured-macro`（expand/panel/code）、task status、link/anchor 與 preformatted code。所有展開規則需記錄原 node path 與 warning；無法無歧義表示但會影響 endpoint/parameter/example 的節點必須 fail。兩種 parser 的 parsed contract 可有來源格式 metadata 差異，但 extractor-visible fields 必須 semantic-equivalent。

### 4.5 Source metadata 與安全輸出

遠端來源不沿用本機 file size/mtime metadata。新增 versioned remote metadata：

```json
{
  "schema_version": 2,
  "source_type": "confluence",
  "source_transport": "rovo_mcp",
  "content_format": "rovo_markdown",
  "fallback_reason": null,
  "source_url": "https://company.atlassian.net/wiki/spaces/SPACE/pages/123456789/...",
  "site_url": "https://company.atlassian.net",
  "cloud_id": "...",
  "page_id": "123456789",
  "page_version": 42,
  "content_sha256": "...",
  "markdown_parser_schema_version": "1",
  "extractor_version": "...",
  "exporter_version": "...",
  "pipeline_fingerprint": "...",
  "fetched_at": "2026-08-28T00:00:00Z"
}
```

- `content_sha256` 由實際送入 parser 的 canonical content bytes 計算，不包含 metadata 或 `fetched_at`；fallback 時不可沿用失真的 Rovo Markdown hash。
- Rovo payload 沒有 page version 時允許 `null`，增量判斷以 content hash 為準。
- `markdown_parser_schema_version` 是明確維護的 parser/parsed-document contract 版本；Markdown parsing 行為或 contract mapping 改變時必須 bump。
- `extractor_version`、`exporter_version` 應由 deterministic code/version manifest 產生，不可使用 process 啟動時間或不穩定的全 repository hash。
- `pipeline_fingerprint = hash(markdown_parser_schema_version + extractor_version + exporter_version + output_schema_version)`。
- 只有 URL/site/page ID、`content_sha256` 與 `pipeline_fingerprint` 全部相同時才可 skip。任一 pipeline component 版本改變，即使 Confluence 內容未變也必須重建輸出。
- 新內容完整取得、parse、extract、validate 後，先寫入同一 output root 下的 staging directory，再以檔案級 atomic replace 發佈。
- 任何失敗都保留上一版成品；不得先呼叫既有 exporter 覆蓋一半後才報錯。
- `load_source_meta()` 必須同時接受既有 local schema 與新的 remote schema；local comparison 邏輯不得改變。

## 5. CLI 與 pipeline 整合

### 5.1 `doc` command

在 `main.py` 與 `src/doc_reader_main.py` 加入 `--confluence-url`，並採以下 routing：

```text
--confluence-url present
  -> ConfluenceDocumentService
  -> MarkdownDocumentParser
  -> existing extractor/exporter

--confluence-url absent
  -> existing resolve_doc_files + parse_vendor_doc
  -> existing extractor/exporter（完全不變）
```

約束：

- `--confluence-url` 與明確傳入的 `--input` 互斥；argparse error 要在建立網路連線前發生。
- `--vendor`、`--output`、`--force` 沿用目前語意。
- 不加入 `--token`、`--api-key` 或 `--email`，避免 secret 出現在 shell history/process list。
- `--force` 表示即使 content hash 相同也重跑 Markdown parse/extract/export，但仍須走 staging + validation。
- log 顯示 vendor、site host、page ID、page version、content hash prefix 與是否 skipped；不顯示 secret、完整 MCP response 或 private page body。

### 5.2 `new-vendor` command

第一版不改變 `find_vendor_document()` 與 `new-vendor` 的自動探索，避免影響目前一次執行流程。Confluence service 通過實際頁面驗收後，再以獨立小階段新增：

```bash
python main.py new-vendor VendorName --confluence-url "https://.../pages/123/..."
```

屆時規則為：

- 有 `--confluence-url`：不搜尋 `Vendor_<Vendor>.doc/.docx`，其餘 xmind/generate 流程不變。
- 無 `--confluence-url`：byte-for-byte 保持目前 discovery 與 doc flow。
- Confluence read 失敗：不得繼續 generate 使用舊資料，除非未來另設一個名稱明確的 opt-in stale-data option；本計畫不預設 stale fallback。

### 5.3 `url` command

`python main.py url --url ...` 維持 supplementary reader，不自動辨識或轉送 Confluence URL。若使用者誤把 private Confluence URL 傳給它，錯誤訊息可提示改用 `doc --confluence-url`，但不得改變原有 fetch fallback。

## 6. 分階段實作

### Phase 0：唯讀 capability spike（不可跳過的 Hard Gate）

Phase 0 在獨立 script/test 中完成，不接 production CLI，也不先寫正式 `MarkdownDocumentParser`。所有項目都要留下去識別化 evidence/fixture 與 pass/fail 結論。Phase 0 未簽核以前，Phase 1～5 不得開始。

#### 0A. 既有 Phase 0 implementation 升級至 Rovo MCP v2

目前已完成的 Phase 0 implementation 是 v1 contract，必須先完成下列 migration，才可執行新的 live gate；不得用臨時 Python probe 取代正式 Phase 0 runner：

1. 將 endpoint validation/default 從 `/v1/mcp/authv2` 改為 `https://mcp.atlassian.com/v2/mcp`，並新增拒絕 v1 endpoint 的測試。
2. 將 `REQUIRED_TOOLS` 的 `getConfluencePage` 改為 `getConfluenceContent`；保留 `getAccessibleAtlassianResources`。
3. 將 page call typed arguments 改為 `cloudId`、`content_url`、`detail="full"`、`content_format="markdown"`、`include_metadata=true`；contract test 必須鎖定 required fields 與 enum values。
4. 將 scope baseline 改為 `read:confluence:agent-interface`，並以 live evidence 記錄 `getAccessibleAtlassianResources` 所需 user-context claims/scopes。
5. 更新 Markdown decoder、metadata/version extraction、truncation detection 與去識別化 v2 response/tool-schema fixtures；不得假設 v1 envelope 與 v2 相同。
6. 更新 runner、runbook、example manifest、admin attestation、failure observations 與 evidence schema/version，使 evidence 清楚記錄 `rovo_contract_version="v2"`。
7. 新增 migration regression tests，證明 v1 `getConfluencePage`、v1 arguments 與 v1 endpoint 不會被誤判為 v2 Phase 0 pass。
8. 保持 production `doc_reader`、extractor、exporter 未接線；本 migration 只修改隔離的 Phase 0 implementation 與其測試/文件。

#### 0B. Admin 與 identity 驗證

1. 完成第 4.3 節 deployment checklist。
2. 確認 organization 已啟用 API token authentication、Confluence Read permission 與正確 IP allowlist。
3. 確認 service account 具有 site/product access，且能讀 fixture pages、不能讀 negative-control page。
4. 分別測試 development personal token 的 Basic auth 與 production candidate service account 的 Bearer auth；記錄兩者可見工具差異。
5. 驗證 API key/token 的 scopes，確認 `read:confluence:agent-interface` 與實際 user-context claims/scopes 能完成 required calls；記錄過多、缺少與最小可行 scope 組合。

#### 0C. Transport 與 tool capability 驗證

1. 對核准 endpoint `https://mcp.atlassian.com/v2/mcp` 完成 MCP handshake/`initialize`；確認未使用 `/v1/sse` 或 `/v1/mcp/authv2`。
2. 執行 `list_tools()`，保存 required tools 的名稱、description、input schema 與 auth-mode 差異。
3. 確認兩個 required tools 存在；optional tools 不納入 gate。
4. 呼叫 `getAccessibleAtlassianResources`，確認 URL host 唯一 mapping 到預期 `cloudId`，且不使用第一筆資源作隱性 default。
5. 使用固定 typed arguments 呼叫 `getConfluenceContent`：`cloudId`、canonical `content_url`、`detail="full"`、`content_format="markdown"`、`include_metadata=true`；保存成功 call 與 schema mismatch 的 contract fixture。
6. 驗證 `getConfluenceContent` 接受 canonical URL、正確處理尾端 slash，且 query/fragment 已由 client 移除；response identity 必須與 URL 解析出的 numeric page ID 一致。

#### 0D. Response 與格式 fidelity 驗證

1. 對第 4.4.2 節九類 fixture pages 呼叫 `getConfluenceContent(detail="full", content_format="markdown")`；長文 fixture 至少 >20,000 字，並含開頭、中段、末尾唯一 marker。
2. 確認每次回傳都有 Markdown body；記錄它位於 `structuredContent` 或 text content block，以及兩者同時存在時的 authoritative location。
3. 保存完整且去識別化的 response envelope，列舉 `hasMore`、`next`、cursor/continuation token、truncated/stop reason 等欄位；若可續讀，驗證逐頁順序、終止條件、重複 cursor 防護與 safety limits。
4. 將 Rovo Markdown、原 Confluence fixture page 的人工結構清單及本機 DOC/HTML export 結果三方比對。
5. 明確驗證 heading、table、merged cell、JSON/XML code、inline code、macro、expand、task、nested table、attachment/embedded page、anchor/link 的保留或缺失情形。
6. 對同一批 page 呼叫 REST API v2 storage format，記錄 authentication、endpoint、response schema、page version 與 DOM inventory；使用 BeautifulSoup spike 驗證是否能補回 Rovo 遺失的必要結構。
7. 模擬 `max_pages`、`max_total_bytes`、cursor loop、缺少末尾 marker、未閉合 code/table 與 Rovo/REST version race，確認都不會發布部分內容。

#### 0D.1 Plan B 決策表

Phase 0 必須留下逐 fixture 的明確決策，而不是只寫「評估 REST」：

| 結果 | 決策 |
|---|---|
| Rovo 對必要結構完整且無 truncation | `rovo_mcp` primary path 通過；REST 保持 disabled |
| Rovo 失真／截斷，但 REST storage 可完整且穩定還原 | 核准 `storage_rest` opt-in fallback，進入 Phase 1 |
| Rovo 與 REST 都無法還原必要結構，或 REST auth/version 無法可靠驗證 | Hard Gate 失敗；停止 production integration |
| 只有 optional presentation detail 遺失 | 依資料等價性規則記 warning；不得把必要欄位降級為 optional |

#### 0E. Failure matrix

必須收集並分類以下結果：

- `401`：錯誤／過期 token。
- `403`：organization permission blocked、scope 缺失、IP blocked、page permission 不足（可分辨範圍以實際 response 為準）。
- not found/不可見 page 的實際 tool error 或 `404` equivalent。
- `429` 與 `Retry-After` 行為。
- transient `5xx`、timeout、disconnect。
- 缺少 required tool、tool input schema 不相容。
- 空頁、malformed payload、truncated payload。
- pagination cursor loop、達 safety limit、Rovo/REST page version 不一致。
- REST fallback authentication/authorization/schema/fidelity failure；確認不會遞迴 fallback。
- sync CLI、純 async caller 與 running-event-loop 誤用情境。

#### Phase 0 Gate 通過條件

- Basic 與 Bearer 都完成驗證；正式路徑的 Bearer auth 可成功 `initialize`、tool discovery 與 read。
- Basic 與 Bearer mode 都使用 v2 endpoint，並能看到及呼叫 `getAccessibleAtlassianResources`、`getConfluenceContent`，正確選出目標 `cloudId` 並取得 full Markdown。
- Phase 0 evidence 明確記錄 `rovo_contract_version="v2"`；v1 endpoint、`getConfluencePage` 或 v1 arguments 不得通過 gate。
- Service account 的 site/product/page 權限模型與最小 scopes 已由實測確認。
- 成功與 failure matrix 都能映射到第 8 節的 domain error，且不洩漏 secret/page body。
- Markdown body 的 response envelope location、structured/text content priority、pagination/truncation、page version 與 >20,000 字長文末尾 marker 已有 fixture/結論。
- 至少 heading、parameter table、JSON/XML code block 能由 Rovo primary 或核准的 REST storage fallback 達成第 9 節資料等價性；若兩條路徑都無法可靠還原，停止計畫，不得進入 Phase 1。
- 若核准 fallback，REST v2 authentication、storage schema、BeautifulSoup DOM mapping、same-version check 與觸發決策表皆已有 contract fixture。
- 其他 unsupported structure 都能被偵測並產生 warning/error，不會靜默遺失。
- 全程不需要任何 write scope/tool。

### Phase 1：純函式與 contract

1. 建立 `ConfluencePageContent`、parsed document models、config validation、canonical/viewpage parser 與受限 redirect resolver。
2. 將 Phase 0 fixture matrix 與 tool schemas 建立為去識別化、可版本控制的 fixtures。
3. 選定並 pin CommonMark + GFM-compatible parser dependency，實作 `MarkdownDocumentParser`；若 Phase 0 核准 fallback，同時 pin BeautifulSoup dependency 並實作 `StorageFormatDocumentParser`。
4. 建立 Markdown parse validation report，包含 source/parsed counts、unsupported structures、warnings 與 fatal errors。
5. 對 parsed document 呼叫**未修改的** `extract_vendor_detail()`，建立 expected detail golden fixtures，並與本機 DOC/HTML export 結果比較。

此階段不需要網路，所有測試可離線執行。

### Phase 2：MCP adapter 與 service facade

1. 加入 pinned MCP SDK dependency。
2. 實作 auth header provider、session lifecycle、tool capability check、site/cloudId resolution、pagination/truncation guard、read retries 與 error mapping。
3. 實作 async-first `ConfluenceDocumentService.read(url)` 與 CLI-only `read_sync(url)`；service 回傳 `ConfluencePageContent` + remote metadata，不呼叫 extractor。
4. `getConfluenceContent` 使用 Phase 0 驗證過的 v2 typed arguments（`cloudId`、`content_url`、`detail="full"`、`content_format="markdown"`、`include_metadata=true`）；runtime schema check 只負責偵測相容性，不動態猜測 arguments。
5. 使用 fake transport 測試完整 JSON-RPC/tool call contract，不以 mock internal SDK method 綁死實作細節。
6. 若核准 fallback，實作 REST storage adapter與集中式 fallback policy；驗證只會由 fidelity/truncation errors 觸發，並拒絕跨版本內容。

### Phase 3：`doc` CLI opt-in integration

1. 新增 `--confluence-url` routing，原 local branch 保持原程式路徑。
2. 串接 `ConfluenceDocumentService -> MarkdownDocumentParser ->` 既有且未修改的 `extract_vendor_detail()` / exporter。
3. 實作 content hash + pipeline fingerprint comparison、staging export 與 atomic publish。
4. 更新 README 的設定、執行範例、錯誤排查與 security note。

### Phase 4：實際環境驗收

1. 對固定測試 page 執行兩次，驗證 source hash 與 pipeline fingerprint 都相同時才 skip。
2. 分別變更 Markdown parser、extractor、exporter 的 version/fingerprint fixture，驗證來源未變仍會重建；這項測試不代表本功能要修改 extractor code。
3. 修改測試 page version/content 後再執行，驗證只更新指定 vendor output。
4. 執行第 9 節資料等價性驗收，檢查 endpoints、request/response pre、parameter tables、error codes、parameter dependencies、checkboxes 與 links。
5. 重跑 revoked scope、錯誤 site、錯誤 page ID、無權限 page、429、timeout 與 malformed/truncated response。
6. 確認 Atlassian audit log 可識別該 service account 的 read activity，且應用程式 log 不含 credential/page body。

### Phase 5：可選的 `new-vendor` integration

只有 Phase 4 通過且 representative vendor output 與原 DOC export 等價後才進行。這一階段是獨立 PR/commit，方便單獨 rollback，不與 Rovo core service 綁在一起。

## 7. 測試與防回歸策略

### 7.1 Unit tests

- Alea、MegaFair、Groove 三個 canonical URL 必須分別解析出正確的 `ngvgs.atlassian.net`、`GA`、numeric page ID 與 page slug。
- canonical URL、percent-encoded slug、trailing slash、query/fragment、非 HTTPS、錯誤 host、缺 space/page ID/slug、page ID 注入字元。
- `/wiki/pages/viewpage.action?pageId=...` 直接解析；`/wiki/display/...` 與 `/wiki/x/...` 以 fake redirect chain 驗證成功、跨 host、loop、超過 redirect limit、無 numeric ID 與多候選情境；space homepage 必須回傳 `ConfluenceUrlResolutionError`。
- slug 改名或與 page title 不同時仍以 numeric page ID 驗證 identity；`content_url` 必須是 allowlisted canonical URL，query、fragment 不得進入 `getConfluenceContent` arguments。
- auth mode/config validation，並驗證 exception/log 的 secret redaction。
- 0/1/multiple accessible site mapping。
- 缺少 required tool、tool-level error、Markdown body 缺失、structured/text envelope location、unknown response schema。
- ATX/setext heading、nested list、GFM table、code fence、indented code、JSON/XML/query string、link、task/checkbox Markdown parsing。
- retry classification：只重試 429/transient 5xx/disconnect，不重試 401/403/schema/tool error。
- remote metadata content hash、pipeline fingerprint 與 `--force` decision。
- Markdown 含 heading/table/code 結構但 parsed document 遺失時，validation 必須 fail，而不是只產生 warning。
- async facade 可在既有 event loop 中直接 await；`read_sync()` 在 running loop 中必須於建立 coroutine 前失敗，且不得留下 un-awaited coroutine warning。
- truncation authoritative signals、cursor continuation、cursor loop、`max_pages`/`max_total_bytes`、末尾 marker缺失與僅有 structural heuristic 的不同判定。
- fallback 僅由 fidelity/truncation errors 觸發；401/403/404/429/5xx/config/schema/site mismatch 不得觸發。

### 7.2 Contract tests

- fake MCP v2 server 驗證 initialize → list tools → accessible resources → `getConfluenceContent` 的 call order，以及 `cloudId`、canonical `content_url`、`detail="full"`、`content_format="markdown"`、`include_metadata=true` arguments。
- 以完整 Phase 0 fixture matrix 驗證 SDK/Markdown decoder；SDK 升級時 tool schema 與 Markdown envelope fixtures tests 必須先通過。
- `MarkdownDocumentParser` output 必須能直接交給現有且未修改的 `extract_vendor_detail()`，不需要 Rovo-specific conditional。
- 以 golden tests 鎖定既有 extractor functions；本功能的 implementation diff 不得包含 `src/doc_reader/doc_extractor.py` 或 `src/doc_reader/parameter_dependency.py` 的行為修改。
- required tools 缺少時 fail；optional tools 缺少時 contract test 仍須成功。
- fake REST v2 server 驗證 `body-format=storage`、page ID/version、credential redaction、merged/nested table與 macro DOM mapping。
- 同一 fixture 的 Rovo Markdown 與 REST storage parsed output 對 extractor-visible fields 必須 semantic-equivalent；版本 race 必須 bounded retry 後 fail closed。

### 7.3 Regression tests

每次提交至少執行：

```bash
python -m unittest discover -s tests
```

並增加以下 invariants：

- 不提供 `--confluence-url` 時，現有 `doc` CLI forwarded args、exit code 與 output schema 不變。
- 對 representative local DOC/DOCX/HTML fixtures，導入前後輸出 semantic-equivalent；時間戳等非內容欄位排除後應 byte-equivalent。
- `url` reader、`pdf` reader、generator 與 `new-vendor` 現有測試全部通過。
- dirty worktree 中非本功能檔案不被清理或覆寫。

### 7.4 Opt-in integration tests

以環境變數 gate，例如 `RUN_ROVO_INTEGRATION=1`，預設 CI 不連 private Atlassian：

- 測試 account 只可讀指定 space/page。
- fixture page 不放 production secret 或真實 Vendor credential。
- integration test 只斷言 metadata/結構與已知 marker，不把完整 private body寫入 CI log/artifact。

## 8. 錯誤處理與可觀測性

對使用者輸出可行動的分類，而不是原始 MCP traceback：

| 類型 | 範例 | 行為 |
|---|---|---|
| `ConfluenceUrlError` | 非 HTTPS、host 不允許、URL syntax 無效 | 在連線前停止並提示正確格式 |
| `ConfluenceUrlResolutionError` | short/display redirect 無法唯一解析、跨 host、loop | 停止並提示 canonical URL；不做搜尋猜測 |
| `RovoConfigurationError` | endpoint/auth mode/allowed site/credential fields 缺失 | 啟動前失敗；不得 fallback |
| `RovoAuthenticationError` | 401、token 過期或 header mode 錯誤 | 停止，提示檢查 Basic/Bearer 設定 |
| `RovoAuthorizationError` | 403、scope/Read permission/IP/product/page access 不足 | 停止，提示 deployment checklist；不洩漏 page 存在性 |
| `RovoCapabilityError` | required tool 缺少或 tool schema 不相容 | 停止，列出缺少的 required tool/schema 差異 |
| `ConfluenceContentFidelityError` | Rovo Markdown 遺失必要 table/macro 結構 | 僅在核准且啟用時走 storage fallback，否則 fail closed |
| `ConfluenceContentTruncatedError` | authoritative truncation、續讀不完整或達 safety limit | 僅在核准且啟用時走 storage fallback，否則 fail closed |
| `ConfluenceRestFallbackError` | REST auth/schema/parser/same-version 驗證失敗 | 保留原始 failure context，不再 fallback，禁止 publish |
| `ConfluenceAsyncContextError` | running loop 中誤用 sync adapter | 提示改用 `await read(...)`；不得啟動第二個 loop |
| `RovoTransportError` | timeout、disconnect、retry 後仍為 transient 5xx | 保留舊輸出，回傳 non-zero |
| `RovoRateLimitError` | 429 且 retry budget 用完 | 保留舊輸出，回傳 non-zero 並顯示可安全揭露的 retry time |
| `ConfluencePageNotFoundError` | page 不存在或不可見 | 停止，不區分不存在與無權限的敏感細節 |
| `MarkdownDocumentParseError` | Markdown syntax/AST 無法解析、必要 heading/table/code 結構遺失 | 保留舊輸出並產生本機 parse validation report |
| `ConfluenceOutputValidationError` | parsed document 與 source inventory 不等價、extract output 缺必要資料 | 不 publish staging output，回傳 non-zero |

建議 hierarchy：

```text
ConfluenceReadError
├── ConfluenceUrlError
│   └── ConfluenceUrlResolutionError
├── RovoConfigurationError
├── RovoAuthenticationError
├── RovoAuthorizationError
├── RovoCapabilityError
├── ConfluenceContentFidelityError
├── ConfluenceContentTruncatedError
├── ConfluenceRestFallbackError
├── ConfluenceAsyncContextError
├── RovoTransportError
│   └── RovoRateLimitError
├── ConfluencePageNotFoundError
├── MarkdownDocumentParseError
└── ConfluenceOutputValidationError
```

CLI 可捕捉共同 base class 統一轉成 non-zero exit code，但 log、測試與使用者訊息必須保留具體 subtype。

建議 metrics：request count、latency、retry count、continuation page/byte count、status/error category、site host、page ID hash、source transport、fallback reason、content changed/skipped。不要記錄 token、Authorization header、完整 URL query、page title/body、raw MCP/REST response。

## 9. 驗收標準

功能完成需同時滿足：

- 給定支援的 private Confluence canonical/viewpage/short/display URL 與正確 service credential，Python 可解析唯一 page ID 並取得該 page，且不需 Public Link 或 browser login。
- Phase 0 hard gate 有簽核記錄；Basic/Bearer、required tools、service account permission、Markdown response envelope 與 failure matrix 都有去識別化 evidence。
- >20,000 字長文的 continuation/truncation 行為已有實測；任何截斷、cursor loop 或 safety limit 都不會發布部分內容。
- Rovo fidelity 不足時，只有經 Phase 0 核准且明確啟用的 REST storage fallback 可以接手；fallback 與 Rovo page version 相同且 parsed output 通過同一資料等價性驗收。
- Async library caller 可直接 `await`；同步 CLI 正常運作；running event loop 中誤用 sync adapter 會收到可行動錯誤，而不是 `asyncio.run()` runtime crash。
- `MarkdownDocumentParser` 產出的 parsed document 可由現有且未修改的 `extract_vendor_detail()` 處理，不需要任何 Rovo-specific extractor branch。
- 最終輸出路徑與既有 doc reader 相同，因此 generator 不需要知道資料來自 Rovo。
- MCP 連線、required tool/schema、Markdown parsing 或 output validation 任一失敗都回傳 non-zero，且不破壞上一版 vendor output。
- 不提供 `--confluence-url` 時，所有既有測試通過，representative local documents 的輸出無語意變化。
- 程式只呼叫 read/discovery tools；不含 create/update/comment/public-link 等 write 行為。
- repository、log、test fixture、output metadata 與 command line 都不含 credential。
- README 記載 setup、最小權限、canonical URL 限制、執行範例與 troubleshooting。

### 9.1 資料等價性驗收

每個 representative fixture 都要建立 source inventory，並與 parsed document、extractor output 比對。不得只用「Markdown/body 非空」或「成功產生檔案」作驗收。

| 項目 | 通過標準 |
|---|---|
| Headings | Rovo Markdown heading 的數量、順序、level 與文字在 parsed paragraphs 一致 |
| Parameter tables | table/row/cell 順序一致；parameter name、type、required、description、remark 不可遺失或錯欄 |
| Code blocks | JSON、XML、URL query 的內容與換行逐字一致；不得 HTML escape、重新排版、截斷或轉成 prose |
| Inline code | 文字不得遺失；若現有 contract 無法保留 style，validation report 必須明記 fidelity limitation |
| Merged/nested tables | 依 documented deterministic rule 展開；若無法無歧義還原則 fail 或明確列為 unsupported，不可猜測 |
| Tasks/checkboxes | Markdown 有 `[x]`/`[ ]` 時逐項一致；Markdown 無 state 時產生 warning，且不得預設 checked/unchecked |
| Links/anchors | link text 與 resolved target 一致；無法表示的 anchor/macro 明確 warning |
| Macro/expand/embed | 每個 unsupported item 都出現在 validation report；影響必要正文時 fail |
| Empty/truncated body | 真正空頁可依 policy 回報空頁；疑似遺失、截斷或 malformed body 必須 fail，不可輸出空的成功結果 |
| Extracted vendor detail | endpoints、methods、request/response examples、parameter tables、error codes、parameter dependencies 與同頁本機 DOC/HTML export 的 golden result semantic-equivalent |

任何必要欄位遺失都屬 `ConfluenceOutputValidationError`，不得以 warning 降級後 publish。

### 9.2 Incremental 與輸出安全驗收

- `content_sha256` 與 `pipeline_fingerprint` 都相同時才 skip。
- Confluence Markdown 內容不變但 Markdown parser/extractor/exporter version 改變時必須重建。
- staging validation 失敗、process 中斷或 atomic publish 失敗時，上一版所有輸出仍完整可讀，不可留下新舊混合檔案。

## 10. Non-goals

- 開啟或關閉 Confluence Public Link。
- 建立、更新、刪除 page 或 comment。
- 讀取整個 space、遞迴 descendants 或同步 attachments。
- 將 Rovo MCP 變成所有 HTTP URL 的通用 fetcher。
- 自動以自然語言搜尋猜測 short URL 對應的 page。
- 對所有 MCP/REST 錯誤做無條件 fallback；REST storage 只處理已分類的 fidelity/truncation failure。
- 在第一版改變 `new-vendor` 的本機檔案探索預設行為。
- 在 extractor/generator 內加入 Atlassian vendor-specific 判斷。

## 11. Rollout 與 rollback

1. 先完成並簽核 Phase 0 evidence；若 hard gate 不通過，停止 rollout。
2. 合併 Phase 1/2 fixtures、URL resolver、typed MCP adapter 與 `MarkdownDocumentParser`，不接 CLI。
3. contract tests 與資料等價性 tests 通過後，以明確 `--confluence-url` 開放 development 使用。
4. 通過 representative vendor comparison、failure matrix 與 atomic-output 驗收後才開放 team 使用。
5. 最後才考慮 `new-vendor --confluence-url`。

Rollback 時移除或停用 `--confluence-url` routing 即可；本機 doc branch、現有輸出 schema 與 generator 沒有被替換，因此不需要回滾既有 Vendor 資料或其他 reader 功能。

## 12. 開發前需由 Phase 0 回答的問題

- 組織目前 API token authentication 與 Confluence Read permission 的實際狀態為何？
- Basic 與 Bearer authentication 實際各自可見哪些 tools？正式 Bearer path 是否能完成 required calls？
- 核准的 `https://mcp.atlassian.com/v2/mcp` 是否能由 Basic 與 Bearer 完成 handshake、required calls 與 full Markdown read？任何 `/v1/*` endpoint 都不得成為 production contract。
- `getConfluenceContent` 在兩種 auth mode 下的 runtime input schema 是否都支援 `cloudId`、`content_url`、`detail="full"`、`content_format="markdown"`、`include_metadata=true`，以及 Markdown body 位於哪個 response field/content block？
- `structuredContent`、text content blocks 哪一個承載 authoritative Markdown；同時存在時內容是否等價？
- Rovo Markdown 是否完整包含 tables、code blocks、tasks/checkboxes、links 與 page version metadata？
- >20,000 字及超過預期 payload 上限的頁面是否會截斷或分頁？Envelope 是否提供 `hasMore`/`next`/cursor/continuation/truncated/stop reason，且如何證明最後一頁完整？
- Confluence REST API v2 的 `/wiki/api/v2/pages/{id}?body-format=storage` 能否由正式 service identity 以最小唯讀權限呼叫？Storage HTML 是否能完整保留 Rovo 遺失的 merged/nested table、expand/panel macro？
- Rovo 與 REST 讀取期間 page version 變更時，如何偵測並 bounded retry，避免混合版本？
- short/display URL 在不使用 browser cookie 或搜尋猜測的情況下，能否透過 allowlisted redirect 唯一解析 numeric page ID？
- `ConfluenceDocumentService` 的 async API、CLI sync adapter 與現有 GUI/Jupyter/async caller 的 event-loop contract 是否全部通過測試？
- service account 可見多個 Atlassian sites 時，URL host 到 `cloudId` 的 mapping 是否唯一？
- service account 是否具有正確 site/product/page viewer 權限，且 negative-control page 確實不可見？

若上述任一必要項不能用 read-only spike 證明，該項必須保留為 blocker，不可以在 production service 中以猜測掩蓋。REST fallback 只有在其自身 auth、schema、版本一致性與資料等價性均被證明後，才是有效的 Plan B。
