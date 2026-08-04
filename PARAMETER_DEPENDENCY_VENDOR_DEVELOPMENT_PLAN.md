# 參數相依性 Vendor 開發流程

## 1. 目的

目前 API parameter test 主要依單一參數的 `name`、`type`、`required` 產生測項。這種模式適合參數彼此獨立的 API，但無法完整覆蓋下列需求：

- 某參數是否必填取決於另一參數的值。
- 某參數只允許出現在特定模式。
- 一個 object 出現時，其子欄位必須一起出現。
- 多個參數必須 all-or-none。
- 參數值會改變其他參數的合法值或必填狀態。

本計畫新增一條獨立的 dependency-aware parameter generation 流程，同時保證沒有相依性規則的 Vendor 完全沿用既有 generator 行為與 XMind 格式。

參考來源：

- [VeliGames 原始 Confluence DOC](new_vendor_source/Vendor_Veligames.doc)
- [VeliGames API summary](new_vendor_detail/Veligames/api_summary.md)
- [VeliGames endpoints](new_vendor_detail/Veligames/endpoints.json)
- [VeliGames raw doc](new_vendor_detail/Veligames/raw_doc.json)
- [VeliGames error codes](new_vendor_detail/Veligames/error_codes.json)
- [現有 test case generator](src/generator/test_case_generator.py)
- [現有 draft builder](src/generator/draft_builder.py)
- [現有 draft schema](src/generator/draft_schema.py)

## 2. 核心設計原則

### 2.1 Explicit opt-in

是否啟用參數相依性功能，只能由明確的 endpoint dependency profile 決定：

```text
dependency profile 不存在或 enabled=false
    -> 完整走既有 parameter generator

dependency profile 存在、enabled=true，且 endpoint 有規則
    -> 該 endpoint 走 dependency-aware generator
```

禁止使用下列方式隱性啟用：

- Vendor 名稱判斷，例如 `if vendor == "VeliGames"`。
- 看到 `cancelType`、`rewardType` 或 `type` 就自動假設有相依性。
- 只因參數 description 含有 `optional`、`required` 等單字就直接切換模式。
- 讓某個 Vendor 的 dependency 規則成為其他 Vendor 的預設值。

### 2.2 Endpoint scope

相依性 scope 必須到 endpoint，不可以只到 Vendor：

```text
Vendor
└── Endpoint
    ├── dependency disabled -> existing generator
    └── dependency enabled  -> dependency-aware generator
```

同一 Vendor 可以只有部分 endpoint 啟用相依性。例如目前 Veligames 可讓 `/api/v1/veligames/win`、`/api/v1/veligames/cancel` 與規則完整的 `/api/v1/veligames/promo-win` 啟用，`/api/v1/veligames/balance`、`/api/v1/veligames/bet` 仍使用原本流程。

### 2.3 規則資料與產生邏輯分離

Dependency profile 只描述條件與欄位狀態，不直接寫死測試步驟。Generator 先將規則編譯成合法 baseline 與單一 mutation，再引用現有 functions 產生：

- preconditions
- remarks
- request example
- success response
- parameter error response
- type-specific validation steps
- XMind field labels

### 2.4 Fail closed

有 profile 但規則無法解析或找不到 selector 時，應停止該 endpoint 的 dependency generation 並產生明確 validation error。不可靜默退回一般格式。規則若可解析但業務語意互相衝突，則保留並照 DOC 各自產生，同時輸出 warning；程式不可猜測哪條才正確。

### 2.4.1 DOC 是唯一真相來源，禁止 fallback 與語意猜測

Dependency reader 與 generator 必須遵守「人類 DOC 寫什麼，就產生什麼」：

- 只有 request table `Remark` 中格式合法的 `Dependency:` 規則可以設定 `parameter_dependency=true`。
- 沒有 `Dependency:` 規則就是 `false`；不得從 Vendor 名稱、endpoint 名稱、參數名稱、`Require=Y/N` 本身、Description、Mapping、補充說明、request/response example、其他 Vendor profile 或既有 generator template 推論。
- 不得使用 default dependency、相似參數規則、keyword matching、LLM semantic inference 或舊 profile 作 fallback。
- 規則語法正確但業務內容寫錯時，仍照 DOC 原文產生。Description、example、enum table 或 error table 的矛盾只能寫 warning，不得自動修正、替換或略過規則。
- 規則在結構上無法執行時，例如 Remark 無法解析、selector path 不存在、affected row 無法定位、條件缺值或缺少明確 expected error，必須停止該 endpoint 的 dependency generation 並回報 validation error；不得切回一般 parameter generator。
- 未啟用 dependency 的 endpoint 完整沿用原 generator；不得因其他 endpoint 或其他 Vendor 啟用而受影響。

因此，DOC 若提供一條格式合法但業務判斷錯誤的規則，產出的 XMind 也會忠實呈現該錯誤，讓文件維護者直接修正來源 DOC，而不是讓程式暗中猜出另一套結果。

### 2.4.2 Dependency parameter test case 的基本產生規則

抓到 selector 與 affected parameter 後，相依參數仍屬於既有 `API parameter test`，不建立新的 XMind 一級分類。每個受影響參數在 DOC 定義的 required／optional context 都必須產生測項，並列在原 endpoint 的 API parameter cases 中。

相依性功能只負責建立正確的 request context，不重寫現有 parameter validation functions：

- selector 與 selector value 決定本 case 使用哪個 dependency context。
- affected parameter 的 `type` 決定呼叫哪些既有 type-specific functions 與測項步驟。
- 該 dependency context 下的 `required`／`optional` 狀態決定 presence case 與 expected response。
- 原有 preconditions、remarks、request formatting、success response、error response、XMind labels 與 data type steps 全部沿用現有 functions。
- 同一 affected parameter 不可再由一般 generator 重複產生一套不含 selector context 的 presence cases；但 intrinsic data type cases 必須保留，並放入正確 dependency context。

固定行為如下：

| Context 中的欄位狀態 | 必須產生的 presence cases | Expected response 選擇 |
|---|---|---|
| `required` | 欄位存在、欄位缺少 | 存在且值合法時 success；缺少時使用 DOC 規則指定的 parameter error |
| `optional` | 欄位存在、欄位省略 | 兩者都使用 success response；欄位存在時仍執行該 data type 的 validation cases |
| `forbidden`／`N(omit)` | 欄位省略、違規帶入 | 省略時 success；帶入時使用 DOC 規則指定的 error |

Data type 與 requiredness 的職責必須分開：

```text
parameter.type
    -> 決定測試步驟集合
       string / enum / boolean / integer / decimal / object / array ...

dependency field_state
    -> 決定 request 中該欄位是否存在
    -> 決定該 presence case 預期 success 或 error
```

例如 `rewardId` 是 `string`：

```text
winType = WIN_FREE
    -> rewardId = required
    -> 沿用 string functions 產生正常值、空值、長度、型別等步驟
    -> 缺少 rewardId 的 case 預期 BAD_REQUEST

winType = WIN_ORDINARY
    -> rewardId = optional 或 forbidden，完全依 DOC Remark
    -> optional：省略成功；帶入時仍沿用 string functions
    -> forbidden：省略成功；帶入時預期 DOC 指定 error
```

Expected response 不得由 data type 自行改變 requiredness，也不得由 requiredness 自行決定 data type 測項。Generator 先解析 dependency context，再把 affected parameter 交給既有 type function，最後依 case kind 選擇 DOC 明確提供的 success／error response。

### 2.4.3 XMind dependency case 分組與既有 functions 隔離

為相容不同 Vendors，dependency scope 必須記錄下列 metrics；它們是規則分析與 presentation 資訊，不可用單一數值直接決定 generation logic：

```text
affected_parameter_count
selector_field_count
selector_value_count
raw_context_count
behavior_partition_count
```

固定定義：

- `affected_parameter_count`：endpoint 內被明確 Dependency Remark 影響的不同參數數量。
- `selector_field_count`：參與條件判斷的不同 selector fields 數量，不是 enum value 數量。
- `selector_value_count`：所有 selector fields 被規則引用的不同 values 數量。
- `raw_context_count`：將 selector value／condition combinations 展開後的原始 context 數量。
- `behavior_partition_count`：依完整 behavior signature 合併後的 context 群組數量。

Behavior signature 至少包含：

```text
field_state
value_constraint
required_companion_fields
forbidden_companion_fields
expected_error
```

只有 behavior signature 完全相同的 raw contexts 才能合併。同樣都是 `optional`，但 value constraint、companion fields 或 expected error 不同時，仍是不同 partition。

#### XMind presentation policy

XMind 分組由每個 behavior partition 的 `partition_affected_parameter_count` 決定，不使用 endpoint-level `dependent_num`，也不使用 `selector_value_count` 或 parameter type：

```python
for partition in behavior_partitions:
    partition_affected_parameter_count = len(partition.affected_parameters)

    if partition_affected_parameter_count == 1:
        render_case_under_original_endpoint_with_context_in_title(partition)
    else:
        render_context_group_under_original_endpoint(partition)
```

