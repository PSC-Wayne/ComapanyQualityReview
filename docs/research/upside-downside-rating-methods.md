# 公司估值與營運風險的雙軸序位評等研究

> 目標：把「上漲潛力」呈現為 1–5 星、把「下跌風險」呈現為 1–5 個哭臉；兩者都是 **ordinal buckets（有序類別）**，不是報酬率或事件機率。本文提出可稽核的設計候選與驗證方法，但**不替產品決定最終門檻、權重或圖示文字**。
>
> 研究日期：2026-07-23。用途為研究框架，不構成投資建議。

## 一、核心結論

1. **一定要拆成兩個軸。** 上漲潛力回答「目前價格相對多種合理估值證據有多便宜／昂貴」；下跌風險回答「基本面、資產負債表、事件與模型不確定性把價值往下打的嚴重度有多高」。高上漲與高風險可以同時成立。
2. **單一目標價不能假裝成機率。** 一個數字沒有說明結果分布、尾部、情境覆蓋、估計誤差或基準率。Damodaran 明確指出：只有情境完整且可合理賦予機率時，才能計算跨情境期望值；情境不完整時不能算期望值。[S5]
3. **先保留估值證據，再壓縮成序位。** 保存 DCF、reverse DCF、相對估值、SOTP、情境與敏感度的原始輸出；最後一層才映射為星／哭臉。圖示是資料壓縮，不是模型本身。
4. **門檻應由治理程序與樣本外結果決定。** 可先比較固定區間、同群分位數、單調分數卡、混合式等候選，再依覆蓋率、單調性、穩定度與實際用途選擇；本文刻意以參數符號表示門檻。
5. **校準必須符合輸出型態。** 對 ordinal rating 檢驗排序力、各 bucket 實現結果的單調性、轉移與穩定性；只有另建「明示機率模型」時，才檢驗機率校準。美國聯準會 SR 11-7 也區分預測值的準確度與風險排序模型的 discriminatory power，並要求概念健全性、持續監控／benchmarking、outcomes analysis／back-testing。[S10]

---

## 二、語意契約：星與哭臉「是什麼、不是什麼」

### 2.1 建議對外定義

- **上漲潛力（★1–★5）**：在固定估值基準日與投資期間下，綜合多種可重現估值證據後，該公司相對目前價格的「有利程度」之序位。
- **下跌風險（☹1–☹5）**：在同一基準日與期間下，綜合基本面脆弱性、資產負債表承受力、離散事件、估值敏感度、資料／模型不確定性後，「永久性損失或重大負面重估脆弱度」之序位。
- ★5 不表示「有 80% 或 100% 機率上漲」；☹5 不表示「有 80% 或 100% 機率暴跌」。除非另外發布已校準的機率模型，否則不得把類別轉譯成機率。
- 評等必須附：**as-of date、價格、幣別、期間、適用產業模型、資料完整度、最近更新日、主要驅動因子、模型不一致／低信心旗標**。

### 2.2 為何不能由單一目標價直接產生五星

若只使用 `（目標價－現價）／現價`：

- DCF 的終值、折現率、再投資與成長假設可能高度敏感；
- 目標價沒有顯示多個模型是否一致；
- 同一數字可能來自完全不同的風險與情境寬度；
- 最樂觀、最可能、最悲觀三個情境若未涵蓋全部結果且沒有可辯護機率，不能稱為機率分布或期望值；[S5]
- 對年輕公司，生存失敗可能是獨立於持續經營 DCF 的離散結果；以折現率「包掉所有風險」會失真。[S6]

因此，目標價最多是**一筆估值觀測**，不能單獨構成「成功機率」。

---

## 三、估值方法庫

下表要求每種方法留下原始結果與假設，不先強迫合併成一個價格。Damodaran 把主要方法分為 DCF、相對估值與或有請求權估值；IFRS 13 與 IVS 則提供市場／收益等估值方法與可觀察輸入的權威框架。[S1][S8][S9]

