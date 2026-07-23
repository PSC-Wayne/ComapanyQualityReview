# 台灣上市櫃公司分析：第一手資料 Authority 與 Point-in-Time／Provenance 契約

> 研究範圍：臺灣證券交易所（TWSE）上市公司與證券櫃檯買賣中心（TPEx）上櫃公司。本文不把興櫃、公開發行公司或第三方資料商自動混入上市／上櫃母體。  
> 查核日期：2026-07-23。本文列出的 URL 均為本次實際連線查核之官方頁面或 API。端點行為仍應以每次擷取時的官方表單與回應為準。

## 1. 結論先行

1. **公司身分與市場歸屬**：上市以 TWSE `t187ap03_L`、上櫃以 TPEx `mopsfin_t187ap03_O` 為當期第一手 authority；兩個市場必須分開解析，禁止查不到就跨市場 fallback。
2. **公司申報內容**：財報、重大訊息、法說會、月營收的內容 authority 是公開資訊觀測站（MOPS）及其由 TWSE／TPEx 發布的官方 OpenAPI。OpenAPI 通常適合「當期全市場快照」；MOPS 查詢頁較適合「指定公司、指定期間、保留原始申報脈絡」。
3. **交易行情與官方估值欄位**：上市以 TWSE 交易後資訊、上櫃以 TPEx 盤後資訊為 authority。價格是交易所市場事實；本益比、殖利率、股價淨值比則是交易所依其口徑計算的衍生資料，必須連同資料日與財報基準保留，不能當成無時點的公司常數。
4. **Point-in-time（PIT）核心**：財務期間結束日、營收月份或法說舉辦日都不等於市場已知日。只有在 `available_at <= decision_time` 時，該版本資料才可進入回測或歷史評分。
5. **修訂不可覆寫歷史**：原申報、更（補）正與重編應 append-only 形成版本鏈。更正發布前的決策只能看到舊版；發布後才可看到新版。
6. **無證據即不可用**：缺列、空字串、`--`、查無資料、解析失敗、名稱對不上或安全攔截頁，一律不得轉成 0。預期資料有缺口時要以 machine-readable gap 記錄並 fail closed。
7. **研究邊界**：全市場層適合做 universe、截面排序及公告事件掃描；指定公司層採單一市場、最近 5 年（精確為最近 20 個已發布季度）深入擷取，並保留逐來源 hash 與 lineage。

---

## 2. Authority 分層與適用範圍

### 2.1 Authority 優先序

| 層級 | 資料 | 第一手 authority | 可接受用途 | 不應取代 authority 的來源 |
|---|---|---|---|---|
| A | 上市／上櫃身分、市場別、當期公司名稱 | TWSE／TPEx 公司基本資料 OpenAPI | 當期 universe、單一市場驗證 | 搜尋引擎、券商名稱表、第三方代碼表 |
| A | 公司申報財報、月營收、重大訊息、法說資料 | MOPS 原始申報／官方 OpenAPI | 原始事實、公告事件、申報版本 | 新聞摘要、資料商重整欄位 |
| A | 成交價量 | TWSE／TPEx 盤後行情 | 日／月價格、成交量、報酬基礎 | 網站爬價、未說明還原口徑的資料 |
| A-derived | 官方本益比、殖利率、股價淨值比 | TWSE／TPEx 盤後估值資料 | 當日官方截面估值 | 把不同供應商的 TTM／股利口徑混用 |
| B-derived | 自行計算品質與估值指標 | 經驗證的 A 層 facts + 明示公式 | 可重算衍生分析 | 無原始座標、無版本時間的彙總數字 |

「第一手」不表示資料永遠不會修訂，也不表示下載當下可重建過去所見。Authority 決定**誰有資格陳述該事實**；PIT 與 provenance 決定**何時知道、取得哪一版、能否重現**。

### 2.2 全市場與指定公司模式不得混淆

