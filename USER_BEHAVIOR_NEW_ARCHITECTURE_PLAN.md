# User Behavior 新架構開發 Plan

## 1. 目的

以 `xmind_detail/User_Behavior_map` 為 User Behavior mapping 的唯一 knowledge source，重構 reference case selection、分類 mapping、draft routing、XMind 固定節點與 validation contract。

本次重構保留既定的目標分類架構，不新增推導 case。第一階段只處理現有 reference cases 的讀取、選擇、分類與輸出；未來再透過明確 extension points 加入依 endpoint、parameter、provider 與 capability 推導的新 cases。

本 Plan 不使用任何特定 vendor 的 `xmind_detail` 作為 mapping 基準，也不以單一 vendor 的 case 數量作為驗收條件。

## 2. Source of truth 與目前基準

### 2.1 唯一 reference source

```text
input_xmind/User_Behavior_map.xmind
  -> xmind_reader
  -> xmind_detail/User_Behavior_map/
     ├── raw/User_Behavior_map_raw.json
     ├── modules/*.json
     ├── tags/*.json
     ├── summary/summary.json
     └── source_meta/User_Behavior_map_source_meta.json
```

Mapping code 只能讀取 `xmind_detail/User_Behavior_map`。`input_xmind/User_Behavior_map.xmind` 更新後，必須先重新執行 xmind reader，再進行 generation。

### 2.2 目前資料基準

目前重新解析後的 knowledge baseline：

- 1 sheet
- 3,212 topics
- 203 reference cases
- 14 module chunks
- 18 tag chunks

目前 modules：

| Module | Cases | 主要用途 |
| --- | ---: | --- |
| `launch_game` | 9 | Launch Game cases |
| `authenticate` | 8 | Authenticate cases 與保留的 special cases |
| `get_player_balance` | 5 | Get Player balance cases |
| `balance` | 1 | 保留的 balance special case |
| `bet_and_settle` | 87 | Bet、Settle、combined endpoint、multiple flow、adjustment、FreeSpin、jackpot |
| `cancel_bet` | 24 | Cancel Bet、rollback 與 adjustment cancel cases |
| `rollback` | 3 | rollback-by-round cancel cases |
| `instant_win` | 7 | Game category |
| `live_game` | 7 | Game category |
| `mini_game` | 12 | Game category |
| `poker_game` | 8 | Game category |
| `slot_game` | 11 | Game category |
| `table_game` | 12 | Game category |
| `video_bingo` | 9 | Game category |

上述數字是 source integrity baseline，不是每個 vendor 都必須生成 203 cases。實際輸出仍須依 capability profile、endpoint topology 與 selected categories 篩選。

## 3. 目標分類架構

```text
User Behavior
├── Bet and Settle
│   ├── Game type
│   │   ├── Game category
│   │   └── Main flow
│   ├── Bet config
│   ├── Settle config
│   ├── BetAndSettle config
│   ├── Special accounts
│   └── Player / Game status
└── Cancel Bet
    ├── Main flow
    ├── Cancel config
    ├── Special accounts
    └── Player / Game status
```

### 3.1 Bet and Settle

#### Game type > Game category

前端操作與遊戲類型 coverage。新的 map 已提供以下 canonical game categories：

- Instant Win
- Live game
- Mini game
- Poker game
- Slot game
- Table game
- Video Bingo

實際選取哪些 categories，以 Confluence `Vendor Master Check List > Game Type` 內逐項 checkbox 的 checked 狀態為準。Doc reader 必須保留每個 inline task 的文字與狀態，輸出 `available_values`／`selected_values`；generator 不得只看整個儲存格是否至少有一項 checked，也不得在已有 `selected_values` 時用 game-code 關鍵字加入未勾選類型。舊 detail 缺少逐項 checkbox metadata 時才允許 game-code fallback。

輸出路徑為：

```text
User Behavior > Bet and Settle > Game type > Game category > <game category>
```

