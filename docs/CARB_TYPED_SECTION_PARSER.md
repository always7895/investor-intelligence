# CARB 氣體絕緣設備逐步淘汰法規段落類型化解析規範 / CARB Typed Section Parser Specification

## 1. 目的與權限邊界 / Purpose and Authority Boundaries

本規範定義加州空氣資源委員會（CARB）氣體絕緣設備（Gas-Insulated Equipment, GIE）六氟化硫（$\text{SF}_6$）逐步淘汰法規之類型化封閉段落解析器（`scripts/carb_typed_section_parser.py`）。

### 核心信任與權利邊界（不可突破）：
1. **非准入狀態（Non-Admitting）：** 解析器輸出狀態嚴格鎖定為 `NON_ADMITTING_REGULATORY_TEXT_PARSE`。
2. **零錄取與零准入（Zero Admissions）：** `runtime_admitted` 恆為 `false`；`company_admissions` 恆為 `0`；`source_admissions` 恆為 `0`。
3. **無法律權利授予（No Legal Rights Conferred）：** 解析器處理官方保留文字，不代表授予公開重發布、商業分發或法律授權；`rights_conferred` 恆為 `false`。
4. **四核心門檻全數不具資格（Four Core Gates Unqualified）：** 系統瓶頸四核心要素（`dependency`, `scarcity`, `pricing`, `capture`）維持 `UNQUALIFIED`，解析器絕不對任何公司（如 Meidensha 或 Siemens）賦予要素評分或市場權威資格。
5. **版本鎖定與檢索時鐘限制：** 解析器僅識別所提供法定文本版本（CCR Title 17 §§ 95350–95359.1 之 49 頁 PDF 文本抽取物），不保證為檢索當下時鐘之現行有效法規。實際語意解讀仍需審查。

---

## 2. 法定來源依據與文字特徵 / Statutory Authority and Source Corpus

- **法規依據：** 加州法規彙編第 17 篇第 3 分部第 1 章第 10 次章第 4 條第 3.1 目（California Code of Regulations, Title 17, Division 3, Chapter 1, Subchapter 10, Article 4, Subarticle 3.1, §§ 95350–95359.1）。
- **保留文本：** `audit-runtime/gemini-executor-20260914/meiden-independent-public-v1/carb-final-regulation.md`
- **抽取文本雜湊：** SHA-256 `16001e51c3c1258670058c0790b882e0660261498eea948b87e967bff5bbf55c`（103,044 位元組）。註：原始 PDF 雜湊未經審查驗證，文本 SHA-256 僅代表保留 Markdown 文本本體。

---

## 3. 表格結構與分類邊界 / Table Structures and Boundary Invariants

法規 § 95352 建立兩個獨立、互斥且具備不同分類維度之淘汰時程表：

### 3.1 表 1：電壓容量 $\le 38\text{ kV}$（含配置維度）
| 序號 | 配置（Configuration） | 電壓容量（Voltage Capacity） | 短路電流容量（kA） | 淘汰生效日（Phase-Out Date） |
|---|---|---|---|---|
| T1-R1 | 地上（Aboveground） | $< 38\text{ kV}$ | 全部（All） | 2025-01-01 |
| T1-R2 | 地上（Aboveground） | $== 38\text{ kV}$ | 全部（All） | 2028-01-01 |
| T1-R3 | 地下（Belowground） | $\le 38\text{ kV}$ | $< 25\text{ kA}$ | 2025-01-01 |
| T1-R4 | 地下（Belowground） | $\le 38\text{ kV}$ | $\ge 25\text{ kA}$ | 2031-01-01 |

### 3.2 表 2：電壓容量 $> 38\text{ kV}$（無配置維度）
| 序號 | 電壓容量（Voltage Capacity） | 短路電流容量（kA） | 淘汰生效日（Phase-Out Date） |
|---|---|---|---|
| T2-R1 | $38 < \text{kV} \le 145$ | $< 63\text{ kA}$ | 2025-01-01 |
| T2-R2 | $38 < \text{kV} \le 145$ | $\ge 63\text{ kA}$ | 2028-01-01 |
| T2-R3 | $145 < \text{kV} \le 245$ | $< 63\text{ kA}$ | 2027-01-01 |
| T2-R4 | $145 < \text{kV} \le 245$ | $\ge 63\text{ kA}$ | 2031-01-01 |
| T2-R5 | $> 245\text{ kV}$ | 全部（All） | 2033-01-01 |

### 3.3 臨界邊界值相等歸屬法則（Boundary Value Equality）
1. **$38\text{ kV}$ 等號歸屬：** $38.0\text{ kV}$ 嚴格屬於表 1（$\le 38\text{ kV}$），絕不落入表 2（表 2 範圍為 $38 < \text{kV}$）。
2. **$145\text{ kV}$ 等號歸屬：** $145.0\text{ kV}$ 嚴格屬於 $38 < \text{kV} \le 145$，絕不落入 $145 < \text{kV} \le 245$。
3. **$245\text{ kV}$ 等號歸屬：** $245.0\text{ kV}$ 嚴格屬於 $145 < \text{kV} \le 245$，絕不落入 $> 245\text{ kV}$。
4. **$25\text{ kA}$ 等號歸屬：** 地下設備 $25.0\text{ kA}$ 屬於 $\ge 25\text{ kA}$（2031-01-01），而非 $< 25\text{ kA}$。
5. **$63\text{ kA}$ 等號歸屬：** 高壓設備 $63.0\text{ kA}$ 屬於 $\ge 63\text{ kA}$（2028-01-01 或 2031-01-01），而非 $< 63\text{ kA}$。

---

## 4. 日期、定義與行為區分 / Dates, Definitions, and Anti-Inference

