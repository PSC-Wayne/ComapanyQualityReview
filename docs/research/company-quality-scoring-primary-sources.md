# 公司品質綜合分數：可稽核量化架構、模型邊界與防重複計分原則

> **用途**：研究與方法設計底稿；不是投資建議，也**不替 Wayne 決定最終權重**。  
> **版本日期**：2026-07-23  
> **核心原則**：先定義欲衡量的潛在構念，再建立「原始資料 → 標準化指標 → 證據家族 → 綜合結果」的可追溯鏈；同一經濟事實不得因換算成多個比率而獲得多次權重。

---

## 1. 先界定「品質」而不是先挑公式

「公司品質」不是會計準則定義的單一量。可稽核架構應把它拆成互相可辨識的構面：

1. **經濟報酬與資本配置結果**：如調整後 ROIC、增量 ROIC。
2. **現金轉換與再投資負擔**：如營業現金流、維持性資本支出後現金、營運資金吸收。
3. **財務韌性**：償債能力、流動性、融資依賴。
4. **報導可靠性／異常風險**：應計品質、Beneish 型警示、重編與監管事件。
5. **競爭優勢的可觀察證據**：定價、留存、單位經濟、進入障礙等；「護城河」本身不是 IFRS/GAAP 科目。
6. **改善／惡化方向**：Piotroski F-score 類的離散訊號。

這些構面可能形成因果鏈：

```text
競爭優勢／進入障礙（驅動因）
        ↓
定價權、留存、單位經濟（中介結果）
        ↓
毛利、資產週轉、ROIC（財務結果）
        ↓
營業現金流與 FCF（現金結果）
```

若把鏈上每一節都當成獨立「正面品質」加分，會把同一成功故事重複計分。反之，Beneish、Altman 主要是**風險篩檢器**，不是品質報酬因子的另一種名稱。

---

## 2. 建議的可稽核資料模型

### 2.1 每一筆指標至少保存的欄位

| 欄位 | 稽核要求 |
|---|---|
| `entity_id`, `period_end` | 公司、合併範圍、財報期間明確；避免把母公司與合併數混用。 |
| `filing_date`, `available_at` | 只使用當時已公開資料，防止前視偏誤。 |
| `source_document`, `source_url` | 原始申報書／財報 URL、版本與頁碼或 XBRL concept。 |
| `raw_fact_id` | 每個原始數字的唯一識別；同一 fact 被多少指標引用可追蹤。 |
| `accounting_standard`, `currency`, `scale` | IFRS／US GAAP、幣別、千／百萬單位。 |
| `formula_version` | 分子、分母、平均或期末值、符號與缺值處理均版本化。 |
| `adjustment_ledger` | 租賃、商譽、研發資本化、一次性項目、併購等調整逐筆列示，保留未調整值。 |
| `evidence_family` | profitability、cash-conversion、solvency、reporting-risk、moat-driver 等。 |
| `lineage_group_id` | 對共同分子／分母或同一因果鏈的指標標示同一群組。 |
| `status` | observed／derived／estimated／not-applicable／missing；不得把缺值當 0 分。 |

### 2.2 三層式輸出

1. **原始層**：逐一保存報表數字、來源與重編版本。
2. **診斷層**：完整展示 F-score、M-score、Z-score、ROIC、FCF 等，但不代表全部都進入加權。
3. **綜合層**：每個潛在構面只輸入一個主要證據；其餘指標改作驗證、信心標籤、上限／否決條件，或敏感度分析。

這個分層允許使用者看見所有模型，又不必把所有模型機械相加。

---

## 3. Piotroski F-score

### 3.1 原始設計與可重現定義

