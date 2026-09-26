# Leopold Aschenbrenner — context model (CONTEXT_ONLY)

Auxiliary hypothesis layer. It never adds score, never restricts the discovery universe to AI and never counts as company evidence or as a second witness for a Serenity view. Essay figures are 2024 scenarios; fund filings are delayed, partial disclosures, not endorsements or current holdings. Project-authored interpretation is labelled INFERENCE.

## Contents

- 1. The essay's causal chain (primary, 2024)
- 2. Testable variables and falsifiers (project-authored)
- 3. Two-year scorecard (secondary, verify before citing)
- 4. Revealed preferences in SEC filings (primary, dated snapshot)
- 5. How research may use this layer
- Sources

## 1. The essay's causal chain (primary, 2024)

*Situational Awareness: The Decade Ahead* (June 2024) is a chain of quantitative extrapolations followed by a political argument. Keep the links separate; a failure in one link does not validate or refute the others.

1. **Effective compute** grows from three sources ("counting the OOMs"): physical training compute "~0.5 OOMs/year"; algorithmic efficiency "~0.5 OOMs/year"; and "unhobbling" (RLHF made a small model equivalent to a ">100x larger" one; chain-of-thought is ">10x effective compute" on reasoning; scaffolding lets GPT-3.5 beat un-scaffolded GPT-4 on coding).
2. **2023→2027:** "another ~100,000x effective compute scaleup" — physical ~2–3 OOMs, algorithmic ~1–3 OOMs (best guess ~2) plus unhobbling — i.e. "another GPT-2-to-GPT-4-sized qualitative jump", making models that "do the work of an AI researcher/engineer" plausible. Stated risks: the data wall, unhobbling stalling at "expert chatbots", trendlines breaking; "the error bars are large".
3. **Training clusters** (essay table): ~2022 ~10k H100-eq, ~10 MW; ~2024 ~100k, ~100 MW; ~2026 ~1M, ~1 GW, "$10s of billions"; ~2028 ~10M, ~10 GW, "$100s of billions"; ~2030 ~100M, ~100 GW, "$1T+", ">20% US electricity".
4. **Total AI investment** (essay table): 2024 ~$150B, 1–2% of US power, 5–10% of TSMC leading edge; ~2026 ~$500B, 5%, ~25%; ~2028 ~$2T, 20%, ~100%; ~2030 ~$8T, 100%, 4x capacity. "These are just very rough numbers anyway."
5. **Binding constraints, in order:** power ("Power has become the binding constraint"; US generation "barely grown 5% in the last decade"; Marcellus/Utica gas ~36 bcf/day ≈ "just under 150GW"; permitting, utility/FERC regulation and NEPA as delay); then CoWoS advanced packaging and HBM ("the primary constraint on churning out more GPUs"); then fabs, memory, packaging and networking capex. Capital is expected to follow revenue, with uncertain diffusion lags.
6. **Political layer:** lab security, a US–China race, a government "Project", alliances and export controls. These are coalition-dependent predictions, unlike the physical extrapolations above.

## 2. Testable variables and falsifiers (project-authored)

Each variable needs current primary evidence; the essay value is only the hypothesis. Macro or aggregate data never satisfies company-order evidence.

| Variable | Essay expectation | Primary evidence to check | Weakens the hypothesis |
| --- | --- | --- | --- |
| Frontier campus power | ~1 GW (2026), ~10 GW (2028) | Operator filings, utility interconnection agreements, permits | Announced GW not energized; distributed training removes single-site need |
| AI capex | ~$500B (2026), ~$2T (2028) | Hyperscaler 10-K/10-Q capex and guidance, neocloud financing | Capex cuts, financing stress, utilization falling |
| Power equipment | Lead times bind | Turbine, transformer, switchgear backlog and delivery disclosures | Lead times shorten, backlog cancellations |
| On-site / behind-the-meter gas | Fastest route | Gas-plant orders, pipeline and air permits | Permitting blocks, grid supply catches up |
| Packaging and memory | CoWoS and HBM bind GPU output | TSMC, Micron, SK hynix, Samsung capacity and pricing statements | Capacity additions outpace demand; price declines |
| Algorithmic efficiency | ~0.5 OOM/yr continues | Model cards, benchmark reports (context only) | Plateau; efficiency gains cut hardware demand (demand elasticity unknown) |
| Export controls | Tightening | Federal Register / BIS rules | Loosening or licensing-for-revenue |

## 3. Two-year scorecard (secondary, verify before citing)

A May 2026 review (philippdubach.com) reports that the physical and technical extrapolations largely held — test-time compute, benchmark saturation, power as the binding constraint (heavy-frame turbine lead times ~243 weeks were cited), behind-the-meter gas buildouts — while the political predictions largely failed or reversed: no nationalised project or lab merger, no allied coalition, export controls loosened (case-by-case H200-class licensing from January 2026), Gulf buildouts proceeded, and the security thesis missed algorithm reproduction (DeepSeek) rather than weight theft. Use this as a lead list; each item needs its own primary check. Research lesson: weight the essay's physical-constraint reasoning above its political timing.

## 4. Revealed preferences in SEC filings (primary, dated snapshot)

Situational Awareness LP (SEC CIK 0002045724). Retrieved from EDGAR on 2026-09-25; values are the 13F `value` field (underlying notional for options, not premium).