| 方法 | 如何進入評等 | 主要來源 | 核心假設 | 限制 | 特別適用產業／情境 |
|---|---|---|---|---|---|
| **DCF（FCFF／FCFE／DDM）** | 保存 base／downside／upside 的企業價值、股權價值與 implied return；記錄終值占比及 WACC／g／margin／ROIC 敏感度 | Damodaran 的 DCF 架構與適用限制；IFRS 13 收益法觀念 [S1][S2][S8] | 現金流、折現率、成長、再投資與穩態條件彼此一致；期間與幣別一致 | 終值主導；負現金流、重整、週期高低點、未使用資產、專利／選擇權與私人公司折現率難估 [S1] | 成熟非金融企業、可預測訂閱／公用事業；銀行宜改 FCFE／DDM，不宜機械套 FCFF |
| **Reverse DCF／implied expectations** | 固定現價，反解市場隱含的營收成長、營益率、ROIC／再投資或穩態假設；與歷史、同業及產業基準率比較，而非宣稱現價錯誤 | DCF 代數框架 [S1][S2]；Damodaran 的 implied ROC/ROE 工具 [S3] | 選定其餘參數後，某一或少數參數可被反解且經濟上可解讀 | 不是獨立估值；解依賴被固定的 WACC、終值與其他參數；多組假設可產生同一價格 | 高成長／敘事股、無盈餘公司、對「市場已反映什麼」比點估值更重要者 |
| **相對估值** | 使用一致定義的 multiples，保留同群中位數／分布與公司調整值；以多指標與基本面控制交叉驗證 | Damodaran 2025 相對估值講義 [S4] | 可找到經濟上可比公司；分子分母屬同一 claimholder；會計定義一致；控制成長、風險、獲利差異 | 同業整體可能高估／低估；可比公司選擇偏誤；會計、週期、地區差異；市場情緒會被帶入 [S4] | 大量同質同業：銀行 P/B–ROE、REIT P/NAV 或 P/FFO、SaaS EV/Sales 配成長／利潤、成熟製造 EV/EBITDA |
| **SOTP（sum of the parts）** | 各事業採最適方法，逐項列 gross value、公司費用、淨債務、少數股權、稅漏損與可實現折價；禁止只報加總數 | Damodaran 資產基礎／SOTP 講義 [S7] | 分部可分離；可取得 stand-alone 現金流或可靠交易／同業資料；不重複計價共享資產與協同 | 分部揭露不足、共用品牌／平台／總部成本難分；拆分稅負、執行成本與 conglomerate discount 未必可實現 [S7] | 控股公司、綜合企業、銀行／保險多子公司、資源與地產資產組合 |
| **情境分析** | 對少數一致的因果情境重算所有財務與估值；若未有完整且可辯護的機率，只呈現情境值／排序，不算期望值 | Damodaran 機率式估值章 [S5] | 情境內部一致；關鍵變數共同移動；若賦予機率，情境需覆蓋完整可能結果且機率總和為 1 | 情境選擇與機率主觀；三情境不等於分布；容易同時改太多不相容參數 | 週期、商品、匯率／利率敏感、監管、轉型、景氣衰退壓力測試 |
| **敏感度分析** | 報告一維／二維矩陣、break-even、tornado chart；抽取「估值對關鍵變數斜率」與「跨合理範圍寬度」作模型不確定性證據 | DCF 框架及 Damodaran 情境／模擬章 [S2][S5] | 一次改動的參數範圍合理；多參數表須維持經濟一致性 | 單變數敏感度忽略相關性與非線性；寬度不是機率；任意範圍會操弄結果 | 所有產業；終值高、槓桿高、毛利／價格敏感公司尤其必要 |
| **決策樹／rNPV** | 把研發、許可、訴訟等離散關卡拆為 event nodes；僅在有外部基準率或經驗資料時賦予機率 | Damodaran 決策樹章 [S5] | 關卡、條件機率、現金流與決策節點可界定；避免把可決策節點當隨機事件 | 稀疏資料、條件相依與管理選擇難估；錯誤精確機率會污染結果 | 生技臨床、礦權、訴訟、單一大案、許可／標案型企業 |
| **Monte Carlo／估值分布** | 對少數關鍵驅動因子指定分布與相關性，輸出估值分布、分位數與尾部；星／哭臉只讀取預先指定統計量 | Damodaran 模擬章 [S5] | 輸入分布、相關結構與動態合理；抽樣數足夠 | 精美分布不會修正錯模型；歷史分布未必前瞻；相關性在壓力期改變；不可把主觀輸入包裝成客觀機率 | 資料充足且多連續風險：商品、金融、運輸、匯率／利率曝險 |