Piotroski（2000）針對**高帳面市值比（high book-to-market）公司**，以九個二元訊號將公司區分為財務狀況較強與較弱者。原始論文為 *Journal of Accounting Research*, 38（Supplement）, pp. 1–41，DOI：[10.2307/2672906](https://doi.org/10.2307/2672906)；另可由 UCLA Anderson 官方網域取得[作者論文版本 PDF](https://www.anderson.ucla.edu/documents/areas/prg/asam/2019/F-Score.pdf)。該版本載明實證涵蓋 1976–1996，最終為 21 年共 14,043 個 high-BM 公司年度觀察值；因此這些結果不可未經重驗證直接外推到今日全市場。

常見的九項重現如下；實作時仍須在公式字典中固定 Compustat／報表欄位與分母：

- **獲利能力**：ROA > 0、CFO > 0、ΔROA > 0、CFO > 淨利（或以總資產尺度化後比較；低應計）。
- **資本結構／流動性／資金來源**：長期槓桿下降、流動比率上升、當期未發行普通股。
- **營運效率**：毛利率上升、資產週轉率上升。

每項符合記 1，合計 0–9。這是**離散訊號總和**，不保留改善幅度；一家公司略高於零與大幅高於零會拿到相同單項分數。

### 3.2 適用邊界

- **原始研究問題不是全市場「絕對品質排名」**，而是在高 book-to-market、常伴隨財務壓力或市場悲觀的樣本中，用歷史財報資訊區分贏家與輸家。
- 它主要衡量**近期財務狀態與方向**，不是永久競爭優勢，也不是盈餘操縱或破產的直接機率。
- 金融業的流動性、槓桿、營運資金與收入模式不同；對銀行、保險等受監管金融機構，九項機械套用的經濟含義可能失真，應標記不適用或另建產業模型。
- 新創、研發密集、重大併購、資產出售或會計政策變更公司，Δ毛利率、Δ週轉與發股訊號可能反映生命週期／交易，而非品質惡化。
- 跨國或跨準則比較時，分類差異會改變 CFO、流動資產／負債、研發與租賃數字。

### 3.3 在綜合分數中的防重複處理

F-score 內已含 ROA、CFO、應計、槓桿、流動性、毛利與週轉。若綜合分數又逐項加入 ROIC、CFO/NI、毛利率趨勢、資產週轉、淨負債等，便會重複計分。

可稽核但**不預設權重**的三種替代方案：

- **方案 A：只作診斷／確認**：ROIC 或現金轉換是主指標；F-score 只決定「改善是否廣泛」，不另加點。
- **方案 B：只取非重疊項**：若主構面已有獲利、現金、槓桿，F-score 僅保留發股或未被涵蓋的方向訊號。
- **方案 C：家族內擇一**：把九項連同其他近似指標放入 evidence family，家族先合成一個輸出，再進入上層綜合。

---

## 4. Beneish M-score

### 4.1 原始設計與公式

Beneish（1999）提出以財報失真結果及操縱誘因的變數，篩檢盈餘操縱風險。原始論文為 *Financial Analysts Journal*, 55(5), 24–36，DOI：[10.2469/faj.v55.n5.2296](https://doi.org/10.2469/faj.v55.n5.2296)。八變數版本通常寫為：

```text
M = -4.84
    + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI
    + 0.115 DEPI - 0.172 SGAI + 4.679 TATA - 0.327 LVGI
```

- DSRI：應收帳款天數指數
- GMI：毛利率惡化指數
- AQI：資產品質指數
- SGI：營收成長指數
- DEPI：折舊率指數
- SGAI：銷管費率指數
- LVGI：槓桿指數
- TATA：總應計／總資產

常見原始分類截點為 **−1.78**；較高（較不負）代表較值得調查，不等於已證實舞弊。實作必須把「八變數版本、係數、截點」綁在同一版本，不能把不同文獻的五變數模型或重估截點混入。

原始文章摘要明確說明：模型約在公開發現前辨識出一半操縱公司，但篩檢結果仍需判斷數字失真究竟來自操縱，還是其他結構性原因。因此 M-score 是**警報器**，不是定罪器。

### 4.2 適用邊界

- 原模型由特定歷史時期、已被辨識的操縱公司與對照樣本估計；基準率、執法環境、會計準則及產業結構改變時，機率校準不會自動保持有效。
- 指數通常需要連續兩年且分母非零；新上市、重整、重大併購、業務模式轉型與高成長公司容易產生結構性異常。
- 銀行、保險、REIT 或其他資產負債表結構特殊產業，不宜未驗證即套用工業／一般企業比率。
- M-score 不是一般「盈餘品質」全貌：它無法取代附註、查核意見、重編、關係人交易與監管事件檢查。

### 4.3 與其他品質指標的重疊

- TATA 與 F-score 的 CFO 對淨利／應計訊號高度同源。
- GMI 與 F-score 的毛利率變化同源。
- LVGI 與 F-score／Z-score／淨負債指標共同使用槓桿事實。
- DSRI、SGI 與現金轉換、營運資金吸收及成長品質也可能同源。

因此較清楚的處理是將 M-score 放在 **reporting-risk** 家族，呈現警示或降低分數信心；不要把「低 M-score」再當成獨立正面品質因子，除非上層已排除其與應計、毛利、槓桿等輸入的重疊。

---

## 5. Altman Z-score

### 5.1 原始模型

Altman（1968）以多元判別分析預測企業破產。原始論文為 *The Journal of Finance*, 23(4), 589–609，DOI：[10.1111/j.1540-6261.1968.tb00843.x](https://doi.org/10.1111/j.1540-6261.1968.tb00843.x)。原始公開製造業版本為：

```text
Z = 1.2 × (營運資金 / 總資產)
  + 1.4 × (保留盈餘 / 總資產)
  + 3.3 × (EBIT / 總資產)
  + 0.6 × (股權市值 / 總負債帳面值)
  + 1.0 × (銷售額 / 總資產)
```

原始常用區間為：Z > 2.99「較安全」、Z < 1.81「財務危機」，中間為灰色區。這些截點只應與原始公式及對應研究語境一起使用。

### 5.2 適用邊界與版本控管

- 原始樣本是規模有限的美國**公開製造業**破產／非破產配對樣本，並非所有國家、年代、規模與產業的通用違約機率。
- 金融業的「營運資金、負債、銷售、總資產」經濟意義與製造業不同；原始 Z 不適合作為銀行／保險品質分數。
- 私人公司版本（常稱 Z′）以股權帳面值取代市值且係數不同；非製造業／新興市場版本（常稱 Z″）移除 sales/TA 並重估係數。**不能只替換一個分子卻保留原係數與截點。**
- 市值／總負債使 Z 含市場價格資訊；若品質框架宣稱「純基本面」，必須明確標記。市場急跌也可能同時壓低 Z 與估值訊號，造成市場情緒重複影響。
- Z 是破產／財務困境篩檢，不是競爭優勢或高報酬能力衡量。高 Z 可能只表示低槓桿與流動性充足。

### 5.3 重疊處理

Z 的營運資金／資產、EBIT／資產、銷售／資產、槓桿／市值資訊分別與流動性、ROA/ROIC、資產週轉、槓桿及市場訊號重疊。可將 Z 放入 **solvency** 家族，作為危機警示、門檻或信心修正；若要直接加權，需先停用同源的個別償債指標，或在家族內先合成一次。

---

## 6. ROIC、FCF 與「護城河」如何不混成同一證據

### 6.1 ROIC：必須先固定口徑

ROIC 不是 IFRS 報表上的標準小計。常見研究式為：

```text
ROIC = 調整後 NOPAT / 平均投入資本
```

最低限度需明定：

- NOPAT 從 EBIT 還是稅後營業利益開始；稅率用法與虧損年度處理。
- 投入資本包含／排除現金、商譽、租賃負債、在建工程與停業資產的規則。
- 使用期初期末平均，並處理重大併購造成的分子分母期間不配對。
- 研發密集公司是否把部分研發視為投資；若調整，估計年限與攤銷表需完整保留。
- 至少同時顯示 reported 與 adjusted 版本，不把分析師估計偽裝成報表事實。

**限制來源**：IAS 38 指出研究支出認列為費用，符合條件的開發支出才資本化；內部生成品牌、刊頭、出版標題、客戶名單等不認列為無形資產。這會讓品牌／研發密集公司在帳面投入資本與當期營業利益上出現不可直接跨公司的差異。來源：[IFRS Foundation—IAS 38](https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/)。

### 6.2 FCF：不是單一會計準則科目

SEC Staff 的 Non-GAAP C&DI Question 102.07 說明，「free cash flow」通常計為 GAAP 營業活動現金流減資本支出，但其名稱不代表公司必然可任意支配，且必須清楚描述計算方式及必要調節。來源：[SEC—Non-GAAP Financial Measures C&DI](https://www.sec.gov/rules-regulations/staff-guidance/corporation-finance-interpretations/non-gaap-financial-measures)。

IAS 7 則規範現金流量表把現金流分為營業、投資、籌資活動，並定義現金及約當現金；它沒有替所有公司定義單一 FCF。來源：[IFRS Foundation—IAS 7](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/)。

因此應明定採用 FCFF、FCFE 或 CFO−capex；另須處理：

- 維持性與成長性 capex（若拆分，多半是估計而非已稽核 fact）。
- 租賃付款、資產證券化、供應鏈融資與利息分類。
- 應收／存貨短期釋放造成的單年現金高峰。
- 股票薪酬是非現金費用，但稀釋並非零成本；不可僅加回而忽略股數影響。

### 6.3 護城河：驅動證據與結果證據分開

「護城河」應拆成可觀察假說，而不是主觀標籤。Porter 的競爭力量架構把產業競爭、買方／供應商力量、替代品與新進入者壓力視為策略分析面向；原始作者材料可由 [Harvard Business Review—How Competitive Forces Shape Strategy](https://hbr.org/1979/03/how-competitive-forces-shape-strategy) 查核。

可建立兩張分離的表：

- **驅動證據（driver）**：法規／專利保護、轉換成本的契約證據、網路密度、通路控制、規模門檻、客戶整合深度。必須有文件來源、日期與可反證條件。
- **結果證據（outcome）**：穩定的超額 ROIC、毛利韌性、留存／流失、價格與量拆解、單位經濟、低獲客回收期。

若結果已在 ROIC／FCF／毛利中加分，driver 最適合作為：

1. 結果持續性的**信心標籤**；或
2. 結果不足時的待驗證假說；或
3. 獨立構面的替代輸入，但此時不得再把同一結果全額加權。

IAS 36 要求資產不得以高於可回收金額列示，且商譽／現金產生單位涉及減損測試；這是帳面資產可回收性的會計檢驗，不等於競爭優勢獲得認證。來源：[IFRS Foundation—IAS 36](https://www.ifrs.org/issued-standards/list-of-standards/ias-36-impairment-of-assets/)。

---

## 7. 防重複計分的操作規則

### 規則 1：建立「原始 fact × 指標」血緣矩陣

每列是原始 fact（CFO、淨利、總資產、EBIT、營收、毛利、負債等），每欄是衍生指標。兩個指標若大量共享 fact，先推定不獨立。例如：

- CFO/NI、應計比率、F-score 的 accrual 訊號、M-score TATA。
- EBIT/資產、ROA、ROIC、Z-score 的 EBIT/TA。
- sales/assets、F-score 週轉改善、Z-score sales/TA。

### 規則 2：建立「構念 × 指標」對照表

每個指標只指定一個**主要構念**，可有次要標籤但不得因此多次進分。模型總分（F、M、Z）需拆解成組件後再判斷重疊，不能因其名稱不同就視為獨立。

### 規則 3：同一證據家族先合成，再跨家族合成

家族內可擇一代表值、取最保守值、使用降維，或做明定的子指標合成；跨家族只接收家族級輸出。方法可不同，但需版本化且做敏感度測試。

### 規則 4：風險警示不自動反轉為品質獎勵

- M-score 無警報 ≠ 證明報導高品質。
- Z-score 安全區 ≠ 有護城河。
- F-score 高 ≠ 結構性高 ROIC。

可把異常作為調查旗標、上限或否決條件；但如何影響總分是治理決策，本研究不指定。

### 規則 5：驅動因與結果擇一主計

如果「高留存 → 高毛利 → 高 ROIC → 高 FCF」都來自同一商業機制，可選結果作主計、驅動作信心；或選驅動與結果不同構面但降低其共同暴露。不得把敘事標籤再疊加在財務結果上。

### 規則 6：先做相關與敏感度診斷，不把統計獨立誤當因果獨立

OECD／European Commission JRC 的 *Handbook on Constructing Composite Indicators* 將理論架構、資料選擇、多變量分析、正規化、權重／聚合及不確定性與敏感度分析列為綜合指標建構流程。可據此：

- 公布 Pearson 與 Spearman 相關矩陣；按產業、年份重算。
- 比較移除任一指標、改變正規化／截尾／缺值規則後的排名穩定度。
- 公布構面對總分的實際貢獻，而不只公布名目權重。
- 若高相關源自共同分母或因果鏈，即使樣本相關暫時偏低，仍應按血緣規則處理。

來源：[European Commission JRC—JRC47008](https://publications.jrc.ec.europa.eu/repository/handle/JRC47008)、[OECD DOI 10.1787/9789264043466-en](https://doi.org/10.1787/9789264043466-en)。

### 規則 7：產業適用性先於缺值補值

金融業、REIT、公用事業、早期生技等若公式的經濟含義失效，應標 `not-applicable`，不是以產業中位數補成「普通品質」。模型版本、產業排除與最低資料覆蓋率均需事前固定。

---

## 8. 建議的模型登錄卡（不含權重決策）

每個模型／指標均填一張：

```yaml
metric_id:
version:
latent_construct:
intended_use: [score_input | validation | warning | cap | display_only]
formula:
raw_fact_ids:
source_documents:
available_at_rule:
accounting_adjustments:
applicable_industries:
excluded_conditions:
missing_data_policy:
winsorization_or_normalization:
calibration_sample:
threshold_source:
overlap_lineage_groups:
known_limitations:
owner_approver:
change_log:
```

並輸出三項治理報告：

1. **涵蓋率報告**：哪些公司因何缺值／不適用。
2. **重疊報告**：共同 fact、共同構念、相關係數、家族內處理。
3. **敏感度報告**：不同合理口徑／模型版本下的分數與排名變動。

---

## 9. 主張—來源稽核表

| 主張／用途 | URL | 來源擁有者 | 適用範圍 | 主要限制 |
|---|---|---|---|---|
| F-score 原始研究以歷史財報訊號區分 high book-to-market 公司；作者版本載明 1976–1996、14,043 個公司年度觀察值 | [DOI 10.2307/2672906](https://doi.org/10.2307/2672906)、[UCLA PDF](https://www.anderson.ucla.edu/documents/areas/prg/asam/2019/F-Score.pdf) | Joseph D. Piotroski；*Journal of Accounting Research*／JSTOR；UCLA Anderson（檔案主機） | 原始研究設計、九項訊號及樣本語境 | 非全市場品質定義；期刊全文可能限制存取；跨期跨國需重驗證 |
| M-score 以財報失真與操縱誘因變數作篩檢；約辨識一半樣本操縱者且需調查結構性原因 | [DOI 10.2469/faj.v55.n5.2296](https://doi.org/10.2469/faj.v55.n5.2296) | Messod D. Beneish；CFA Institute / Financial Analysts Journal（現由 Taylor & Francis 平台提供） | 盈餘操縱風險初篩 | 不是舞弊認定；歷史樣本與基準率限制；特殊產業需驗證 |
| 原始 Altman Z 是公開製造業語境的破產判別模型 | [DOI 10.1111/j.1540-6261.1968.tb00843.x](https://doi.org/10.1111/j.1540-6261.1968.tb00843.x) | Edward I. Altman；American Finance Association / Wiley | 原始五比率公式、判別研究 | 不可將原式、Z′、Z″係數與截點混用；非通用違約機率 |
| 綜合指標需有理論架構、多變量分析、權重／聚合及敏感度／不確定性分析 | [JRC47008](https://publications.jrc.ec.europa.eu/repository/handle/JRC47008)、[OECD DOI](https://doi.org/10.1787/9789264043466-en) | OECD；European Commission Joint Research Centre | 綜合指標設計與治理方法 | 原手冊以國家層級指標為主要案例；套用公司分數需調整分析單位 |
| IAS 7 定義並分類營業、投資、籌資現金流，但不提供通用 FCF 小計 | [IAS 7](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/) | IFRS Foundation / IASB | IFRS 現金流分類 | US GAAP 分類可能不同；摘要頁非完整授權準則文本 |
| SEC 說明 FCF 通常為 CFO 減 capex，名稱不表示可任意支配，需揭露計算與調節 | [Non-GAAP C&DI Q102.07](https://www.sec.gov/rules-regulations/staff-guidance/corporation-finance-interpretations/non-gaap-financial-measures) | U.S. Securities and Exchange Commission, Division of Corporation Finance | 美國公開公司非 GAAP 揭露 | 監管揭露指引，不是估值上的唯一 FCF 定義 |
| IAS 38 對研究／開發支出及內生品牌、客戶名單的認列造成 ROIC 可比性問題 | [IAS 38](https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/) | IFRS Foundation / IASB | IFRS 無形資產認列與衡量 | 分析師資本化調整仍是估計，需另列調整表 |
| IAS 36 減損測試檢查資產可回收額，不等於護城河認證 | [IAS 36](https://www.ifrs.org/issued-standards/list-of-standards/ias-36-impairment-of-assets/) | IFRS Foundation / IASB | IFRS 資產與商譽減損 | 會計估計具有判斷；不能直接量化競爭優勢 |
| 五力架構可用來拆解競爭壓力與進入障礙假說 | [HBR 原始作者材料](https://hbr.org/1979/03/how-competitive-forces-shape-strategy) | Michael E. Porter；Harvard Business Review | 產業結構／競爭策略質化分析 | 不是會計分數；需轉成公司、時間與來源明確的可反證證據 |

---

## 10. 結論（保留給治理者的決策空間）

1. F-score、M-score、Z-score回答不同問題：**改善方向、操縱風險、財務困境**；都不應被直接等同於「公司品質」。
2. ROIC、FCF、毛利／週轉、應計、槓桿，以及三個模型的組件大量共用原始財報事實。應先做 fact lineage 與 evidence family，再決定是否進入綜合層。
3. 護城河的驅動證據與 ROIC／FCF 的結果證據要分開；同一因果鏈只能有一個主要加權入口，其餘作驗證或信心資訊。
4. 權重、門檻、否決條件與產業模型是治理選擇；應由 Wayne／模型治理者在看到覆蓋率、重疊與敏感度報告後決定，本文件不代為選擇。