- **13F for 2026-03-31** (accession 0002045724-26-000008): long power, memory and AI-hosting names (e.g. Bloom Energy 878.7M common, SanDisk 724.4M, CoreWeave 556.1M, IREN 401.0M, Core Scientific 389.1M, Applied Digital 320.0M) alongside large put notional on compute and semiconductor names — VanEck Semiconductor ETF 2,042.7M, NVIDIA 1,568.3M, Oracle 1,072.9M, Broadcom 1,006.2M, AMD 969.2M, Micron 583.7M, TSMC 535.1M, ASML 494.1M.
- **13F for 2026-06-30** (accession 0000935836-26-000418, filed 2026-08-14): 26 rows, total 20,242,292,228 (self-summed). The compute/semiconductor puts are gone except a small Infosys put. SanDisk 5,673.7M and Micron 5,573.8M (together ≈ 56%), Bloom Energy 1,898.8M, TSMC 1,265.1M, Nebius 1,232.9M, CoreWeave 744.5M, Core Scientific 665.6M, STMicroelectronics 584.3M, Applied Digital 469.0M, Riot 468.2M, SharonAI 456.8M, IREN 433.3M, plus smaller power and hosting positions (CleanSpark, Keel Infrastructure, Solaris Energy Infrastructure, WhiteFiber, Bitdeer, T1 Energy, HIVE, Babcock & Wilcox, ProPetro, Vishay, Cerebras).
- **Schedule 13D, SharonAI Holdings** (event 2026-08-27, accession 0000935836-26-000468) and **13D/A No. 1** (event 2026-09-15, filed 2026-09-17, accession 0000935836-26-000500): 8,070,950 Class A shares, 21.1%, after exercising prefunded warrants for 2,674,823 shares on 2026-09-15 (companion Form 4, accession 0000935836-26-000494); about $523.9M of working capital; filers include Leopold Aschenbrenner and Carl Shulman; stated purpose is investment ("undervalued"), not control.
- **Event timeline between the 13Fs** (EDGAR, verified 2026-09-25): 13G on Nebius Group, 5.6% (event 2026-05-19, accession 0000935836-26-000303); Form 3 and 13G on SharonAI (SHAZ), 19.9% (event 2026-06-22), Form 4 exercise (2026-06-30) and 13G/A at 19.9% (event 2026-06-30, filed 2026-08-14); **13D/A on Core Scientific at 14,089,395 shares, 4.4% — below the 5% line (event 2026-07-15, filed 2026-08-04, accession 0000919574-26-004796)**; N-PX for 2026-06-30. No filing after 2026-09-17 as of 2026-09-25.

**July 2026 deleveraging (secondary, verified in the report).** 24/7 Wall St (2026-08-03) reports positions "financed with significant leverage, as much as four times its equity", that "margin requirements forced the liquidation of those positions", that the portfolio was sold to Citadel Advisors, and that the fund still showed about 80% year to date because roughly 25% of net assets sat in Anthropic, reportedly up 620%. Other outlets give conflicting fund sizes (about $20B versus $45B before the event); those figures are CONFLICTED and not used. The Core Scientific 13D/A (below 5% on 2026-07-15) is consistent with the timing; the event's size is not established by a primary source.

INFERENCE (project-authored): the Q1 book paired long exposure to physical constraints (power, memory, powered hosting sites) with large put notional on crowded compute beta; by Q2 the hedges were removed and memory became the dominant exposure, while power, powered-site and neocloud capacity stayed core. The Q2 13F predates the July liquidation, so it no longer proxies current exposure; the Q3 13F (due by 2026-11-14) is the next primary snapshot. What failed in July was trade construction — leverage and correlated legs — which neither confirms nor refutes the physical-constraint thesis; the SharonAI stake kept rising afterwards. Limits: a 13F cannot show whether puts hedged longs, omits shorts, foreign listings and private positions, and lags by up to 45 days; positions may already differ.

## 5. How research may use this layer

1. Generate hypotheses about which physical layer binds (power, site, memory, packaging) and when; then test each company with the Serenity lens and admitted evidence.
2. Record the essay expectation and the dated primary observation side by side; never promote a scenario to a forecast.
3. Treat fund positions as dated opinions of one investor. They are not company facts, independent corroboration or a reason to buy.
4. When Serenity and this layer point at the same constraint, record two views of one question, not two evidence families.
5. Refresh section 4 after each new 13F, 13D/A, 13G or Form 4 and move superseded snapshots to history.
6. In the phase engine (`scripts/thesis_phase.py`) signals from this layer carry the `ASCHENBRENNER_CONTEXT` lens: they are listed for context and never counted toward any phase, constraint family or ranking.
7. Leverage lesson for sizing guidance: a correct physical-constraint view can still be liquidated by leverage and correlated legs; options and sizing guidance stay unlevered with position caps.

## Sources

- Essay (primary): https://situational-awareness.ai/from-gpt-4-to-agi/ ; https://situational-awareness.ai/racing-to-the-trillion-dollar-cluster/ ; https://situational-awareness.ai/lock-down-the-labs/
- SEC EDGAR (primary): https://data.sec.gov/submissions/CIK0002045724.json and the accession folders above under https://www.sec.gov/Archives/edgar/data/2045724/
- Scorecard (secondary): https://philippdubach.com/posts/aschenbrenners-receipts/
- July 2026 deleveraging (secondary): https://247wallst.com/investing/2026/08/03/leopold-aschenbrenners-20-billion-ai-hedge-fund-imploded-heres-how-its-still-up-80-this-year/ (2026-08-03); conflicting size: https://economistwritingeveryday.com/2026/08/11/boy-wonder-leopold-aschenbrenner-blows-up-his-45-billion-situational-awareness-hedge-fund/ (2026-08-11)
