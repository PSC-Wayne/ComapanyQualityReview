# 台灣上市櫃財報查核報告、會計師意見與財務鑑識訊號

> 範圍：臺灣證券交易所上市公司與證券櫃檯買賣中心上櫃公司；一般產業為主，金融、保險、證券等特許業別另受各業財報編製準則規範。  
> 查核基準日（as of）：**2026-07-23**。法規與準則應按「財務報導期間結束日／查核報告日當時有效版本」適用，不可用今日版本倒套歷史案件。  
> 本文是資料 authority、擷取與風險研究，不是法律或審計意見。

## 1. 結論先行

1. **法律義務與期限**以《證券交易法》第 14、20、20-1、36 條及其施行細則為最高層 authority；一般曆年制上市櫃公司原則上年度財報於年度終了後三個月內申報，第一、二、三季於各季終了後 45 日內申報。[證券交易法（FSC）](https://law.fsc.gov.tw/LawContent.aspx?id=FL007009)／[第 36 條（全國法規資料庫）](https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0400001&flno=36)
2. **報告內容 authority**是公司實際申報至公開資訊觀測站（MOPS）的會計師查核／核閱報告及完整財報電子書，不是新聞或資料商的單一「意見」欄位。MOPS `t163sb03` 可取得事務所、簽證會計師、報告日、意見／結論類型與完整報告文字。[MOPS 會計師查核（核閱）報告](https://mopsov.twse.com.tw/mops/web/t163sb03)
3. **專業判斷 authority**是會計研究發展基金會（ARDF）發布的我國審計／核閱準則：700（查核報告）、705（修正式意見）、706（強調／其他事項）、570（繼續經營）、701（關鍵查核事項）、2410（財務報表核閱）。[ARDF 已發布公報目錄](https://www.ardf.org.tw/fas4.html)／[公報全文入口](https://www.ardf.org.tw/ardf.html)
4. **年度查核與季度核閱不可混成同一強度**：查核取得合理確信並表示「意見」；核閱主要採查詢、分析性程序及其他核閱程序，風險降至中度水準，作成「結論」，其範圍明顯小於查核，不能解讀成同等保證。[核閱準則 2410](https://www.ardf.org.tw/ardf/2025/2410.pdf)
5. **「無保留」不代表零風險**。無保留意見仍可能同時存在「繼續經營相關重大不確定性」、「強調事項」、「其他事項」及高風險關鍵查核事項（KAM）；這些段落本身通常不修改意見，卻可能比意見標籤更有鑑識價值。[審計準則 570](https://www.ardf.org.tw/ardf/2025/570.pdf)／[706](https://www.ardf.org.tw/ardf/2025/706.pdf)／[701](https://www.ardf.org.tw/ardf/2025/701.pdf)
6. **更補正與重編必須版本化**：MOPS 更（補）正表會揭露公司、公告日期、資料種類與更正內容；達施行細則第 6 條門檻者須重編並重行公告。不得以最新重編版覆寫歷史所見。[MOPS 財報更（補）正](https://mopsov.twse.com.tw/mops/web/t56sb31_q1)／[證交法施行細則第 6 條](https://law.fsc.gov.tw/LawContent.aspx?id=FL007010)
7. **最適合機器化的是「結構欄位＋章節偵測＋版本事件」三層**。MOPS metadata 可高度結構化；完整報告的章節、KAM、繼續經營與附註交叉引用可半結構化；風險嚴重度、管理階層假設是否可信仍需人工或可稽核的 NLP 規則覆核。

---

## 2. Authority 分層

| 層級 | Authority | 決定什麼 | 官方來源 |
|---|---|---|---|
| A（法律） | 證券交易法、施行細則 | 財報定義、不得虛偽隱匿、簽證責任、年度／季度申報期限、重編門檻、變更簽證會計師之重大事件性質 | [證券交易法](https://law.fsc.gov.tw/LawContent.aspx?id=FL007009)、[施行細則](https://law.fsc.gov.tw/LawContent.aspx?id=FL007010) |
| A（主管機關命令） | FSC 各業財務報告編製準則 | 財報組成、會計政策、期中報導、附註及更正要求 | [證券發行人財務報告編製準則](https://law.fsc.gov.tw/LawContent.aspx?id=FL007203) |
| A（申報原文） | MOPS | 公司實際申報的報告、意見、簽證人、報告日、完整財報與更補正 | [財報公告 `t163sb01`](https://mopsov.twse.com.tw/mops/web/t163sb01)、[查核／核閱報告 `t163sb03`](https://mopsov.twse.com.tw/mops/web/t163sb03)、[更補正 `t56sb31_q1`](https://mopsov.twse.com.tw/mops/web/t56sb31_q1) |
| A（專業準則） | ARDF 審計／核閱準則 | 各意見與報告段落的專業定義、形成條件與報告格式 | [ARDF 公報目錄](https://www.ardf.org.tw/fas4.html)、[全文閱覽](https://www.ardf.org.tw/ardf.html) |
| A（公告事件） | MOPS 重大訊息；TWSE／TPEx OpenAPI | 會計師更換、延遲、董事會通過、更正／重編等公告時點與公司說明 | [MOPS 歷史重大訊息](https://mopsov.twse.com.tw/mops/web/t05st01)、[TWSE 每日重大訊息](https://openapi.twse.com.tw/v1/opendata/t187ap04_L)、[TPEx 每日重大訊息](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O) |
| B（衍生） | 研究系統 | 逾期天數、會計師輪替、KAM 變動、版本差異、風險分數 | 必須回指上述 A 層原始 bytes、URL、公告時間及 hash |

**重要限制**：FSC 法規頁在 2026-07-23 顯示《證券發行人財務報告編製準則》已有部分條文預定 2028-01-01（民國 117 年）施行；PIT 系統必須保存公布日、施行日及歷史法規版本，不能只看「目前頁面」。[FSC 編製準則法規頁](https://law.fsc.gov.tw/LawContent.aspx?id=FL007203)

---

## 3. 年度查核與季度核閱

| 維度 | 年度財報 | 第一、二、三季財報 |
|---|---|---|
| 法定工作 | 會計師**查核簽證** | 會計師**核閱** |
| 法定期限（一般規則） | 年度終了後 3 個月內 | 各季終了後 45 日內 |
| 報告產出 | 查核「意見」 | 核閱「結論」 |
| 確信強度 | 合理確信（高度，但非絕對保證） | 有限確信；作成不適當結論之風險降至中度 |
| 主要工作差異 | 風險評估、控制瞭解、實證程序等，以取得足夠適切查核證據 | 主要為查詢、分析性程序及其他核閱程序，範圍顯著小於查核 |
| 常見標準無保留文字 | 「在所有重大方面……允當表達」 | 負面確信式：「並未發現……有未依照……編製，致無法允當表達之情事」 |
| KAM | 上市櫃年度查核報告通常依 701 準則溝通 | 2410 核閱報告不應機械期待年度式 KAM；若出現特殊段落，應按原文分類 |
| MOPS 實測欄位 | `查核類型：無保留結論/意見`，正文為「會計師查核報告」 | 同一類型欄位可能仍顯示 `無保留結論/意見`，正文為「會計師核閱報告」；故必須另存 `engagement_type` |

來源：[證交法第 36 條](https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0400001&flno=36)、[審計準則 700](https://www.ardf.org.tw/ardf/2025/700.pdf)、[核閱準則 2410](https://www.ardf.org.tw/ardf/2025/2410.pdf)、[MOPS `t163sb03`](https://mopsov.twse.com.tw/mops/web/t163sb03)。

> 例外：法令可能對特定業別、特殊情況或延期另有規定。逾期判定不可只用固定月曆日；需綁定公司會計年度、適用業別、當時法規、假日順延與主管機關個案／通案展延證據。[證交法第 36 條第二項授權](https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0400001&flno=36)

---

## 4. 意見、段落與風險訊號

### 4.1 無保留意見／無保留結論

- **年度無保留意見**：會計師認為財報在所有重大方面依適用財報架構編製並允當表達。[審計準則 700](https://www.ardf.org.tw/ardf/2025/700.pdf)
- **季度無保留結論**：核閱人員未發現財報在所有重大方面有未依適用架構編製致無法允當表達之情事；這是有限確信，不能寫成「會計師證明財報正確」。[核閱準則 2410](https://www.ardf.org.tw/ardf/2025/2410.pdf)
- **風險解讀**：基準風險最低，但必須再檢查繼續經營、強調事項、其他事項、KAM、前期比較數由他人查核、附註與後續更正。
- **術語陷阱**：「修正式意見」不是「無保留報告中多了一個段落」。705 所稱修正式意見只有保留、否定、無法表示三類；強調事項不等於修正意見。[705](https://www.ardf.org.tw/ardf/2025/705.pdf)／[706](https://www.ardf.org.tw/ardf/2025/706.pdf)

### 4.2 修正式意見：保留、否定、無法表示

審計準則 705 以「事項性質」及其影響是否「廣泛」決定意見：[審計準則 705](https://www.ardf.org.tw/ardf/2025/705.pdf)

| 類型 | 專業條件摘要 | 研究風險 | 應擷取 |
|---|---|---:|---|
| 保留意見 | 已取得證據且不實表達重大但不廣泛；或無法取得足夠適切證據，可能影響重大但不廣泛 | 高 | `qualified_basis_type=misstatement|scope_limitation`、涉及科目、金額、期間、附註、量化影響 |
| 否定意見 | 已取得證據，認為不實表達重大且廣泛 | 極高／通常 fail-closed | 否定意見基礎全文、受影響報表與項目、管理階層未調整事項 |
| 無法表示意見 | 無法取得足夠適切證據，可能未偵出不實表達之影響重大且廣泛；極罕見時亦可能源於多項不確定性相互影響 | 極高／通常 fail-closed | 範圍限制來源、缺失證據、可能影響、責任段落差異 |

季度核閱亦可能出現修正式結論或因範圍限制無法作成結論；應依 2410 報告原文分類，避免把所有季度結果硬映射為年度「意見」。[核閱準則 2410](https://www.ardf.org.tw/ardf/2025/2410.pdf)

### 4.3 繼續經營重大不確定性（MURGC）

- 570 要求查核人員對管理階層採用繼續經營基礎是否適當，以及使企業繼續經營能力可能產生重大疑慮之事件或情況是否存在重大不確定性作成結論。[審計準則 570](https://www.ardf.org.tw/ardf/2025/570.pdf)
- 若繼續經營基礎適當且附註充分，通常另列「與繼續經營相關之重大不確定性」段，**意見可仍是無保留**；揭露不適當時則可能修正意見。[審計準則 570](https://www.ardf.org.tw/ardf/2025/570.pdf)
- 未出現該段不等於會計師保證公司能繼續經營；570 明定會計師未提及重大不確定性不能視為對繼續經營能力之保證。[審計準則 570](https://www.ardf.org.tw/ardf/2025/570.pdf)
- **高價值欄位**：`going_concern_material_uncertainty`、段落全文、引用附註、疑慮事件（流動性、債務違約、持續虧損、資本不足等）、管理階層因應計畫、會計師對揭露充分性結論。
- **風險**：極高，但不應自動等同破產；應把「重大不確定性」與一般管理階層責任段固定文字分開。所有標準報告都會說管理階層須評估繼續經營，僅此固定文字不是警訊。

### 4.4 強調事項

- 強調事項用來提醒使用者注意已在財報中適當表達／揭露、且對理解財報至關重要之事項；本身不是修正意見，也不能代替修正意見。[審計準則 706](https://www.ardf.org.tw/ardf/2025/706.pdf)
- **風險強度取決於內容**：重大訴訟、災害、重大期後事項、會計基礎特殊性、重編等通常值得提高風險；純制度性提醒不宜一律重罰。
- 擷取：標題、全文、所引附註、主題 taxonomy、是否重複多期、首次／消失期。

### 4.5 其他事項

- 其他事項是指未在財報中表達／揭露、但與使用者了解查核、會計師責任或報告攸關的事項；通常不修改意見。[審計準則 706](https://www.ardf.org.tw/ardf/2025/706.pdf)
- 常見內容包括前期比較數由其他會計師查核、另有個體財報等。不是每個「其他事項」都是負面訊號。
- **較高風險模式**：前任會計師意見不同、前期未經查核、比較資訊有範圍問題、與其他報告責任相關之異常說明。

### 4.6 關鍵查核事項（KAM）

- KAM 是會計師從與治理單位溝通事項中，依專業判斷選出的「對本期財報查核最為重要之事項」；會計師是在整體財報形成意見的過程中因應，**不對每一 KAM 單獨表示意見**。[審計準則 701](https://www.ardf.org.tw/ardf/2025/701.pdf)
- 每一 KAM 應至少擷取：標題、為何最重要、引用附註、會計師如何因應、涉及科目／估計／控制、年度。
- **有價值的衍生訊號**：
  - 新增 KAM，尤其收入認列、存貨跌價、商譽／資產減損、關係人、重大估計或 IT 控制；
  - 同一 KAM 多年持續但風險敘述惡化；
  - 引用附註、會計估計與財報數字不一致；
  - KAM 數量驟減／消失但業務風險未消失，應人工檢查，不能直接判定美化；
  - KAM 不是「會計師發現錯誤清單」，也不宜以項數直接線性扣分。

### 4.7 財報附註

《證券發行人財務報告編製準則》第 4 條把附註／附表納入財務報表；第 15 條要求重大會計政策、重大判斷與估計不確定性、或有負債與承諾、財務風險、借款、關係人、重大災害等揭露；期中財報另依 IAS 34 及第 20 條揭露自前一年度結束後之重大事項。[FSC 編製準則](https://law.fsc.gov.tw/LawContent.aspx?id=FL007203)

優先擷取附註主題：

- 繼續經營與流動性、借款到期、財務契約違約／豁免；
- 重大會計判斷、估計不確定性與估計方法變動；
- 收入認列（總額／淨額、履約義務）、存貨與呆帳、減損；
- 關係人、資金貸與、背書保證、或有負債、重大訴訟與承諾；
- 期後事項、處分／取得資產、停業單位；
- 會計政策變動、錯誤更正、追溯重編、重分類及前後期影響；
- 與 KAM／保留基礎／強調事項的附註交叉引用。

**限制**：附註長、表格跨頁、公司自訂標題、PDF 字型與掃描檔會降低解析率；XBRL 可改善數字擷取，但敘述、查核判斷及交叉引用仍需保留電子書／HTML 原文。[MOPS 財報公告](https://mopsov.twse.com.tw/mops/web/t163sb01)

---

## 5. 會計師／事務所更換

1. 《證券交易法施行細則》第 7 條把「變更簽證會計師」列為對股東權益或證券價格有重大影響之事項，但事務所內部調整除外；依證交法第 36 條第三項，此類事項原則上應於事實發生日起二日內公告申報。[施行細則第 7 條](https://law.fsc.gov.tw/LawContent.aspx?id=FL007010)／[證交法第 36 條](https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0400001&flno=36)
2. 事件 authority 應先取 MOPS 歷史重大訊息正文，再以連續季度 `t163sb03` 的事務所／簽證人實際變化驗證。[MOPS 重大訊息](https://mopsov.twse.com.tw/mops/web/t05st01)／[MOPS 查核核閱報告](https://mopsov.twse.com.tw/mops/web/t163sb03)
3. 機器欄位：`old_firm`、`new_firm`、`old_cpas[]`、`new_cpas[]`、`event_at`、`announcement_at`、`reason_text`、`internal_rotation_flag`、`disagreement_or_scope_issue_flag`、`first_report_period_under_new_auditor`。
4. 風險排序：
   - **低／中**：同一事務所內簽證會計師定期輪調，且公告／報告敘述一致；
   - **中／高**：事務所更換、無清楚理由、接近申報期限、連續短期更換；
   - **高／極高**：伴隨管理階層與前任會計師歧見、查核範圍限制、延遲、修正式意見、更補正／重編。
5. 僅比較會計師姓名會產生大量假陽性；必須區分「事務所內部調整」與真正 auditor dismissal/resignation/change，並保留公司公告理由原文。

---

## 6. 延遲申報

### 判定方式

```text
statutory_due_at = due_date(
  fiscal_period_end,
  engagement_type,
  issuer_type,
  industry_rule,
  special_extension,
  holiday_policy,
  law_version
)

filing_delay_days = official_filed_at - statutory_due_at
late = official_filed_at > statutory_due_at
```

- 一般基準：年度 3 個月、Q1/Q2/Q3 45 日。[證交法第 36 條](https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0400001&flno=36)
- `official_filed_at` 必須是官方申報／公告時間，不得以財報期末、董事會日、查核報告日或本系統下載日替代。[MOPS 財報公告](https://mopsov.twse.com.tw/mops/web/t163sb01)
- 若 MOPS 目標表只有日期無時間，保留 date precision，盤中回測採「次一交易時點可用」等保守規則；若無可靠申報 timestamp，首次成功擷取只能作 `available_at` 的保守上界，不可宣稱為原始 filing time。
- 查核報告日早於期限但申報晚，仍是申報延遲；報告日晚於期限則是更強警訊，但兩者須分欄。
- 風險訊號：首次逾期、連續逾期、逾期天數惡化、延遲同時伴隨更換事務所／範圍限制／重編／繼續經營。個案展延或特殊法令存在時不得誤判。

---

## 7. 更（補）正、重編與版本風險

### 法規與來源

- 編製準則第 5 條要求，財報違反準則或其他規定而經 FSC 通知調整者應調整更正；達規定標準時應重行公告，並註明通知調整理由、項目與金額。[FSC 編製準則](https://law.fsc.gov.tw/LawContent.aspx?id=FL007203)
- 施行細則第 6 條規定重編門檻：個體／個別與合併財報分別依綜合損益、資產負債表更正金額及占原營收／總資產比率判斷；未達門檻者仍應於指定網站更正。[證交法施行細則](https://law.fsc.gov.tw/LawContent.aspx?id=FL007010)
- MOPS `t56sb31_q1` 實際提供資料年度、季別、公司代號／名稱、公告日期、資料說明、更（補）正內容與詳細資料入口。[MOPS 更（補）正查詢](https://mopsov.twse.com.tw/mops/web/t56sb31_q1)

### 風險分級

| 更正型態 | 典型風險 |
|---|---:|
| 英文版、頁碼、格式、錯字，不影響數字／意見 | 低，但仍留版本 |
| 附註或附表補充（關係人、背書保證、承諾、資金貸與等） | 中至高，依內容 |
| XBRL tag／分類錯置但原始報告正確 | 中；影響機器資料品質 |
| EPS、收入總額／淨額、現金流、資產負債或權益更正 | 高 |
| 更正保留結論／查核報告文字、意見類型、會計師報告 | 高至極高 |
| 達門檻重編、主管機關要求、重行查核／核閱 | 極高 |
| 同一公司短期多次更正或跨期追溯 | 加重訊號 |

### PIT 版本契約

- 不覆寫：`original -> correction -> restatement` append-only。
- 最少欄位：`version_id`、`supersedes_version_id`、`announcement_at`、`available_at`、`reason_text`、`affected_statements/notes`、`quantified_effects`、`audit_report_changed`、`source_sha256`。
- `as_of=T` 只能選 `available_at <= T` 的最後一版；更正發布前的研究結果應看到當時舊版。今天下載的重編報告不能回填成歷史已知。
- 區分：`correction`（錯誤更正）、`supplement`（補揭露）、`restatement`（重編）、`reclassification`（重分類）、`accounting_policy_retrospective_application`（會計政策追溯適用），不要全部壓成一個 boolean。

---

## 8. 建議可擷取資料模型

### 8.1 報告主檔

```yaml
issuer:
  market: listed | otc
  security_code: "2330"
  reported_name: "..."
report:
  fiscal_year_roc: 114
  fiscal_quarter: 4
  fiscal_period_end: "2025-12-31"
  statement_scope: consolidated | separate | individual
  engagement_type: audit | review
  report_title: "會計師查核報告"
  report_date: "2026-02-10"
  firm_name: "..."
  signing_cpas: ["...", "..."]
  mops_opinion_label_raw: "無保留結論/意見-"
  normalized_outcome: unmodified_opinion | qualified_opinion | adverse_opinion | disclaimer | unmodified_conclusion | qualified_conclusion | adverse_conclusion | unable_to_conclude | unknown
  report_text: "..."
```

上述 metadata 與全文可由 MOPS `t163sb03` 取得；公司、期別與合併／個別必須共同驗證，不能只用公司代碼。[MOPS `t163sb03`](https://mopsov.twse.com.tw/mops/web/t163sb03)

### 8.2 章節與訊號

```yaml
sections:
  opinion_or_conclusion_text: "..."
  basis_text: "..."
  going_concern_material_uncertainty_text: null
  emphasis_of_matter: []
  other_matter: []
  key_audit_matters:
    - title: "..."
      why_significant: "..."
      audit_response: "..."
      note_references: ["附註五", "附註十五"]
  predecessor_auditor_reference: null
  comparative_information_issue: null
flags:
  modified_outcome: false
  going_concern_material_uncertainty: false
  emphasis_present: false
  other_matter_present: true
  kam_count: 1
  scope_limitation: false
  restatement_reference: false
```

### 8.3 公告與版本

```yaml
timing:
  announced_at: "...+08:00"
  available_at: "...+08:00"
  availability_basis: official_timestamp | official_date_conservative | first_retrieval
  retrieved_at: "...+08:00"
  statutory_due_at: "...+08:00"
  delay_days: 0
version:
  version_id: "..."
  supersedes_version_id: null
  correction_type: none | correction | supplement | restatement | reclassification
  correction_reason: null
provenance:
  landing_url: "https://mopsov.twse.com.tw/mops/web/t163sb03"
  data_url: ".../ajax_t163sb03"
  request_parameters_sanitized: {}
  http_status: 200
  source_sha256: "..."
  parser_version: "..."
```

---

## 9. 可機器化程度

| 對象 | 程度 | 理由／限制 |
|---|---:|---|
| 公司、年季、合併／個別、事務所、會計師、報告日、MOPS 意見標籤 | 高 | `t163sb03` 為半結構化 HTML；仍須防版型變動、全形空白、同名與歷史名稱 |
| 年度查核 vs 季度核閱 | 高 | 年季＋報告標題＋正文準則引用可三重判定；不可只信共用「結論/意見」標籤 |
| 保留／否定／無法表示、修正基礎 | 中高 | 標題相對穩定；仍需解析不實表達 vs 範圍限制及廣泛性 |
| 繼續經營重大不確定性 | 中高 | 專屬標題可抓；須排除每份標準責任段都有的固定「繼續經營」文字 |
| 強調事項／其他事項 | 中高 | 標題可抓，但內容風險需語義分類；「其他事項」常為中性 |
| KAM 分段、標題、附註引用 | 中 | 公司格式不一、跨頁、子標題及條列；KAM 嚴重度需人工覆核 |
| 核閱結論 | 中高 | 標準負面確信文字可規則化；修正式結論與無法作成結論需完整原文 |
| 會計師／事務所更換 | 中高 | 連續報告 diff 容易；但是否事務所內輪調、真正辭任／解任須合併重大訊息 |
| 延遲申報 | 中 | 計算簡單；難點是可靠 filing timestamp、特殊期限／展延、假日與歷史法規 |
| 更補正／重編事件 | 高（事件）／中（影響量） | `t56sb31_q1` 有事件欄位；詳細影響可能埋在文字、附件及新舊報告 |
| 財報附註敘述與跨期 semantic diff | 中低 | 長篇 PDF／HTML、表格、OCR、標題漂移與會計語義；需人工抽查 |
| 「舞弊／公司會倒」結論 | 低且不應自動化 | 查核報告是合理／有限確信，不是舞弊保證或破產預測；只能產生待查風險訊號 |

### 實作上的解析優先序

1. 先取 `t163sb01` 公告脈絡與 `t163sb03` 報告 metadata／全文。[公告](https://mopsov.twse.com.tw/mops/web/t163sb01)／[報告](https://mopsov.twse.com.tw/mops/web/t163sb03)
2. 按報告標題、年季與準則引用判定 `audit|review`。
3. 以章節標題定位，不以關鍵字計數代替：例如固定責任段出現「重大不確定性」不代表真的有 MURGC 專段。
4. 從 705／570／706／701／2410 建立可版本化標題詞典與段落狀態機。[ARDF 全文入口](https://www.ardf.org.tw/ardf.html)
5. 接 `t56sb31_q1` 與 `t05st01`，建立更正、會計師更換、延遲說明的事件鏈。[更補正](https://mopsov.twse.com.tw/mops/web/t56sb31_q1)／[重大訊息](https://mopsov.twse.com.tw/mops/web/t05st01)
6. 對高風險命中保留整段原文、附註引用與人工覆核狀態；分類器輸出不可取代 source text。

---

## 10. Point-in-Time（PIT）與 as-of 契約

### 必要時間

- `fiscal_period_end`：財報經濟期間結束日；
- `report_date`：會計師報告日期；
- `board_approved_at`：董事會通過日（若可得）；
- `announced_at`：公司向官方系統公告申報時間；
- `available_at`：研究系統可安全使用的最早時間；
- `retrieved_at`：本系統完成下載時間；
- `valid_from/valid_to`：報告版本在知識時間軸上的半開區間。

`report_date` 不等於 `announced_at`；期間結束日更不等於市場已知日。可用條件至少為：

```text
available_at <= decision_time
AND valid_from <= decision_time < valid_to
AND issuer identity 可於 decision_time 唯一解析
```

### 歷史重建限制

- MOPS 現行查詢可查歷史報告，但今天取回的內容可能已反映後續更補正；若沒有保存原始版 bytes，不能保證重建「當時畫面」。
- OpenAPI 每日重大訊息適合當日全市場掃描，不自動等於完整歷史 archive；指定公司歷史應使用有界 MOPS 查詢並持續封存。[TWSE OpenAPI](https://openapi.twse.com.tw/v1/opendata/t187ap04_L)／[TPEx OpenAPI](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O)
- 只有日期沒有時間時，不可假設 00:00 已知；日頻回測可保守延至下一可交易時點。
- 法規與 ARDF 準則本身也要版本化：保存 `standard_version`、發布／修訂日、適用期間；不能以 2026 年準則名稱假設所有歷史報告格式一致。[ARDF 公報目錄](https://www.ardf.org.tw/fas4.html)

---

## 11. 建議風險訊號框架（非投資建議）

### Fail-closed／人工必審

- 否定意見、無法表示意見；
- 季度無法作成結論或相當程度範圍限制；
- 繼續經營重大不確定性；
- 財報重編且影響收入、損益、權益或意見；
- 延遲＋事務所更換＋修正式意見的組合；
- 報告內容、MOPS 類型欄位與更補正事件互相矛盾。

### 高風險但需內容判讀

- 保留意見／保留結論；
- 強調事項涉及重編、重大訴訟、災害、重大期後事項；
- 事務所更換理由不明、頻繁更換或接近期限；
- KAM 新增收入認列、減損、關係人或重大估計，且附註假設惡化；
- 多次更正、主管機關要求補充揭露、查核報告本身補正。

### 不應單獨視為負面

- 無保留報告中的一般「其他事項」（例如另有個體財報）；
- KAM 數量多；
- 同事務所內正常簽證會計師輪調；
- 純格式／英文版／XBRL tag 更正；
- 標準責任段中固定出現「繼續經營」、「重大不確定性」或「舞弊」文字。

建議將每個訊號輸出為 `severity + evidence + source_url + source_hash + as_of + review_status`，而不是只留一個不可解釋的總分。

---

## 12. 已驗證的官方入口清單

### MOPS

- 財務報告公告：<https://mopsov.twse.com.tw/mops/web/t163sb01>
- 會計師查核（核閱）報告：<https://mopsov.twse.com.tw/mops/web/t163sb03>
- 財務報告更（補）正：<https://mopsov.twse.com.tw/mops/web/t56sb31_q1>
- 歷史重大訊息：<https://mopsov.twse.com.tw/mops/web/t05st01>
- 即時重大訊息入口：<https://mopsov.twse.com.tw/mops/web/t05sr01_1>

MOPS 的 `ajax_...` action 為實際資料回應，但參數及版型可能變動；正式擷取應先讀 landing form、使用單一 session、有界查詢、驗證公司／市場／年季／報告類型，並保存 method、參數、HTTP status、bytes 與 SHA-256。

### FSC／法規

- 證券交易法：<https://law.fsc.gov.tw/LawContent.aspx?id=FL007009>
- 證券交易法第 36 條（單條）：<https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0400001&flno=36>
- 證券交易法施行細則：<https://law.fsc.gov.tw/LawContent.aspx?id=FL007010>
- 證券發行人財務報告編製準則：<https://law.fsc.gov.tw/LawContent.aspx?id=FL007203>

### ARDF

- 已發布公報目錄：<https://www.ardf.org.tw/fas4.html>
- 公報內容閱覽：<https://www.ardf.org.tw/ardf.html>
- 700 財務報表查核報告：<https://www.ardf.org.tw/ardf/2025/700.pdf>
- 701 查核報告中關鍵查核事項之溝通：<https://www.ardf.org.tw/ardf/2025/701.pdf>
- 705 修正式意見之查核報告：<https://www.ardf.org.tw/ardf/2025/705.pdf>
- 706 查核報告中之強調事項段及其他事項段：<https://www.ardf.org.tw/ardf/2025/706.pdf>
- 570 繼續經營：<https://www.ardf.org.tw/ardf/2025/570.pdf>
- 2410 財務報表之核閱：<https://www.ardf.org.tw/ardf/2025/2410.pdf>

### 交易所／櫃買 OpenAPI

- TWSE 上市公司每日重大訊息：<https://openapi.twse.com.tw/v1/opendata/t187ap04_L>
- TPEx 上櫃公司每日重大訊息：<https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O>
- TWSE OpenAPI 規格：<https://openapi.twse.com.tw/v1/swagger.json>
- TPEx OpenAPI 規格：<https://www.tpex.org.tw/openapi/swagger.json>

---

## 13. 研究限制

1. **不同行業**：銀行、保險、證券等有各自編製準則與監理要求；本文的一般發行人欄位表不能取代業別 schema。
2. **歷史格式漂移**：審計公報改編為準則、報告格式與 KAM 適用範圍曾演進；長期資料必須依 period/version 解析。
3. **MOPS 非穩定公共 API 契約**：HTML／AJAX 表單可變、可能限流或出現安全頁；錯誤頁不可當「無資料」。
4. **報告標籤不足**：MOPS 共用的「無保留結論/意見」不能單獨區分查核與核閱，更不能涵蓋所有段落風險。
5. **PDF／OCR**：完整電子書可能有字型、跨頁表格或掃描問題；解析失敗須標 `parse_error`，不可默認無風險。
6. **查核不是舞弊保證**：合理確信不是絕對確信；核閱確信更低。沒有修正式意見不證明沒有舞弊、流動性問題或未來倒閉風險。[審計準則 700](https://www.ardf.org.tw/ardf/2025/700.pdf)／[核閱準則 2410](https://www.ardf.org.tw/ardf/2025/2410.pdf)
7. **PIT 證據缺口**：未從當時即封存原始報告與公告 timestamp 時，今日官方查詢不必然足以重建歷史可見版本；應誠實標示 `historical_as_seen_unproven`。