| 模式 | 建議來源型態 | 典型用途 | 契約 |
|---|---|---|---|
| 全市場快照 | TWSE／TPEx OpenAPI；MOPS `t163...`／月營收彙總查詢 | universe、最新期截面、公告掃描、每日行情／估值 | 原始回應可包含多家公司；manifest 必須標 `endpoint_scope=full_market` |
| 指定公司歷史 | MOPS `t164...` 公司財報；MOPS 歷史重大訊息／法說；交易所個股歷史行情 | 單一公司近 5 年深度研究 | 先以單一市場 identity 驗證；每筆 durable artifact 只能宣稱實際請求的公司／市場／期間 |
| 解析後 facts | 上述 raw 的衍生資料 | 指標、圖表、模型 | 每筆 fact 必須回指 source hash 及表格座標；不可只留清理後 CSV |

若指定公司流程不得持久保存全市場資料，使用 bulk 端點時只能在暫存區抽取，寫入公司級 artifact 後刪除 bulk bytes；manifest 仍要誠實記錄原端點是 full-market，而不能偽稱 company-level。

---

## 3. 各資料域的官方來源與契約

## 3.1 公司身份、上市／上櫃歸屬

### 官方來源

- 上市公司基本資料：<https://openapi.twse.com.tw/v1/opendata/t187ap03_L>
- 上櫃公司基本資料：<https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O>
- TWSE OpenAPI 規格：<https://openapi.twse.com.tw/v1/swagger.json>
- TPEx OpenAPI 規格：<https://www.tpex.org.tw/openapi/swagger.json>

### 規則

- `security_code` 只代表該市場證券代碼，不直接等於永久法人 `company_id`。
- 使用者指定上市時，只查上市 authority；指定上櫃時，只查上櫃 authority。找不到即 `identity_not_found_in_requested_market`，不得偷偷改查另一市場。
- current OpenAPI 是**當期快照**，不能單靠今天的公司名稱反推 5 年前名稱、市場或法人關係。
- 保存原始全名、簡稱、代碼、市場、產業別、出表日期與 retrieval time。名稱正規化值只能作搜尋輔助，不可取代 reported name。
- 要做歷史分析，須由按日／按次保存的官方快照及官方更名、合併、終止上市櫃事件建立 SCD2：`[valid_from, valid_to)`。沒有權威事件能唯一解析時，永久 ID 留 NULL，不可用模糊名稱硬接。
- 跨期整併、代碼重用、換股合併或市場移轉，不得自動沿著「看起來像同一家公司」的 lineage 串接。

## 3.2 財務報告

### 官方來源

**全市場／最新截面**

- TWSE 最新一般業綜合損益表例：<https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci>
- TPEx OpenAPI 規格中提供 `mopsfin_t187ap06_O_*`（損益表）與 `mopsfin_t187ap07_O_*`（資產負債表），並依一般業、金融、保險、證券期貨、金控等 schema 分流。
- MOPS 全市場比較報表：`t163...` 系列，例如 <https://mopsov.twse.com.tw/mops/web/t163sb04>。應先讀官方表單，再以有界年份、季別及市場實測 request scope。

**指定公司／歷史**

- 資產負債表：<https://mopsov.twse.com.tw/mops/web/t164sb03>，POST `ajax_t164sb03`
- 綜合損益表：<https://mopsov.twse.com.tw/mops/web/t164sb04>，POST `ajax_t164sb04`
- 現金流量表：<https://mopsov.twse.com.tw/mops/web/t164sb05>，POST `ajax_t164sb05`
- 財務報告公告：<https://mopsov.twse.com.tw/mops/web/t163sb01>
- 財務報告更（補）正查詢：<https://mopsov.twse.com.tw/mops/web/t56sb31_q1>

### 最近 5 年 selected-company 契約

- 先從官方已發布財報資料找出最大有效 ROC 年／季，不以今天日期猜「應該已公布」。
- 最近 5 年定義為**最近 20 個已發布季度**，不是 5 個曆年標籤。
- 每季應期待 balance、income、cash flow 三種報表，共 60 個 logical jobs；非季報制或客觀不適用者仍須有明確理由。
- `TYPEK=sii`（上市）與 `TYPEK=otc`（上櫃）是 single-market request 的一部分。回應須驗證報表類型、ROC 年季、提供資料的公司名稱及有效資料表。
- 損益／現金流可能是累計值，單季值只能依明示 value basis 合法推導；Q4 單季不得把全年值直接當 Q4。
- 產業 schema 不同時，以官方該業別欄位為準。欄位不存在不等於 0，也不得以經濟意義不同的欄位偷代。