Provider coverage 必須依賴 Confluence 提供 provider、game category 與 game code 的對應資訊。目前階段不判斷 provider coverage、不建立 provider leaf，也不因 provider 或 game code 自動複製 cases；詳細 deferred 規則見第 8 節。

#### Game type > Main flow

正常或業務流程型 cases，包括 win、lose、insufficient fund、FreeSpin、jackpot、adjustment success、multiple bet/settlement success 與 combined endpoint success flow。

#### Bet config

Bet Controller 或下注階段的反向、重複交易、錯誤 response 與狀態衝突測試。

#### Settle config

Settle／Result／Credit Controller 或結算階段的反向、重複交易、錯誤 response、round completion、multiple settlement、jackpot settlement 與 adjustment config 測試。

#### BetAndSettle config

Combined BetAndSettle Controller 專用的反向、重複交易、狀態衝突、round completion 與 rollback 後再次呼叫測試。只要 reference case 的 source leaf 是 `BetAndSettle config`，就保留 combined endpoint 語意並輸出到獨立 branch：

```text
User Behavior > Bet and Settle > BetAndSettle config
```

不得再依 title、steps 或 endpoint role 把這類 cases 拆分到 `Bet config` 或 `Settle config`。

#### Special accounts

特殊 account 行為，例如 `timeout`、`error`、`delay10s`、`result0`。優先使用 source path 的明確 `Special accounts` leaf；只有舊 reference 缺少 leaf 時才允許 title fallback。

#### Player / Game status

Game 或 player 被關閉、停用或狀態異常的測試。優先使用 source path 的明確 `Player / Game status` leaf。

### 3.2 Cancel Bet

#### Main flow

Cancel Bet／rollback 的正常成功流程。

#### Cancel config

Cancel Controller 的反向、重複取消、錯誤 response、已結算／未結算狀態衝突與 rollback config 測試。

#### Special accounts

Cancel Bet 特殊 account 行為，例如 `timeout`、`refund0`、`cancel`、`delay10s`。

#### Player / Game status

Cancel Bet 在 game 或 player 狀態異常時的行為。

### 3.3 不受本次分類樹重構影響的既有 roots

以下 cases 保持既有 User Behavior sibling routes，不套用 Bet/Cancel 的 title-based subcategory routing：

- `User Behavior > Launch Game`
- `User Behavior > Get Player balance`
- Debit/Credit terminology aliases

`Authenticate` reference cases 仍由 endpoint topology 決定是否選取；其輸出位置須維持既有 generation contract，不可因 title 出現 timeout、error 或 status 被誤放到 Bet and Settle／Cancel Bet。

## 4. Mapping 設計原則

### 4.1 Selection 與 routing 必須分離

- **Selection**：根據 vendor capability 與 endpoint topology 決定要讀哪些 source module/path。
- **Routing**：將已選到的 reference case 映射到 canonical output section。

不可再用 output section 反推 source selector，也不可讓 title keyword 改變 capability selection。

### 4.2 Mapping precedence

每筆 reference case 依以下順序決定 output section：

1. Exact source module + normalized path rule。
2. Exact canonical leaf rule，例如 `bet config`、`settle config`、`Special accounts`。
3. Legacy title fallback，只處理 source path 缺少明確 leaf 的舊資料。
4. 無法判斷時不得默認丟到 `Bet and Settle` root；必須標記 unmapped 並在 validation/report 中顯示。

### 4.3 Path normalization

正規化只能處理不影響語意的差異：

- trim whitespace
- case folding
- `cancel Bet` / `Cancel Bet` 大小寫統一
- `special accounts` / `Special accounts` 大小寫統一
- `Video bingo` / `Video Bingo` 顯示名稱統一
- source aliases，例如 `BetAndSettle`、`bet and settle`

Path matching 必須以 segment 為單位，不可繼續使用任意 substring matching，以免 `main flow`、`config` 或相似 branch 誤匹配。

### 4.4 Source path 優先於 title

新的 map 已明確提供 `main flow`、`bet config`、`settle config`、`cancel config`、`Special accounts`、`Player / Game status`。Mapping code 應直接信任這些 leaf。

