import {describe,expect,test,vi} from "vitest";
import {existsSync,readFileSync,writeFileSync} from "node:fs";
import {resolve} from "node:path";
import {buildCoveredCallMessages,validateCoveredCallCycle} from "../src/v213/covered-call";
import {estimateTop20Fallback} from "../src/v213/bottleneck-v3";

// The renderer is tested after its independent rights gate; only this isolated
// fixture replaces admission. Production and all real rights-admission tests are unchanged.
vi.mock("../src/v213/public-options-admission",()=>({
 admitPublicOption:()=>({ok:true,operator_accepted:true}),
 OptionRightsNotAdmittedError:class extends Error {},
}));

const stamp="2026-11-08T14:16:09Z";
const sample=()=>({
 ticker:"SIVE.ST",strategy:"COVERED_CALL",expiry:"2026-11-20",dte:12,
 spot:15.5,currency:"SEK",multiplier:100,quote_basis:"delayed",
 timestamp:stamp,source:"synthetic quote fixture",
 provenance:"https://example.com/test",rights_status:"operator_accepted_unlicensed",
 asof_date:"2026-11-08",monthly_rule:"THIRD_FRIDAY",
 suggestions:[],
 quote_observation:{kind:"TWO_SIDED",strike:17,bid:0.02,ask:0.03,last:null,
   annualized_yield:Math.round((.02/15.5*365/12)*1e6)/1e6,oi:100,volume:5}
});
describe("observation-only monthly call is not a recommendation",()=>{
 test("SIVE-shaped two-sided low yield is valid and the LINE line shows strike, expiry, quote, yield and basis",()=>{
  const c=validateCoveredCallCycle(sample(),Date.parse(stamp),stamp,"monthly");
  expect(c).not.toBeNull();
  const t=buildCoveredCallMessages(c!,"每月期權","text");
  expect(t).toHaveLength(1);
  const line=(t[0] as any).text as string;
  for(const phrase of ["SIVE.ST","2026-11-20","17.00","Bid","Ask","參考年化","低於6%門檻","報價觀察","非交易建議"])
    expect(line).toContain(phrase);
  const flex=buildCoveredCallMessages(c!,"每月期權","flex");
  expect(flex).toHaveLength(1);
 });
 test("no two sided uses last only, never invents bid/ask",()=>{
  const c=sample();
  const last=.03;
  c.quote_observation={
   ...c.quote_observation,kind:"NO_TWO_SIDED",bid:null as any,ask:null as any,last:last as any,
   annualized_yield:Math.round(last/15.5*365/12*1e6)/1e6
  };
  const validated=validateCoveredCallCycle(c,Date.parse(stamp),stamp,"monthly");
  expect(validated).not.toBeNull();
  const msg=buildCoveredCallMessages(validated!,"每月期權","text")[0] as any;
  expect(msg.text).toContain("無雙邊報價");
  expect(msg.text).toContain("Last");
  expect(msg.text).not.toContain("Bid $");
 });
 test("forged percent, no true bid, weekly route and expired quote fail closed",()=>{
  const fake=sample();
  fake.quote_observation.annualized_yield=.44;
  expect(validateCoveredCallCycle(fake,Date.parse(stamp),stamp,"monthly")).toBeNull();
  const bid=sample();bid.quote_observation.bid=0;
  expect(validateCoveredCallCycle(bid,Date.parse(stamp),stamp,"monthly")).toBeNull();
  expect(validateCoveredCallCycle(sample(),Date.parse(stamp),stamp,"weekly")).toBeNull();
  expect(validateCoveredCallCycle(sample(),Date.parse("2026-11-30T00:00:00Z"),stamp,"monthly")).toBeNull();
 });
});

describe("Top20 reported quarter and peer fallback",()=>{
 const entry=(revenue:number|null,yoy:number|null,prev:number|null,currency="USD")=>({
  symbol:"UNIT_A",layer:"LAYER_A",fundamentals:{
    quarter_end:"2026-09-30",source:"SEC EDGAR XBRL companyfacts",
    source_url:"https://example.com/filing",revenue,revenue_unit:currency,
    revenue_yoy:yoy,revenue_yoy_prev:prev
  },market:{currency,ret_6m:0.04}
 });
 const doc=(main:any,others:any[]=[])=>({
  generated_at:stamp,top:[main,...others],industries:[{id:"LAYER_A",median_revenue_yoy:0.20}]
 });
 test("issuer's own YoY is damped and labeled historical, both horizons numeric",()=>{
  const main=entry(100_000_000,.20,.30);
  const result=estimateTop20Fallback(doc(main) as any,main as any);
  expect(result).not.toBeNull();
  expect(result!.m6.basis).toBe("歷史推估");
  expect(result!.m6.amount).toBeCloseTo(212_500_000,0);
  expect(result!.m12.amount).toBeCloseTo(450_000_000,0);
  expect(result!.m12.change).toBeCloseTo(.125,5);
 });
 test("with no own YoY, layer median on filed revenue is explicitly distinguished",()=>{
  const main=entry(100_000_000,null,null);
  const result=estimateTop20Fallback(doc(main) as any,main as any);
  expect(result!.m12.basis).toBe("產業中位數推估");
  expect(result!.m12.amount).toBeCloseTo(440_000_000,0);
 });
 test("no issuer revenue uses same-currency layer proxy and never claims it as filed",()=>{
  const main=entry(null,null,null);
  const peer=entry(80_000_000,.10,null);
  peer.symbol="UNIT_B";
  const result=estimateTop20Fallback(doc(main,[peer]) as any,main as any);
  expect(result!.m12.amount).toBeCloseTo(352_000_000,0);
  expect(result!.m12.explanation).toContain("不是該公司的已報營收");
  const badPeer=entry(80_000_000,.10,null,"KRW");badPeer.symbol="UNIT_C";
  expect(estimateTop20Fallback(doc(main,[badPeer]) as any,main as any)).toBeNull();
 });
});

// Current read-only public chain is optional in normal CI. The test's admission mock
// proves *format rendering* only, not authorization for a public LINE deployment.
const work=resolve(process.cwd(),"../..");
const publicPath=resolve(work,"runtime/sive_monthly_public_probe.json");
test.skipIf(!existsSync(publicPath))("read-only SIVE public-chain preview renders its real monthly observation",()=>{
 const publicSnapshot=JSON.parse(readFileSync(publicPath,"utf8"));
 const cycle=validateCoveredCallCycle(publicSnapshot.monthly,
   Date.parse(publicSnapshot.observed_at),publicSnapshot.observed_at,"monthly");
 expect(cycle).not.toBeNull();
 const rendered=buildCoveredCallMessages(cycle!,"每月期權","text");
 const line=(rendered[0] as any).text as string;
 for(const value of ["SIVE.ST","2026-11-20","Bid","Ask","參考年化","擷取"])
   expect(line).toContain(value);
 writeFileSync(resolve(work,"SIVE-MONTHLY-RENDER.txt"),
   "READ-ONLY PUBLIC CHAIN / OFFLINE RENDER (admission mocked in test, not a public rights approval)\\n"+line+"\\n");
});
