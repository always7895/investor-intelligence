# Investor Intelligence v2.1.3 — Serenity 公開邏輯與相關專案稽核

本文件記錄本專案如何吸收公開專案的工程優點，同時維持來源、授權與方法定位邊界。

## 方法定位

本專案只做 **Serenity 公開邏輯高保真重建**，不宣稱取得私人方法、不宣稱官方公式或官方分數，也不把外部專案的自述績效當成投資事實。方法論參考，不是公司證據；不能滿足任何公司的證據門檻。

## 採納的共同優點

- 先排稀缺產業鏈層級，再排公司；避免直接從熱門 ticker 出發。
- 先建立廣泛候選宇宙，再以瓶頸、認證、產能、公司捕捉與風險縮小範圍。
- 區分 forward thesis、reaffirmation、supplier map、retrospective victory lap。
- 使用 evidence ladder：監管／交易所／公司正式揭露優先，產業媒體交叉驗證，社群只作線索。
- 明確列出反證、thesis killers、融資／稀釋、客戶集中、架構繞過與產能解除風險。
- 保留來源 URL、發布／截至日期與檢索狀態，檢索時間不得取代發布時間。
- 角色分離：蒐證、正向論點、反證、風險與發布 gate 不由同一個推論直接放行。

## 最終候選的兩種證據模式

### EVIDENCE_QUALIFIED

公司或投資論點至少有兩個獨立 claim family、兩個獨立網域與一個第一手來源。任何正向 Serenity 優勢另需新鮮第一手來源及獨立營運的非第一手佐證。

### LIMITED_RESEARCH_CANDIDATE

若獨立公司主張仍不足，所有 demand wave、chokepoint、pricing power、replacement friction、TAM capture 正向分數必須先歸零。該股票只可作研究候選，並須具備最新可取得的第一手公司來源與另一個新鮮受監管身分來源。它不是已驗證 thesis、不得進入高信心模型推論，亦不得用身分資料證明公司優勢。

## 市場與最新資料

- Yahoo／yfinance 僅維持 adjusted-close 相容性計算。
- 高信心至少需要兩個新鮮、可比較且獨立營運的市場 provider。
- 不同 adjustment basis 不直接比較。
- 市場來源採 pairwise conflict，Yahoo 不是真值錨點。
- 過期或未標日期的 LIVE/CACHED 資料從覆蓋率排除。
- 衝突資料保留，不平均成單一答案。
- 公司 current-state、結構性資料與宏觀資料使用不同時效門檻。

## 受審查的方法論參考

- `yan-labs/serenity-aleabitoreddit`：採納刷新後再使用、上游多跳供應鏈映射、融資與客戶集中、訊號新舊區分。
- `muxuuu/serenity-skill`：採納先排名稀缺層級、建立廣泛候選宇宙、證據階梯與反證清單。
- `quantskills/skill-serenity-research-model`：採納資料契約、來源 URL／日期保留、前瞻訊號與回顧貼文分離。

以上只採納一般化工程與研究模式，不複製其程式碼；方法論參考，不是公司證據，也不定義 Serenity 官方公式。

完整 commit pin 與採納邊界見 `config/v213-serenity-methodology-reference-pins.json`。