Title keyword 只保留為 backward-compatible fallback，且 fallback 只能在 Bet and Settle 或 Cancel Bet scope 內執行。Launch Game、Authenticate、Get Player balance 不得套用。

### 4.5 `Special test cases` 不等於 `Special accounts`

`Special test cases` 是 source-only 保留區，不可因名稱相似自動映射成 `Special accounts`。第一階段維持排除，除非個別 rule 明確 allowlist；被排除的 cases 必須出現在 mapping report。

## 5. 新 source path → canonical output mapping

### 5.1 Game category modules

| Source module/path | Canonical output section |
| --- | --- |
| `instant_win / Game category > Instant Win` | `User Behavior > Bet and Settle > Game type > Game category > Instant Win` |
| `live_game / Game category > Live game` | `User Behavior > Bet and Settle > Game type > Game category > Live game` |
| `mini_game / Game category > Mini game` | `User Behavior > Bet and Settle > Game type > Game category > Mini game` |
| `poker_game / Game category > Poker game` | `User Behavior > Bet and Settle > Game type > Game category > Poker game` |
| `slot_game / Game category > Slot game` | `User Behavior > Bet and Settle > Game type > Game category > Slot game` |
| `table_game / Game category > Table game` | `User Behavior > Bet and Settle > Game type > Game category > Table game` |
| `video_bingo / Game category > Video bingo` | `User Behavior > Bet and Settle > Game type > Game category > Video Bingo` |

### 5.2 Bet and Settle module

| Source path pattern | Canonical output section | Rule |
| --- | --- | --- |
| `Mandatory > bet and settle > game type > main flow` | `User Behavior > Bet and Settle > Game type > Main flow` | exact path |
| `BetAndSettle > Mandatory > main flow` | `User Behavior > Bet and Settle > Game type > Main flow` | exact path |
| `FreeSpin > main flow` | `User Behavior > Bet and Settle > Game type > Main flow` | capability-selected flow |
| `* > jackpot > main flow` | `User Behavior > Bet and Settle > Game type > Main flow` | capability-selected flow |
| `modify_settlement_adjustment > main flow` | `User Behavior > Bet and Settle > Game type > Main flow` | settlement adjustment success |
| `Multiple Bets > * > main flow` | `User Behavior > Bet and Settle > Game type > Main flow` | multiple bet success |
| `Mandatory > bet and settle > bet config` | `User Behavior > Bet and Settle > Bet config` | exact leaf |
| `Multiple Bets > * > bet config` | `User Behavior > Bet and Settle > Bet config` | exact leaf |
| `Mandatory > bet and settle > settle config` | `User Behavior > Bet and Settle > Settle config` | exact leaf |
| `* > Multiple Settlement > * > settle config` | `User Behavior > Bet and Settle > Settle config` | settlement flow/config |
| `modify_settlement_adjustment > adjustment config` | `User Behavior > Bet and Settle > Settle config` | ReBetResult is settlement-side behavior |
| `BetAndSettle > * > BetAndSettle config` | `User Behavior > Bet and Settle > BetAndSettle config` | preserve combined controller config |
| `* > Special accounts` | `User Behavior > Bet and Settle > Special accounts` | exact leaf |
| `* > Player / Game status` | `User Behavior > Bet and Settle > Player / Game status` | exact leaf |

### 5.3 Combined BetAndSettle config

Source paths `BetAndSettle > ... > BetAndSettle config` 一律映射到獨立 canonical branch：

```text
User Behavior > Bet and Settle > BetAndSettle config
```

此規則採 source leaf exact match，不分析 title 或 steps，也不依 case 內容拆分到 `Bet config`／`Settle config`。不同 source variants，例如 `Mandatory` 與 `Has round-end control parameter`，可透過 `source_path`、`selected_category` 與 `mapping_rule_id` 追蹤，但共用相同 output section。

### 5.4 Cancel Bet 與 rollback modules

