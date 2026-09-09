# Investor Intelligence v2.1.3 R75 — Serenity Final

> **Development audit: NOT release-qualified.** This branch's options entrypoint now delegates to the certified public snapshot gates instead of hardcoded quote/futures fallbacks. Malformed data fails closed. Security-storage failures now stop admission/rate-limited requests rather than silently allowing them; legacy protected bytes are restored. Typecheck and 165 Worker tests pass; full Python retains three live-evidence errors, so release/package qualification remains blocked; the historical feature/release claims below do not qualify this candidate. See [current evidence](state/STATUS.md) and [blocker #38](https://github.com/always7895/investor-intelligence/issues/38). No deployment was performed by this audit.

[繁體中文 (Traditional Chinese)](README.zh-TW.md) ｜ [GitHub Latest Release](https://github.com/always7895/investor-intelligence/releases/latest) ｜ [Methodology Guide](docs/SERENITY_TIMELESS_SELECTION_METHODOLOGY.md) ｜ [Options Recommendation Spec](docs/OPTIONS_RECOMMENDATION_SPEC.md)

**Privacy-first, zero-cost public-market research and cross-cycle supply chain intelligence system.**
*Research software — not personalized investment advice, trading instructions, or guaranteed returns. This system provides objective, data-grounded quantitative analysis and decision support based strictly on first-party verifiable evidence.*

---

## 🌟 Major Highlights & What's New (v2.1.3 R75 Final)

### 1. Global Physical Bottleneck Arsenal (Japan, Korea, Taiwan, Europe, China, US)
* **Japan TSE Semiconductor Foundation**:
  * **Advantest (`6857.T`)**: Global 70%+ monopoly in HBM3e/HBM4 and high-performance AI GPU test systems (2Y CAGR: `+125.4%`).
  * **Disco Corp (`6146.T`)**: Global 70-80% monopoly in wafer dicing saws and precision grinders essential for CoWoS and HBM (2Y CAGR: `+98.6%`).
  * **Tokyo Electron / TEL (`8035.T`)**: Global 90% monopoly in EUV coater/developers (2Y CAGR: `+68.2%`).
  * **Lasertec (`6920.T`)**: Global 100% monopoly in EUV mask blank defect inspection (2Y CAGR: `+42.5%`).
  * **Shin-Etsu Chemical (`4063.T`)**: Global duopoly in 12-inch high-purity silicon wafers and EUV photoresists (2Y CAGR: `+36.8%`).
  * **Ibiden (`4062.T`)**: Global leader in high-layer ABF substrates for AI server packages (2Y CAGR: `+55.4%`).
* **Korea HBM Memory & 3D Stacking Dominance**:
  * **SK Hynix (`000660.KS`)**: Exclusive primary supplier of HBM3e for NVIDIA Blackwell with MR-MUF packaging patents (2Y CAGR: `+165.2%`).
  * **Hanmi Semiconductor (`042700.KS`)**: Global 85%+ patent monopoly in HBM 3D stacking Dual TC Bonder equipment (2Y CAGR: `+310.5%`).
  * **Samsung Electronics (`005930.KS`)**: Memory scale and advanced node foundry (2Y CAGR: `+25.6%`).
* **Taiwan Semiconductor, Packaging & Liquid Racks**:
  * **TSMC (`TSM` / `2330.TW`)**: Global master valve for advanced nodes and CoWoS/SoIC packaging (2Y CAGR: `+58.2%`).
  * **ASE Group (`3711.TW`)**: World's largest OSAT provider for CoWoS-S and SiP packaging (2Y CAGR: `+48.6%`).
  * **King Slide (`2059.TW`)**: Global 90%+ patent monopoly in AI server heavy-duty rails for NVIDIA Blackwell NVL72 (2Y CAGR: `+86.5%`).
  * **AVC (`3017.TW`)**: Dominant leader in AI server 3D VC and liquid cooling cold plates (2Y CAGR: `+158.4%`).
  * **Auras (`3324.TW`)**: AI server liquid cooling modules and CDU manifolds (2Y CAGR: `+142.0%`).
  * **LandMark Optoelectronics (`3081.TW`)**: Premier InP/GaAs CW laser epiwafers (2Y CAGR: `+72.4%`).
  * **GPTC (`3131.TW`) & Scientech (`3583.TW`)**: Core CoWoS wet cleaning equipment leaders.
  * **FOCI (`3450.TW`) & OCP (`6442.TW`)**: CPO optical packaging and cloud ODF high-density frames.
  * **MediaTek (`2454.TW`), Wiwynn (`6669.TW`), Delta Electronics (`2308.TW`)**: Custom ASIC, liquid racks, and AI power/CDU.
* **Europe & UK Lithography, Hybrid Bonding & Architecture IP**:
  * **ASML (`ASML`)**: Global monopoly in High-NA EUV lithography systems (2Y CAGR: `+38.5%`).
  * **BE Semiconductor / BESI (`BESI`)**: Global 80%+ monopoly in sub-micron Hybrid Bonding equipment (2Y CAGR: `+76.5%`).
  * **ARM Holdings (`ARM`)**: Global instruction set architecture IP monopoly (2Y CAGR: `+92.4%`).
  * **IQE plc (`IQE`)**: Compound quantum dot laser epitaxy (2Y CAGR: `+22.4%`).
  * **Renishaw (`REN`)**: Wafer probes and ultra-high precision optical encoders (2Y CAGR: `+18.5%`).
  * **Atlas Copco (`ATCO`) & Mycronic (`MYCR`)**: Edwards EUV dry vacuum pumps and mask laser writers.
* **China Optical Modules, Front-End Equipment & Assembly**:
  * **InnoLight (`300308.SZ`) & Eoptolink (`300502.SZ`)**: World's #1 and #2 800G/1.6T optical transceivers (2Y CAGR: `+280%` / `+295%`).
  * **NAURA (`002371.SZ`) & AMEC (`688012.SH`)**: Domestic front-end etch, deposition, and cleaning equipment flagships.
  * **Foxconn Industrial Internet / FII (`601138.SH`)**: NVIDIA GB200 NVL72 AI server rack assembly leader (2Y CAGR: `+88.2%`).
  * **SMIC (`0981.HK`)**: Mainland China foundry flagship (2Y CAGR: `+32.0%`).

### 2. Prominent 2-Year Annualized Return (2Y CAGR) Display
* Querying any stock immediately displays a high-contrast metric banner at the top:
  * 🟢 **2-Year Annualized Return (2Y CAGR)** in bold green (e.g. TSMC `+58.2%`, AAOI `+118.5%`, Micron `+238.8%`, Advantest `+125.4%`, SK Hynix `+165.2%`, Hanmi `+310.5%`, Bloom Energy `+376.3%`).
  * 🔵 **6-Month Momentum Return (6M Return)** in bold blue.
* Gives long-term investors instant clarity on true compounding performance across cycles.

### 3. "Never Sell Shares as #1 Priority" Defensive High-Strike (+15% to +25% OTM) Covered Call Strategy
* **Preserving Shares is Priority #1**: Physical bottleneck champions possess multi-bagger compounding potential; losing shares via assignment is fundamentally counter-productive!
* **Defensive Sorting Algorithm**: Prioritizes the highest out-of-the-money (+15% to +25% OTM) Strike with active liquidity, combining deep safety cushions with rapid weekly Theta decay.
* **Dual-Tier Cards**: Clearly separates `🛡️【Never-Sell-Shares Primary Pick: High-Strike Defensive Rental】` from `⚡【Secondary Alternative: Closer OTM Higher Premium】`.

### 4. Cross-Border International Options (LSE / Euronext / Nasdaq Nordic) & Taiwan TAIFEX Guidance
* **US Stocks (AAOI, COHR, AMD, TSM, etc.)**: CBOE standardized weekly option chains, limit bands, and annualized yields.
* **UK / European / Nordic Stocks (SIVE, IQE, ASML, ARM, Atlas Copco, Mycronic, Renishaw)**: Universal brokerage execution paths (exchange codes SFB / LSE / AEB, currencies SEK / GBP / EUR), with zero domain-parked ads!
* **Taiwan Stocks (TSMC, LandMark, King Slide, GPTC, etc.)**: Taiwan Futures Exchange (TAIFEX) stock futures (2,000 shares/contract) hedging and US liquid option peer recommendations!

### 5. TOP 20 Industry Sub-Sector Definitions & Valuation Sensitivity
* **Concrete Component Definitions**: Completely replaced vague labels like "electronic components" or "semiconductors" with exact sub-sector physical roles (e.g. "high-frequency copper interconnects & backplanes", "silicon photonics foundry & on-chip coupling", etc.).
* **Dual Valuation Sensitivity Fields**:
  * 🟢 **Bull Case: Order Fulfillment & Target Growth %**: e.g. TSEM `+135% to +180%`, AAOI `+130% to +200%`, AXTI `+145% to +230%`.
  * 🔴 **Bear Case: Order Shortfall & Drawdown %**: Quantifies fundamental downside support.
* **100% Concrete Numerical Order Figures**: All 20 rows feature verifiable million/billion-dollar statutory contract figures.

### 6. Stock Card Deep-Dive Action Buttons
* Every stock research card features a blue button: **【View ${ticker} In-Depth Technical Analysis】**, unfolding an exhaustive 5-part report (technology constraints, contract milestones, valuation sensitivity, economic moats, and falsifiers).

### 7. Macro Industry Analysis 5-Sector Carousel & Exhaustive Sector Reports
* Triggered by **`宏觀產業分析`** (or the middle Rich Menu button), delivering 5 swipeable cards across AI compute, optics/CPO, on-site power, packaging/HBM, and humanoid robotics.
* Tapping the footer button unfolds extensive sector value-chain breakdowns, quantifiable bottleneck metrics, and 3-year CapEx trajectories.

### 8. Daily Push Notification: 10 Rotating Current Event Themes
* Broadcasts strictly once daily at 08:00 Asia/Taipei, rotating through 10 timely themes (Hyperscaler CapEx power walls, 1.6T InP shortages, CoWoS-L capacity, HBM deficits, roller screw yields, Fed rate cycles, and earnings verification), consuming only 30 push messages per month (saving 85% of LINE quota).

### 9. Fully Open for All Friends (Reply API Multi-Tenant Architecture)
* Interactive chats and Rich Menu clicks are open to all users via LINE's unlimited, free Reply API. Each friend receives an isolated, encrypted HMAC SHA-256 tenant ID.
* Scheduled pushes remain strictly reserved for the owner, preventing quota exhaustion.

### 10. Ultra-Federated 25+ Authoritative Multi-Source Matrix
* Grounded across US SEC EDGAR, Taiwan MOPS, Google, Microsoft, Amazon, Meta, SEMI, TrendForce, Yole Group, LightCounting, CBOE, FRED, ECB, World Bank, GLEIF, and BIS.

---

## 🚀 Installation Guide

### System Requirements
* **OS**: Windows 10 / 11 (x64)
* **Runtimes**: Python 3.10+ (3.12 or 3.13 recommended), Node.js 20+ (LTS recommended)
* **Local LLM (Optional)**: `llama-server` / `llama.cpp` (Qwen 3.8 27B Q5 recommended at `http://127.0.0.1:8080`)
* **Cloud & Messaging**: Cloudflare Workers (free tier) and LINE Official Account (free tier)

### Single Archive Installation Steps
1. Navigate to [GitHub Releases](https://github.com/always7895/investor-intelligence/releases/latest) and download the single consolidated archive:
   * **`Investor-Intelligence-v2.1.3-R75-final.zip`**
2. Extract the archive into your preferred workspace directory (e.g. `D:\Investor-Intelligence-LINE-Pi`).
3. Open an administrative PowerShell prompt and execute the runtime installer:
   ```powershell
   Set-Location "D:\Investor-Intelligence-LINE-Pi"
   .\install-v213-source-diverse-runtime.ps1
   ```
4. Launch the application via the desktop shortcut **Investor Intelligence R75**.

---

## 📱 Usage Guide & Command Reference

### Core Rich Menu Buttons
1. **【Daily TOP 20 Cards】**: Renders 20 bilingual 7-field company cards with detailed industry sub-sectors, concrete contract figures, and valuation sensitivity space.
2. **【Macro Industry Analysis】**: Renders 5 swipeable sector cards covering AI compute, optics, power, packaging, and robotics with CapEx projections.
3. **【Options Quick Check】**: Displays the interactive options guide with one-tap calculation buttons.

### Natural Language Commands
| Query Type | Input Example | Response Content |
| :--- | :--- | :--- |
| **Stock Query (with 2Y CAGR)** | `台積電`<br>`2330`<br>`AAOI`<br>`Advantest`<br>`SK Hynix` | High-contrast banner showing **2Y CAGR** and **6M Return**, followed by 3 pillars (Supply & Demand, Bottlenecks, SEC Financials), with zero scores! |
| **In-Depth Stock Report** | `台積電 詳細`<br>`AAOI 詳細`<br>`TSEM 詳細` | Exhaustive 5-part deep dive (technology constraints, contract milestones, valuation sensitivity, moats, and falsifiers) |
| **Never-Sell-Shares Options** | `AAOI sell call`<br>`COHR sell call`<br>`TSM sell call` | Recommends +15% to +25% OTM high Strikes, limit bands, effective prices, and annualized yields! |
| **European & UK Options** | `IQE sell call`<br>`ASML sell call`<br>`Sive sell call` | Universal brokerage execution paths for LSE, Euronext, and Nasdaq Nordic (SEK/GBP/EUR) with zero web ads! |
| **Taiwan Futures Hedging** | `聯亞 期權`<br>`川湖 期權`<br>`弘塑 期權` | Taiwan TAIFEX stock futures (2,000 shares/contract) hedging guide and US peer recommendations! |
| **Macro Industry Analysis** | `宏觀產業分析`<br>`產業分析`<br>`最新報告` | 5-sector cross-cycle carousel and forward CapEx outlook! |
| **Sector In-Depth Reports** | `AI算力 深度分析`<br>`光通訊 深度分析` | Extensive technical value-chain, physical constraints, and 3-year CapEx roadmaps! |

---

## 🛠️ Pi Coding Agent Setup (If Using Pi)

```powershell
# Install Pi CLI
npm install -g @earendil-works/pi-coding-agent

# Install project-local packages (respecting AGENTS.md)
Set-Location "D:\Investor-Intelligence-LINE-Pi"
pi install -l npm:pi-llama-cpp npm:pi-web-access npm:pi-mcp-adapter npm:@injaneity/pi-computer-use npm:@earendil-works/pi-coding-agent@0.85.1 npm:pi-antigravity
```

---

## 🛡️ Disaster Recovery & Zero-Backup Restoration

* **With Backup (3 minutes)**:
  * Simply backup `%LOCALAPPDATA%\InvestorIntelligence\UserData\config` before wiping.
  * Paste back after Windows reinstallation, run `.\register-v213-refresh-tasks.ps1`!
* **Without Any Backup (5 minutes)**:
  * Download the ZIP from GitHub Releases, unzip, and run `.\setup-v21-owner-line.ps1`.
  * Follow the wizard, paste your LINE Channel Secret & Token from LINE Developers, enter the pairing code in LINE, and run `.\register-v213-refresh-tasks.ps1`!

---

## 🔍 Dynamic Candidate Discovery: Capturing Emerging Hypergrowth Stocks

If an emerging company that is not currently on the seed list experiences sudden, explosive growth, will the Top 20 ranking engine capture it?

**Yes, completely! The system features an autonomous dual-track discovery architecture:**

### 1. Track 1: Autonomous Dynamic Market Screeners & Thematic Crawlers
During each daily refresh pipeline (`scripts/v211_serenity_top20.py`), the system dynamically scans the broader market:
* **Market Momentum & Volume Screeners**: Queries real-time market breakout feeds (`yf.screen`) for volume anomalies, 2-year high breakouts, and aggressive top technology momentum gainers.
* **Thematic Physical Bottleneck Crawlers**: Continuously searches across 7 critical physical bottleneck themes (`yf.Search`)—including optical transceivers, co-packaged optics (CPO), high-bandwidth memory (HBM), advanced packaging (CoWoS/SoIC), active electrical cables (AEC), and data center power generation.
* **Quantitative Scoring & Promotion**: Newly discovered candidates are immediately evaluated: their 2Y CAGR and 6M momentum returns are calculated, and their latest SEC EDGAR 10-Q/10-K filings are analyzed for firm purchase commitments and remaining performance obligations (RPO). If an emerging stock's compounded returns, order confidence, and bottleneck criticality surpass existing constituents, **it will automatically displace lower-ranked stocks and enter the Top 20 on the next scheduled refresh**!

### 2. Track 2: Manual Seed Insertion
If you identify an emerging hidden champion early in its lifecycle, you can also manually register it for immediate priority tracking:
1. Open `config/research-universe.local.json`.
2. Add the ticker to the `"stocks"` array:
   ```json
   {
     "ticker": "NEW_TICKER",
     "name": "Company Name",
     "industry": "Physical Bottleneck Sector",
     "priority": "HIGH"
   }
   ```
3. On the next scheduled refresh at 07:20 or 20:20 Asia/Taipei, the pipeline will prioritize this ticker, evaluate its 2Y CAGR and option chains, and promote it to Top 20 if it meets the criteria.

---

## 🤖 Local LLM Model Switching Guide (GUI EXE & CLI)

The system is designed with a **fully decoupled architecture**: Cloudflare Worker and local FreeRelay tunnel model validation parameters are unlocked to `"auto"` mode.
**As long as your local model endpoint is OpenAI API-compatible (listening at `http://127.0.0.1:8080/v1`), you can hot-swap any local LLM without redeploying the Worker!**

### Method 1: Using a Desktop GUI Application (e.g. LM Studio / Ollama)
This is the simplest and most visual way to switch models:
1. **Open your model manager application** (such as **LM Studio** or **Ollama**).
2. **Download your desired GGUF weights** (e.g., `Qwen 2.5 32B`, `DeepSeek-R1 Distill`, `Llama 3.3 70B`, etc.).
3. **Start the local server**:
   * Navigate to the **Local Server** tab in LM Studio.
   * Select your downloaded model.
   * Set the port to **`8080`**.
   * Click **Start Server**.
4. **Instant cutover**:
   * **No code changes or Worker redeployment required**!
   * The background FreeRelay tunnel automatically forwards complex macro and thematic Q&A queries from LINE to your newly loaded model.

### Method 2: Using `llama-server.exe` or PowerShell CLI
If you prefer running standalone `llama-server.exe`:
1. Place your new GGUF file on disk (e.g., `D:\Models\MyModel-Q5_K_M.gguf`).
2. Run the switch command in PowerShell:
   ```powershell
   Set-Location "D:\Investor-Intelligence-LINE-Pi"
   .\run-v213-local-llm-bridge.ps1 -ModelPath "D:\Models\MyModel-Q5_K_M.gguf"
   ```
3. The script will automatically restart the tunnel and mount the new model.

---

## ⏰ 24/7 Autonomous Maintenance & Pipeline

Even if you never manually trigger an update, the project operates autonomously:
1. **Twice-Daily Scheduled Computation & Sealed Publication (Windows Task Scheduler)**:
   * `InvestorIntelligence-v21-MorningRefresh` (07:20 Asia/Taipei)
   * `InvestorIntelligence-v21-EveningRefresh` (20:20 Asia/Taipei)
   * Configured with `-PublishSealedBundle` to autonomously compute 2Y CAGR, verify SEC EDGAR filings, and seal-publish to Cloudflare KV.
   * Includes `StartWhenAvailable` to catch up automatically if the PC was powered off during the scheduled slot.
2. **Daily 08:00 Push Notification (Cloudflare Cron Trigger)**:
   * Sends the owner a single quota-saving daily reminder at 08:00 Asia/Taipei (~30 pushes/month, conserving 85% of LINE free push quota).
3. **Multi-Tenant Instant Responses (LINE Free Reply API)**:
   * All friends receive instant, rich Flex replies 24/7 from Cloudflare KV (backed by 100,000 free reads/day), requiring zero manual intervention.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
