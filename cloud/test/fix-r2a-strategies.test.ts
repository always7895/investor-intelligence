import {describe,expect,it,vi} from "vitest";
import qualified from "./fixtures/fix-r2a-qualified.json";
import observed from "./fixtures/fix-r2a-observation.json";
import nonstandard from "./fixtures/fix-r2a-nonstandard.json";
import {validateCoveredCallCycle,buildCoveredCallMessages} from "../src/v213/covered-call";

// Isolated renderer assertion only; canonical admission is covered by the full existing suite.
vi.mock("../src/v213/public-options-admission",()=>({
 admitPublicOption:()=>({ok:true,operator_accepted:true}),
 OptionRightsNotAdmittedError:class extends Error {}
}));
const stamp="2026-11-08T14:16:09Z";
const now=Date.parse(stamp);
const msgText=(messages:readonly any[])=>messages.map(m=>m.text??JSON.stringify(m)).join("\n");

describe("G01 nearest standard monthly with no minimum DTE",()=>{
 it("accepts the standard Friday and refuses weekly dates and false monthly-rule claims",()=>{
   expect(validateCoveredCallCycle(qualified,now,stamp,"monthly")).not.toBeNull();
   const short={...qualified,expiry:"2026-11-13",dte:5,monthly_rule:undefined};
   expect(validateCoveredCallCycle(short,now,stamp,"monthly")).toBeNull();
   const falseMarker={...nonstandard,monthly_rule:"LATER_LISTED"};
   expect(validateCoveredCallCycle(falseMarker,now,stamp,"monthly")).toBeNull();
 });
 it("rejects old weekly-in-monthly rows with or without the obsolete marker",()=>{
   const { monthly_nonstandard: _obsolete, ...legacy } = nonstandard;
   expect(validateCoveredCallCycle(legacy,now,stamp,"monthly")).toBeNull();
   expect(validateCoveredCallCycle(nonstandard,now,stamp,"monthly")).toBeNull();
 });
 it.each([0,1,2,3,4,5,6])("keeps %i-DTE standard observations and warns only at short expiry",dte=>{
   const { strategies: _strategies, ...base } = observed;
   const at = Date.parse("2026-11-20T20:59:00Z") - dte*86_400_000;
   const captured = new Date(at).toISOString();
   const raw = {...base, expiry:"2026-11-20", dte, timestamp:captured,
     asof_date:captured.slice(0,10),
     quote_observation:{...base.quote_observation,
       annualized_yield:base.quote_observation.bid/base.spot*365/Math.max(dte,1)}};
   const cycle=validateCoveredCallCycle(raw,at,captured,"monthly");
   expect(cycle).not.toBeNull();
   for(const style of ["text","flex"] as const){
     const text=msgText(buildCoveredCallMessages(cycle!,"每月期權",style));
     expect(text).toContain("2026-11-20");
     expect(text.includes("年化收益以至少 1 天換算")).toBe(dte<=2);
   }
   if(dte===0)expect(validateCoveredCallCycle(raw,Date.parse("2026-11-20T21:00:00Z"),captured,"monthly")).toBeNull();
 });
});
describe("G02 covered call, CSP and protective collar require independently validated real legs",()=>{
 it("shows low-yield eligible CC beside CSP and collar without a premium hurdle (text + Flex)",()=>{
   const cycle=validateCoveredCallCycle(qualified,now,stamp,"monthly");
   expect(cycle).not.toBeNull();
   expect(cycle?.suggestions.length).toBeGreaterThan(0);
   expect(cycle?.quote_observation).toBeUndefined();
   expect(cycle!.suggestions.some(item=>item.annualized_yield>0 && item.annualized_yield<.02)).toBe(true);
   const text=msgText(buildCoveredCallMessages(cycle!,"每月期權","text"));
   for(const label of ["備兌買權","現金擔保賣權","領口策略","保護賣權","限價","年化","非個人化投資建議"])
      expect(text).toContain(label);
   expect(text).not.toMatch(/6[%％].{0,4}門檻/);
   expect(text).not.toContain("舊版資料");
   const flex=buildCoveredCallMessages(cycle!,"每月期權","flex");
   expect(flex[0]?.type).toBe("flex");
   expect(JSON.stringify(flex)).toContain("領口策略");
   expect(JSON.stringify(flex)).not.toMatch(/6[%％].{0,4}門檻/);
 });
 it("delta-ineligible CC retains its refusal while genuine put strategies use recommendation cards",()=>{
   const cycle=validateCoveredCallCycle(observed,now,stamp,"monthly");
   expect(cycle).not.toBeNull();
   expect(cycle?.suggestions).toHaveLength(0);
   expect(cycle?.quote_observation?.kind).toBe("TWO_SIDED");
   const text=msgText(buildCoveredCallMessages(cycle!,"每月期權","text"));
   for(const label of ["現金擔保賣權","領口策略","保護賣權"])
     expect(text).toContain(label);
   expect(text).not.toMatch(/6[%％].{0,4}門檻/);
   const flex=buildCoveredCallMessages(cycle!,"每月期權","flex");
   expect(flex).toHaveLength(1);
   expect(JSON.stringify(flex)).toContain("現金擔保賣權");
 });
 it("tampered leg or annualized yield refuses the public strategy, never invents a filled cell",()=>{
   const bad=structuredClone(qualified);
   bad.suggestions[0]!.bid=0;
   expect(validateCoveredCallCycle(bad,now,stamp,"monthly")).toBeNull();
   const forged=structuredClone(observed);
   forged.quote_observation!.annualized_yield=0.99;
   expect(validateCoveredCallCycle(forged,now,stamp,"monthly")).toBeNull();
 });
});