| Source module/path pattern | Canonical output section |
| --- | --- |
| `cancel_bet / Mandatory > cancel Bet > main flow` | `User Behavior > Cancel Bet > Main flow` |
| `cancel_bet / Mandatory > cancel Bet > cancel config` | `User Behavior > Cancel Bet > Cancel config` |
| `cancel_bet / rollback_* > * > cancel config` | `User Behavior > Cancel Bet > Cancel config` |
| `rollback / rollback_by_round > * > cancel config` | `User Behavior > Cancel Bet > Cancel config` |
| `cancel_bet / modify_settlement_adjustment > adjustment config` | `User Behavior > Cancel Bet > Cancel config` |
| `cancel_bet / * > Special accounts` | `User Behavior > Cancel Bet > Special accounts` |
| `cancel_bet / * > Player / Game status` | `User Behavior > Cancel Bet > Player / Game status` |

### 5.5 非 Bet/Cancel mappings

| Source module/path | Canonical output section |
| --- | --- |
| `launch_game / Mandatory > launch game` | `User Behavior > Launch Game` |
| `get_player_balance / Mandatory > get player balance` | `User Behavior > Get Player balance` |
| `authenticate / Authenticate > Mandatory` | 依既有 Authenticate generation contract |

`authenticate`、`balance` 與 `cancel_bet` 內的 `Special test cases` 第一階段不自動映射；保留在 excluded/unmapped report，等待明確 product rule。

## 6. Mapping code 重構方案

### 6.1 建立單一 mapping module

新增 `src/generator/user_behavior_mapping.py`，集中維護：

- canonical output section constants
- game category module aliases
- source path normalization
- exact/pattern mapping rules
- BetAndSettle config exact-leaf mapping rule
- legacy title fallback phrases
- excluded source branches
- mapping decision/result model

建議 mapping API：

```python
@dataclass(frozen=True)
class UserBehaviorMappingDecision:
    output_section: str | None
    category: str
    rule_id: str
    status: str  # mapped | excluded | unmapped
    reason: str


def map_user_behavior_case(
    selected_category: str,
    reference_case: dict[str, Any],
) -> UserBehaviorMappingDecision:
    ...
```

Generator、schema、validator、writer 與 tests 都引用同一組 constants/rules，禁止各檔案複製 mapping dictionary。

### 6.2 `src/generator/test_case_generator.py`

1. 保留 capability-driven category selection，但重寫 `_user_behavior_selectors()` 為明確 source selector table。
2. `_path_matches()` 改為 normalized segment prefix/exact matching，不使用 substring。
3. `_user_behavior_output_section()` 改呼叫 `map_user_behavior_case()`。
4. 移除目前 `Jackpot / FreeSpin`、`Adjustment`、`Vendor specific cases` 等不在目標架構內的硬編碼 output branches。
5. `_user_behavior_title_subcategory()` 降級為 legacy fallback，不得覆蓋明確 source leaf。
6. 每筆生成 case 的 `source_reference` 新增：
   - `source_module`
   - `source_path`
   - `mapping_rule_id`
   - `mapping_status`
7. excluded/unmapped cases 不進入 draft cases，但必須進入 generation mapping report。

### 6.3 `src/generator/draft_schema.py`

1. 從 mapping module 匯入 canonical sections。
2. 更新 `ALLOWED_OUTPUT_SECTIONS`，加入完整 target leaves 與 Game category leaves。
3. 更新 `KNOWLEDGE_CATEGORY_TO_XMIND_SECTION`：category 應對應 canonical parent contract；個別 reference case 的 leaf 由 mapping decision 決定。
4. 保留 Debit/Credit alias contract，但 alias 後必須保留相同 leaf 結構。
5. `amount_precision` 仍路由 `API parameter test`，不得再映射到 Bet and Settle。

### 6.4 `src/generator/draft_builder.py`

1. 移除重複維護的 knowledge-category mapping。
2. `generation_mapping` 直接序列化 mapping module 提供的 canonical contract。
3. 在 draft metadata 記錄 User Behavior source：
   - source directory
   - source XMind hash
   - mapping contract version

### 6.5 `src/generator/draft_validator.py`

新增驗證：

