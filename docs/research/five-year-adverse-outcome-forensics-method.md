# 近五年下市股票與高點回撤逾 50% 股票：Point-in-Time 財報鑑識研究方法

> **文件性質**：研究方法與治理契約；不含產品碼、不構成投資建議，也不先決定產品分數或警報門檻。  
> **市場範圍**：台灣普通股；每一次研究執行只能選 `market=listed`（TWSE 上市）或 `market=otc`（TPEx 上櫃）其中之一。兩市場可依同一方法各自研究，但不得在同一母體中混合校準、查不到便跨市場 fallback，或把轉上市／轉上櫃誤標為失敗。  
> **研究基準日**：由每次執行的 `study_cutoff` 決定；日期與時間一律保存 `Asia/Taipei` 時區。  
> **核心資料原則**：官方來源優先、as-of 可得、原始 bytes 留存、SHA-256、逐欄 lineage、完整 coverage、任何身分／版本／公司行動／價格缺口一律 fail closed。

---

## 1. 研究問題與核心結論

本研究回答兩個不同但可重疊的問題：

1. 過去五年在指定市場終止上市／上櫃的股票，終止原因、財報警訊、公開事件與市場路徑為何？
2. 過去五年在指定市場曾由可驗證高點下跌**嚴格超過 50%**的股票，在跌破門檻前有哪些當時已可知的財報警訊？

兩者必須採 **multi-label** 保存：

- `delisted_all=1`：五年結果窗內曾終止該市場掛牌，不論原因；
- `delisted_adverse=1`：終止原因經官方文件確認屬財務／申報／交易／法遵等不利原因；
- `drawdown_gt_50=1`：公司行動還原後的股東財富序列，於結果窗內首次出現 `DD_t > 0.50`；
- `adverse_union=1`：`delisted_adverse=1 OR drawdown_gt_50=1`；
- `delisted_non_adverse=1`：合併、股份轉換、收購私有化、轉市場等非失敗型終止掛牌，保留於案例全集，但不可直接當成財務失敗正例。

**不得把「所有下市」等同「財務危機」；也不得把股價跌逾 50% 等同舞弊或破產。** 兩者是研究結果（outcome），警訊只是事前風險證據。

---

## 2. 時間軸、樣本母體與分析單位

### 2.1 五年結果窗

令：

```text
C  = study_cutoff（含時區的研究截點）
W0 = C 往前推 5 個曆年後的次一時點
O  = [W0, C]，即結果認定窗
```

採曆年位移，不用「1,250 個交易日」近似。閏日、休市與臨時停止交易依官方交易日曆及實際行情處理。所有輸出保存 `study_cutoff_policy_version`。

### 2.2 Single-market 母體

每一市場各自建立歷史母體：

```text
U_m = 在結果窗 O 的任一時點，曾於指定市場 m 有效掛牌交易的合格普通股證券
```

建母體時使用**歷史成分／掛牌事件**，不是今天仍存在的公司名單。最低納入條件：

- 該證券在指定市場有官方掛牌身分與有效區間；
- 能唯一解析當時的 `market + security_code + reported_name`；
- 證券型態為普通股；ETF、ETN、權證、基金、債券、特別股、TDR／DR 不自動混入；
- 創新板、KY、第一上市或其他制度別若納入，必須另存 `board/regime` 並分層報告，不得假設風險基準率相同；
- 新上市股票仍納入，但只從實際首個可交易日開始觀察，不能要求不存在的上市前行情；財報前史不足另記 `limited_history`。

同一證券由上櫃轉上市，對上櫃研究是 `market_transfer_out`，對上市研究則由上市生效日起成為新風險區間。可建立明示的 investment lineage 以計算股東財富，但**不得因此把兩市場證券期間併成同一 single-market calibration row**。

### 2.3 三種分析單位不得混淆

1. **證券—事件（security-event）**：用於下市、首次跌破 50%、停止交易等事件鑑識。
2. **證券—landmark（security-as-of）**：每月末或每季末形成一次當時可知的風險快照，用於模型訓練與評估。
3. **法律實體—財報期（entity-period）**：用於合併財報 facts 與衍生指標。

證券代碼不是永久法人 ID。合併、股份轉換、代碼重用、公司更名、分割及市場移轉都需以帶有效期間的 history table 明示；無法唯一解析時，該列為 `identity_unresolved`，不得用名稱相似度硬接。

---

## 3. 下市／下櫃事件與原因分類

### 3.1 事件時間欄位

每一終止掛牌事件至少保存：