一個 partition 只影響一個參數時，不建立只有一個 child 的 context parent；條件直接放入 case title。多個參數共享完全相同的 context 時，才建立 context group。

`win.rewardId` 範例：

```text
affected_parameter_count = 1
selector_field_count = 1          # winType
selector_value_count = 3          # WIN_FREE, WIN_ORDINARY, WIN_JACKPOT
raw_context_count = 3
behavior_partition_count = 2      # required, optional
```

```text
API parameter test
└── win
    ├── case：check the rewardId validation
    │           (required when winType=WIN_FREE)
    └── case：check the rewardId validation
                (optional when winType in [WIN_ORDINARY, WIN_JACKPOT])
```

Optional partition 可將相同行為的 selector values 合併，並保存：

```json
{
  "covered_selector_values": ["WIN_ORDINARY", "WIN_JACKPOT"],
  "representative_selector_value": "WIN_ORDINARY"
}
```

Requiredness 只需使用 deterministic representative context 測試一次；其他 selector values 仍由 selector parameter 自己的 enum/value validation 覆蓋。若同一 partition 需要實際驗證所有 selector values，可放在同一 case 的不同 steps，不建立多個單一-child parents。

#### Optional case 的 minimal valid baseline

Optional affected parameter 不能完全忽略 dependency。Generator 仍須選出一個讓受測參數解析為 optional 的合法 representative context，但移除所有與本測項無關的 optional fields。

Optional case baseline 只包含：

1. 所有 unconditional required parameters。
2. 建立 representative context 所需的 selector fields 與 values。
3. 該 context 下其他 conditionally required parameters。
4. 建立 nested path 所需的 required parent objects。
5. 受測 optional parameter；依 step 決定 present 或 omitted。

不得包含其他 unconditional optional 或 conditionally optional parameters。`optional + omitted` 與 `optional + valid value` 預期 success；`optional + invalid value/type` 仍 follow 現有 type-specific function，不能因 optional 就一律判定 success。

#### 與現有 generator/functions 的 routing 邊界

不是所有 endpoints、也不是 dependency endpoint 的所有 parameters 都走新流程。Routing 必須在 endpoint 與 parameter 兩層隔離：

```text
endpoint.parameter_dependency = false
    -> 所有 parameters 完整走既有 generator

endpoint.parameter_dependency = true
    -> selector-only parameter
         保留既有 enum/value/type validation

    -> affected parameter
         由 dependency wrapper 建立 behavior partitions 與 baseline
         再重用既有 type-specific step functions

    -> unaffected parameter
         完整走既有 generator
```

同一參數可能同時是 selector 與 affected parameter，例如 `cancel.isAdjustment`。此時必須合併角色：dependency wrapper 負責 required／optional presence contexts；既有 boolean／enum function 只提供 intrinsic value/type steps，不得再由 `_parameter_case()` 產生第二條沒有 context 的重複 case。

實作限制：

- 不修改原始 parameter dict 的 `required`；每個 partition 建立獨立 resolved parameter copy，例如 `effective_required=Y/N`。
- 不改變 `_parameter_case()`、`_parameter_steps()`、`_optional_parameter_steps()` 等既有 functions 對非 dependency parameters 的呼叫結果。
- Dependency wrapper 只負責 context、baseline、effective field state、case title 與 expected response routing；data type step 內容仍由既有 functions 提供。
- 建立 `dependency_affected_fields` 與 `dependency_selector_fields` endpoint-local sets，禁止 module-level/global state。
- 同一 affected parameter 的一般 presence case 必須停用，避免 standard generator 與 dependency generator 重複產生互相矛盾的測項。
- XMind context group 只改 presentation path，不得改變 draft 中的真實 `endpoint`。
- `stable_case_id` 使用 `endpoint + affected_parameter + behavior_signature + case_kind`，不包含 XMind presentation path；日後調整分組時仍可正確 merge。
- 無 dependency profile 的 Vendor、同 Vendor 的 disabled endpoint，以及 enabled endpoint 中的 unaffected parameters，輸出必須與導入此功能前保持 semantic-equivalent。

### 2.4.4 實作複雜度與測試排程（Implementation Complexity）

Behavior Partition 與 Context 合併是此功能的高風險區域。計算 `behavior_partition_count`，再依 `partition_affected_parameter_count` 動態選擇「context 寫入單一 case title」或「建立 Context Group」，會增加 presentation layer 的分支與 edge cases。若規則解析、partition compiler、case generation 與 XMind rendering 同時實作，發生錯誤時很難判斷問題位於哪一層。

因此必須將責任拆成四個可獨立驗證的階段：

```text
normalized dependency rules
    -> behavior partition compiler
    -> flat draft dependency cases
    -> XMind presentation planner
    -> XMind writer
```

各層輸入／輸出：

| Layer | 只負責 | 不負責 |
|---|---|---|
| Rule parser | 將 DOC Remark 轉成 normalized rules | 不決定 XMind parent、不產生 steps |
| Partition compiler | 計算 raw contexts、behavior signatures、partitions 與 representative context | 不格式化 case title、不呼叫 XMind writer |
| Case generator | 依 partition 建 baseline，重用現有 type functions，輸出 flat draft cases | 不決定 XMind 樹狀分組 |
| Presentation planner | 將 flat cases 規劃成 inline-title 或 context-group view model | 不修改 rules、expected response、stable case ID |
| XMind writer | 按 view model 寫 topics | 不重新計算 partition |

#### 分階段實作與測試排程

**Stage 1：Behavior Partition engine**

- 先完成 canonical condition key 與 behavior signature。
- 輸入 normalized rules，只輸出 partitions JSON，不產生 draft 或 XMind。
- 驗證 `win.rewardId`：3 個 raw contexts 必須合併為 2 個 behavior partitions。
- 驗證相同 `optional` 但 value constraint／error 不同時不得合併。
- 驗證 selector field count 與 selector value count 不混用。

通過條件：partition snapshot 穩定且 deterministic；相同輸入順序不同時仍得到相同 partition IDs 與排序。

**Stage 2：Flat draft case generation**

- 每個 behavior partition 產生 flat dependency cases。
- 此階段所有 case 暫時都直接掛在原 endpoint，不建立 Context Group。
- 驗證 required／optional／forbidden presence cases 與 type-specific steps。
- 驗證 affected parameter 不會再產生無 context 的 standard duplicate case。
- 驗證 disabled endpoint 與 unaffected parameter 完整沿用舊 generator。

通過條件：draft case 數量、rule coverage、stable case IDs、steps 與 expected response 全部正確，且尚未依賴 XMind presentation。

**Stage 3：XMind presentation planner**

- `partition_affected_parameter_count == 1`：context 寫入 case title。
- `partition_affected_parameter_count > 1`：在原 endpoint 下建立 Context Group。
- 禁止以 `raw_context_count`、`selector_value_count`、parameter data type 或 Vendor 名稱決定 parent。
- 驗證 Context Group 不會變更 case 的真實 endpoint、stable case ID、steps 或 expected response。

通過條件：presentation snapshot 與 flat draft 一一對應；每個 draft case 在 XMind 恰好出現一次。

**Stage 4：跨 Vendor regression**

- 至少選一個無 dependency 的 Vendor，確認輸出 semantic-equivalent。
- 選一個只有單一 affected parameter 的 endpoint，驗證 inline-title。
- 選一個同 context 有多個 affected parameters 的 endpoint，驗證 Context Group。
- 選一個存在 selector + affected 角色重疊、nested object 或多 selector 的 endpoint。
- 執行 XMind 寫入、回讀、case count、stable ID 與 human merge regression。

通過條件：新功能只改變明確 dependency cases 的 presentation；其他 cases 與 Vendors 不變。

#### 必測 edge cases

- 一個 affected parameter、三個 selector values、兩個 behavior partitions。
- 多個 raw contexts 合併後只剩一個 behavior partition。
- 兩個 affected parameters 分屬不同 selectors，不得被合併到同一 Context Group。
- 多個 affected parameters 共享同一完整 behavior signature，應建立一個 Context Group。
- 同一 affected parameter 被兩個 selector fields 共同控制。
- 同一參數同時是 selector 與 affected parameter。
- Optional representative context 需要其他 conditional required companions。
- Nested parent optional、child required when parent present。
- 相同 field state 但 expected error／value constraint 不同，不得合併。
- Partition 合併後只有一個 child，不得建立無意義的單一-child parent。
- Rule／case／presentation 順序改變時，partition ID、stable case ID 與輸出排序仍 deterministic。
- Presentation planner 缺少 partition 或 case 重複掛載時必須 validation fail，不得靜默寫入 XMind。

#### 降低風險的實作限制

