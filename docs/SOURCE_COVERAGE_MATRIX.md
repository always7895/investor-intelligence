# Authoritative source coverage matrix

The source catalog has no fixed numeric ceiling. Coverage is expanded by authority and claim class, while runtime work remains bounded by request, byte, time, host-concurrency, retry and free-quota budgets. Catalog membership never activates a source.

## Current coverage families

| Family | Primary authority examples | Intended claims | Current runtime posture |
|---|---|---|---|
| Securities filings | SEC EDGAR, SEDAR+, EDINET, DART and national regulators | filings, XBRL, ownership, enforcement | disabled pending per-source gates |
| Exchange disclosure | TWSE/MOPS, TPEx, HKEX, SGX, ASX, JPX/TDnet, KRX and other regulated venues | announcements, corporate actions, listing status | disabled pending rights/adapters |
| Entity identity | GLEIF and official company registries | LEI, legal name, jurisdiction, status, relationships | GLEIF staged; others catalogued |
| Central banks | ECB, Federal Reserve sources, BoE, BoC, BoJ, CBC Taiwan, HKMA, RBA, RBI and others | rates, FX, credit, banking, reserves, policy | ECB staged; others catalogued |
| National statistics | BLS, BEA, Census, ONS, Statistics Canada, DGBAS Taiwan, ABS, SingStat and peers | GDP, labor, inflation, trade, industry, population | disabled pending adapters |
| Multilateral statistics | World Bank, OECD, BIS, IMF, WTO, ILO, UN and Eurostat | macro, development, trade, banking, productivity | World Bank reviewed; others catalogued |
| Government finance | Treasury and official fiscal/open-budget systems | debt, auctions, spending, grants, procurement | disabled pending adapters |
| Energy and grids | EIA, energy regulators, grid operators and official commodity infrastructure | generation, storage, fuels, grid events, emissions | disabled pending rights/adapters |
| Climate and environment | meteorological, climate and environmental authorities | weather/climate series, emissions, hazards | disabled pending adapters |
| Patents, trademarks and grants | national patent offices, WIPO/EPO-type authorities and government funding agencies | patents, applicants, classifications, grants | disabled pending adapters |
| Telecommunications and digital policy | telecom regulators, spectrum authorities, digital ministries and cyber authorities | broadband, spectrum, data centers, digital rules | disabled pending adapters |
| Banking and insurance supervision | FDIC, EBA, EIOPA and national prudential supervisors | institutions, deposits, capital, failures, risk | disabled pending adapters |
| Market infrastructure | exchanges, clearing houses, CSDs and official trade repositories | instruments, settlement, market status, derivatives | disabled pending adapters |
| Issuer primary publications | verified investor-relations domains linked from regulator/exchange/entity records | earnings, guidance, presentations and releases | discovery only; never auto-activated |
| Institutional editorial | reviewed public broadcasters and institutional newsrooms | corroboration and discovery only | cannot own material claims |

## Public option-source candidates

The shared LINE Bot needs option BID/ASK observations without using IBKR or any account-derived data. Official candidates include Cboe, OCC, Nasdaq, NYSE/ICE, CME, Eurex, HKEX, TAIFEX, JPX/OSE and ASX. They currently serve only as a review queue:

- no production provider selected;
- no candidate runtime-enabled;
- rights and redistribution review pending;
- adapter fixtures pending;
- current/live LINE option data disabled;
- yfinance classified as unreviewed delayed development compatibility only;
- no broker or paid fallback.

## Admission rules

A source becomes runtime-eligible only after all of the following are true for the exact source and adapter revision:

1. legal operator and authority scope reviewed;
2. endpoint linked from official documentation;
3. free/public access and attribution/redistribution terms reviewed;
4. strict schema and fixture tests pass;
5. private/broker/tenant lineage is impossible for public data;
6. safe HTTPS host/path/redirect/DNS boundaries pass;
7. freshness and revision/vintage handling are defined;
8. rate-limit, quota, request, byte and wall-time budgets are defined;
9. at least two probation probes succeed;
10. source health is `HEALTHY` or explicitly acceptable `DEGRADED`;
11. the exact canonical candidate passes BARRY.

A large catalog never overrides these gates. Unknown fields, unknown rights, unknown health and conflicting material values all fail closed.