### 3.1 模型三角檢驗，而非「平均三個目標價」

建議保存一個 evidence matrix：

- `V_DCF`：內含假設的一致現金流價值；
- `E_reverse`：市場價格要求的隱含營運表現是否落在歷史／同業可行範圍；
- `V_relative`：同群定價；
- `V_SOTP`：適用時的分部價值；
- `V_scenario[k]`／`V_quantile[q]`：情境或模擬結果；
- `uncertainty`：輸入品質、敏感度、模型分歧、覆蓋缺口。

合併規則可選 weighted median、trimmed mean、保守交集或模型投票；**權重須事前按產業／公司型態版本化**，不能因結果不喜歡而臨時改。模型差距本身是資訊：差距過大應提高「低信心／模型風險」旗標，而不是被平均掉。

---

## 四、基準率（outside view）

Reference class forecasting 的核心是先看可比群實際結果分布，以 outside view 對抗只看公司故事的 optimism bias。[S12] 在公司評等中可採：

1. **定義 reference class**：產業 × 商業模式 × 生命週期 × 地區／監管 × 規模 × 槓桿 × 起始估值狀態；定義必須在看結果前固定。
2. **選擇結果變數與期間**：例如三年營收 CAGR、達成目標毛利的時間、FCF 轉正、再融資／違約、永久性資本損失、相對最大回撤；不可混用不同期間。
3. **取得 point-in-time 分布**：含失敗、下市、併購與改名公司，避免 survivorship bias。
4. **inside／outside view 對照**：把管理層／分析師假設與同群分布並列；若採 shrinkage，保存原值、基準率、收縮係數與理由。
5. **稀疏樣本分層回退**：公司細分類不足時，依事前規則回退至較廣產業／生命週期；顯示樣本數與年度範圍。

可用的一手資料例：美國 BLS Business Employment Dynamics 公布 establishment age and survival tables；Damodaran 的年輕公司研究示範把分產業存活率帶入估值，並提醒年輕公司歷史短、相對估值可比性弱。[S6][S13] 但「美國新設事業存活率」不能直接當某上市公司的倒閉率；它只是一個需要再條件化的基準率。

---

## 五、下跌風險分解

### 5.1 不以一個 beta 或折現率包掉所有風險

建議風險記錄至少拆成：

1. **營運／需求**：量、價、流失、集中度、訂單品質、週期；
2. **單位經濟／利潤**：毛利、營業槓桿、成本轉嫁、固定成本；
3. **資本密集與執行**：capex、產能爬坡、營運資金、專案延遲；
4. **財務韌性**：淨槓桿、利息保障、到期牆、浮息、契約、流動性、稀釋；
5. **資產／會計品質**：應收／存貨、商譽、資本化、準備、表外義務；
6. **治理／資本配置**：關係人、控制權、併購、回購／增資、管理層可信度；
7. **法規／訴訟／地緣／ESG 事件**；
8. **估值與市場結構**：起始 multiple、擁擠、流動性；
9. **模型／資料風險**：敏感度、資料陳舊、分部缺失、模型分歧與適用範圍外使用。