### PIT 與修訂

- `fiscal_period_end` 是經濟期間；`announced_at`／`available_at` 才是知識時間。
- `t164...` 表格若未帶可靠公告時間，須以財報公告／申報紀錄建立版本時間；仍無法證明時，只能使用保守的首次成功擷取時間，並標 `availability_basis=retrieval_upper_bound`，不可倒填法定截止日或季末日。
- 更（補）正、重編與會計政策回溯應新增版本：`version_id`、`supersedes_version_id`、`correction_announced_at`、原因與新 raw hash。不得 overwrite 原始版本。
- 查詢 `as_of=T` 時，對每一 `(market, security_code, fiscal_period, report_type)` 只選 `available_at <= T` 的最新版本；若版本次序不清楚，回傳 unavailable。

## 3.3 重大訊息

### 官方來源

- 上市公司每日重大訊息：<https://openapi.twse.com.tw/v1/opendata/t187ap04_L>
- 上櫃公司每日重大訊息：<https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O>
- MOPS 歷史重大訊息：<https://mopsov.twse.com.tw/mops/web/t05st01>，POST `ajax_t05st01`
- MOPS 即時重大訊息入口：<https://mopsov.twse.com.tw/mops/web/t05sr01_1>

### 規則

- 每日 OpenAPI 適合全市場事件掃描；指定公司完整歷史宜用 MOPS `t05st01`，以公司、年度／月或日期區間作有界查詢。
- 至少保存發言日期、發言時間、事實發生日、主旨、條款、說明、公司代號／名稱及原始順序。
- **事件發生日不等於市場知道日**。回測可用時間預設為官方發言日期＋發言時間；若缺時區則明示採 `Asia/Taipei`。盤後公告不可放進同日收盤前的決策。
- 撤回、更正或補充訊息應是新事件並連回原事件，不刪除原文。若官方沒有穩定 event ID，可由 source hash、公司、發言時間與原始列座標形成 source event key，但不能宣稱為官方 ID。
- 重大訊息可能包含子公司事件；`issuer_security_code` 與內文中的 subject company 必須分欄，不能因文字出現另一公司名稱就改綁 identity。

## 3.4 法人說明會

### 官方來源

- MOPS 法人說明會一覽表：<https://mopsov.twse.com.tw/mops/web/t100sb02_1>，POST `ajax_t100sb02_1`

### 規則

- 全市場可用於某月法說排程／事件發現；指定公司以公司代號＋年份／月份有界查詢，並保留簡報、影音或公司網站連結的原始 URL。
- 分開保存：`announcement_at`（何時公告）、`event_start_at`（何時舉辦）、`material_published_at`（簡報何時可取得）、`retrieved_at`。三者不可互相替代。
- 法說內容在舉辦前不必然已公開；即使會議早已排程，簡報數字也只能在實際發布後使用。
- 簡報若後續換檔，需以 URL、HTTP metadata、byte count、SHA-256 建立新版本；同 URL 內容改變不可覆蓋舊 hash。
- 對口頭前瞻、簡報估計、已實現財報數字加 `fact_status`（如 `management_guidance`、`unaudited`、`reported`），不得把 guidance 當成已實現營收。

## 3.5 月營收

### 官方來源

- 上市公司每月營業收入彙總：<https://openapi.twse.com.tw/v1/opendata/t187ap05_L>
- 上櫃公司每月營業收入彙總：<https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O>
- MOPS 月營收查詢可由官方 MOPS 的月營收彙總表單進行年份、月份、市場的有界查詢；採用前應實測表單 action、request parameters 與 response scope，不應僅憑第三方套件的 endpoint 名稱。

### 規則

