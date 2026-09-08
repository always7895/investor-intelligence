# Investor Intelligence v2.1.3 R75 — Serenity Final

[繁體中文 (Traditional Chinese)](README.zh-TW.md) ｜ [GitHub Latest Release](https://github.com/always7895/investor-intelligence/releases/latest) ｜ [Methodology Guide](docs/SERENITY_TIMELESS_SELECTION_METHODOLOGY.md) ｜ [Options Recommendation Spec](docs/OPTIONS_RECOMMENDATION_SPEC.md)

**Privacy-first, zero-cost public-market research and cross-cycle supply chain intelligence system.**
*Research software — not personalized investment advice, trading instructions, or guaranteed returns. This system provides objective, data-grounded quantitative analysis and decision support based strictly on first-party verifiable evidence.*

---

## 🌟 Major Highlights & What's New (v2.1.3 R75 Final)

### 1. Cross-Cycle Physical Bottleneck Selection (Serenity Methodology)
* **Beyond Rigid Sector Buckets**: Operationalizes Serenity's (@aleabitoreddit) physical constraint layer framework. Dynamically identifies structural transition demand waves: optical co-packaging (CPO/CW lasers/InP substrates), advanced packaging (CoWoS/SoIC), memory supercycles (HBM/niche DRAM), on-site datacenter power generation (SOFC/SMR/microgrids), and humanoid robotics precision mechanical actuation (planetary roller screws / frameless motors).
* **100% First-Party Contract Evidence**: All 20 tracked symbols are **100% backed by statutory SEC disclosures (RPO / Backlog) or official multi-year customer agreements** (e.g. TSEM $1.3B contracts / $290M prepayments, COHR multibillion-dollar NVIDIA agreement, AXTI Lumentum/Coherent capacity reservation deposits). Zero "undisclosed" placeholders.

### 2. Macro Industry Review (Latest Report Overhaul)
* **Eliminates Redundancy**: Individual 7-field company cards are dedicated to the `TOP20` Rich Menu. The **"Latest Report" is completely elevated to macro cross-cycle reviews across 5 core sectors**:
  1. 🤖 **AI Compute & Scale-Out Networking** (inference demand, power walls, cloud hyperscaler CapEx exceeding $350B)
  2. ⚡ **Optical Interconnect, CPO & Silicon Photonics** (800G/1.6T transitions, InP substrate and CW laser capacity deficit of 40-60%)
  3. 🔋 **AI Datacenter Power & On-Site Generation** (4-7 year grid interconnection queue, 15-year SOFC / SMR PPA visibility)
  4. 📦 **Advanced Packaging & High-Bandwidth Memory** (CoWoS tightness, HBM allocations locked through 2027, mature DRAM displacement)
  5. 🦾 **Humanoid Robotics & Actuation Mechanics** (2026-2027 pilot scale, precision grinding yield constraints on roller screws)
* **Forward CapEx & Revenue Outlook**: Every sector features concrete forward capital expenditure projections and revenue visibility metrics.

### 3. Arbitrary Option Ticker Support (Unrestricted Lookups)
* **No Pinned Symbols**: Freely query ANY US stock symbol paired with options keywords (e.g. `AAOI sell call`, `AXTI weekly options`, `COHR options`, `AMD sell call`, `MU monthly options`, `TSM options`).
* **High-Precision Limit & Yield Analytics**: Automatically calculates Strike K (% OTM), real-time Bid/Ask/Mid, **Recommended Limit Order Bands**, effective sale prices, break-even points, implied volatility (IV), annualized yields (Mid % / Bid %), and liquidity verification (PASS / Observe).
* **Objective International Guidance**: For non-optionable small caps or non-US listings (e.g. Sivers Semiconductors on Stockholm First North, ESMT on Taiwan TWSE, IQE on London LSE), the system provides factual market listing context, advises equity-only positioning, and routes users to liquid optical supply chain peers.

### 4. Once-Daily Quota-Saving Push & Dynamic Content Engine
* **Extreme Quota Conservation**: Broadcasts strictly **ONCE per day at 08:00 Asia/Taipei (00:00 UTC)**. Evening pushes are turned off, consuming only 30 push messages per month (conserving 85% of LINE's 200 free monthly quota).
* **Dynamic Non-Repeating Text**: Dynamically weaves in current Taipei calendar dates, weekday-specific tactical commentary (Monday opening through Sunday review), top 3 leading bottlenecks, top momentum gainer, and rotating daily contract spotlights.
* **Zero-Cost Rich Menu Inquiries**: User inquiries through the LINE Rich Menu utilize the unlimited, 100% free LINE Reply API, consuming zero push quota.

### 5. Standardized Unified UI/UX Presentation
* "Latest Report", Options Limit Observation, and Top20 cards share an identical, polished UI/UX template with clean emojis, card hierarchies, divider lines, and risk control reminders. All internal debug HTML comments are stripped.

### 6. Dynamic Model Discovery & Dual-Track GPU Failover
* **Dynamic Model Discovery**: Removed rigid model ID locks; automatically binds whatever model is loaded into the Router (`http://127.0.0.1:8080`).
* **Zero-Downtime Fallback**: If local GPU slot 0 is occupied by other local tasks, the system automatically serves authoritative audited snapshot facts without dead-end offline errors.

### 7. Multi-Source Federation Expanded to Google & Global Standards
* Expanded authoritative sources to include **Google (Google Finance / Google Cloud Datacenter / Alphabet 10-K CapEx filings)**, US SEC EDGAR, Nasdaq Official Directory, Chicago Board Options Exchange (CBOE), Taiwan MOPS, SEMI, TrendForce, ECB, World Bank, and GLEIF.

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
4. (Optional) If deploying or modifying Cloudflare Workers:
   ```powershell
   Set-Location "D:\Investor-Intelligence-LINE-Pi\cloud"
   npm ci --ignore-scripts --no-audit --no-fund
   ```
5. Launch the application via the desktop shortcut **Investor Intelligence R75**.

---

## 📱 Usage Guide & Command Reference

### Core Rich Menu Buttons
1. **【Daily TOP 20 Cards】**: Immediately renders 20 bilingual 7-field company cards detailing long-term 2Y annualized returns, short-term 6M returns, current orders, future outlook, and statutory contract amounts.
2. **【Market & Latest Report】**: Renders the Traditional Chinese macro cross-cycle review across AI compute, optics, power, packaging, and robotics with CapEx projections.
3. **【Stock & Options Quick Check】**: Displays quick query instructions for option chains and limit bands.

### Natural Language Commands (Supports Any Symbol)
| Query Type | Input Example | Response Content |
| :--- | :--- | :--- |
| **Covered Call (Sell Call)** | `AAOI sell call`<br>`COHR sell call`<br>`AMD sell call` | 7-15% OTM Strike, real-time Bid/Ask/Mid, **Recommended Limit Band**, effective price, annualized yield, liquidity PASS |
| **Weekly Options** | `AXTI weekly options`<br>`NVDA weekly`<br>`BE options` | Expiration date (DTE), Call/Put limit bands, IV, Delta |
| **Monthly Options** | `MU monthly options`<br>`TSM options`<br>`TSEM options` | Monthly Strike distribution, break-even price, limit bands |
| **Physical Bottleneck Research** | `SIVE`<br>`AXTI`<br>`3006.TW`<br>`COHR` | Fab expansions, customer production orders, prepayment contracts, and dilution risks |
| **Macro Industry Report** | `最新報告`<br>`大盤報告`<br>`早報` | 5-sector physical constraint analysis, hyperscaler CapEx outlook, revenue visibility, and guardrails |
| **Full Top 20 Text** | `TOP20`<br>`Top20 文字` | Complete 20-company sequential text report with all contract details |

---

## 🛠️ Pi (Coding Agent) Extension & Configuration Guide

If you utilize the [Pi Coding Agent](https://github.com/earendil-works/pi-coding-agent) to maintain, develop, or extend this repository, please adhere to the project's engineering contract (`AGENTS.md`) by **installing packages project-locally (`pi install -l`) and never globally**:

### 1. Install Pi CLI
```powershell
npm install -g @earendil-works/pi-coding-agent
```

### 2. Install Project-Local Pi Packages
From the repository root:
```powershell
Set-Location "D:\Investor-Intelligence-LINE-Pi"

pi install -l npm:pi-llama-cpp npm:pi-web-access npm:pi-mcp-adapter npm:@injaneity/pi-computer-use npm:@earendil-works/pi-coding-agent@0.85.1 npm:pi-antigravity
```

#### Package Descriptions:
* **`npm:pi-llama-cpp`**: Local llama-server / Router integration (`http://127.0.0.1:8080`) for zero-cost, private local LLM inference.
* **`npm:pi-web-access`**: Multi-angle web search and research report content extraction.
* **`npm:pi-mcp-adapter`**: Model Context Protocol (MCP) tool chaining and execution.
* **`npm:@injaneity/pi-computer-use`**: Desktop UI observation and testing tools.
* **`npm:@earendil-works/pi-coding-agent@0.85.1`**: Core Pi agent SDK runtime.
* **`npm:pi-antigravity`**: Antigravity OAuth and image tooling.

### 3. `.pi/settings.json` Configuration
The project is pre-configured with `.pi/settings.json`:
```json
{
  "packages": [
    "npm:pi-llama-cpp",
    "npm:pi-web-access",
    "npm:pi-mcp-adapter",
    "npm:@injaneity/pi-computer-use",
    "npm:@earendil-works/pi-coding-agent@0.85.1",
    "npm:pi-antigravity"
  ],
  "llamaServerUrl": "http://127.0.0.1:8080",
  "defaultProvider": "llama.cpp",
  "defaultModel": "auto",
  "skills": [
    "skills/serenity-public-research"
  ],
  "enableSkillCommands": true,
  "defaultThinkingLevel": "xhigh",
  "defaultTools": [
    "read",
    "powershell",
    "bash",
    "edit",
    "write",
    "grep",
    "find",
    "ls"
  ]
}
```

### 4. Built-In Skill
* **`skills/serenity-public-research`**: Automatically loaded by Pi when working in this repository. Guides public Serenity supply chain research, constraint layer mapping, and contract evidence validation.

---

## 🛡️ Security, Privacy & Risk Boundaries

1. **Strict Privacy & Broker Separation**:
   * Read-only public-market research tool. **Never connects to brokerage execution APIs, and never accesses or stores private credentials, portfolios, or account balances.**
2. **Fail-Closed Verification Gates**:
   * If public data exceeds the 24-hour freshness gate (86,400s), the system refuses to guess numbers, preventing outdated quote misguidance.
3. **Zero-Cost Architecture**:
   * Cloudflare Workers Free Tier (100,000 requests/day)
   * LINE Official Account Free Tier (200 push messages/month; unlimited free interactive replies)
   * Local Llama-server / Qwen 27B (0 API token cost)

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