SEC Regulation S-K Item 105 要求揭露 material risk factors、解釋風險如何影響該公司／證券、按相關標題組織，並抑制可套用到任何公司的 generic boilerplate；這可作公司風險拆解的最低「公司特定性」原則。[S14] SR 11-7 則要求識別模型風險來源與大小，並指出複雜度、輸入／假設不確定性、使用廣度及影響都會增加模型風險。[S10]

### 5.2 每個風險節點的可稽核欄位

- `risk_id`、定義、來源與 as-of date；
- **exposure**（暴露）、**transmission**（如何進入營收／成本／資產負債表／multiple）、**buffer**（現金、保險、契約、定價權）、**severity**（若發生的價值衝擊）、**persistence／reversibility**；
- leading indicator、trigger、管理措施、殘餘風險；
- 是否已進入 base DCF／downside scenario／折現率，避免 double count；
- 資料品質與分析者信心。

若沒有可靠機率，應標為 exposure／severity ordinal 或壓力情境，不得硬填 `30%`。只有有外部事件統計、完整事件樹或經校準模型時，才另存 probability 欄位。

---

## 六、ordinal bucket 設計候選（不鎖定最終門檻）

以下 `T1<T2<T3<T4`、`Q1…Q4`、權重與 veto 條件均為**待治理與回測選定的參數**，不是本文建議的最終數字。

### 候選 A：絕對經濟區間（透明、跨期較易解讀）

**上漲星等輸入**可用 `U = robust_central_value / current_price - 1`，其中 central value 是預先指定的 weighted median／trimmed aggregate，而不是單一目標價。

- ★1：`U < T1`
- ★2：`T1 ≤ U < T2`
- …
- ★5：`U ≥ T4`

**哭臉輸入**可用 downside severity 統計量，例如 `D = (current_price - conservative_value) / current_price`、壓力情境永久損失、或歷史模型學得的 downside composite，再以 `R1…R4` 映射。

- 優點：容易說明；同一公司跨期變化可比較。
- 缺點：不同利率、波動與產業下相同百分比未必等義；若 central／conservative value 的產生不嚴謹，仍是假精確。
- 治理待決：期間、價值統計量、通膨／市場風險溢酬 regime、產業是否共用門檻。

### 候選 B：reference-class 分位序位（天然 ordinal）

將 `U` 與 `D` 分別放入同日期、同產業／生命週期 reference class 的經驗分布；以待選 `Q1…Q4` 切成五級。可比較等頻分箱、非等頻尾部加密、或按經濟損失最佳化的分箱。

- 優點：不要求把估值差轉成機率；適應市場 regime；可直接檢查 bucket 單調性。
- 缺點：永遠會有「相對高星」公司，即使整個市場都貴；小同群不穩；公司跨群可能跳級。
- 必備控制：同時顯示絕對 `U／D`、同群定義、樣本數、分位邊界與版本。

### 候選 C：單調 evidence scorecard（可解釋、容許缺值）

上漲潛力分數由可審核的 ordinal features 組成，例如：

- DCF 價值差 band；
- reverse DCF 隱含成長／margin 相對基準率的可達性；
- relative valuation 經基本面調整後位置；
- SOTP 折價（若適用）；
- 方法一致度與敏感度懲罰。

下跌風險分數可由：

- 營運脆弱、財務韌性、治理／事件、會計品質、估值敏感度、模型／資料風險；
- 事前定義的 **gate／veto**（如 imminent liquidity breach、going-concern、重大查核範圍限制）限制最低哭臉級數；
- 風險共因子與 double count 檢查。

總分再以 `S1…S4` 映射五級。

- 優點：理由碼清楚；能處理沒有完整估值分布的公司。
- 缺點：權重與分箱會產生模型風險；加總可能讓重大單點風險被大量小優點抵銷。
- 治理待決：加法、worst-of、幾何平均或 gate 的組合；缺值是中性、懲罰或不評等。

### 候選 D：模型共識 × 不確定性混合式（推薦列入 champion/challenger 比較）

先用估值模型取得 `location`，再用下列證據估 `uncertainty`：模型間離散、敏感度寬度、終值占比、資料品質、reference-class 距離及情境覆蓋。