- `first_public_announcement_at`：官方首次公開該終止或處分資訊的時間；
- `decision_announced_at`：交易所正式決定／公告時間；
- `last_trading_date`：最後實際可交易日；
- `suspension_start_at`：停止交易起點（如有）；
- `delisting_effective_date`：終止上市／上櫃法律／市場生效日；
- `cash_or_share_consideration_available_at`：收購、合併或股份轉換對價可知時間；
- `recovery_paid_at`：清算、收購或其他實際回收日（如有）。

主下市標籤事件日為 `delisting_effective_date`；但預警 lead time 另相對於首次公開不利公告及最後交易日報告。不得用後來公告日回填先前市場已知時間。

### 3.2 原因 taxonomy

官方原文、法條與交易所原因碼完整保存，再映射到下列研究類別；不得只留研究類別而刪除官方理由：

| 研究類別 | 典型事件 | `delisted_adverse` | 注意事項 |
|---|---|---:|---|
| `merger_share_exchange_acquisition` | 被合併、股份轉換、收購私有化、設立金控 | 0 | 不代表失敗；另評估對價與股東實現報酬。 |
| `market_transfer` | 上櫃轉上市、上市轉其他交易板／制度 | 0 | 在原市場是終止，在新市場是新掛牌區間。 |
| `voluntary_delisting_other` | 公司申請終止，未屬危機且有公平對價 | 原則 0 | 必須讀正式公告與對價；理由不明不可猜。 |
| `bankruptcy_dissolution_reorganization` | 破產、解散、清算、重整、撤銷登記 | 1 | 區分聲請、裁定、確定及實際回收。 |
| `financial_distress_net_worth` | 淨值、持續虧損、債務違約、無法繼續經營等觸發規則 | 1 | 保存適用規則版本及款次。 |
| `filing_audit_failure` | 未依法申報、無法出具財報、查核意見／會計師問題導致終止 | 1 | 不把所有更正或會計師更換自動視為此類。 |
| `trading_integrity_regulatory` | 重大違規、拒絕往來、退票、證券交易／法遵原因 | 1 | 以交易所、FSC／金管會正式文件為準。 |
| `operating_inactivity_material_change` | 營業範圍重大變更、停業或實質營運不足 | 1 或 competing | 需依規則及個案判定，保留二次覆核。 |
| `management_stock_legacy_regime` | 管理股票終止、舊制度原因 | 個案 | 不以名稱直接推論損失，讀公告及歷史規則。 |
| `other_official_reason` | 官方列「其他」或款次未完成映射 | NULL | `reason_unresolved`，不得放入 adverse/non-adverse 校準。 |

同一事件可有一個 primary reason 與多個 contributing reasons。兩位研究者獨立分類；不一致交由第三人依官方公告裁決，保存原判、理由、規則版本與 reviewer。

---

## 4. 「由高點下跌超過 50%」與公司行動還原

### 4.1 主序列：股東財富 total-return index

主分析使用官方未還原收盤價與官方公司行動，重建每一證券的 `wealth_index_t`。原則是：若投資人在事件前持有一單位經濟權益，現金股利、股票股利、分割／反分割、現金減資退還、彌補虧損減資、面額變更、合併／股份轉換、權利分派後，其財富路徑不得因純機械除權而虛假下跌。

```text
running_peak_t = max(wealth_index_s), s <= t
DD_t           = 1 - wealth_index_t / running_peak_t
MDD            = max(DD_t)
drawdown_gt_50 = 1 iff 存在 t 使 DD_t > 0.50
```

`= 50%` 不算「超過 50%」。金額、比率與因子以固定精度 Decimal 計算，不使用浮點誤差判定門檻。

### 4.2 公司行動 adjustment ledger

每一事件逐筆保存：

- 除權／除息基準日、最後交易日、恢復交易日；
- 現金股利、股票股利、分割／反分割比例；
- 現金減資退還、虧損減資及新舊股數／面額；
- 現金增資、認購權及權利價值的既定處理；
- 合併、股份轉換、收購對價與生效日；
- source artifact、官方原始欄位、source SHA-256、座標、可得時間；
- adjustment formula/version、調整前後股數、現金與財富值。

不得對所有事件套一個未經核對的通用乘數。先以交易所除權息計算資料為基準，再以 MOPS 公司行動公告核對事件性質。任何影響財富路徑的事件缺少比例、現金對價或生效日，該段為 `corporate_action_gap`；精確 MDD 不發布。

### 4.3 合併、私有化與終端值

- 現金收購：在對價實現日加入實際現金對價；不把下市後「無報價」當價格為零。
- 換股：可沿官方換股比例建立**投資對價 lineage**，但不改寫法律實體 identity；後續新證券價格只用於股東財富回收分析，不併入原公司財報。
- 不利下市且尚無可驗證回收：MDD 截至最後可交易價格右設限，`terminal_recovery=unavailable`。可另報「回收為 0」與「最後價」的敏感度界限，但不得把假設值當觀測值。
- 長期停止交易：停止交易不是休市，也不是零報酬；另標 `price_path_censored_by_suspension=1`。