- User Behavior case 必須落在 canonical leaf，不能停在 `Bet and Settle` 或 `Cancel Bet` root。
- 不允許舊的 `User Behavior > Game type > ...` root-level Game type。
- 不允許 `Jackpot / FreeSpin`、`Adjustment`、`Vendor specific cases` 舊輸出 branch。
- `mapping_rule_id` 必須存在於 mapping registry。
- Bet/Cancel descendant 必須與 category contract 相容。
- Game category leaf 必須是目前已知的 canonical game category；本階段不接受或建立 provider descendant。
- excluded/unmapped 數量必須出現在 report，不能被靜默遺失。

### 6.6 `src/xmind_writer/metersphere_xmind_writer.py`

`_ensure_fixed_user_behavior_categories()` 改成按固定順序建立：

```text
Bet and Settle
  Game type
    Game category
    Main flow
  Bet config
  Settle config
  BetAndSettle config
  Special accounts
  Player / Game status
Cancel Bet
  Main flow
  Cancel config
  Special accounts
  Player / Game status
```

刪除 writer 目前預建的舊 branches。一般 canonical branch 即使沒有 cases 仍保留；`BetAndSettle config` 例外，只有 draft 中確實存在對應 cases 時才建立，沒有資料時不得輸出空節點。

### 6.7 其他受影響檔案

- `src/generator/reference_selector.py`：保留 capability selection；補上新 module aliases 與 source selector contract。
- `src/generator/user_behavior_text_normalizer.py`：Debit/Credit 轉換只替換 operation root，保留其後的 canonical leaf path。
- `src/generator/human_xmind_merger.py`：merge 時接受新 canonical paths，stable case matching 不依 output section 單獨判斷。
- `src/generator/test_case_summary.py`：輸出 source module/path、mapping rule、target section 與 excluded/unmapped count。
- `README.md`、`GENERATION_PLAN.md`：mapping code 完成後同步更新，不保留舊 branch 表格。

## 7. API parameter 與 decimal 規則

1. 所有純 parameter validation 與 amount precision cases 統一放在 `API parameter test`。
2. Amount parameter cases 必須包含兩個小數位數邊界 steps：
   - `Input max_decimal decimal numbers`：剛好等於允許上限，屬於合理範圍，預期 request 成功。
   - `Input max_decimal + 1 decimal numbers`：超過允許上限一位，預期回傳 parameter validation error。
3. `max_decimal` 優先從 Confluence vendor API 文件的明確 decimal 定義取得，包括 amount/balance parameter 的 description、remark、mapping、type 或 request/response parameter table 中的 decimal places、digits after decimal、scale、precision、maximum 等限制。
4. Request/response examples 只能作為補充證據，不能單獨視為 vendor 支援小數位數上限。Confluence 找不到明確 decimal 定義時，統一使用：

   ```text
   max_decimal = 8
   ```

5. 因此找不到 Confluence 定義時必須產生：
   - 合理邊界 step：`Input 8 decimal numbers`，例如 `100.12345678`，預期成功。
   - 超界 step：`Input 9 decimal numbers`，例如 `100.123456789`，預期 parameter validation error。
6. 若 Confluence 明確定義 `max_decimal = N`，則必須產生：
   - `Input N decimal numbers`，預期成功。
   - `Input N + 1 decimal numbers`，預期 parameter validation error。
7. 目前 `_amount_decimal_case()` 只建立超界案例；抓不到 decimal 定義時會以 9 位小數測試，等同預設 `max_decimal = 8` 後測試 `max_decimal + 1`。實作時需新增剛好等於 `max_decimal` 的合理邊界 step，並將預設值明確集中為常數，不再透過 hard-coded `9` 間接表示。
8. 建議將單一 `_amount_decimal_case()` 重構為可同時回傳 valid-boundary 與 invalid-boundary step specs；兩個 steps 必須共用同一次 `max_decimal` 解析結果，避免來源或 fallback 不一致。
9. Decimal steps 應檢查 request amount、response amount，以及 Confluence 有定義時的 rounding／precision；numeric 與 numeric-string parameter 必須沿用各自正確的 JSON request 格式。
10. 只有主要驗證業務 flow 或 controller state/error 的 case 才能進入 User Behavior。
11. 不可因 reference title 含 `amount`、`bet` 或 `settle` 就改變 API parameter case 的 section。

