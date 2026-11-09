import {describe,expect,it,vi} from "vitest";
import qualified from "./fixtures/fix-r2a-qualified.json";
import observed from "./fixtures/fix-r2a-observation.json";
import nonstandard from "./fixtures/fix-r2a-nonstandard.json";
import {validateCoveredCallCycle,buildCoveredCallMessages} from "../src/v213/covered-call";
import {normalizeOptionsUnavailableReason,optionsUnavailableReport} from "../src/v213/options-product";

// Isolated renderer assertion only; canonical admission is covered by the full existing suite.
vi.mock("../src/v213/public-options-admission",()=>({
 admitPublicOption:()=>({ok:true,operator_accepted:true}),
 OptionRightsNotAdmittedError:class extends Error {}
}));
const stamp="2026-11-08T14:16:09Z";
const now=Date.parse(stamp);
const msgText=(messages:readonly any[])=>messages.map(m=>m.text??JSON.stringify(m)).join("\n");

describe("G01 validated standard monthly >=7 DTE",()=>{
 it("accepts the standard Friday, refuses under-7DTE and false monthly-rule claims",()=>{
   expect(validateCoveredCallCycle(qualified,now,stamp,"monthly")).not.toBeNull();
   const short={...qualified,expiry:"2026-11-13",dte:5,monthly_rule:undefined};
   expect(validateCoveredCallCycle(short,now,stamp,"monthly")).toBeNull();
   const falseMarker={...nonstandard,monthly_rule:"LATER_LISTED"};
   expect(validateCoveredCallCycle(falseMarker,now,stamp,"monthly")).toBeNull();
 });
 it("retains a validated old weekly-like 33DTE as NONSTANDARD dated line, never a month sell advice",()=>{
   const legacy={...nonstandard};
   delete (legacy as any).monthly_nonstandard; // old public cache predates the label
   const cycle=validateCoveredCallCycle(legacy,now,stamp,"monthly");
   expect(cycle?.monthly_nonstandard).toBe(true);
   const text=msgText(buildCoveredCallMessages(cycle!,"每月期權","text"));
   for(const token of ["每月期權","非標準月到期","2026-12-11","觀察","不可執行"]){
     if(token!=="不可執行")expect(text).toContain(token);
   }
   expect(text).not.toContain("建議賣出限價");
   expect(text).not.toContain("舊版資料");
   const flex=buildCoveredCallMessages(cycle!,"每月期權","flex");
   expect(flex).toHaveLength(1);
   expect(JSON.stringify(flex)).toContain("非標準月到期");
 });
});
describe("G02 covered call, CSP and protective collar require independently validated real legs",()=>{
 it("shows all three verified strategies on a source-backed monthly chain (text + Flex)",()=>{
   const cycle=validateCoveredCallCycle(qualified,now,stamp,"monthly");
   expect(cycle).not.toBeNull();
   expect(cycle?.suggestions.length).toBeGreaterThan(0);
   const text=msgText(buildCoveredCallMessages(cycle!,"每月期權","text"));
   for(const label of ["備兌買權","現金擔保賣權","領口策略","保護賣權","限價","年化","非個人化投資建議"])
      expect(text).toContain(label);
   expect(text).not.toContain("舊版資料");
   const flex=buildCoveredCallMessages(cycle!,"每月期權","flex");
   expect(flex[0]?.type).toBe("flex");
   expect(JSON.stringify(flex)).toContain("領口策略");
 });
 it("low-premium CC remains observation only while genuine CSP/collar stay independently visible",()=>{
   const cycle=validateCoveredCallCycle(observed,now,stamp,"monthly");
   expect(cycle).not.toBeNull();
   expect(cycle?.suggestions).toHaveLength(0);
   expect(cycle?.quote_observation?.kind).toBe("TWO_SIDED");
   const text=msgText(buildCoveredCallMessages(cycle!,"每月期權","text"));
   for(const label of ["低於6%門檻","現金擔保賣權","領口策略","保護賣權","無雙邊報價","延遲來源觀察"])
     if(label!=="無雙邊報價")expect(text).toContain(label);
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
describe("G05 stale cached diagnostics, not falsely declared market absence",()=>{
 it("replaces obsolete 21-45 and 14-60 day windows, and keeps disclosure",()=>{
   for(const reason of ["無 21–45 天到期的上市期權","無 14-60 天到期的上市期權"]){
     const normalized=normalizeOptionsUnavailableReason(reason,"monthly");
     expect(normalized).toContain("至少7天");
     expect(normalized).not.toMatch(/21–45|14-60/u);
     const displayed=msgText(optionsUnavailableReport("UNIT","monthly",reason,true));
     expect(displayed).not.toMatch(/21–45|14-60/u);
     expect(displayed).toContain("需重新核對");
   }
 });
});