### 4.4 結果窗內的高點與 carry-in

主定義要求 running peak 與首次跌破都發生於結果窗 O（新股則自上市日起）。另作 `carry_in_drawdown` 敏感度：允許高點位於 W0 前最多 24 個月，而跌破發生於 O。兩種結果分開報告，不可事後選較多案例的版本。

### 4.5 事件日

- `peak_date`：導致該次首次跌破的先前 running peak 日期；同高點多日採最早或最後一天必須事前固定，建議採**最後一次達峰日**以衡量連續下跌期。
- `dd50_trigger_date`：收盤後 `DD_t` 首次嚴格大於 0.50 的交易日。
- `trough_date`：該次 episode 在恢復或結果窗結束前的最低財富日。
- `recovery_date`：首次回到舊高點；未恢復則右設限。

同一股票可有多個 drawdown episode；主案例使用結果窗內第一次跨越 50% 的 episode，嚴重度另報全窗 MDD。當日收盤形成的事件只能在收盤後被確認。

---

## 5. 事前觀察窗與兩種研究設計

### 5.1 事件鑑識（case forensics）

對每個事件建立固定快照：

- `T-24m`、`T-12m`、`T-6m`、`T-3m`、`T-1 trading day`；
- `T` 為 `dd50_trigger_date` 或 `delisting_effective_date`；
- 另以 `first_public_adverse_announcement_at` 作事件資訊時間軸。

每個快照只使用該截點已可得版本。觀察輸入可包含最多最近 20 個已發布季度，但趨勢特徵的最低期數、跨期間距及缺值規則事前固定。事件發生後的資料只能用於「解釋後果」，不得回填為事前警訊。

事件鑑識用來回答「發生了什麼、當時可看到什麼」，**不能**單獨估計 precision，因為只看案例沒有完整非案例分母。

### 5.2 Landmark cohort（模型校準／驗證）

在每個固定月末或季末 `L`，對當時仍可投資且身分有效的全母體股票產生一列：

```text
features = facts with available_at <= L
outcome  = L 後固定 H 期間內是否發生指定 adverse outcome
```

Wayne 已將正式 headline calibration 固定為 `H=12 個月`；本研究 label 必須升版並以 12 個月 outcome 作正式權重、bucket 與模型選擇。24／36 個月只能建立明確分離的 sensitivity label/version，禁止混入正式 12 個月 headline calibration。死亡、下市、合併與停止交易不得從 denominator 消失。對負例必須有完整 H 期追蹤；不足者為 right-censored，不可當 0。

同一公司多個 landmark 高度相關；信賴區間、bootstrap 或 standard error 必須以公司群聚，且 train/test 不得讓同一事件 episode 透過重疊 landmark 同時外洩。

---

## 6. Point-in-Time 財報可得時間與修訂

### 6.1 統一時間契約

每筆原始／解析 fact 至少區分：

- `fiscal_period_end`／`effective_at`：經濟期間；
- `announced_at`：公司／官方發布時間；
- `available_at`：研究系統可安全使用的最早時間；
- `retrieved_at`：本系統取得時間；
- `valid_from`, `valid_to`：該版本在知識時間的半開有效區間 `[from, to)`。

```text
admissible(fact, L) :=
  fact.available_at <= L
  AND fact.valid_from <= L < fact.valid_to
  AND identity_as_of(L) 可唯一解析
  AND source/coverage/lineage 驗證通過
```

季末日、法定申報截止日、營收月份、事件事實日均不等於 `available_at`。若官方只有日期沒有可靠時間，固定於該日期後的下一個 Asia/Taipei 午夜整點開始可用；不得改用「下一交易日開盤前」或其他市場日曆政策。盤後公告不能進入其正式 `available_at` 前的快照。

### 6.2 財報與更正

- MOPS 資產負債表、綜合損益表、現金流量表及財報公告共同建立申報版本；
- 原申報、更（補）正、重編、會計政策追溯調整 append-only，保存 `supersedes_version_id`；
- 歷史查詢只選 `available_at <= L` 的最新可驗證版本；今天看到的更正版不得回填昨天；
- MOPS 歷史報表若無法證明首次公告時間，只能以首次成功留存時間作 `retrieval_upper_bound`。若首次留存晚於研究 landmark，該 fact 對該 landmark 不可用；
- 損益與現金流累計數轉單季時，所需前一累計版本也必須在 L 前可得；缺一不可推；
- 年度與季度、合併與個體、一般業與金融／保險 schema 不得混用；經濟上不適用記 `not_applicable`，缺值記明確 reason，均不得轉 0。

### 6.3 最小 lineage

每個 canonical fact／feature 應能回溯到：