- 第一版先完成 flat draft correctness，再啟用動態 Context Group。
- Context Group 可置於獨立 presentation feature flag；關閉時仍輸出正確的 inline-title cases，方便比對與除錯。
- Partition compiler 與 presentation planner 必須是 pure functions，不讀寫 global state。
- 每一層保存可比較的 JSON snapshot，禁止只靠最終 XMind 人工檢查。
- 不在 XMind writer 內臨時計算 dependency 或合併 contexts。
- 任一 stage validation 失敗即停止，不得 fallback 到另一種 grouping mode。

## 2.5 Veligames 目前文件與 reader 輸出審閱

### 2.5.1 審閱範圍與結論

本次在更新後的原始 DOC 上重新執行 `doc_reader --force`，再審閱下列來源：

- 原始 `new_vendor_source/Vendor_Veligames.doc`。
- `new_vendor_detail/Veligames/api_summary.md`。
- `new_vendor_detail/Veligames/endpoints.json`。
- `new_vendor_detail/Veligames/error_codes.json`。
- `new_vendor_detail/Veligames/capability_profile.json`。
- `new_vendor_detail/Veligames/vendor_master_checklist.json`。
- `new_vendor_detail/Veligames/game_codes.json`。
- `new_vendor_detail/Veligames/raw_doc.json`。
- `new_vendor_detail/Veligames/source_meta.json`。

Freshness 與輸出檢查：

- 原始 DOC：182,109 bytes，修改時間 2026-08-04 16:00:14。
- `source_meta.json` 已更新為相同 size／mtime，reader 產物不再是舊版 DOC 的快照。
- `endpoints.json`：5 個 endpoints。
- `error_codes.json`：13 個 error codes，包含所有 API 的 `BAD_REQUEST`。
- `vendor_master_checklist.json`：10 筆 checklist。
- `game_codes.json`：2 筆 game codes。
- request／response examples、capability profile 與 raw document payload 均已重建。

更新後 DOC 已在既有 request table 直接使用 `Require=Y/N` 與 `Required when`／`Require when`／`Optional when`。目前共抽出 10 個 `Y/N` request parameters：

```text
/win: rewardId
/cancel: refTransactionId, adjustmentRefund,
         adjustmentRefund/amount, adjustmentRefund/currency, isAdjustment
/promo-win: casinoBonusTemplateId, freeBetId, providerId, gameId
```

因此，舊結論「DOC 只有靜態 Y/N，必須先新增完整 dependency table」已不成立。現在主要缺口是 reader 尚未把既有 Y/N Remark 編譯成 normalized dependency fields；`endpoints.json` 目前只保存 `required: "Y/N"` 與壓平後的 Remark，尚未輸出 `parameter_dependency`、selectors、affected parameters、rules、behavior partitions 或 test case scope。

目前可確認的同 API request parameter dependency 如下。此表是人工審閱結果，只用來核對 reader 後續輸出，不得 hardcode 到 generator：

| Endpoint | DOC 目前狀態 | Selector → affected parameters | 目前能否直接建立 executable rule |
|---|---|---|---|
| `/api/v1/veligames/balance` | 沒有同 request parameter dependency | `sessionId`／`gameId` 涉及 session expired state | 否；屬於外部 state dependency，第一版保持 `false` |
| `/api/v1/veligames/bet` | 沒有同 request parameter dependency | `isAdjustment` 影響 expired session handling；jackpot fields 依賴 game capability | 否；屬於 session／capability／workflow，不得轉成 parameter dependency |
| `/api/v1/veligames/win` | `rewardId` 已是 `Y/N`，Required clause 明確寫出 `winType` | `winType → rewardId` | 條件主體足夠；Optional block 可在同 Remark 內沿用唯一 selector `winType`。但 optional 與補充說明的 omitted 語意仍需統一 |
| `/api/v1/veligames/cancel` | 5 個參數已是 `Y/N` | `cancelType → refTransactionId, isAdjustment`；`isAdjustment → adjustmentRefund, adjustmentRefund.amount, adjustmentRefund.currency` | 部分可解析。Adjustment 三列明確寫出 `isAdjustment`；`refTransactionId`、`isAdjustment` 的 Remark 只列 `CANCEL_*` values，缺少 selector `cancelType`，嚴格 parser 必須報錯 |
| `/api/v1/veligames/promo-win` | 4 個 presence parameters 已是 `Y/N`；`amount.amount` 有 rewardType value constraint | `rewardType → casinoBonusTemplateId, freeBetId, providerId, gameId, amount.amount` | 尚不可完整執行。四個 Y/N Remark 只列 reward values，未在同 Remark 明確寫出 selector `rewardType`；`amount.amount` 條件仍在 Description／Remark prose，尚未成為正式 value-constraint rule |

`rewardSource` 目前沒有明確改變其他 request parameter requiredness 的規則，因此不列為 selector；`campaignId` 也維持一般 optional parameter。現行 `doc_reader` 尚未實作 dependency compiler，所以在正式 parser／validator 完成前，不能只看到 `Y/N` 就直接設定 `parameter_dependency=true`。

### 2.5.2 目前 DOC 的缺口與最低成本修正方向

原始 DOC 的 request parameter table 只有：

```text
Parameter | Type | Require | Description | Mapping | Remark
```

現有 request table 已足以承載第一版 dependency，不需要新增 endpoint metadata table 或獨立 matrix，也不需要要求作者學習 `eq`／`in` DSL。`Y/N` 與人類可讀的 Required／Optional blocks 已經存在；最低成本工作應分成「DOC 必須補清楚的語意」與「reader 必須修正的抽取能力」。

#### DOC 只需做的最小修改

1. **每個 Remark 至少明確寫一次 selector field。** 後續 Optional block 可以在同一 Remark 內沿用該唯一 selector，不需要每行重複。

   ```text
   refTransactionId
   Required when cancelType = CANCEL_BET
                 cancelType = CANCEL_TRANSACTION
   Optional when cancelType = CANCEL_ROUND

   isAdjustment
   Required when cancelType = CANCEL_BET
   Optional when cancelType = CANCEL_ROUND
                 cancelType = CANCEL_TRANSACTION
   ```

   `/promo-win` 的 `casinoBonusTemplateId`、`freeBetId`、`providerId`、`gameId` 也只需在各自 Remark 第一個 clause 補上 `rewardType`。若整份 Remark 沒有 selector evidence，reader 必須報 parse error，不得從 enum values 猜 selector。

2. **統一 optional 與 omitted／forbidden 的語意。** 目前存在下列衝突：

   - `/win.rewardId`：table Remark 寫其他 win types 為 optional，補充說明寫其他 win types 不會帶。
   - `/promo-win.casinoBonusTemplateId`：Description 寫非 `CASINO_BONUS` 時 omitted，Remark 寫 optional。
   - `/cancel.adjustmentRefund`：table 由 `isAdjustment` 決定 required／optional，但補充說明又寫 `CANCEL_TRANSACTION` 不使用。

   DOC 必須明確選擇 `optional` 或 `omit/forbidden`。Generator 不得替文件決定。

3. **明確指定 dependency negative case 的 error。** 目前 Y/N Remarks 沒有 error token。若依本計畫的 no-fallback contract，應在規則中明確提供 `BAD_REQUEST`，不能由 generator 自行繼承全域 parameter error。

4. **Value constraint 需放回受影響參數列。** `/promo-win.amount.amount` 的 `CASINO_BONUS = 0`、其他 reward types `> 0` 已存在於文件，但主要寫在 Description。若要產生 dependency value cases，應在 `amount/amount` 的 Remark 用可解析 Required／value block 明確寫出 selector `rewardType` 與各值限制。

5. **外部 state 文字不要改成 Y/N dependency。** `/balance` session expired、`/bet isAdjustment` session handling、jackpot game capability、without corresponding bet/win 都維持 behavior/state 說明，第一版 parameter parser 應忽略。

#### Reader 必須修正，不應把成本轉嫁給 DOC 作者

- 保留 `<br>`、paragraph 與 list item 的 clause/value 邊界。目前 `endpoints.json` 將 `WIN_ORDINARY`、`WIN_JACKPOT` 壓成 `WIN_ORDINARYWIN_JACKPOT`，也將 `Required` 與 `Optional` clauses 直接黏在一起；這是 reader normalization 問題，不應要求作者改成新的大表格。
- Keyword parsing 大小寫不敏感，支援 `Required when`、`Require when`、`Optional when`、可選半形／全形冒號、額外空白與缺少分號。
- 同一 state block 的 multiline values 正規化為 OR；同一 Remark 只有一個已明確 selector 時，後續 values-only shorthand 可以安全沿用。
- Nested field 由結構化 parent/child row deterministic 正規化：`adjustmentRefund/amount → adjustmentRefund.amount`、`amount/amount → amount.amount`。無法唯一映射才 validation fail，不讓 generator 猜。
- `endpoints.json` 的 `section` 應定位到真正 endpoint heading，而不是全部落在 `Vendor_Veligames`。
- 補充說明在 `api_summary.md`／`raw_doc.json` 目前多次重複，reader 應在不改變原文證據的前提下去除輸出重複項。
- Reader 應新增 `parameter_dependencies.json`、`parameter_dependency_validation_report.json`，並在 `endpoints.json` 輸出 endpoint flag、selectors、affected parameters 與 profile reference。