## 8. Provider 與 game coverage

Provider 與 game coverage 必須由 Confluence 明確提供以下可追溯資訊，才能可靠判斷：

```text
provider -> game category -> game codes
```

目前先保留此需求，不進行開發：

- 不從 game code 命名、reference case title 或單一 request example 猜測 provider。
- 不新增 provider/game-code data contract、parser、mapping code 或 validator rule。
- 不建立 provider descendant，不依 provider 增生或合併 test cases。
- 不把 provider coverage 納入本階段 unit、integration、regression 或 acceptance criteria。

未來只有在 Confluence 能穩定抽取 provider、game category、game code 與來源定位後，才另外建立開發 Plan。屆時再定義跨 provider 共用 case、provider-specific case、stable case id 與 coverage validation；在此之前 `Game type > Game category` 只使用 `User_Behavior_map` 目前已有的 canonical game categories。

## 9. 未來推導 extension points

第一階段只為下列非 provider 項目建立 extension interface，不啟用自動推導：

- `parameter -> behavior category`
- `endpoint role -> behavior flow`
- `capability -> template selector`
- `combined endpoint capability -> BetAndSettle config template selector`

`provider -> game coverage` 完全 deferred；依第 8 節規則，本階段連 interface 或 data contract 都不建立。

未來產生的 cases 必須：

- 使用 deterministic stable case id。
- 標記 `generated_by` 與 rule/version。
- 與 XMind reference-adapted cases 分開追蹤。
- 重跑時不得重複產生或覆蓋人工維護內容。

## 10. 實作階段

### Phase 1：建立 mapping contract

1. 新增 `user_behavior_mapping.py`。
2. 定義 canonical sections、source aliases、path normalization 與 mapping decision model。
3. 將本 Plan 第 5 節的 mapping table 寫成 data-driven rules。
4. 建立 source inventory test，確認 203 reference cases 都是 mapped、explicitly excluded 或 explicitly unmapped。

### Phase 2：重寫 selection 與 routing

1. 分離 selectors 與 output routing。
2. 改為 segment-aware path match。
3. 以 source path leaf 優先，title routing 降為 fallback。
4. 加入 BetAndSettle config exact-leaf routing。
5. 將 mapping decision 寫入 `source_reference` 與 report。

### Phase 3：同步 schema、validator 與 writer

1. 移除重複 mapping constants。
2. 更新 allowed sections 與 mapping validation。
3. Writer 預建完整固定分類樹。
4. Debit/Credit aliases 保留 leaf path。

### Phase 4：測試與 migration

1. 更新 unit tests。
2. 重新生成所有可用 vendor drafts/XMind。
3. XMind 回讀並比較 case stable id、scenario、steps 與 target path。
4. 建立舊 branch → 新 branch migration report。
5. 更新 regression baseline；只有已說明的 routing path 變更可接受，case 內容遺失不可接受。

### Phase 5：文件與後續擴充

1. 更新 README 與 generation documentation。
2. 文件保留 provider/game coverage 的 Confluence prerequisite；本階段不實作 provider/game-code data contract。
3. 評估是否啟用 parameter/capability-driven behavior derivation。

## 11. 測試計畫

### 11.1 Unit tests