```text
provider + landing_url + data_url + request params
source_sha256 + byte_count + retrieved_at
market + security_code + reported_name + fiscal period
artifact_id + version_id + available_at
raw string + unit + scale + currency + value basis
(table index, row index, column index/original field)
parser/schema/formula version
all numerator/denominator/comparison-period fact IDs
```

同一 `(source hash, table, row, column)` 不可被互斥 facts 重複占用。任何衍生警訊都需列出完整當期與比較期 lineage，不能只指向清理後 CSV。

---

## 7. 財報與公開資訊警訊 taxonomy

警訊先按 evidence family 保存連續值與理由碼，再決定是否進模型。禁止因一個事實換算成多個比率而重複加權。

| 家族 | 候選警訊（均須 PIT） | 常見誤判／適用限制 |
|---|---|---|
| `profitability_deterioration` | 營收、毛利率、營益率、ROA/ROIC 持續惡化；連續虧損；固定成本營運槓桿 | 週期谷底、一次性停工、新廠爬坡；金融業不可套一般企業公式。 |
| `cash_conversion_accruals` | 淨利與 CFO 背離、應計升高、應收／合約資產／存貨快於營收、營運資金長期吸收 | 高成長備貨、里程碑合約、季節性；須同季節同比與產業基準。 |
| `asset_quality_impairment` | 商譽／無形資產／在建工程／閒置資產偏高、減損、資產重分類、資本化政策改變 | 併購與研發密集公司結構性偏高；減損是落後訊號。 |
| `liquidity_solvency` | 現金耗用、短債／總債上升、利息保障下降、流動比惡化、負淨值、到期牆、違約／退票、持續經營疑慮 | 銀行、保險、REIT 需專用路由；未披露 covenant 不代表沒有風險。 |
| `financing_dilution` | 現增、私募、可轉債／附認股權融資、頻繁股本膨脹、庫藏股與增資反覆、資金缺口 | 成長型融資不必然不利；需看用途、價格、控制權與後續報酬。 |
| `reporting_audit_integrity` | 逾期申報、更補正／重編、非無保留意見、查核範圍限制、持續經營段、頻繁換會計師、財報版本衝突 | 更正可能不重大；換所可能正常輪調。嚴重性依正式意見與原因，不靠關鍵字定罪。 |
| `governance_related_party` | 關係人交易／資金貸與／背書保證異常、董事或控制權快速更替、治理違規、內控聲明問題 | 集團正常交易需與規模、條件、回收及揭露完整性比較。 |
| `operating_concentration` | 單一客戶／供應商／產品／地區集中、停工、重要合約流失、月營收崩落 | 揭露可能不連續；避免用事後法說補以前未公開資訊。 |
| `capital_allocation` | 高價併購、商譽累積、低回報 capex、資產處分維持獲利、異常股利／減資與負債並存 | 現金減資或處分也可能是有效率返還資本。 |
| `listing_market_status` | 變更交易、分盤、停止買賣、處置、交易量枯竭 | 多為晚期警訊；若評估 12/24 月早期預警，須另報「含／不含市場狀態」模型。 |
| `market_valuation_fragility` | 極端估值、價格與基本面背離、波動與流動性惡化 | 不是財報警訊，須獨立家族；不可讓 outcome 期間價格進 feature。 |
| `data_model_risk` | 身分未解、歷史名稱缺口、財報版本不明、公司行動缺漏、schema 不適用、低覆蓋 | 這是 no-rating／低信心依據，不是把公司判成壞公司的分數。 |

Piotroski、Beneish、Altman 可作診斷，但需使用固定版本及適用產業；Beneish 警報不是舞弊證明，Altman 原始式不是所有產業通用，F-score 與 CFO、毛利、槓桿等高度重疊。模型總分進上層前須拆 component 並做 raw-fact × indicator lineage matrix。

### 7.1 防 label leakage 的 feature 層級

至少發布三個 challenger：

1. `financial_only`：僅用財報及月營收；
2. `financial_plus_governance_events`：加入當時已公開治理、查核、重大訊息；
3. `all_public_pre_event`：再加入變更交易、停止買賣、流動性與市場訊號。

這可區分「能提早看出的基本面風險」與「交易所已公開危機後才響的警報」。任何在 outcome trigger 後才發布的公告一律禁止進入該 landmark feature。

---

## 8. 避免 look-ahead 與 survivorship bias

### 8.1 強制檢核