候選規則：

- 星等主要由 location 決定，但低信心最多升至某一待定級，或顯示 `★4（低信心）` 而不改級；
- 哭臉主要由 downside severity／fragility 決定，uncertainty 可作加級或獨立徽章；
- 不把 uncertainty 同時重罰星與哭臉，除非治理文件明確說明其不同傳導路徑，避免 double count。

- 優點：不會把狹窄且高品質的估值與寬廣猜測視為相同。
- 缺點：兩階段規則較複雜；若 confidence cap 不透明，使用者會誤解。

### 候選 E：雙指標矩陣，不合成總推薦

最終只發布 `(★, ☹)`，例如「★★★★／☹☹☹☹」，另附信心；不產生「買／賣」或單一總分。

- 優點：保留凸性與風險的不同概念；高風險高潛力不會被平均成「中性」。
- 限制：需要 UI 教育；排序清單若要求一維排序，必須另定用途特定的決策規則，且不得回寫為評等本身。

### 6.1 候選比較實驗，而非拍板門檻

對 A–D 做同一份 point-in-time 樣本外資料比較：

- bucket 間實現結果是否單調；
- ★5–★1 的 forward total return／相對報酬 spread；
- 各 ☹ bucket 的重大永久損失率、最大回撤、再融資／稀釋等是否單調；
- 覆蓋率、換手率、跨期轉移、產業集中、缺值率；
- 壓力期與常態期是否穩定；
- 跨產業公平性及小樣本可信區間；
- 簡單基準（單一 multiple、等權模型、僅槓桿）是否已同樣有效。

最後由治理委員會依產品用途選門檻；保存所有候選結果，避免只報告「贏家」。

---

## 七、產業適配：同一語意，不同 feature／估值路由

| 產業／型態 | 上漲潛力主要證據 | 下跌風險特有項目 | 不宜機械使用 |
|---|---|---|---|
| 銀行 | FCFE／DDM、P/B 對可持續 ROE、分部 SOTP | CET1、資產品質、存款／融資、利率與信用壓力、監管 | EV/EBITDA；把存款全視為一般企業債務 |
| 保險 | DDM、P/B、embedded value／分部 | 準備金尾部、資產負債久期、再保、清償能力 | 僅看當期 EPS multiple |
| REIT／地產 | NAV、cap rate 情境、P/FFO、資產 SOTP | LTV、債務到期、出租率、租戶集中、開發承諾 | 一般製造業 FCF 模型而忽略資產重估與配息規則 |
| 商品／週期 | mid-cycle DCF、成本曲線、normalized multiple | 商品價格、營運槓桿、capex、資源壽命、國家風險 | 用景氣高峰 EPS 配低 P/E 判便宜 |
| SaaS／平台 | reverse DCF、EV/Sales 經成長／FCF 調整、長期 unit economics | 留存、CAC、雲成本、股權稀釋、平台依賴 | 未控制成長／毛利的裸 EV/Sales |
| 生技／研發 | rNPV／決策樹、授權可比、資產 SOTP | 臨床／監管關卡、現金 runway、融資稀釋、專利 | 把完整管線塞入單一 WACC DCF；無基準率卻填精確成功率 |
| 控股／綜合企業 | SOTP（各分部各自路由） | 雙重槓桿、稅漏損、少數股權、資本配置、折價可實現性 | 只對合併 EBITDA 套單一 multiple |
| 公用／受監管 | DDM／DCF、rate base／allowed ROE | 法規重設、燃料回收、建設超支、利率與融資 | 忽略監管資產負債與核准機制 |
| 年輕／未獲利 | reverse DCF、營收／unit economics 情境、存活調整 | runway、後續融資、產品市場契合、失敗基準率 | 只靠終值或未條件化的新創平均存活率 [S6] |

---

## 八、模型校準、驗證與回測

### 8.1 驗證層次

依 SR 11-7，可把治理分成三層：[S10]