- 七個 Game category modules 映射到 Bet and Settle 下的 canonical path。
- `game type > main flow` 映射到 `Game type > Main flow`。
- bet/multiple-bet config 映射到 `Bet config`。
- settle/multiple-settlement/jackpot-settlement config 映射到 `Settle config`。
- combined endpoint 的 `BetAndSettle config` leaf 映射到獨立 `BetAndSettle config` branch。
- Cancel/rollback config 映射到 `Cancel config`。
- 明確 `Special accounts` leaf 優先於 title。
- 明確 `Player / Game status` leaf 優先於 title。
- title fallback 只在 Bet/Cancel scope 生效。
- Launch Game、Authenticate、Get Player balance 不會被 title fallback 改路由。
- `Special test cases` 不會被誤認為 `Special accounts`。
- Path matching 是 segment-aware，大小寫與空白正規化不影響結果。
- `Mandatory` 與 `Has round-end control parameter` variants 的 BetAndSettle config cases 都進入獨立 branch。
- Unmapped case 不會靜默進入 root。
- Debit/Credit aliases 保留 canonical leaf。
- Amount precision 留在 API parameter test。
- Confluence 定義 `max_decimal = N` 時，同時產生 N 位成功與 N+1 位失敗 steps。
- Confluence 未定義 decimal range 時，使用 `max_decimal = 8`，同時產生 8 位成功與 9 位失敗 steps。
- Request/response example 的小數位數不會取代明確 Confluence range 或預設 8 位規則。

### 11.2 Source inventory tests

對 `xmind_detail/User_Behavior_map/modules/*.json` 執行 inventory：

- 讀取 203 cases。
- 每筆 case 取得唯一 `mapping_rule_id`，或被明確標為 excluded/unmapped。
- mapped + excluded + unmapped = 203。
- 不允許因 duplicate content hash 而在 mapping 階段意外遺失 case；去重應由獨立規則處理。

### 11.3 Integration tests

- Draft validation 通過。
- Writer 建立固定 target tree，順序正確。
- 生成 XMind 可由 xmind reader 回讀。
- 回讀後 case count、stable case id、scenario、steps、expected results 不遺失。
- Summary 顯示 source path → mapping rule → target path。
- Excluded/unmapped cases 有可追蹤 report。

### 11.4 Regression tests

對所有可用 vendor 執行 generation：

- 不出現 syntax error、mapping error 或 draft validation error。
- 不再輸出舊 User Behavior branches。
- API parameter test 與其他非 User Behavior cases 不受影響。
- 沒有 optional capability 的 vendor 仍能正常產生固定空 branch。
- Case 數量變化必須能由 selection 或 mapping report 解釋。

## 12. Acceptance criteria

1. Mapping knowledge 只來自 `xmind_detail/User_Behavior_map`。
2. `Bet and Settle` 固定包含 Game type、Bet config、Settle config、Special accounts、Player / Game status；`BetAndSettle config` 僅在有對應 cases 時出現。
3. `Game type` 固定包含 Game category、Main flow。
4. `Cancel Bet` 固定包含 Main flow、Cancel config、Special accounts、Player / Game status。
5. Game type 不再是 Bet and Settle 外部的獨立 root。
6. 不再產生 `Jackpot / FreeSpin`、`Adjustment`、`Vendor specific cases` 舊 branches；其 cases 依語意進入 Main flow 或 config。
7. Launch Game、Authenticate、Get Player balance 不被 Bet/Cancel fallback 誤分類。
8. `Special test cases` 不會被當成 `Special accounts`。
9. User Behavior case 不得停在 Bet and Settle／Cancel Bet root。
10. 203 筆 source reference cases 全部可被 inventory accounting。
11. 每筆 mapped case 都能追溯 source module、source path 與 mapping rule id。
12. API amount precision cases 位於 API parameter test，且同時具備 `max_decimal` 合理邊界成功 step 與 `max_decimal + 1` 超界失敗 step；Confluence 未定義時使用 8／9 位小數。
13. 生成 XMind 回讀 validation 通過。
14. 所有 vendor regression 通過，任何 case count/path 變更都有 report 可解釋。

## 13. 交付順序

1. `user_behavior_mapping.py` 與 mapping contract tests。
2. Generator selector/routing 重構。
3. Draft schema、builder、validator 同步。
4. XMind writer 固定分類樹更新。
5. Summary、mapping report 與 inventory accounting。
6. Unit/integration/regression tests。
7. 重新生成 outputs 並執行 XMind 回讀驗證。
8. 更新 README、GENERATION_PLAN 與 regression baseline。