- 母體來自每一歷史時點曾掛牌者，含後來下市、合併、更名、轉市場及停止交易者；
- 只能使用 `available_at <= landmark` 的當時版本；
- 不用今天公司名單、產業分類、股本或更正版財報重建過去；
- 公司行動按當時官方事件逐筆還原，不購買第三方「已調整價」後忽略其黑箱口徑；
- 當日收盤價／成交量只在收盤後可用；
- 正負例均需完整追蹤；下市不得因行情表後續無列而被 drop；
- 選股、同業分位、winsorization、normalization 只用當時橫截面；
- threshold、feature、產業 route、缺值政策只在 train/validation 定案，test 不回頭調；
- 人工看完案例後新增的警訊標為 `post_hoc_hypothesis`，不可回頭計入同一案例的樣本外成績。

### 8.2 Coverage 與 fail-closed

對每一預期輸入鍵輸出：

```text
(expected_key, status, artifact_id/source_hash, reason, attempts)
status ∈ {available, gap, error, not_applicable}
```

建議互斥原因碼：`not_yet_published`、`official_blank`、`no_official_row`、`not_applicable`、`identity_unresolved`、`historical_name_unresolved`、`ambiguous_revision_order`、`corporate_action_gap`、`price_gap_on_trading_day`、`suspended_no_price`、`terminal_recovery_unavailable`、`schema_changed`、`security_interstitial_response`、`source_hash_mismatch`。

必要來源有 gap／error 時：

- 個股精確 MDD：公司行動或交易日價格缺口即 unavailable；
- 必要財報 feature：輸出 `NULL + reason`，不得以 0、中位數或今天版本補；
- 低於事前最低 coverage：`no_rating`，不得只從完整案例挑選；
- 研究總表仍保留 unavailable 列，以揭露 selection pressure。

---

## 9. False positives 與 false negatives

### 9.1 典型 false positives

- 合併／股份轉換／私有化而終止掛牌，但股東獲得合理對價；
- 上櫃轉上市等市場移轉；
- 高成長造成應收、存貨、capex 與融資同步上升；
- 半導體、航運、原物料等週期性谷底；
- 重大併購、會計政策或 IFRS 分類改變造成比率跳動；
- 生技／研發公司正常現金耗用，卻被一般製造業 Z／F／FCF 模型誤判；
- 健全公司的現金減資、分割或股票股利被錯當價格崩跌／資本危機；
- 市場全面崩跌使高品質公司短暫回撤逾 50%，但基本面與永久損失未發生。

控制方式：下市原因分層、產業 route、公司行動還原、相對市場／產業回撤並列、episode 恢復時間、人工案例複核；但人工複核不得改掉原始 outcome。

### 9.2 典型 false negatives

- 舞弊、資產掏空或表外義務在事件前未揭露；
- 客戶流失、產品失敗、災害、訴訟或監管禁令突然發生；
- 母公司／銀行短期支援延後危機，使財報比率看似安全；
- 價格泡沫破裂主要由估值壓縮，財報尚未惡化；
- 季報頻率太低，危機在兩個申報點間快速發生；
- 官方歷史版本、公司行動或公告時間不可重建而被 fail closed；
- 模型不適用產業、結構性轉型或新上市公司缺少比較期。

因此應同時報告 feature-family 的 misses，不把 recall 不足解讀為「未被抓到的公司沒有警訊」。

---

## 10. 評估指標：precision、recall、lead time

### 10.1 混淆矩陣的單位

主單位是 `security-landmark`，在固定 horizon H 內：

```text
TP = landmark 發警報，且 H 內發生目標 outcome
FP = landmark 發警報，但完整 H 內未發生
FN = landmark 未發警報，但 H 內發生
TN = landmark 未發警報，且完整 H 內未發生
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
```

分母為 0 時回傳 unavailable，不得填 0 或 1。事件稀少時至少同報事件數、公司數與 bootstrap 信賴區間。

### 10.2 必報結果

分別對 `drawdown_gt_50`、`delisted_adverse`、`adverse_union` 報告：

- precision、recall、F1；
- PR-AUC／average precision 與 outcome prevalence；ROC-AUC 只作輔助，不能掩蓋 class imbalance；
- 每 100 家公司年警報數、每抓到一個事件所需調查數；
- fixed-alert-budget recall（例如固定可查核量下的召回）；
- 不同產業、規模、board、年份／regime 的切片；
- drawdown severity、事件後回收、下市 terminal recovery，不只二元命中；
- 含及不含 late-stage market-status features 的增量表現。

門檻不能只最大化 F1；需依研究用途呈現 precision–recall frontier，交由治理者選擇調查成本與漏失成本。

### 10.3 Lead time

對每個 TP 定義：

```text
alert_at = 第一個達門檻且滿足 sustained-alert 規則的 landmark 可得時間
event_at = dd50_trigger close 或 delisting effective date
lead_time = event_at - alert_at
```

`sustained-alert`（單點或連續兩次）須事前固定。報告：