總結：最新版 DOC 已完成大部分低成本標記工作；不再需要把 10 個 conditional parameters 從 `Y/N` 重新改一次。DOC 主要補 selector、消除 optional／omit 矛盾、明確 error/value constraint；reader 則負責保留原始行結構、容錯解析、path normalization、evidence localization 與 normalized dependency 輸出。

### 2.5.3 低成本的 `Require + Remark` dependency contract

DOC 只需修改真正具有條件式 presence／requiredness 的 request parameter 列：把 `Require` 改為 `Y/N`，並在同列 `Remark` 加上一句固定前綴的說明。若欄位只有 value constraint 會改變，`Require` 可保留原值。建議格式：

```text
Dependency: when <selector-path> <operator> <value> => Y;
otherwise => N(<optional|omit>); error=<ERROR_CODE>
```

欄位語意：

- `when` 後面是 selector condition；第一版支援 `=`、`in [...]`、`present`、`absent`、`true`、`false`。
- `Y` 轉成 affected field 的 `required`。
- `N(optional)` 代表該條件下可帶可不帶。
- `N(omit)` 代表該條件下應省略，轉成 `forbidden`。條件結果只寫裸 `N` 視為格式不完整；禁止預設成 `optional` 或 `omit`。
- `error` 必須在 Dependency Remark 明確提供。不得從 endpoint、error table、response example 或其他參數繼承；缺少時該規則 validation fail。
- affected field 不必重複寫在 Remark；它就是當列的 `Parameter`。

例如 `/api/v1/veligames/win` 只需修改一格：

| Parameter | Type | Require | Description | Mapping | Remark |
|---|---|---|---|---|---|
| `rewardId` | `String` | `Y/N` | 原描述保留 | 原 mapping 保留 | `Dependency: when winType = WIN_FREE => Y; otherwise => N(omit); error=BAD_REQUEST` |

Reader 解析後得到：

```text
endpoint = /api/v1/veligames/win
selector = winType
affected_field = rewardId
parameter_dependency = true
```

判定規則為：

```text
至少一列 Remark 有合法 Dependency 條件
    + selector 與 affected field 都存在於同 endpoint request schema
    -> parameter_dependency = true

沒有合法 Dependency Remark
    -> parameter_dependency = false

Require=Y/N 但 Remark 缺少、無法解析或引用不存在的 parameter
    -> 拒絕該列並寫入 validation error
    -> 若 endpoint 沒有其他有效 Dependency Remark，parameter_dependency = false
    -> 禁止猜測或 fallback
```

普通 `Require=N`、Description 裡的 `required when`，以及 response/precondition 下的補充說明都不能啟用相依性，也不能補齊或覆寫 `Dependency:` 規則。Dependency parser 對這些內容一律忽略。

### 2.5.4 Nested field、群組與 value constraint 的低成本表示

不新增 dependency matrix，但 Remark 必須允許多個以分號分隔的條件。Nested parameter 使用 canonical dot path，例如：

```text
amount.amount
amount.currency
adjustmentRefund.amount
adjustmentRefund.currency
```

Reader 可保留原始表格名稱，但 dependency engine 統一使用 canonical dot path。只有 doc_reader 全域 schema 已明確定義的 deterministic path conversion 才能使用，例如固定將結構化 parent/child 輸出成 dot path；遇到無法唯一映射的 `amount/amount` 不得猜測，必須 validation fail。

Parent-child 或 companion group 可直接寫在 child parameter 的 Remark：

```text
Dependency: when adjustmentRefund present => Y;
otherwise => N(omit); group=adjustment_refund; error=BAD_REQUEST
```

Value constraint 也放在同一列：

```text
Dependency: when rewardType = CASINO_BONUS => Y(value=0);
when rewardType in [MONEY_REWARD,FREE_BET_WIN] => Y(value>0);
error=BAD_REQUEST
```

這些固定 token 只描述通用條件，不包含 Vendor 名稱或預設參數名稱，因此不同 Vendor 可使用完全不同的 selector 與 affected fields，不需要 generator hardcode。

### 2.5.5 Veligames 在現有 request 表格的最小修改

以下只列需要修改的 `Require` 與 `Remark`；`Type`、`Description`、`Mapping` 和其他內容保持不變。

#### `/api/v1/veligames/win`

| Parameter | Require | Remark 增補內容 |
|---|---|---|
| `rewardId` | `Y/N` | `Dependency: when winType = WIN_FREE => Y; otherwise => N(omit); error=BAD_REQUEST` |

Reader 輸出 `dependency_selectors=["winType"]`、`dependency_affected_parameters=["rewardId"]`。`isCashOut`、`isPromo`、`isAdjustment` 目前只描述交易來源或跨 API 行為，不加入 parameter dependency。

#### `/api/v1/veligames/cancel`

| Parameter | Require | Remark 增補內容 |
|---|---|---|
| `refTransactionId` | `Y/N` | `Dependency: when cancelType in [CANCEL_TRANSACTION,CANCEL_BET] => Y; when cancelType = CANCEL_ROUND => N(omit); error=BAD_REQUEST` |
| `adjustmentRefund` | `Y/N` | `Dependency: when cancelType = CANCEL_BET => N(optional); otherwise => N(omit); group=adjustment_refund; error=BAD_REQUEST` |
| `adjustmentRefund.amount` | `Y/N` | `Dependency: when adjustmentRefund present => Y; otherwise => N(omit); group=adjustment_refund; error=BAD_REQUEST` |
| `adjustmentRefund.currency` | `Y/N` | `Dependency: when adjustmentRefund present => Y; otherwise => N(omit); group=adjustment_refund; error=BAD_REQUEST` |
| `isAdjustment` | `Y/N` | `Dependency: when adjustmentRefund present => Y(value=true); otherwise => N(omit); group=adjustment_refund; error=BAD_REQUEST` |

Reader 輸出：

```json
{
  "dependency_selectors": ["cancelType", "adjustmentRefund"],
  "dependency_affected_parameters": [
    "refTransactionId",
    "adjustmentRefund",
    "adjustmentRefund.amount",
    "adjustmentRefund.currency",
    "isAdjustment"
  ]
}
```

`cancelType` 是 selector，不是 affected field；`roundId` 目前所有 cancelType 都 required，因此也不是 dependency affected field。依現有文字只能確定 `adjustmentRefund present -> isAdjustment=true`，不能反向推論 `isAdjustment=true -> adjustmentRefund required`。

#### `/api/v1/veligames/promo-win`

目前已確認的兩列可先這樣修改：

| Parameter | Require | Remark 增補內容 |
|---|---|---|
| `casinoBonusTemplateId` | `Y/N` | `Dependency: when rewardType = CASINO_BONUS => Y; otherwise => N(omit); error=BAD_REQUEST` |
| `amount.amount` | `Y` | `Dependency: when rewardType = CASINO_BONUS => Y(value=0); when rewardType in [MONEY_REWARD,FREE_BET_WIN] => Y(value>0); error=BAD_REQUEST` |

這會讓 reader 確認 selector `rewardType` 影響 `casinoBonusTemplateId` 與 `amount.amount`。不需要新增 matrix，但 `freeBetId`、`providerId`、`gameId` 若也有相依性，仍需各自在原 request table 的 `Remark` 補一條同格式規則；在條件未確認前不把它們列入 affected parameters。`campaignId` 維持一般 optional parameter。

### 2.5.6 沒有明確規則時保持 dependency disabled

#### `/api/v1/veligames/bet`

目前 DOC 的補充文字包含下列內容，但因 request table 沒有格式合法的 `Dependency:` Remark，必須設定 `parameter_dependency=false`：

- `isAdjustment=true` 時忽略 session expired：這是 runtime session state，不是單純參數 required/forbidden。
- `jackpotContribution`、`jackpotId` 只在 game supports jackpot 時出現：selector 是 game capability，不是 request field；文件未說明是否 all-or-none。
- `isBonusBuy=true` 時可能沒有對應 win：這是跨 API workflow dependency。

Parser 不把這些文字轉成 candidate 或推測規則。若未來 dependency engine 支援外部 context，必須先另訂明確格式；在格式正式納入 schema 前仍保持 disabled。

#### `/api/v1/veligames/balance`

`session expired + valid gameId -> return balance` 同時依賴 session state 與參數值。第一版不應標成 parameter dependency。若要測試，應放在 behavior/state dependency，而不是 request parameter dependency。

### 2.5.7 doc_reader 應輸出的 JSON 與 Markdown contract

Reader 不可依 Vendor 名稱 hardcode；它只依 request table 的 `Require` 與固定格式 `Dependency:` Remark 解析。每個 endpoint 建議新增：