1. **概念健全性**：方法為何適用；資料、變數、轉換、權重、單調約束、假設、限制及用途文件化；由獨立於開發者的人做 effective challenge。
2. **持續監控**：資料輸入、計算與輸出是否照設計；與替代模型／外部基準 benchmarking；監控 overrides、漂移、缺值、產業組成及 rating migration。
3. **結果分析**：以未用於開發且頻率／期間匹配的樣本，將輸出與實際結果比較。SR 11-7 特別說明 back-testing 是在未用於模型開發的期間比較實際與預測，holdout 測試不能取代持續 back-test。[S10]

Basel 的 VaR backtesting 三色區不是本評等的可直接移植門檻，但提供重要治理先例：以例外數形成 green／yellow／red 的**分級監管反應**，並明示統計誤差與模型可能正確卻被拒絕、模型錯誤卻未被拒絕的取捨。[S11] 因此五星／五哭臉的界線也應附樣本不確定性，而非宣稱自然真理。

### 8.2 上漲星等的 outcome tests

正式 headline outcome test 固定 `H=12 個月`，使用含股利、分拆、下市回收值的 total return。24／36 個月只能以獨立 sensitivity label/version 執行，且禁止參與正式 headline 權重、bucket、模型選擇、label maturity、purge/embargo 或 champion 決策：

- 各星 bucket 的平均、中位、分位報酬與相對產業／市場報酬；
- 星等與 forward return 的 Spearman／Kendall 排序；
- bucket 單調性、top-minus-bottom spread、bootstrap 信賴區間；
- 「估值帶是否涵蓋後續可觀測結果」僅在輸出確為有定義的預測區間時測 coverage；一般 bull/base/bear 不可冒充 prediction interval；
- 模型一致度／低信心標記是否真的對應較大誤差。

### 8.3 下跌哭臉的 outcome tests

先定義不可事後改的 adverse outcomes：

- 固定期間最大回撤與相對回撤；
- 盈餘／FCF 永久下修、資產減損、稀釋、契約違反、再融資壓力、違約／破產／下市；
- 一段恢復期後仍未回復的 permanent capital loss proxy。

檢查各哭臉 bucket 的事件率、loss severity、expected shortfall proxy 與轉移矩陣是否單調。報告事件數與信賴區間；稀有事件不可只報百分比。

### 8.4 ordinal 與 probability 的校準不可混淆

- **Ordinal 主模型**：目標是正確排序與分段；檢驗單調性、discrimination、穩定度、轉移及實現結果分布。
- **若另有明示機率子模型**（例如兩年內再融資失敗）：才做 reliability diagram、calibration-in-the-large、calibration slope、Brier／log loss，並按產業、規模、時期切片。
- 不得把「某 bucket 歷史上 18% 發生事件」直接宣告為下一家公司 18% 機率；若要這樣做，需建正式條件機率模型、時間窗、樣本與再校準程序。

### 8.5 回測資料紀律

- point-in-time 財報與當時可知的 restatement 狀態；使用發布日，不用會計期末日偷看；
- 保留當時成分股、下市、破產、併購、改名及 corporate actions；
- 模型選擇、門檻與產業路由均做版本控制；
- train／validation／test 依時間切分，另做 rolling／expanding window；
- 門檻選定後以 frozen champion 對 challenger 平行跑；
- 對利率、景氣、泡沫／崩盤 regime、產業、國家與公司生命週期分層；
- 完整記錄人工 override 前後結果。若 override 經常改善或損害結果，都應觸發模型檢討；SR 11-7 亦將高頻 override 視為底層模型可能需修訂的訊號。[S10]

---

## 九、最低可稽核資料契約

每次評等產生不可變快照，至少包含：