- median、25/75 percentile、最小／最大 lead time；
- 在事件前至少 3、6、12、24 個月的 event-level recall；
- 相對 `first_public_adverse_announcement_at`、`dd50_trigger_date`、`delisting_effective_date` 三個時鐘；
- 負 lead time（事件後才警報）列為 late detection，不得算 TP；
- 對同一事件多個 landmark 只以最早合格 alert 計一次 event-level lead time，避免灌水。

若公司在 peak 前已長期警報，另報 `lead_to_peak` 與 `lead_to_trigger`；兩者回答不同問題。

---

## 11. Train／validation／test 的時間切分

### 11.1 首選：把近五年案例窗封存為 out-of-time test

最乾淨的設計是：

1. **Train**：只使用 W0 以前、已有完整 PIT 與 H 期 outcome 的 landmarks；
2. **Validation**：緊接 W0 前的一段時間，用於 feature、門檻、產業 route、alert persistence 與 calibration；
3. **Embargo/purge**：任何 label horizon 跨入後一區間的 landmark 不進前一區間，避免同一事件及未來價格重疊；
4. **Test**：W0 起的近五年 adverse cases 與同期完整母體一次性評估；看完 test 後的變更只能成為下一版 challenger。

切分按 landmark／可得時間，不按今天的公司，也不隨機拆公司列。若同一法律實體跨證券或跨市場，entity group 不得跨 fold 洩漏。

### 11.2 只有近五年 PIT 資料時

若沒有 W0 前的可靠 as-seen archive，**不能誠實地訓練並校準一個正式模型**。原因包括：

- 正式 H=12 個月時，靠近 C 的負例尚未成熟；24／36 個月 sensitivity maturity 必須在其獨立 label/version 內另算且不得影響 headline calibration；
- 嚴格 purge 後可供 train/validation/test 的時間很短；
- 下市是低基準率事件，事件數可能不足；
- 今天回抓 MOPS 最新更正版不能重建當時所見。

此時只能：

- 做描述性案例鑑識、警訊 prevalence 與 matched-control 探索；
- 使用事前固定的外部／簡單 benchmark，不在五年案例上調到最佳；
- 若做 expanding-window rolling origin，明確標 `exploratory`，每 fold 均要求 train label 已成熟、validation/test 時間在後、H 期 overlap 已 purge；
- 不發布「已校準機率」、正式 precision 承諾或產品門檻。

### 11.3 Calibration 與最終測試

若輸出只是 ordinal risk score，校準目標是 bucket 的事件率／嚴重度單調性、排序力與穩定性。只有另建「H 內 adverse outcome 機率」時，才做 calibration-in-the-large、calibration slope、reliability diagram、Brier 與 log loss。test 不用於 isotonic／Platt fitting，也不因 test 不漂亮重切年份。

---

## 12. 案例研究與模型校準的分界

| 項目 | 案例研究 | 模型校準／驗證 |
|---|---|---|
| 目的 | 重建因果時間線、找出可反證的風險機制與資料缺口 | 估計規則在完整母體的排序／分類表現與警報成本 |
| 樣本 | 可刻意涵蓋典型、極端、反例與不同下市原因 | 全部合格 landmark；不能只挑成功案例 |
| 特徵 | 可閱讀附註、公告、法規與質化材料 | 必須在所有母體以同一 PIT schema 可重現 |
| 新發現 | 記為 hypothesis／candidate feature | 只能在 train/validation 定義；test frozen |
| 結果 | 故事、事件圖、機制、反事實與證據強弱 | precision、recall、lead time、PR-AUC、穩定性與 CI |
| 人工判斷 | 可深度判讀，但保留 reviewer 與來源 | override 需事前規則、雙人覆核、有效期及 pre/post 結果 |
| 可否宣稱機率 | 不可 | 只有正式機率模型、成熟 labels 與樣本外校準才可 |

**禁止 circularity**：先看五年失敗案例、挑出共同比率，再在同一案例集宣稱該比率具有預測力。案例研究可以生成假說；模型校準必須在未參與假說挑選的 temporal holdout 檢驗。

Matched controls 只用於解釋：以事件前 landmark 的市場、產業 route、規模、上市年齡及必要時估值配對，且 matching variables 也要 PIT。正式 precision/recall 仍以完整 cohort 為準，不能用 1:1 case-control 的人工基準率。

---

## 13. 台灣官方資料 authority

以下以「誰有資格陳述該事實」分工；同一事件應交叉核對，但第三方資料商不取代官方原始來源。