```json
{
  "endpoint": "/api/v1/veligames/cancel",
  "parameter_dependency": true,
  "parameter_dependency_source": "request_parameter_remark",
  "dependency_schema_version": "parameter-dependencies/v1",
  "dependency_selectors": ["cancelType", "adjustmentRefund"],
  "dependency_affected_parameters": [
    "refTransactionId",
    "adjustmentRefund",
    "adjustmentRefund.amount",
    "adjustmentRefund.currency",
    "isAdjustment"
  ],
  "parameter_dependencies": [
    {
      "rule_id": "cancel_round_ref",
      "when": {"field": "cancelType", "operator": "eq", "value": "CANCEL_ROUND"},
      "affected_field": "refTransactionId",
      "field_state": "forbidden",
      "error_code": "BAD_REQUEST",
      "source_evidence": {
        "section": "2.4 /api/v1/veligames/cancel",
        "table": "Request Parameters",
        "parameter": "refTransactionId",
        "column": "Remark"
      }
    }
  ]
}
```

`api_summary.md` 也應新增人工可讀摘要：

```text
## Parameter Dependencies

- /api/v1/veligames/cancel: enabled
  - selectors: cancelType, adjustmentRefund
  - affected fields: refTransactionId, adjustmentRefund,
    adjustmentRefund.amount, adjustmentRefund.currency, isAdjustment
- /api/v1/veligames/win: enabled
  - selectors: winType
  - affected fields: rewardId
- /api/v1/veligames/promo-win: enabled_explicit_rules_only
  - selectors: rewardType
  - affected fields: casinoBonusTemplateId, amount.amount
  - parameters without explicit rules: rewardSource, freeBetId, providerId, gameId
```

建議另外輸出：

```text
new_vendor_detail/<Vendor>/parameter_dependencies.json
new_vendor_detail/<Vendor>/parameter_dependency_validation_report.json
```

Validation report 至少包含：

- explicit enabled/disabled endpoint 清單。
- selector 與 affected field 是否存在於 request parameters。
- canonical path 是否可解析到 parent/child。
- enum selector values 是否在文件允許值中；不一致只記 warning，仍按 Remark 原值產生。
- error code 是否存在於 `error_codes.json`；Remark 已明確提供但查無 code 時只記 warning，不可替換成其他 error。
- 同條件下 required/forbidden 衝突；規則仍照 DOC 保留，報告必須指出 DOC 自相矛盾，不得由程式決定哪條優先。
- `Require=Y/N` 但缺少或無法解析 `Dependency:` Remark。
- 未包含合法 `Dependency:` Remark 的 endpoint 必須明確輸出 `parameter_dependency=false`。
- 未包含合法規則的參數不得出現在 selectors、affected parameters 或 dependency profile。

### 2.5.8 跨 Vendor、無 hardcode 的抽取規則

實作不得判斷 `vendor == Veligames`，也不得以 `cancelType`、`rewardType` 等名稱觸發。通用 reader 只接受：

1. 既有 request table headers：`Parameter | Type | Require | Description | Mapping | Remark`。
2. `Require` 的 `Y`、`N`、`Y/N` 固定語意。
3. `Remark` 中明確的 `Dependency:` 前綴與固定 token。
4. canonical parameter path、schema 支援的 operator 與 field state。
5. endpoint request parameter table 與 error code table只能用於 validation report，不得更改 Remark 規則的語意或值。

不同 Vendor 可以有完全不同的 selector 與 affected fields；差異全部存在資料中：

```text
DOC existing request table + Require/Remark convention
    -> doc_reader normalized dependency JSON
    -> validator
    -> endpoint dependency index
    -> dependency-aware generator
```

任何未被 schema 表達的自然語言一律忽略，不建立 `dependency_candidates`，也不可改變 `parameter_dependency`、affected parameters 或 expected result。

## 3. VeliGames Cancel dependency 分析

官方規則摘要：

- Request body 参数預設 mandatory，除非文件明確說明 optional 或 omitted。
- `cancelType` 支援 `CANCEL_TRANSACTION`、`CANCEL_BET`、`CANCEL_ROUND`。
- `refTransactionId` 在 `CANCEL_ROUND` 必須省略。
- `adjustmentRefund` 只允許於 `CANCEL_BET`。
- `adjustmentRefund` 出現時，`adjustmentRefund.amount`、`adjustmentRefund.currency` 與 `isAdjustment` 必須搭配。
- `correlationId`、`extraInfo` 為 optional。

第一版應建立以下 variant matrix：

| Parameter | `CANCEL_TRANSACTION` | `CANCEL_BET` | `CANCEL_ROUND` |
|---|---|---|---|
| `cancelType` | 固定值 | 固定值 | 固定值 |
| `refTransactionId` | Required | Required | Forbidden / omitted |
| `roundId` | 依原始 parameter table | 依原始 parameter table | Required，指定整個 Round |
| `adjustmentRefund` | Forbidden | Optional conditional group | Forbidden |
| `adjustmentRefund.amount` | Forbidden | Required when parent exists | Forbidden |
| `adjustmentRefund.currency` | Forbidden | Required when parent exists | Forbidden |
| `isAdjustment` | 不由推論擴張 | Required when `adjustmentRefund` exists | 不由推論擴張 |
| `correlationId` | Optional | Optional | Optional |
| `extraInfo` | Optional | Optional | Optional |

文件沒有明確定義的行為不得自行補成 expected result。例如文件只說 `adjustmentRefund` 不可用於其他 cancel type，但 Dependency Remark 未明確提供 error code 時，profile validation 應阻止該規則產生；不得繼承 endpoint parameter error，也不得建立 placeholder。

## 4. Dependency profile 資料契約

### 4.1 建議檔案

每個 Vendor 可選擇提供：

```text
new_vendor_detail/<Vendor>/parameter_dependencies.json
```

檔案不存在即代表沒有啟用 dependency-aware generation。

### 4.2 Schema 範例

```json
{
  "schema_version": "parameter-dependencies/v1",
  "vendor": "Veligames",
  "enabled": true,
  "endpoints": [
    {
      "endpoint": "/api/v1/veligames/cancel",
      "enabled": true,
      "selectors": ["cancelType", "adjustmentRefund"],
      "variants": [
        {
          "id": "cancel_transaction",
          "when": [
            {"field": "cancelType", "operator": "eq", "value": "CANCEL_TRANSACTION"}
          ],
          "field_states": {
            "refTransactionId": "required",
            "adjustmentRefund": "forbidden"
          }
        },
        {
          "id": "cancel_bet",
          "when": [
            {"field": "cancelType", "operator": "eq", "value": "CANCEL_BET"}
          ],
          "field_states": {
            "refTransactionId": "required",
            "adjustmentRefund": "optional"
          }
        },
        {
          "id": "cancel_round",
          "when": [
            {"field": "cancelType", "operator": "eq", "value": "CANCEL_ROUND"}
          ],
          "field_states": {
            "roundId": "required",
            "refTransactionId": "forbidden",
            "adjustmentRefund": "forbidden"
          }
        }
      ],
      "dependencies": [
        {
          "id": "adjustment_refund_group",
          "when": [
            {"field": "cancelType", "operator": "eq", "value": "CANCEL_BET"},
            {"field": "adjustmentRefund", "operator": "present"}
          ],
          "require": [
            "adjustmentRefund.amount",
            "adjustmentRefund.currency",
            "isAdjustment"
          ],
          "value_constraints": [
            {"field": "isAdjustment", "operator": "eq", "value": true}
          ]
        }
      ],
      "source_evidence": [
        {
          "source": "new_vendor_source/Vendor_Veligames.doc",
          "section": "2.4 /api/v1/veligames/cancel",
          "table": "Request Parameters",
          "parameter": "refTransactionId",
          "column": "Remark",
          "text": "Dependency: when cancelType in [CANCEL_TRANSACTION,CANCEL_BET] => Y; when cancelType = CANCEL_ROUND => N(omit); error=BAD_REQUEST"
        }
      ]
    }
  ]
}
```

### 4.3 支援的第一版操作符

條件操作符先限制為可驗證的小集合：

- `eq`
- `in`
- `present`
- `absent`
- `true`
- `false`

欄位狀態：

- `required`
- `optional`
- `forbidden`

不支援 `inherit` 或缺值預設；每個條件分支必須由 DOC 明確指定狀態。

Dependency 動作：

- `require`
- `forbid`
- `all_or_none`
- `value_constraints`

第一版不加入任意 Python expression、eval 或文字公式，以免規則難以驗證與跨 Vendor 污染。

### 4.4 `new_vendor_detail` 新增的 dependency test case scope

`doc_reader` 在每個 Vendor 目錄新增兩個檔案，並擴充兩個既有檔案：