- OpenAPI 適合最新月份全市場截面，欄位通常含資料年月、當月、上月、去年同月、累計與增減比。
- `資料年月` 是營運月份，`出表日期` 是快照出表日；兩者都不必然等於公司最初申報的精確時刻。若要做歷史 PIT，需保存每日官方快照或取得可證明原始申報時間的 MOPS 紀錄。
- 不用「每月 10 日」等法定／慣例截止日代替實際 `available_at`。公司提早申報與更正均會造成差異。
- 當月、累計及同比欄位要視為各自的 reported facts。自行重算同比時需保留兩個月份的 lineage；不得因官方同比空白而把它設為 0。
- 更正營收須保留舊、新版本及更正可得時間；以今天下載的最新表回填過去會產生 revision look-ahead。

## 3.6 股價、成交量與估值

### 上市 TWSE 官方來源

- 全市場當日成交資訊 OpenAPI：<https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL>
- 全市場指定交易日盤後表：<https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20260722&type=ALLBUT0999&response=json>
- 指定公司月內每日成交：<https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260701&stockNo=2330&response=json>
- 全市場最新官方估值：<https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL>
- TWSE Swagger 另列 `BWIBBU_d`（依日期）與 `BWIBBU_ALL`（依代碼查詢）資料集；使用前按規格與實際回應確認 query semantics。

### 上櫃 TPEx 官方來源

- 全市場最新行情 OpenAPI：<https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes>
- 指定日全市場行情：<https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=2026/07/22&id=&response=json>
- 指定公司月內每日成交：<https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code=6488&date=2026/07/01&response=json>
- 全市場最新官方估值 OpenAPI：<https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis>
- 指定日估值：<https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date=2026/07/22&id=&response=json>

### 規則

- 日行情要保存交易日、OHLC、成交股數／金額／筆數、漲跌、註記及市場。休市日是 `not_a_trading_day`，不是缺值；交易日缺列才是 coverage gap。
- 原始價格與公司行動調整後價格是不同資料產品。若官方來源提供的是未還原價，不得標為 adjusted price；自建還原序列須記錄除權息／分割等每個 adjustment event 與公式。
- 當日盤後資料只能在官方發布且成功取得後使用。若策略在收盤撮合前決策，不得使用該日最終收盤價、成交量或當日估值。
- 官方估值欄位是衍生值。每筆至少綁 `market_date`、證券、官方欄位值、source hash；TPEx 回應另有「股利年度」及「財報年／季」時必須保存。空白本益比常可能源於虧損或不適用，不得轉成 0。
- 若自行計算估值，價格、流通股數、EPS／淨值／股利都必須是同一 `as_of` 可見版本，並明示 TTM、年度、預估或公告股利口徑；不得拿今天的股本或重編財報回算過去估值。

---

## 4. 統一 Point-in-Time 契約

### 4.1 必要時間欄位

每個資料物件應盡可能區分：

- `effective_at`：經濟事實生效時間，例如財報期末、營收月份、交易日、法說時間。
- `announced_at`：官方／公司發布時間。
- `available_at`：資料可安全進入研究系統的最早時間；有可靠公告時間時可由其推導，否則採保守的首次成功取得時間。
- `retrieved_at`：本系統實際完成下載時間（含時區）。
- `valid_from`、`valid_to`：該版本在知識時間軸上的有效區間，採半開區間 `[valid_from, valid_to)`。

核心判定：

```text
admissible(fact, decision_time) :=
    fact.available_at <= decision_time
    AND fact.version.valid_from <= decision_time < fact.version.valid_to
    AND fact.identity 在 decision_time 可唯一解析
```

`retrieved_at` 不能任意被當成真正的 announced time，但在缺乏更早證據時，它是防止 look-ahead 的保守上界。任何 inferred timestamp 都必須保存 `availability_basis` 與推導規則。

### 4.2 決策切點

- 日期一律保存原字串、解析後時間與 `Asia/Taipei` 時區；民國年轉換也保存原值。
- 日頻回測應明示決策在開盤前、盤中或收盤後。例如以 T 日收盤後資料形成訊號，最早通常只能在下一個可交易時點執行。
- 只有日期、沒有時間的公告，不得假設凌晨已知。可採「下一交易日開盤前才可用」等保守政策，並以 policy version 記錄。
- API 的 `出表日期`、response date 或 retrieval date 不等於公司原始公告時間；無法證明時不得精細化成虛構時間。

