#!/usr/bin/env python3
"""
v2.1.3 Macro Industry Research Builder & Candidate Ranker.
Dynamic TOP5 evaluation across 12-36M horizon without hardcoded winners.
Strict admission:
- Verifiable growth rate with units, period, publisher, date, source_id.
- Missing growth rate -> UNAVAILABLE.
- Rejection of company-count percentage as market growth.
- Opportunity score is System Operationalization, not probability.
- Deterministic handling of 0, <5, 5, >5 candidates.
- Fail-closed if <5 qualified candidates admitted.
- Disqualified/unadmitted candidates output rank=null, NOT_PUBLICATION_QUALIFIED.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "v213-macro-industry-policy-v1.json"

# SYNTHETIC CONTRACT FIXTURE ONLY (operator rule 2026-09-25: no hand-written production data).
# These rows prove the card/overview contract in tests; they are never published. Production
# candidates come from scripts/industry_rotation.py (BLS PPI + SEC XBRL, recomputed from live data).
_SYNTHETIC_CONTRACT_UNIVERSE = [
    {
        "industry_id": "advanced_packaging_hbm",
        "industry_name": "先進封裝與高頻寬記憶體 (Advanced Packaging & HBM)",
        "current_state": "AI 晶片對 2.5D/3D 封裝與 HBM3e/HBM4 需求爆發，產能持續滿載配置。",
        "outlook_12_36m": "隨雲端資料中心與推論晶片架構迭代，記憶體頻寬成為算力關鍵瓶頸，預期未來2年維持極高景氣度。",
        "growth": {
            "rate_pct": 250.0,
            "units": "% YoY",
            "period": "2026",
            "type": "forecast",
            "publisher": "World Semiconductor Trade Statistics (WSTS)",
            "date": "2026-06",
            "source_id": "wsts-outlook",
            "url": "https://www.wsts.org/76/Recent-News-Release",
            "raw_passage": "Memory segment is forecast to surge by around 250 percent year over year, reaching more than USD 800 billion in 2026."
        },
        "demand_drivers": ["AI 加速器叢集規模化擴展", "LLM 參數量與記憶體頻寬牆 (Memory Wall)", "次世代伺服器架構換裝"],
        "supply_constraint_chokepoint": "TSV 矽穿孔良率、CoWoS/先進封裝設備機台產能、高階基板層數瓶頸",
        "pricing": "強定價權；記憶體原廠具長約定價優勢，高階封裝具技術溢價",
        "value_chain_position": "半導體後段高階封裝與高頻寬記憶體製造，緊密結合 Foundry 與 Hyperscalers",
        "beneficiaries_key_suppliers": ["TSMC", "SK Hynix", "Micron", "ASE Technology", "Advantest"],
        "catalysts": {
            "m6": "次世代 AI 晶片放量拉動 HBM3e 12-Hi 認證",
            "y1": "HBM4 混合鍵合 (Hybrid Bonding) 技術試產驗收",
            "y2": "3D 晶圓級整合封裝進入主流雲端算力中心"
        },
        "risks_lifecycle": "處於高速成長至成熟前中期；主要風險為主要雲端業者資本支出下修與同業激進擴產後的供需反轉。",
        "scores": {
            "demand": 24,
            "chokepoint": 24,
            "pricing": 19,
            "value_chain": 14,
            "catalysts": 14
        },
        "confidence": {
            "data_completeness": 92,
            "source_independence": 88,
            "verification_status": "OFFICIAL_PROSE_VERIFIED"
        }
    },
    {
        "industry_id": "robotics_automation",
        "industry_name": "工業與智慧型機器人 (Robotics & Industrial Automation)",
        "current_state": "製造業與物流自動化推進，但目前缺乏公認統一之 12-36M 全球市場複合年增率數值。",
        "outlook_12_36m": "人口結構老化與缺工驅動長期導入，AI 具身智慧為長期潛力方向。",
        "growth": None,  # Missing verifiable growth rate -> UNAVAILABLE!
        "demand_drivers": ["全球製造業勞動力短缺", "工廠柔性製造與供應鏈在地化", "具身智能技術實驗進展"],
        "supply_constraint_chokepoint": "減速機高精度加工、諧波減速機壽命、即時控制感測晶片交期",
        "pricing": "普通工業機械手臂面臨激烈價格競爭；高階減速機與精密感測具備部分定價權",
        "value_chain_position": "中游機器人本體製造與上游關鍵精密零組件",
        "beneficiaries_key_suppliers": ["Fanuc", "Keyence", "Harmonic Drive", "Yaskawa"],
        "catalysts": {
            "m6": "國際機器人展新型雙臂協作機型發布",
            "y1": "AI 視覺指引搬運機器人在主流物流倉儲滲透率翻倍",
            "y2": "人形機器人在特定封閉場景商業試點驗收"
        },
        "risks_lifecycle": "處於成長早期過渡期；受整體製造業 Capex 景氣週期波動影響大。",
        "scores": {
            "demand": 16,
            "chokepoint": 14,
            "pricing": 11,
            "value_chain": 10,
            "catalysts": 11
        },
        "confidence": {
            "data_completeness": 55,
            "source_independence": 70,
            "verification_status": "QUALITATIVE_ONLY_GROWTH_UNAVAILABLE"
        }
    },
    {
        "industry_id": "optical_networking",
        "industry_name": "高速光通訊與 CPO (Optical Networking & CPO)",
        "current_state": "800G 光模組進入大規模部署，1.6T 光模組展開樣品認證與小批量導入。",
        "outlook_12_36m": "資料中心內部機櫃互聯與交換機算力叢集頻寬翻倍，矽光子與 CPO 成為光電整合必然趨勢。",
        "growth": {
            "rate_pct": 38.5,
            "units": "% CAGR",
            "period": "2025-2027",
            "type": "forecast",
            "publisher": "LightCounting Market Research",
            "date": "2026-05",
            "source_id": "lightcounting-optical-forecast",
            "url": "https://www.lightcounting.com",
            "raw_passage": "Datacenter optical transceiver revenue is projected to expand at 38.5% CAGR from 2025 through 2027."
        },
        "demand_drivers": ["AI 叢集超大規模 Scale-out 互聯", "低延遲與低功耗傳輸需求", "PCIe 6.0/7.0 與 Ultra Ethernet 升級"],
        "supply_constraint_chokepoint": "磷化銦 (InP) 晶圓基板供應、EML/CW 外部光源激光器產能、高精光學耦合封裝",
        "pricing": "先進 800G/1.6T 短期具技術溢價；成熟 400G 價格隨規模平穩年降",
        "value_chain_position": "上游光晶片/基板至中游高階收發模組封裝",
        "beneficiaries_key_suppliers": ["Coherent", "Lumentum", "AXT Inc", "Innolight", "Fabrinet"],
        "catalysts": {
            "m6": "1.6T 光模組在大型雲端客戶完成互通性驗收",
            "y1": "商用 CPO 交換機小批量出貨",
            "y2": "共封裝光學進入主流量產產線"
        },
        "risks_lifecycle": "成長期加速階段；主要風險為架構切換延遲與光晶片良率拉升不及預期。",
        "scores": {
            "demand": 23,
            "chokepoint": 22,
            "pricing": 17,
            "value_chain": 14,
            "catalysts": 13
        },
        "confidence": {
            "data_completeness": 88,
            "source_independence": 85,
            "verification_status": "INDEPENDENT_RESEARCH_VERIFIED"
        }
    },
    {
        "industry_id": "grid_power_infrastructure",
        "industry_name": "電網與電力基礎設施 (Grid & Power Infrastructure)",
        "current_state": "大型資料中心並網申請排隊長達 3-5 年，高壓變壓器與開關設備嚴重缺貨。",
        "outlook_12_36m": "算力擴張最大物理限制轉移至電網接入與輸配電設備，長期剛性合約支撐強勁能見度。",
        "growth": {
            "rate_pct": 21.0,
            "units": "% YoY",
            "period": "2026",
            "type": "forecast",
            "publisher": "Federal Energy Regulatory Commission (FERC) / DOE",
            "date": "2026-04",
            "source_id": "ferc-doe-transmission",
            "url": "https://www.energy.gov/gdo/national-transmission-needs-study",
            "raw_passage": "High-voltage transformer and substation infrastructure capex is expected to grow 21% year-over-year in 2026."
        },
        "demand_drivers": ["AI 算力中心 GW 級電力負荷要求", "老舊電網現代化更新", "再生能源並網消納需求"],
        "supply_constraint_chokepoint": "方向性電磁鋼片 (GOES) 特殊材料短缺、高壓變壓器繞線產能、變電站建設審批週期",
        "pricing": "強議價權；交期拉長至 120-180 週，買方接受附帶原物料價格連動條款之長約",
        "value_chain_position": "重型電力設備製造、特高壓輸變電零件與電網工程總承包",
        "beneficiaries_key_suppliers": ["Eaton", "Schneider Electric", "Siemens Energy", "Hitachi Energy"],
        "catalysts": {
            "m6": "美國 FERC 電網互聯審批加速新規落地",
            "y1": "新建 GOES 電磁鋼片專用產線完工調試",
            "y2": "多座 1GW+ 專用核能/微電網供電中心併網供電"
        },
        "risks_lifecycle": "成熟轉向超級資本週期復甦；主要風險為環評訴訟延宕、大宗原物料銅鋼劇烈震盪。",
        "scores": {
            "demand": 22,
            "chokepoint": 23,
            "pricing": 18,
            "value_chain": 13,
            "catalysts": 13
        },
        "confidence": {
            "data_completeness": 86,
            "source_independence": 84,
            "verification_status": "OFFICIAL_PROSE_VERIFIED"
        }
    },
    {
        "industry_id": "thermal_cooling_systems",
        "industry_name": "先進散熱與液冷系統 (Advanced Thermal & Liquid Cooling)",
        "current_state": "單晶片 TDP 突破 1000W，傳統風冷接近物理散熱極限，冷板式液冷全面加速標配。",
        "outlook_12_36m": "機櫃功率密度從 20kW 邁向 100kW+，水冷冷卻液分配單元 (CDU) 與歧管成為標準配備。",
        "growth": {
            "rate_pct": 45.0,
            "units": "% CAGR",
            "period": "2025-2027",
            "type": "forecast",
            "publisher": "Omdia / Informa Tech Datacenter Thermal Research",
            "date": "2026-03",
            "source_id": "omdia-cooling-research",
            "url": "https://omdia.tech.informa.com",
            "raw_passage": "Direct-to-chip liquid cooling market is projected to expand at 45% CAGR through 2027."
        },
        "demand_drivers": ["GPU/ASIC 熱設計功耗 (TDP) 持續攀升", "資料中心綠色能源效率 PUE <= 1.15 強制監管", "高密度伺服器機櫃空間節省需求"],
        "supply_constraint_chokepoint": "快接頭 (Quick Disconnects) 無洩漏密封專利與精密加工良率、CDU 幫浦可靠性測試",
        "pricing": "具驗證門檻產品具高毛利；客製化水冷板與分流管具較高定價彈性",
        "value_chain_position": "資料中心機電散熱設備、伺服器內部冷板與流體循環控制模組",
        "beneficiaries_key_suppliers": ["Vertiv", "Cooler Master", "Auras Technology", "Boyd", "Parker Hannifin"],
        "catalysts": {
            "m6": "下一代伺服器機櫃全面出貨標配直達晶片冷板",
            "y1": "全浸沒式液冷在特定高算力叢集取得規模商業訂單",
            "y2": "無水式兩相相變散熱技術完成大型資料中心場域長期可靠度驗證"
        },
        "risks_lifecycle": "導入成長初期至放量期；主要風險為冷卻液外洩造成短路損害之保固責任、冷卻液法規管制。",
        "scores": {
            "demand": 21,
            "chokepoint": 19,
            "pricing": 16,
            "value_chain": 13,
            "catalysts": 13
        },
        "confidence": {
            "data_completeness": 84,
            "source_independence": 80,
            "verification_status": "INDEPENDENT_RESEARCH_VERIFIED"
        }
    },
    {
        "industry_id": "semiconductor_equipment_materials",
        "industry_name": "半導體前段設備與關鍵特用化學材料 (Semiconductor Equipment & Materials)",
        "current_state": "EUV 微影、原子層沉積 (ALD)、先進蝕刻與極高深寬比設備需求穩定，國產化與多極供應鏈重組加速。",
        "outlook_12_36m": "2nm 節點邁向 GAAFET / RibbonFET 架構，沉積蝕刻道數倍增，帶動關鍵特殊化學品與耗材用量擴張。",
        "growth": {
            "rate_pct": 14.2,
            "units": "% YoY",
            "period": "2026-2027",
            "type": "forecast",
            "publisher": "Semiconductor Equipment and Materials International (SEMI)",
            "date": "2026-05",
            "source_id": "semi-equipment-market-data",
            "url": "https://www.semi.org/en/news-resources/press-releases",
            "raw_passage": "Global total semiconductor manufacturing equipment sales are expected to increase 14.2% year-over-year."
        },
        "demand_drivers": ["先進邏輯 2nm/A16 晶圓廠資本支出", "高階記憶體產線轉型", "各國半導體自主供應鏈補貼建設"],
        "supply_constraint_chokepoint": "極紫外光光學鏡頭鏡組產能、電子級特氣/高純化學品認證週期、多重曝光光罩檢測時間",
        "pricing": "極高技術壁壘造就寡占定價權，機台價格隨技術難度自然調漲",
        "value_chain_position": "半導體製造最上游生產工具與核心化學消耗品",
        "beneficiaries_key_suppliers": ["ASML", "Applied Materials", "Lam Research", "Tokyo Electron", "Entegris"],
        "catalysts": {
            "m6": "High-NA EUV 商用機台進入客戶量產晶圓廠試運轉",
            "y1": "GAAFET 2nm 晶圓進入正式商業產線量產",
            "y2": "背部供電 (Backside Power Delivery) 設備訂單迎來採購高峰"
        },
        "risks_lifecycle": "成熟資本密集產業；主要風險為地緣政治出口管制擴大、終端消費性電子復甦疲弱對晶圓廠擴產節奏之壓抑。",
        "scores": {
            "demand": 19,
            "chokepoint": 23,
            "pricing": 18,
            "value_chain": 14,
            "catalysts": 12
        },
        "confidence": {
            "data_completeness": 90,
            "source_independence": 89,
            "verification_status": "OFFICIAL_PROSE_VERIFIED"
        }
    }
]

SYNTHETIC_FIVE_QUALIFIED = [
    _SYNTHETIC_CONTRACT_UNIVERSE[0],
    next(c for c in _SYNTHETIC_CONTRACT_UNIVERSE if c["industry_id"] == "optical_networking"),
    next(c for c in _SYNTHETIC_CONTRACT_UNIVERSE if c["industry_id"] == "grid_power_infrastructure"),
    next(c for c in _SYNTHETIC_CONTRACT_UNIVERSE if c["industry_id"] == "thermal_cooling_systems"),
    next(c for c in _SYNTHETIC_CONTRACT_UNIVERSE if c["industry_id"] == "semiconductor_equipment_materials"),
]


def load_policy(policy_path: Path) -> dict:
    if not policy_path.exists():
        return {}
    with policy_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_candidate(candidate: dict) -> tuple[bool, str]:
    """Validate candidate against strict admission rules."""
    growth = candidate.get("growth")
    if not growth:
        return False, "GROWTH_RATE_MISSING_UNAVAILABLE"

    # Reject company-count percentage as market growth
    units = str(growth.get("units", "")).lower()
    passage = str(growth.get("raw_passage", "")).lower()
    if any(term in units or term in passage for term in ["company", "companies", "ticker", "家數", "候選家數", "candidates percentage"]):
        return False, "COMPANY_COUNT_PERCENTAGE_CANNOT_BE_MARKET_GROWTH"

    rate_pct = growth.get("rate_pct")
    if rate_pct is None or not isinstance(rate_pct, (int, float)):
        return False, "INVALID_NUMERIC_GROWTH_RATE"

    if not growth.get("units") or not growth.get("period") or not growth.get("publisher") or not growth.get("date"):
        return False, "INCOMPLETE_GROWTH_METADATA"

    if not growth.get("source_id"):
        return False, "UNADMITTED_GROWTH_SOURCE"

    return True, "QUALIFIED"


def calculate_opportunity_score(candidate: dict) -> int:
    """Calculate System Operationalization score (0-100), not probability."""
    scores = candidate.get("scores", {})
    demand = min(25, max(0, int(scores.get("demand", 0))))
    chokepoint = min(25, max(0, int(scores.get("chokepoint", 0))))
    pricing = min(20, max(0, int(scores.get("pricing", 0))))
    value_chain = min(15, max(0, int(scores.get("value_chain", 0))))
    catalysts = min(15, max(0, int(scores.get("catalysts", 0))))
    return demand + chokepoint + pricing + value_chain + catalysts


def evaluate_candidates(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    qualified = []
    disqualified = []
    for cand in candidates:
        ok, reason = validate_candidate(cand)
        cand_copy = json.loads(json.dumps(cand))
        # Data-driven rows carry their computed strength; hand-scored rows exist only in synthetic tests.
        cand_copy["opportunity_score"] = (int(cand_copy["data_strength"]) if "data_strength" in cand_copy
                                          else calculate_opportunity_score(cand_copy))
        if ok:
            cand_copy["admission_status"] = "ADMITTED"
            qualified.append(cand_copy)
        else:
            cand_copy["admission_status"] = "NOT_PUBLICATION_QUALIFIED"
            cand_copy["disqualification_reason"] = reason
            cand_copy["rank"] = None
            cand_copy["growth"] = None
            disqualified.append(cand_copy)

    # Rotation order (phase, then data strength) when present; otherwise opportunity score.
    qualified.sort(key=lambda c: (c.get("rotation_rank", 0), -c["opportunity_score"]))
    for idx, cand in enumerate(qualified):
        cand["rank"] = idx + 1

    return qualified, disqualified


def load_rotation_candidates(path: Path | None = None) -> tuple[list[dict], dict, dict | None]:
    """(candidates, deep analyses, rotation doc) from the fresh data-driven rotation; empty when stale or missing."""
    import industry_rotation
    document = industry_rotation.load_rotation(path or industry_rotation.OUTPUT_PATH)
    if document is None:
        return [], {}, None
    return list(document.get("macro_candidates", [])), dict(document.get("deep_analyses", {})), document


def build_macro_overview_output(qualified: list[dict], disqualified: list[dict], is_synthetic=False,
                                deep_analyses: dict | None = None, rotation: dict | None = None) -> dict:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    qualified_count = len(qualified)
    shortfall = max(0, 5 - qualified_count)
    is_top5_admitted = shortfall == 0 and qualified_count >= 5

    report = {
        "schema_version": 1,
        "title": "TOP5產業總覽",
        "generated_at": stamp,
        "horizon": "12-36M",
        "qualified_count": qualified_count,
        "shortfall": shortfall,
        "status": "ADMITTED_TOP5" if is_top5_admitted else "SHORTFALL_NOT_QUALIFIED",
        "publication_qualified": is_top5_admitted and not is_synthetic,
        "synthetic_contract_fixture": is_synthetic,
        "candidate_pool_size": qualified_count + len(disqualified),
        "industries": qualified[:5],
        # Deep analyses travel inside the sealed overview (the seal admits one macro object).
        "deep_analyses": {c["industry_id"]: (deep_analyses or {})[c["industry_id"]]
                          for c in qualified[:5] if c.get("industry_id") in (deep_analyses or {})},
        "data_basis": ({"method": rotation.get("method"), "as_of": rotation.get("as_of"), "quarter": rotation.get("quarter"),
                        "receipt_count": len(rotation.get("receipts", []))} if rotation else None),
        "excluded_candidates": [
            {
                "industry_id": c.get("industry_id"),
                "industry_name": c.get("industry_name"),
                "reason": c.get("disqualification_reason")
            }
            for c in disqualified
        ]
    }

    if shortfall > 0:
        report["shortfall_report"] = (
            f"短缺通報：符合完整可查證成長率、供給瓶頸與價值鏈證據之合格產業僅 {qualified_count} 個，"
            f"距 TOP5 門檻尚缺 {shortfall} 個。依規範拒絕湊數假裝滿額。"
        )

    return report


def main():
    parser = argparse.ArgumentParser(description="v2.1.3 Macro Industry Research Builder")
    parser.add_argument("--input", type=str, help="Path to input candidates JSON")
    parser.add_argument("--output", type=str, help="Path to output JSON")
    parser.add_argument("--policy", type=str, default=str(DEFAULT_POLICY_PATH), help="Policy JSON path")
    parser.add_argument("--synthetic-fixture", action="store_true", help="Generate synthetic 5 qualified candidates to prove UI contract")
    args = parser.parse_args()
    deep: dict = {}
    rotation: dict | None = None

    if args.synthetic_fixture:
        candidates = SYNTHETIC_FIVE_QUALIFIED
        is_synthetic = True
    elif args.input:
        with Path(args.input).open("r", encoding="utf-8") as f:
            candidates = json.load(f)
        is_synthetic = False
    else:
        # Default live evaluation: the data-driven rotation; stale or missing data is a shortfall.
        candidates, deep, rotation = load_rotation_candidates()
        is_synthetic = False

    qualified, disqualified = evaluate_candidates(candidates)
    result = build_macro_overview_output(qualified, disqualified, is_synthetic=is_synthetic,
                                         deep_analyses=deep, rotation=rotation)

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Wrote output to {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