| 資料域 | 第一手 authority／官方入口 | 本研究用途與限制 |
|---|---|---|
| 上市身分 | TWSE `t187ap03_L`：<https://openapi.twse.com.tw/v1/opendata/t187ap03_L> | 當期上市 identity；latest snapshot 不能單獨重建歷史母體。 |
| 上櫃身分 | TPEx `mopsfin_t187ap03_O`：<https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O> | 當期上櫃 identity；需保存歷史快照與掛牌事件。 |
| 終止上市名單 | TWSE 終止上市公司：<https://www.twse.com.tw/zh/listed/suspend-listing.html>；Swagger 列 `company/suspendListingCsvAndHtml` | 確認終止上市日期、名稱、代碼；詳細原因仍讀正式公告、MOPS 重大訊息與適用規則。 |
| 終止上櫃名單／原因 | TPEx 終止上櫃公司：<https://www.tpex.org.tw/zh-tw/mainboard/listed/delisted.html> | 頁面提供代碼、名稱、日期、原因／法條，亦可按官方原因類型查詢；保存原始款次。 |
| 市場正式公告與規則 | TWSE／TPEx 市場公告、法令規章；TPEx 公告查詢入口可由 <https://www.tpex.org.tw/zh-tw/announce/market/announce.html> 進入 | 終止、停止／恢復交易、變更交易、合併／股份轉換及規則版本 authority。URL 若改版應從官網導覽重新發現並記 manifest。 |
| 上市歷史行情 | TWSE 指定公司月行情：<https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260701&stockNo=2330&response=json> | 官方未還原 OHLC／成交；日期與代碼為示例參數，正式擷取逐月 coverage。 |
| 上櫃歷史行情 | TPEx 指定公司月行情：<https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code=6488&date=2026/07/01&response=json> | 同上；交易日缺列與停止交易分開。 |
| 上市除權息 | TWSE OpenAPI `TWT48U_ALL`：<https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL> | 除權息預告／計算基礎；歷史還原需每日快照、正式公告及其他公司行動補足。 |
| 上櫃除權息 | TPEx OpenAPI：<https://www.tpex.org.tw/openapi/v1/tpex_exright_daily>、<https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost> | 除權息計算結果／預告；不可涵蓋所有減資、合併等事件。 |
| 財務報表 | MOPS 指定公司資產負債表 `t164sb03`、損益表 `t164sb04`、現金流量表 `t164sb05`：<https://mopsov.twse.com.tw/mops/web/t164sb03>、<https://mopsov.twse.com.tw/mops/web/t164sb04>、<https://mopsov.twse.com.tw/mops/web/t164sb05> | 原始申報財報；須驗證市場、公司、年季、schema、合併範圍及版本。 |
| 財報公告／更正 | MOPS 財報公告：<https://mopsov.twse.com.tw/mops/web/t163sb01>；更（補）正：<https://mopsov.twse.com.tw/mops/web/t56sb31_q1> | 建立 announced/available/version chain；查詢頁最新內容不自動等於歷史 as-seen。 |
| 重大訊息 | MOPS 歷史重大訊息：<https://mopsov.twse.com.tw/mops/web/t05st01>；上市當日 OpenAPI：<https://openapi.twse.com.tw/v1/opendata/t187ap04_L>；上櫃當日 OpenAPI：<https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O> | 終止、違約、退票、停工、併購、減資、會計師及治理事件；發言時間才是可得基準，事實日不能取代。 |
| 月營收 | 上市：<https://openapi.twse.com.tw/v1/opendata/t187ap05_L>；上櫃：<https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O> | latest full-market snapshot；歷史 PIT 需留存每次版本與更正。 |
| 股利／董事會事件 | TWSE `t187ap45_L`、TPEx `mopsfin_t187ap39_O`（依各自 Swagger）及 MOPS 公司公告 | 核對股利、股本與董事會決議；不能只靠價格跳空反推事件。 |
| 監理處分／法規 | 金融監督管理委員會／證券期貨局官方網站與法規查詢；TWSE／TPEx 業務規則 | 會計、內控、證券法遵與處分類事件；保存發布時間、文號及適用版本。 |
| 法律實體補充 | 經濟部商工登記公示資料、司法院裁判書／公告 | 解散、合併、清算、重整及法人狀態的 supporting authority；不能取代交易所的終止掛牌事實。 |

TWSE Swagger：<https://openapi.twse.com.tw/v1/swagger.json>；TPEx Swagger：<https://www.tpex.org.tw/openapi/swagger.json>。端點、參數與 response scope 以每次擷取時官方規格及 bounded probe 為準，不能只抄第三方套件名稱。

---

## 14. 原始資料、hash、lineage 與研究輸出

### 14.1 每個 raw artifact 的 manifest

```yaml
artifact_id: immutable-id
provider: TWSE | TPEx | MOPS | FSC | MOEA | JUDICIAL
market: listed | otc
endpoint_scope: full_market | selected_company | event_notice
requested_security_code: string_or_null
resolved_reported_name: string_or_null
landing_url: url
data_url: url
http_method: GET | POST
request_parameters: {}
http_status: integer
retrieved_at: timestamp_with_timezone
source_byte_count: integer
source_sha256: lowercase_hex
period_or_event_key: string
response_identity: {}
availability_basis: official_timestamp | conservative_next_asia_taipei_midnight | retrieval_upper_bound
parser_version: string
retention_class: string
```