```yaml
rating_id: unique-id
decision_time: RFC3339-timezone-aware-instant
as_of_date: derived-Asia-Taipei-date
price: {value: ..., currency: ..., source: ..., timestamp: ...}
headline_horizon: 12_months
sensitivity_horizons: [versioned_non_headline_labels]
company: {id: ..., industry_route: ..., lifecycle: ...}
source_manifest:
  - {field: revenue, source_url_or_filing: ..., filing_date: ..., extracted_at: ...}
valuation_models:
  - model: DCF_FCFF
    version: ...
    applicability: ...
    inputs: {...}
    outputs: {base: ..., downside: ..., upside: ..., sensitivities: ...}
  - model: reverse_DCF
    version: ...
    fixed_inputs: {...}
    implied_expectations: {...}
  - model: relative
    peer_set_as_of: [...]
    multiple_definitions: {...}
    outputs: {...}
risk_register:
  - {risk_id: ..., exposure: ..., transmission: ..., buffer: ..., severity: ...,
     scenario_link: ..., source: ..., confidence: ...}
reference_class: {definition: ..., sample_period: ..., n: ..., fallback: ...}
aggregation: {candidate: ..., version: ..., raw_score: ..., thresholds_version: ...}
ratings: {upside_ordinal: 1-5, downside_ordinal: 1-5, confidence: ...}
reason_codes: [...]
overrides: {before: ..., after: ..., owner: ..., rationale: ..., expiry: ...}
limitations: [...]
```

稽核時應可由 source manifest 重算每個 feature、由 version 重建每個 bucket，並知道缺值如何處理。任何門檻／權重變更須有生效日，不回寫歷史；回測可另以新版本重跑，但須標示為 retrospective reconstruction。

---

## 十、產品／治理決策狀態（研究方法不覆寫 owner 決策）

1. **已確認：**星與哭臉 headline 固定 12 個月；24／36 個月只可作獨立 sensitivity label/version，不得進入 headline 權重、bucket 或模型選擇。
2. 上漲潛力用絕對報酬、相對產業報酬，或兩者並列？
3. **已確認：**下跌風險保留 drawdown、永久損失、重大基本面事件三分項與 composite；Critical Event Bomb 額外顯示且不改寫原哭臉。
4. bucket 要追求固定經濟語意、橫截面分布平衡，還是樣本外單調性？
5. 低信心要降級、封頂、另加徽章，或乾脆 no-rating？
6. **已確認：**重大單點風險可採 hard gate／更嚴格 floor／Bomb，不得被普通優點平均抵銷；Bomb 物質性門檻仍須 PIT 校準。
7. 產業專屬模型共享同一門檻，或只共享對外語意？
8. 歷史回測須累積多少事件與多久樣本才允許發布五級？
9. **已確認：**只有 Wayne 可批准、須獨立 Reviewer、最長 90 天；不可任意手改數字，只可加註、阻擋、Bomb 或更嚴格 floor，新資料觸發新 generation 重算重審。
10. 是否允許另外發布「已校準機率」；若允許，須與 ordinal 圖示在視覺與文字上明確分離。

---

## 十一、建議的研究／落地順序

1. 先定 outcome 與期間，不先定星級門檻。
2. 建 point-in-time source manifest、產業路由與風險 taxonomy。
3. 同時實作 A–D 候選規則於研究資料（非產品碼），保存連續原始分數。
4. 用 frozen temporal test 比較簡單 benchmark、候選模型與人工判斷。
5. 檢查單調性、穩定性、尾部事件與產業公平性；公開失敗案例。
6. 由治理程序選門檻、版本、生效日與 review cadence；保留 challenger。
7. 對外只說 ordinal 語意；若未另經機率校準，禁止任何「五星＝X%」文案。

---

## 來源（以第一手／權威原典為主）

- **[S1] Aswath Damodaran, NYU Stern, “Approaches to Valuation.”** DCF、相對估值、或有請求權估值的定義及 DCF 適用限制。  
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/approach.html
- **[S2] Aswath Damodaran, NYU Stern, “Discounted Cash Flow Valuation” lecture notes.** DCF 的現金流、折現率與終值架構。  
  https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/dcfcf.pdf