### 4.3 修訂版本選擇

```text
key = (market, security_code, data_domain, fiscal_or_event_period, canonical_field)
versions = 所有 source versions，依 available_at、官方序次、retrieved_at 排序
as_of_value(T) = versions 中 available_at <= T 的最後一個可驗證版本
```

- 不物理刪除 superseded version。
- 若兩版同時點衝突且無法判定順序，狀態為 `ambiguous_revision_order`，而非任選一版。
- 更正發布前保留錯誤舊值，正是 PIT 回測需要的歷史真相；「現在知道的正確值」與「當時可知值」應是兩個查詢模式。

---

## 5. Provenance 與完整性契約

### 5.1 每個 durable raw artifact 的最小 manifest

```yaml
artifact_id: immutable-id
provider: TWSE | TPEx | MOPS
market: listed | otc
endpoint_scope: full_market | selected_company
requested_security_code: "2330"   # full-market 可為 null
resolved_official_name: "台積電"
landing_url: "..."
data_url: "..."
http_method: GET | POST
request_parameters: {}             # 排除 cookie/token 等秘密
http_status: 200
retrieved_at: "2026-07-23T...+08:00"
response_content_type: "..."
source_byte_count: 12345
source_sha256: "..."
compression: none | gzip
compressed_byte_count: null
period: "115Q1"
report_or_domain: balance | income | cash_flow | revenue | material_event | investor_conference | price | valuation
response_identity_name: "..."
retention_class: full_market_8q | selected_company_20q | event_history | market_history
parser_version: "..."
```

POST body、實際 endpoint、market 參數與 response scope 都是 provenance。landing page 與 data URL 要分開記錄。壓縮保存時同時記原始 bytes 與壓縮後 byte count；`source_sha256` 應對官方原始 response bytes，而非美化後 HTML 或解析 CSV。

### 5.2 Parsed fact lineage

每筆 canonical fact 至少包含：

- `source_sha256`、artifact ID；
- table index、row index、column index／原始欄名；
- 原始字串、解析值、單位、幣別、倍率、value basis；
- security code、reported name、market、period／event time；
- parser／schema mapping version；
- source version 與 `available_at`。

座標皆須為非負整數；同一次產出中，同一 `(source hash, table, row, column)` 不得被兩個互斥 canonical facts 重複占用。衍生指標 lineage 應列出全部分子、分母與比較期來源，而非只指向結果 CSV。

### 5.3 Run-level coverage

對預期集合逐列輸出：

```text
(expected key, status, artifact_id/source_hash, reason, attempts)
status ∈ {available, gap, error, not_applicable}
```

指定公司 20 季 × 3 報表必須正好有 60 列 coverage。任一 gap／error 預設阻止發布完整評分；只有明示可降級的指標才可輸出 `NULL + unavailable_reason`，不可靜默以剩餘資料計成看似完整。

---

## 6. 缺值、錯誤與 fail-closed 分類

建議使用互斥 reason code：

- `not_yet_published`：截至 as-of 尚未發布；
- `not_applicable`：官方 schema／公司型態客觀不適用；
- `official_blank`：官方列存在但欄位空白；
- `no_official_row`：預期市場／公司／期間無資料列；
- `market_holiday`：非交易日；
- `identity_unresolved`／`identity_name_mismatch`；
- `historical_name_unresolved`；
- `security_or_interstitial_response`；
- `wrong_market`、`wrong_period`、`wrong_report_type`；
- `parse_error`、`schema_changed`；
- `source_hash_mismatch`／`cache_corrupt`；
- `ambiguous_revision_order`。

以下回應即使 HTTP 200 也必須拒收：MOPS 安全／驗證中介頁、查無公司、空表、報表標題不符、年季不符、提供資料公司名稱與官方 identity 不一致、內容其實是錯誤頁。對 cache resume 也要重驗 gzip、byte count、hash、manifest identity 與內容，不可因檔案存在就跳過。

---