### 4.1 法律日期嚴格區分
- **取得限制日（Acquisition Applicability / Phase-Out Date）：** 各類別設備自指定日期（如 2025-01-01、2028-01-01 等）起不得為在加州境內使用而「取得（Acquire）」。
- **法規公布／生效日（Promulgation / Effective Date）：** 法規令本身的生效時間，與分階段的設備取得淘汰日截然不同，不得混淆。
- **購買合約日 vs 取得日 vs 啟用安裝日：**
  - 「購買（Purchase）」：買賣雙方簽署具法律約束力之合約（§ 95351(a)(12)）。
  - 「取得（Acquire）」：取得所有權、實際占有或租賃（§ 95351(a)）。
  - 「啟用安裝（Activation / Active GIE）」：連接至電網或注氣完成備妥運轉（§ 95351(a)(1)）。
  - 法規明訂豁免條件：在淘汰生效日前已簽約購買之設備，若在購買後 24 個月內進入加州，仍屬合法取得（§ 95352(a)(3)），安裝日期則不受限。

### 4.2 非一刀切禁令（No Blanket Ban）
- CARB 法規絕非「2025 年全球全面禁用 $\text{SF}_6$」或「僅限乾空氣技術（dry-air only）」。法規為加州境內、依電壓與短路容量自 2025 年至 2033 年分段逐步淘汰。

### 4.3 防推論與型別安全守則
- **禁止由型號推論容量：** 絕不允許從設備型號（如 "8VN1"）自動推論短路電流容量（kA）。必須具有明確數值輸入。
- **拒絕型別混淆：** 數值輸入必須為有限正實數（`float` 或 `int`），嚴格拒絕 `bool`（防止 Python 自動轉型為 1）、`NaN`、`Infinity` 及字串單位混淆。

---

## 5. 例外條款與外部交互參照 / Exceptions and Cross-References

### 5.1 法定例外與但書
1. **§ 95352(a)(1) 行政專員核准豁免或故障應急：** 依 § 95357 申請，且用途嚴格受限。
2. **§ 95352(a)(2) 既存設備：** 於淘汰日前已在加州且向 CARB 完成年報申報者。
3. **§ 95352(a)(3) 淘汰日前已採購並於 24 個月內運抵：** 區分採購日與入境加州日。
4. **§ 95352(a)(4) 原廠保固瑕疵換貨：** 替換不良品。
5. **§ 95352(b) 禁止改裝：** 淘汰日起嚴禁將非 $\text{SF}_6$ 設備改裝為 $\text{SF}_6$。
6. **§ 95352(c) 零組件排除：** 替換零件（replacement parts）不受表 1、表 2 淘汰日期限制。

### 5.2 外部交互參照（UNRESOLVED_OUTSIDE_CORPUS 與 StatutoryCitation 結構）
所有 7 項外部法定與標準引用均透過不可變 `StatutoryCitation` 資料結構類型化封閉管理，嚴格標記為未解析，限制解讀完整性：
- **封閉分類體系（ReferenceClass）：** 嚴格區分 `HealthSafetyCode` (3)、`40CFR` (1)、`17CCR` (2)、`consensusstandards` (1)，以及例外兜底 `OTHER` / `UNPARSEABLE`。
- **不可變記錄（StatutoryCitation）：** 欄位包含 `citation_id`、`reference_class`、`statutory_body`、`title`、`section`、`source_anchor`、`span` (含起始、長度、SHA-256 雜湊)、`unresolved_outside_corpus: true`、`limits_complete_interpretation: true`、`status: "UNRESOLVED_OUTSIDE_CORPUS"`。
- **保留文字精確錨定（Actual Retained Anchors）：**
  1. `EXT-REF-1` (`HealthSafetyCode`): 加州健康與安全法第 38510, 38560, 38580, 39600, 39601 條（法規授權依據）。
  2. `EXT-REF-2` (`HealthSafetyCode`): 加州健康與安全法第 39047 條（「人」之定義）。
  3. `EXT-REF-3` (`HealthSafetyCode`): 加州健康與安全法第 41513 條（禁制令執法依據）。
  4. `EXT-REF-4` (`40CFR`): 聯邦法規第 40 篇第 98 部分附表 A-1（全球暖化潛勢 GWP 納入參照）。
  5. `EXT-REF-5` (`17CCR`): 加州法規彙編第 17 篇第 95100 條等及第 95104(e) 條（Cal e-GGRT 申報系統）。
  6. `EXT-REF-6` (`17CCR`): 加州法規彙編第 17 篇第 91000–91022 條（機密資訊處理程序）。
  7. `EXT-REF-7` (`consensusstandards`): NIST 及量秤／流量計產業共識標準（ISWM、NCWM 校準方法）。
- **反推論限制：** 絕不從記憶或外部推論法條實質內容、生效版本或現行性；非准入狀態維持不變。

---

## 6. CLI 介面與安全性規範 / CLI Interface and Security Invariants

### 6.1 CLI 調用方式
```bash
python scripts/carb_typed_section_parser.py --input <path_to_markdown> --output <path_to_output_json>
```

### 6.2 安全與隱私保護
1. **獨占建立（O_CREAT | O_EXCL）：** 輸出檔案必須以排他模式建立，若目標檔案已存在則立即拒絕，防止 TOCTOU 覆寫風險。
2. **序列化先行：** JSON 在記憶體中序列化完成後方才開啟並寫入輸出檔案。
3. **靜態錯誤碼（Zero Diagnostics Leakage）：** 發生錯誤時僅輸出靜態代碼（如 `ERR_INPUT_FILE_NOT_FOUND`, `ERR_TABLE_MISSING`, `ERR_OUTPUT_ALREADY_EXISTS`），絕不回顯內部路徑、使用者輸入或堆疊追蹤。