| 檔案 | 用途 | Generator 是否讀取 |
|---|---|---:|
| `parameter_dependencies.json` | 唯一可執行的 dependency 規則與 test case scope | 是 |
| `parameter_dependency_validation_report.json` | structural errors、semantic warnings、disabled endpoint 原因 | 否，只供人類檢查 |
| `endpoints.json` | 每個 endpoint 增加 dependency 開關與 selectors／affected parameters 摘要 | 是，作 endpoint schema 與一致性檢查 |
| `api_summary.md` | 顯示 enabled／disabled endpoint 與 scope，不作 generation input | 否 |

`capability_profile.json`、`raw_doc.json`、`error_codes.json` 與補充 Markdown 不得用來推論 dependency。Dependency generator 的唯一規則來源是 `parameter_dependencies.json`。

`parameter_dependencies.json` 必須列出所有 endpoint；沒有合法 `Dependency:` Remark 的 endpoint 也要明確寫 `parameter_dependency=false`：

```json
{
  "schema_version": "parameter-dependencies/v1",
  "vendor": "Veligames",
  "source_file": "new_vendor_source/Vendor_Veligames.doc",
  "endpoints": [
    {
      "endpoint": "/api/v1/veligames/cancel",
      "parameter_dependency": true,
      "selectors": ["cancelType", "adjustmentRefund"],
      "affected_parameters": [
        "refTransactionId",
        "adjustmentRefund",
        "adjustmentRefund.amount",
        "adjustmentRefund.currency",
        "isAdjustment"
      ],
      "rules": [
        {
          "rule_id": "cancel.refTransactionId.1",
          "source_parameter": "refTransactionId",
          "require_raw": "Y/N",
          "remark_raw": "Dependency: when cancelType = CANCEL_ROUND => N(omit); error=BAD_REQUEST",
          "when": {
            "field": "cancelType",
            "operator": "eq",
            "value": "CANCEL_ROUND"
          },
          "affected_field": "refTransactionId",
          "field_state": "forbidden",
          "error": "BAD_REQUEST",
          "source_evidence": {
            "table": "Request Parameters",
            "parameter": "refTransactionId",
            "column": "Remark"
          }
        }
      ],
      "test_case_scope": {
        "included_rule_ids": ["cancel.refTransactionId.1"],
        "selector_values": {
          "cancelType": ["CANCEL_ROUND"]
        },
        "parameters": [
          {
            "name": "refTransactionId",
            "rule_ids": ["cancel.refTransactionId.1"],
            "case_kinds": ["valid_baseline", "present_when_forbidden"]
          }
        ],
        "excluded_parameters": [
          {
            "name": "roundId",
            "reason": "no_explicit_dependency_rule"
          }
        ]
      }
    },
    {
      "endpoint": "/api/v1/veligames/balance",
      "parameter_dependency": false,
      "selectors": [],
      "affected_parameters": [],
      "rules": [],
      "test_case_scope": {
        "included_rule_ids": [],
        "selector_values": {},
        "parameters": [],
        "excluded_parameters": []
      },
      "disabled_reason": "no_explicit_dependency_remark"
    }
  ]
}
```

`test_case_scope.case_kinds` 只能由已解析 rule state 透過固定 mapping 編譯，不可由 LLM 或 parameter name 猜測：

| DOC rule state | 固定 case kinds |
|---|---|
| `required` | `valid_baseline`, `missing_when_required` |
| `forbidden` | `valid_baseline`, `present_when_forbidden` |
| `optional` | `valid_baseline`, `omitted_when_optional` |
| `value=...`／`value>...` | `valid_constraint_value`, `invalid_constraint_value` |
| `group=...` | `complete_group`, `missing_each_group_member` |

這個 mapping 只決定「已明確規則要產生哪些標準 case kinds」，不判斷參數是否有相依性。若未來要增加 case kind，必須擴充 DOC grammar 與 schema；不得在 generator 增加隱性 fallback。

`endpoints.json` 每個 endpoint 只保留 routing 摘要，完整規則不重複存放：

```json
{
  "endpoint": "/api/v1/veligames/cancel",
  "parameter_dependency": true,
  "dependency_selectors": ["cancelType", "adjustmentRefund"],
  "dependency_affected_parameters": ["refTransactionId", "adjustmentRefund"],
  "dependency_profile_file": "parameter_dependencies.json"
}
```

若 `endpoints.json` 摘要與 `parameter_dependencies.json` 不一致，draft build 必須失敗，不得選其中一份猜測。

## 5. 開發流程

### Phase 1：建立 schema 與 validator

新增：

```text
src/generator/parameter_dependency_schema.py
src/generator/parameter_dependency_validator.py
```

Validator 的 structural error 必須檢查：

- `schema_version` 是否支援。
- Vendor 與 endpoint 是否存在。
- selector 是否存在於 request parameters。
- variant ID 是否唯一。
- `when` 使用的欄位是否存在。
- nested field 的 parent 是否存在。
- 每條規則是否含 `source_evidence`。

下列屬於 semantic warning，不得修改或淘汰 DOC 規則：

- `required` 與 `forbidden` 對同一條件產生衝突。
- selector value 不在 enum table。
- error code 不在 error table。
- 規則與 Description、補充說明、request/response example 不一致。
- 規則無法組成業務上合理的 baseline。

完成條件：結構上無法執行的 profile 在產生 XMind 前即失敗，錯誤訊息指出 endpoint、variant、field 與 rule ID；結構合法但語意可疑的 profile 仍按 DOC 產生並留下 warning。

### Phase 2：載入與 endpoint gating

在 `draft_builder.py` 增加可選讀取：

```text
parameter_dependencies.json
```

Draft 建議新增：

```json
{
  "source_files": {
    "parameter_dependencies": ".../parameter_dependencies.json",
    "parameter_dependency_validation_report": ".../parameter_dependency_validation_report.json"
  },
  "parameter_dependency_profile": {
    "enabled": true,
    "source_file": ".../parameter_dependencies.json",
    "endpoints": [
      {
        "endpoint": "/api/v1/veligames/cancel",
        "parameter_dependency": true,
        "selectors": ["cancelType", "adjustmentRefund"],
        "affected_parameters": [
          "refTransactionId",
          "adjustmentRefund",
          "adjustmentRefund.amount",
          "adjustmentRefund.currency",
          "isAdjustment"
        ],
        "rules": [],
        "test_case_scope": {
          "included_rule_ids": [],
          "selector_values": {},
          "parameters": [],
          "excluded_parameters": []
        }
      }
    ]
  }
}
```

Draft 的 `parameter_dependency_profile` 必須是已驗證 `parameter_dependencies.json` 的完整 deterministic copy，不重新讀 DOC、不重新解析 Remark，也不從 `endpoint_roles`、`error_codes` 或現有 `parameter_error` 補資料。可另外保存 checksum，確保 draft scope 可追溯到同一份 reader output。

在 `case_generation_context.py` 建立 endpoint index：

```text
endpoint -> parameter_dependency flag
         -> validated rules by rule_id
         -> selectors
         -> affected_parameters
         -> test_case_scope
```

唯一 routing function 必須區分 disabled、enabled-valid 與 enabled-invalid，不能使用 truthy/falsy 寫法把錯誤吃掉：

```python
dependency_scope = dependency_scope_for_endpoint(context, endpoint)

if dependency_scope.parameter_dependency is False:
    generate_existing_parameter_cases(...)
elif dependency_scope.is_valid:
    generate_standard_cases_for_unaffected_parameters(...)
    generate_dependency_cases_from_explicit_scope(...)
else:
    raise ParameterDependencyValidationError(...)
```

只有 `affected_parameters` 交給 dependency generator；同 endpoint 其餘參數繼續使用既有 generator。不得修改既有 `_parameter_case()` 與 `_parameter_steps()` 的預設呼叫結果，也不得在 dependency case 使用 `context.parameter_error` 作 fallback。

產生完成後，每條 dependency case 寫入 draft `test_cases[]`：

```json
{
  "output_section": "API parameter test",
  "category": "parameter_dependency_validation",
  "endpoint": "/api/v1/veligames/cancel",
  "parameter": "refTransactionId",
  "dependency_rule_id": "cancel.refTransactionId.1",
  "dependency_case_kind": "present_when_forbidden",
  "dependency_context": {
    "cancelType": "CANCEL_ROUND"
  },
  "dependency_mutation": {
    "operation": "add",
    "field": "refTransactionId"
  },
  "expected_error": {
    "code": "BAD_REQUEST",
    "source": "dependency_remark"
  },
  "source_reference": {
    "file": "new_vendor_source/Vendor_Veligames.doc",
    "parameter": "refTransactionId",
    "rule_id": "cancel.refTransactionId.1"
  }
}
```

Draft 中每個 dependency case 必須能反查到 `parameter_dependency_profile.endpoints[].test_case_scope` 的 rule ID 與 case kind。找不到對應 scope 的 case 視為非法，不可寫入 XMind。

### Phase 3：建立 valid baseline request

新增：

```text
src/generator/parameter_dependency_resolver.py
```