## 7. 歷史名稱與法人／證券 lineage

1. 保存三種名稱：官方當期 identity name、來源頁 reported name、正規化 search name。
2. 以 authoritative event 建立 `security_name_history(security_code, market, reported_name, valid_from, valid_to, source_hash)`；區間半開且不可重疊。
3. MOPS 舊報表可能顯示歷史名稱而當期 identity API 顯示新名稱。只有名稱歷史能在該期唯一對應時才接受；否則產生 `historical_name_unresolved`，不可用字串相似度靜默通過。
4. 證券代碼、市場證券、法律實體分層建模；合併、分割、KY／存託憑證、代碼重用及市場移轉都需明示 owner 與有效期間。
5. 永久 `company_id` 只有在 as-of resolver 能證明唯一 active security row 與有效 reported-name history 時才可填；否則 NULL 比錯接更安全。

---

## 8. 避免 Look-ahead 的檢核表

- [ ] universe 是以研究當時可知的上市／上櫃成分建立，而不是今天仍存續公司名單（避免 survivorship bias）。
- [ ] 每個 fact 的 `available_at` 不晚於決策時間。
- [ ] 季末日、營收月份、事實發生日、法說日期未被誤作公告時間。
- [ ] 使用的是 as-of 當時版本，不是今天下載的更正版。
- [ ] 收盤前訊號未使用當日最終收盤、成交量或盤後估值。
- [ ] 財報累計值已正確轉單季，且轉換所需前期資料當時可知。
- [ ] 歷史估值未使用今日股本、今日名稱、後來重編 EPS 或後來公告股利。
- [ ] 退市、移轉、改名與代碼重用未被 current identity snapshot 抹去。
- [ ] 空白、不適用、查無資料及解析失敗未被轉成 0。
- [ ] 所有衍生值可回溯至原始 source hash、欄位座標及公式版本。

---

## 9. 建議的實務採集邊界

### 全市場層

- 每日保存上市與上櫃 identity 快照、行情、估值、重大訊息；每月保存月營收快照；每個財報發布週期保存各產業 schema 財報快照。
- 全市場季度 raw retention 若受政策限制，可只保留最近 8 個已發布季度，但 PIT 長期回測所需的歷史版本不能在未另有合規 archive 前被刪除。
- snapshot 必須連同 retrieval timestamp 與 source hash 保存，否則 latest-only API 無法重建過去所見。

### 指定公司層

- 接受明確的 `market + security_code`；禁止自動跨市場。
- 抓取最近 20 個已發布季度的 3 張公司財報、同期間月營收、重大訊息、法說與交易所行情／估值。
- 原始與 manifest 依公司／市場／期間分區；每次 run 產生完整 coverage manifest。
- 對 MOPS 採單一 persistent session、先載入 landing page、公司端點有效 worker=1、小幅延遲、暫時性錯誤指數退避與可驗證 resume，避免把 rate limit 安全頁誤存為資料。

---

## 10. 本次實際查核摘要（2026-07-23）

- TWSE／TPEx 公司基本資料 API 均回 HTTP 200，內容分別包含上市／上櫃公司代號與名稱。
- 上市／上櫃月營收 API 均回 HTTP 200，內容包含資料年月與出表日期。
- 上市／上櫃重大訊息 API 均回 HTTP 200，內容包含發言日期、發言時間、事實發生日、主旨及說明。
- TWSE `STOCK_DAY_ALL`、`BWIBBU_ALL`，TPEx `tpex_mainboard_daily_close_quotes`、`tpex_mainboard_peratio_analysis` 均回 HTTP 200。
- TWSE 指定日全市場／指定公司月行情，以及 TPEx 指定日全市場／指定公司月行情／指定日估值查詢均回 HTTP 200。
- MOPS `t05st01`、`t100sb02_1`、`t163sb01`、`t56sb31_q1`、`t164sb03` landing pages 均可取得；HTML 表單分別指向相對應 `ajax_...` POST action。

以上只是端點存在與回應 schema 的查核，不代表所有歷史期間均完整。正式採集仍須逐期間建立 coverage、驗證 identity／報表內容及保存 hash。