Hash 對官方原始 response bytes，不對美化 HTML 或解析後 CSV。POST body、實際 data URL、market 參數、content type、byte count 均屬 provenance。原始與更正版都保留，不 overwrite。

### 14.2 必要研究表

- `security_history`：市場、代碼、名稱、board、security type、掛牌／終止有效區間；
- `entity_security_link`：法律實體與證券關係、來源、有效區間、是否唯一；
- `delisting_events`：所有時間欄、官方原因、研究分類、review；
- `corporate_action_ledger`：逐事件現金／股數／對價與 adjustment lineage；
- `daily_wealth_and_drawdown`：raw close、factor、cash flow、wealth、peak、DD；
- `fact_versions`：財報／營收／公告版本鏈；
- `landmark_features`：只含當時可得 facts、coverage 與模型版本；
- `outcome_labels`：label version、horizon、event/censor time、原因；
- `coverage_manifest`：每個預期鍵的 available/gap/error/not_applicable；
- `casebook`：事前快照、事件時間線、支持與反證證據；
- `evaluation_report`：fold、門檻、precision/recall/lead time/CI 及切片。

### 14.3 可重現與 QA gate

1. 單一市場身分與完整歷史母體通過；
2. 終止掛牌全集與交易所名單逐筆 reconcile；
3. 每一交易日價格 coverage 及停止交易狀態可解釋；
4. 公司行動逐筆對帳；抽樣證明純除權不產生假回撤；
5. 財報版本與 available_at 可重建；
6. 每一 feature 可回到 source hash 與座標；
7. label 計算在固定 Decimal／公式版本重跑一致；
8. 時間 fold、purge、embargo 與 right-censoring 通過；
9. test 在方法 frozen 前不可查看；
10. 任一必要 gate 失敗則輸出 machine-readable unavailable，不發布看似完整結果。

---

## 15. 建議的研究執行順序

1. 固定 `market`、`study_cutoff`、普通股範圍、board strata、結果窗與 H；
2. 由歷史掛牌／終止事件建立 survivorship-free 母體；
3. 取得終止掛牌全集，保存官方原因原文與法條並雙人分類；
4. 取得官方日行情及公司行動，建立 adjustment ledger 與 wealth index；
5. 產生 DD50 episodes、終止事件及 censoring 狀態；
6. 依事件前固定截點擷取 as-of 財報、月營收、重大訊息與版本；
7. 建立警訊 feature family、lineage matrix、適用產業與缺值規則；
8. 先完成案例研究，所有新發現只進 hypothesis register；
9. 若有足夠 W0 前 PIT archive，再於 train/validation 固定模型；近五年窗作 out-of-time test；
10. 發布完整母體的 coverage、false positive/negative 案例、precision/recall/lead time 與限制。

---

## 16. 事前登錄仍需治理者確認的參數

- 五年窗的精確時分秒與資料延遲 cutoff；
- 是否納入創新板、KY／第一上市及其分層方式；
- 12 個月正式 headline horizon 已確認；仍須固定 24／36 個月 sensitivity label 的獨立版本名稱與禁止混入 headline calibration 的機械 gate；
- drawdown 同高點採最後達峰日的政策；
- carry-in peak 是否只作敏感度；
- 權利價值、換股終端值、未回收下市的 valuation policy；
- landmark 頻率、alert sustained 規則、最低資料 coverage；
- adverse delisting 邊界類別的 adjudication 規則；
- first-release 產業 route；
- 調查預算／漏失成本對應的 operating threshold；
- 至少多少獨立事件與多少年份才允許正式校準。

在上述項目及歷史 PIT coverage 未鎖定前，本文件支持**研究與資料稽核**，不支持對外宣稱一個已校準的失敗機率或產品警報準確率。

---

## 17. 與專案其他研究文件的關係

- `taiwan-company-data-authority.md`：官方資料 authority、PIT、版本、source hash、lineage 與 gap 契約；本文件完全繼承。
- `company-quality-scoring-primary-sources.md`：F-score、M-score、Z-score、ROIC／FCF 的模型適用邊界與防重複計分。
- `upside-downside-rating-methods.md`：downside ordinal outcome、已確認 12 個月 headline horizon、24／36 個月 sensitivity 隔離、模型治理與 temporal validation。
- `company-quality-decision-map.md`：目前產品治理決策；若其 horizon、downside composite 或市場範圍改變，本研究 label/version 必須明示升版，不得靜默回寫歷史。