每個 variant 先從 `endpoint.request_example` 建立 baseline，再套用：

1. selector values。
2. `required` fields 的正常值。
3. 移除 `forbidden` fields。
4. 保留或移除 optional fields，依該 scenario 的目的決定。
5. 驗證 baseline 本身符合全部 dependency rules。

Baseline 不可使用 placeholder request。若 request example 缺少必填欄位，應從現有 `_normal_request_value()` 取得正常值；仍無法建立時則停止該 variant。

### Phase 4：以單一 mutation 產生相依性測項

避免所有參數做完整 Cartesian product。每個 case 都從一份合法 baseline 開始，只改一項規則：

```text
valid baseline
    -> remove one required field
    -> add one forbidden field
    -> remove one required companion
    -> change one selector value
    -> violate one value constraint
```

這樣可以確定失敗原因對應單一 dependency rule，也避免 case 數量爆炸。

VeliGames `/api/v1/veligames/cancel` 第一版至少產生：

1. `CANCEL_TRANSACTION` baseline 成功。
2. `CANCEL_TRANSACTION` 缺少 `refTransactionId` 失敗。
3. `CANCEL_TRANSACTION` 帶 `adjustmentRefund` 失敗。
4. `CANCEL_BET` baseline 成功。
5. `CANCEL_BET` 帶完整 adjustment group 成功。
6. `CANCEL_BET` 有 `adjustmentRefund`、缺 amount 失敗。
7. `CANCEL_BET` 有 `adjustmentRefund`、缺 currency 失敗。
8. `CANCEL_BET` 有 `adjustmentRefund`、缺 `isAdjustment` 失敗。
9. `CANCEL_BET` 有 `adjustmentRefund`、但 `isAdjustment=false` 失敗。
10. `CANCEL_ROUND` baseline 成功。
11. `CANCEL_ROUND` 缺少 `roundId` 失敗。
12. `CANCEL_ROUND` 帶 `refTransactionId` 失敗。
13. `CANCEL_ROUND` 帶 `adjustmentRefund` 失敗。

### Phase 5：引用既有 step functions

新增 dependency compiler，但不重寫既有輸出格式：

```text
resolved context + mutation
    -> existing precondition function
    -> existing remarks function
    -> existing success/error response function
    -> existing step/expected formatter
    -> existing XMind writer
```

建議將目前內嵌在 `_parameter_steps()` 的 request-line formatting 抽成可重用 helper，但保持其 public behavior 不變：

- `format_request_mutation()`
- `success_step_case()`
- `error_step_case()`
- `_preconditions()`
- `_remarks()`
- `_expected_error_response()`

Dependency case 建議使用獨立 category：

```json
{
  "category": "parameter_dependency_validation",
  "scenario": "case：check CANCEL_ROUND parameter dependency",
  "dependency_rule_id": "cancel_round",
  "dependency_context": {
    "cancelType": "CANCEL_ROUND"
  }
}
```

XMind 仍放在 `API parameter test > cancel`，不影響其他 section。可以在 case title 顯示 selector context，避免與一般 `check the <parameter> validation` 混淆。

### Phase 6：處理一般參數測項與 dependency 測項的邊界

同一 endpoint 啟用 dependency 後，不代表所有 parameter 都改用 dependency 格式：

- 完全不受 dependency 影響的參數，繼續使用 `_parameter_case()`。
- selector parameters 產生 enum、未知值與 variant coverage。
- conditional parameters 由 dependency generator 產生 required/optional/forbidden cases。
- object 自身的 type validation 仍使用既有 object parameter steps。
- object child 的 intrinsic type validation 仍使用既有 type-specific steps，但 request context 必須選擇允許該 child 出現的 variant。

例如：

```text
transactionId
    -> 一般 parameter test

cancelType
    -> selector test + 三個 variant baseline

refTransactionId
    -> dependency test，依 cancelType 驗證 required / forbidden

adjustmentRefund.amount
    -> 在 CANCEL_BET + adjustmentRefund present 的合法 context 中
       重用 decimal parameter steps
```

這一層需要建立 `dependency_affected_fields` 集合，避免同一參數同時被一般 generator 與 dependency generator 重複產生互相矛盾的測項。

### Phase 7：Validation report 與 summary

Validation report 新增：

- dependency profile 是否啟用。
- 啟用的 endpoint 數。
- 每個 endpoint 的 variant 數。
- 每條 rule 的 positive / negative coverage。
- 未使用或未覆蓋的 dependency rule。
- 因文件不明確而跳過的規則。

Summary 新增：

```text
API parameter test
- standard parameter cases: N
- dependency parameter cases: N
- dependency endpoints: /api/v1/veligames/win, /api/v1/veligames/cancel, /api/v1/veligames/promo-win
- parameters without explicit dependency rule: promo-win.rewardSource, promo-win.freeBetId, promo-win.providerId, promo-win.gameId
```

## 6. 防止污染其他 Vendor 的措施

### 6.1 Golden regression

挑选至少三個沒有 dependency profile 的 Vendor，保存 generator 输出摘要与结构 snapshot：

- endpoint 数量
- test case 数量
- stable case IDs
- XMind hierarchy
- 每个 parameter 的 steps

加入断言：引入 dependency 功能前后，这些 Vendor 的输出必须 byte-equivalent，或在无法保证 ZIP metadata 一致时达到 semantic-equivalent。

### 6.2 No-profile contract test

必须有独立测试证明：

```python
assert dependency_rules_for_endpoint(context_without_profile, endpoint) is None
assert generated_cases == existing_generator_cases
```

### 6.3 Endpoint-level isolation test

同一个 Vendor 内：

- `/api/v1/veligames/cancel` 有 dependency profile。
- `/api/v1/veligames/balance` 没有 profile。

断言 `/api/v1/veligames/balance` 的 cases 与旧 generator 完全一致。

### 6.4 禁止全域 mutable state

Dependency rules 必须放在 generation context 中传递，不允许 module-level cache、global Vendor flag 或修改通用 parameter object。每次 endpoint generation 都从 context 读取自己的规则。

## 7. 测试策略

### Unit tests

- Profile schema validation。
- Endpoint path matching。
- Variant condition matching。
- Required / optional / forbidden resolution。
- Nested object dependency resolution。
- all-or-none group。
- conflicting but parseable rules are both preserved and produce semantic warnings。
- unknown selector fail fast。
- missing source evidence error。
- endpoint 沒有 `Dependency:` Remark 時，即使 Description、補充說明或 example 含 dependency-like 文字，仍輸出 `parameter_dependency=false`。
- `Require=Y/N` 但沒有合法 `Dependency:` Remark 時 validation fail，不得切回一般 parameter generator。
- 其他 Vendor 使用相同參數名稱時，不會載入 Veligames 規則。
- selector value 或 error code 與其他 DOC 區塊矛盾時，照 Remark 原值產生並輸出 warning，不得自動修正。
- Dependency Remark 缺少 error 時停止該 endpoint，不得繼承任何通用 parameter error。

### Generator tests

- VeliGames Cancel 产生三种 cancelType baseline。
- `CANCEL_ROUND` 不含 `refTransactionId`。
- `CANCEL_TRANSACTION` 与 `CANCEL_BET` 缺少 `refTransactionId` 会失败。
- `adjustmentRefund` 不会出现在非 `CANCEL_BET` baseline。
- Adjustment group 缺任一 companion 都会产生独立 negative case。
- Dependency child parameter 的 intrinsic type validation 使用正确 variant baseline。
- `win.rewardId` 的三個 raw contexts 合併為兩個 behavior partitions，只產生 required／optional 兩條 dependency cases，不建立三個單一-child context parents。
- Behavior partition 只有一個 affected parameter 時，context 寫入 case title；有多個 affected parameters 時才建立 context group。
- Affected parameter 不再出現一條沒有 dependency context 的重複 standard presence case。
- Selector-only 與 unaffected parameters 仍呼叫原有 parameter/type functions，steps 與 expected response 不變。
- 同時是 selector 與 affected parameter 的欄位只產生一套 context-aware cases，intrinsic type steps 不重複。
- Optional baseline 會省略其他 optional fields，但保留該 context 下所有 unconditional 與 conditional required fields。

### Backward compatibility tests

- 无 profile Vendor 的 case 数量、stable IDs、步骤和 expected 不变。
- 有 profile Vendor 中，无规则 endpoint 的结果不变。
- 有 profile endpoint 中，unaffected parameters 的 case 數量、stable IDs、steps 與 expected 不變。
- `include_parameter_validation=false` 时 dependency cases 也不产生。
- Human XMind merge 仍以 stable key 合并，并保留 markers。

### End-to-end tests

1. 建立 draft。
2. 验证 dependency profile。
3. 产生 JSON cases。
4. 写入 XMind。
5. 回读 XMind。
6. 比对 draft case count 与 parsed case count。
7. 确认 dependency context、steps、expected result 未遗失。

## 8. 建议修改文件