- **[S3] Aswath Damodaran, NYU Stern, Spreadsheet Programs.** 包含 implied ROC／ROE、估值與敏感度等作者工具及用途說明。  
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/spreadsh.htm
- **[S4] Aswath Damodaran, NYU Stern, “Relative Valuation” lecture packet, updated Jan. 2025.** multiples 定義一致性、分布、基本面驅動與可比公司控制。  
  https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/valpacket2spr25.pdf
- **[S5] Aswath Damodaran, “Probabilistic Approaches in Valuation: Scenario Analysis, Decision Trees, and Simulations,” Chapter 33.** 情境完整性、賦予機率的條件、決策樹、分布與相關性限制。  
  https://pages.stern.nyu.edu/~adamodar/pdfiles/val3ed/c33.pdf
- **[S6] Aswath Damodaran, “Valuing Young, Start-up and Growth Companies: Estimation Issues and Valuation Challenges.”** 年輕公司存活／失敗、DCF 與相對估值困難。  
  https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/younggrowth.pdf
- **[S7] Aswath Damodaran, NYU Stern, “Asset Based Valuation / Sum of the Parts.”** 分部可分離性、stand-alone cash flow、內在／相對 SOTP 與限制。  
  https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/assetvaluation.pdf
- **[S8] IFRS Foundation, IFRS 13 Fair Value Measurement.** 公允價值、估值技術及輸入層級的權威準則入口。  
  https://www.ifrs.org/issued-standards/list-of-standards/ifrs-13-fair-value-measurement/
- **[S9] International Valuation Standards Council, International Valuation Standards.** 國際估值準則與 IVS 200 Businesses and Business Interests 的官方入口。  
  https://ivsc.org/standards/
- **[S10] Board of Governors of the Federal Reserve System & OCC, SR 11-7, “Supervisory Guidance on Model Risk Management,” 2011.** 模型風險、effective challenge、概念健全性、持續監控、benchmarking、outcomes analysis 與 back-testing。  
  https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107a1.pdf
- **[S11] Basel Committee on Banking Supervision, “Supervisory Framework for the Use of Backtesting…,” 1996.** exceptions、統計錯誤及 green/yellow/red 分級反應。此處僅借鏡驗證治理，不移植其 VaR 門檻。  
  https://www.bis.org/publ/bcbs22.pdf
- **[S12] Bent Flyvbjerg, “From Nobel Prize to Project Management: Getting Risks Right,” Project Management Journal 37(3), 2006；作者版。** outside view 與 reference class forecasting。  
  https://arxiv.org/pdf/1302.3642
- **[S13] U.S. Bureau of Labor Statistics, Business Employment Dynamics, “Establishment Age and Survival Data.”** 新設事業存活基準率的一手資料入口。  
  https://www.bls.gov/bdm/bdmage.htm
- **[S14] U.S. Securities and Exchange Commission, Release No. 33-10825, “Modernization of Regulation S-K Items 101, 103, and 105,” 2020.** material、公司特定、按標題組織的 risk-factor 規範。  
  https://www.sec.gov/files/rules/final/2020/33-10825.pdf
- **[S15] Moody’s Investors Service, “Rating Symbols and Definitions.”** 信用評等作為 ordinal symbols、修飾符與定義治理的業界原典；可借鏡類別定義，但不能把信用評等門檻直接移植到股票上漲／下跌評等。  
  https://www.moodys.com/sites/products/ProductAttachments/AP075378_1_1408_KI.pdf

### 來源適用提醒

- Damodaran、Flyvbjerg 是原作者／作者機構版本，適合作方法原典；IFRS、IVSC、Fed/OCC、Basel、SEC、BLS 是準則或監理／政府原始來源。
- Basel 三色區與 Moody’s 信用符號只提供「有序類別、定義、驗證與治理」的設計先例，**不是**股票評等的現成門檻。
- 所有來源都不能替代在目標市場、產業、資料頻率與投資期間上的 point-in-time 樣本外驗證。