| 文件 | 修改内容 |
|---|---|
| `src/generator/draft_builder.py` | 可选载入 dependency profile，写入 draft context |
| `src/generator/case_generation_context.py` | 建立 endpoint-level dependency index |
| `src/generator/test_case_generator.py` | 加入 endpoint gating 与 dependency case routing；保留既有默认路径 |
| `src/generator/draft_schema.py` | 新增 dependency category 与 case fields |
| `src/generator/draft_validator.py` | 验证 dependency case contract 与 rule coverage |
| `src/generator/test_case_summary.py` | 输出 dependency coverage 统计 |
| `src/generator/parameter_dependency_schema.py` | 新增 profile schema constants |
| `src/generator/parameter_dependency_validator.py` | 新增 profile validator |
| `src/generator/parameter_dependency_resolver.py` | 建立 variant baseline 与 field state |
| `src/generator/parameter_dependency_generator.py` | 编译 dependency mutations 并调用既有 step helpers |
| `src/doc_reader/parameter_dependency_linter.py` | 重用 reader parser／validator，提供 DOC dependency grammar CLI lint |

## 9. 分阶段交付

### Milestone A：VeliGames Cancel pilot

- 只調整原始 DOC 既有 request table 的 `Require` 與 `Remark`，再由 `doc_reader` 產生 VeliGames `/api/v1/veligames/cancel` dependency profile；禁止新增高成本 matrix，也禁止在 generator 手工寫死參數名稱或規則。
- 完成 schema、validator、resolver 与 endpoint gating。
- 产出三种 cancelType 与 adjustment group cases。
- 验证其他 VeliGames endpoints 没有格式变化。

### Milestone B：通用化

- 支援 `required_when`、`forbidden_when`、`all_or_none` 与 value constraint。
- 将 `/api/v1/veligames/win` 的 `winType=WIN_FREE -> rewardId required` 纳入 profile。
- `/api/v1/veligames/promo-win` 先納入已確認的 `rewardType` 規則；Vendor 日後只需在相關參數列補 `Dependency:` Remark，即可逐欄加入 `rewardSource` 相關規則。

### Milestone C：Reader 辅助抽取

- Reader 只從既有 request table 的 `Dependency:` 固定句型抽出正式規則。
- 其他自然語言完全不解析、不建立 candidate，也不加入 profile。
- 每條規則保留 request table、Parameter row、Remark 原文作為 source evidence。
- `parameter_dependencies.json` 只能由這些明確規則建立，不接受 fallback profile 或人工藏在 generator 內的規則。

### Milestone D：State Dependency RFC（Milestone C 完成後）

- 只撰寫 RFC 與資料契約，不直接擴張現有 parameter dependency parser。
- 定義 Session State、Game Capability、Workflow State 與 Transaction State domains。
- 定義跨 API setup、state transition、expected response、cleanup 與 coverage policy。
- 使用獨立 schema、validator、case category 與 feature flag。
- 未通過 RFC review 前，所有跨 API／外部狀態文字保持在 parameter dependency scope 之外。

## 10. Definition of Done

- VeliGames `/api/v1/veligames/cancel` 三种 cancelType 的 dependency cases 完整生成。
- Conditional required、forbidden、all-or-none 与 value constraint 均有测试覆盖。
- 相依性参数的 intrinsic type tests 会在正确 variant context 中执行。
- 无 dependency profile 的 Vendor 输出不变。
- 同 Vendor 无 dependency rules 的 endpoint 输出不变。
- 不使用 Vendor name hardcode。
- 不产生未知或虚构的 parameter error placeholder。
- Draft validation、XMind 写入与回读全部通过。
- Summary 能清楚区分 standard parameter cases 与 dependency parameter cases。

## 11. 后续可扩展范围

完成 Cancel pilot 后，同一机制可覆盖：

- VeliGames `/api/v1/veligames/win`：`winType=WIN_FREE -> rewardId required`。
- VeliGames `/api/v1/veligames/promo-win`：先覆蓋文件已明確的 `rewardType -> casinoBonusTemplateId / amount.amount`；`rewardSource` 對 `providerId`、`gameId`、`freeBetId` 的影響，等各欄 Remark 補齊後再逐條啟用。
- 其他 Vendor 的 action/subtype、bonus mode、rollback mode、round completion mode 等条件式参数。

所有扩展都必须继续遵守 endpoint-level explicit opt-in，不能把某个 Vendor 的 dependency matrix 当成通用默认行为。

## 12. 綜合建議與優化路線（Recommendations）

### 12.1 引入 Dependency Grammar Linter／Validator

Fail-closed 能防止錯誤規則污染測項，但若只在 test case generator 執行時才發現問題，DOC 維護者的回饋時間過長。第一版應提供輕量 CLI linter，與 `doc_reader` 使用完全相同的 normalization、parser 與 validator，不可另外實作一套較寬鬆或較嚴格的規則。

建議新增：

```text
src/doc_reader/parameter_dependency_linter.py
```

建議支援兩種使用方式：

```text
# 只檢查，不輸出 dependency profile
doc_reader --lint-parameter-dependencies <source-doc>

# 正常 reader 流程，同時將 lint error 視為失敗
doc_reader <source-doc> --check-parameter-dependencies
```

Linter 使用時機：

1. DOC 作者本機修改後立即執行。
2. Git pre-commit／CI 對 repository 內的來源 DOC 執行。
3. Confluence 匯出 DOC 後，在進入 reader pipeline 前執行。
4. Web UI 可作後續輔助工具，但第一版不阻塞 CLI 與 CI 落地。

Linter 必須輸出：

- exit code：無 error 為 `0`，存在 structural error 為非 `0`。
- CLI 人類可讀摘要。
- `parameter_dependency_validation_report.json` 機器可讀報告。
- source file、endpoint、request table、parameter row、Require 原文、Remark 原文、normalized text、error code、reason 與 accepted examples。
- 若原始格式可提供穩定 line number 則一併輸出；Confluence MIME/HTML 無穩定行號時，以 endpoint + table + parameter row 定位，不可顯示猜測行號。

Linter 只回報，不修改 DOC；不得 auto-fix selector、state、value 或 error code。

### 12.2 漸進式 Grammar Standard

第一版應將「作者可寫格式」與「內部 normalized operators」分開定義：

```text
human-friendly DOC grammar
    -> deterministic normalization
    -> token parsing
    -> normalized dependency AST
```

DOC 作者可繼續使用大小寫、冒號、換行與 multiline values 的既有寫法，不要求直接撰寫 `eq`、`in` 等 token。內部 parser 仍需有版本化 grammar，例如：

```text
parameter-dependency-grammar/v1
```

概念 EBNF：

```ebnf
remark          = clause, { clause-separator, clause } ;
clause          = state-keyword, [ colon ], "when", [ colon ], condition-block ;
state-keyword   = "required" | "require" | "optional" ;
condition-block = explicit-condition | inherited-value-list ;
explicit-condition = selector, ( equals-value | value-lines ) ;
equals-value    = "=", value ;
value-lines     = value, { line-break, [ selector, "=" ], value } ;
```

EBNF 描述結構；大小寫、空白、Markdown emphasis、半形／全形冒號與句尾符號由 normalization layer 處理。分號不是必填，因此錯誤訊息不可寫成 `Expected ';'`。

第一版錯誤訊息應針對真正缺少的結構，例如：

```text
Missing selector field before value WIN_FREE.
Expected a value after "winType =".
Optional block contains multiple selector fields; AND/OR is ambiguous.
No prior unique selector is available for shorthand values.
Dependency error code is missing.
```

每個 parser error 需包含：

```text
error_code
source location
raw text
normalized text
unexpected token
expected structure
accepted example
action
```

Grammar 版本只漸進新增可明確解析的形式。不得為了接受未知自然語言而加入 fuzzy matching 或 LLM fallback。

### 12.3 分階段處理跨 API／狀態相依性

Milestone A～C 只處理同一 API request 內的 parameter-to-parameter dependency：

```text
selector field in request
    -> affected field in the same request
```

下列內容不納入 `parameter_dependency`：

- Session expired／active state。
- Game capability，例如 supports jackpot。
- Bet／Win／Cancel 之間的 workflow state。
- Previous transaction、round closed、reward lifecycle 等跨 API 狀態。

Milestone C 完成並通過跨 Vendor regression 後，再新增獨立的 **Milestone D：State Dependency RFC**。RFC 必須先定義：

- selector domain：`session_state`、`game_capability`、`workflow_state`、`transaction_state`。
- state evidence 的來源與生命週期。
- 跨 API baseline／setup／cleanup。
- state transition 與 expected response schema。
- 與 parameter dependency 的 routing 邊界。
- 防止 Cartesian product 與 case 數量爆炸的 coverage policy。

State dependency 必須使用獨立 schema、validator、case category 與 feature flag，不可擴張 `parameter_dependency=true` 的語意，也不可讓 parameter parser 從補充說明推論 workflow 規則。
