import {expect,test,vi} from "vitest";
import {readFileSync,mkdirSync,writeFileSync,existsSync} from "node:fs";
import {resolve} from "node:path";
import {validateCoveredCallCycle,buildCoveredCallMessages} from "../src/v213/covered-call";
import {optionsUnavailableReport} from "../src/v213/options-product";
import {loadOptionsCoverage,buildOptionsCoverageMessages,validateOptionsCoverage,OPTIONS_COVERAGE_KEY} from "../src/v213/options-coverage";
import {OPTIONS_KEY} from "../src/v213/market-observations";

const root=resolve(process.cwd(),"../..");
const read=(s:string)=>readFileSync(resolve(root,"data",s),"utf8");
const hasRealCopy=existsSync(resolve(root,"data","real_coverage_body.json"))
  && existsSync(resolve(root,"data","real_options_body.json"));
const preCoverage=hasRealCopy?read("real_coverage_body.json"):"{}";
const preOptions=hasRealCopy?read("real_options_body.json"):"{}";
const stage=process.env.R2A_STAGE==="AFTER"?"AFTER":"BEFORE";
const afterPath=resolve(root,"data","after_coverage_body.json");
function msgText(messages:any[]):string{
 return messages.map((m:any)=>m.type==="text"?m.text:JSON.stringify(m)).join("\n");
}
function normalizedText(messages:any[]):string{
 const full=msgText(messages);
 return full.replace(/https?:\/\/\S+/g,"[URL]").slice(0,3900);
}
function datedMonthlyContent(text:string,expiry:unknown,accepted:boolean):boolean{
 if(!accepted||typeof expiry!=="string"||!/^\d{4}-\d{2}-\d{2}$/u.test(expiry))return false;
 const datedExpiry=text.includes("到期 "+expiry);
 const quoteLine=text.split("\n").some(line=>
   /\bBid\s+\$?[\d,.]+(?:\s+[A-Z]{3})?/u.test(line)&&/\bAsk\s+\$?[\d,.]+(?:\s+[A-Z]{3})?/u.test(line));
 const observationLine=text.includes("報價觀察")&&text.includes("履約價 ")
   &&text.split("\n").some(line=>line.includes("無雙邊報價")&&line.includes("Last "));
 return datedExpiry&&(quoteLine||observationLine);
}
function monthlyCalendarKind(expiry:unknown,rule:unknown):"standard"|"declared_shift"|"nonstandard"|"undated"{
 if(typeof expiry!=="string"||!/^\d{4}-\d{2}-\d{2}$/u.test(expiry))return "undated";
 const day=new Date(expiry+"T00:00:00Z");
 if(!Number.isFinite(day.getTime())||day.toISOString().slice(0,10)!==expiry)return "undated";
 const first=new Date(Date.UTC(day.getUTCFullYear(),day.getUTCMonth(),1));
 const thirdFriday=1+(5-first.getUTCDay()+7)%7+14;
 if(day.getUTCDate()===thirdFriday)return "standard";
 if((rule==="HOLIDAY_SHIFT"||rule==="LATER_LISTED")
   &&day.getUTCDate()>=thirdFriday-4&&day.getUTCDate()<thirdFriday)return "declared_shift";
 return "nonstandard";
}
test("monthly calendar metric detects unmarked legacy weeklies",()=>{
 expect(monthlyCalendarKind("2026-12-11",undefined)).toBe("nonstandard");
 expect(monthlyCalendarKind("2026-12-18",undefined)).toBe("standard");
 expect(monthlyCalendarKind("2026-12-17",undefined)).toBe("nonstandard");
 expect(monthlyCalendarKind("2026-12-17","HOLIDAY_SHIFT")).toBe("declared_shift");
 expect(monthlyCalendarKind("2026-12-17","LATER_LISTED")).toBe("declared_shift");
 expect(monthlyCalendarKind("2026-12-11","HOLIDAY_SHIFT")).toBe("nonstandard");
 expect(monthlyCalendarKind("2026-02-30",undefined)).toBe("undated");
});
test("monthly metric excludes unavailable headings and dated refusals",()=>{
 expect(datedMonthlyContent("期權報價不可用 · SIVE.ST 每月期權",undefined,false)).toBe(false);
 expect(datedMonthlyContent("每月期權 到期 2026-11-20；無雙邊報價","2026-11-20",false)).toBe(false);
 expect(datedMonthlyContent("每月期權 到期 2026-11-20\n履約價 17.00 SEK","2026-11-20",true)).toBe(false);
 expect(datedMonthlyContent("每月期權 到期 2026-11-20\nBid 0.10 SEK／Ask 0.20 SEK","2026-11-20",true)).toBe(true);
 expect(datedMonthlyContent("每月期權 到期 2026-11-20\nBid $0.10／Ask $0.20","2026-11-20",true)).toBe(true);
 expect(datedMonthlyContent("每月期權｜報價觀察\n到期 2026-11-20｜履約價 17.00 SEK\n無雙邊報價；Last 來源未提供","2026-11-20",true)).toBe(true);
});
test.skipIf(!hasRealCopy)("offline full source snapshot, monthly and coverage real render; no production access",async()=>{
 const saved=stage==="AFTER"&&existsSync(afterPath)?readFileSync(afterPath,"utf8"):preCoverage;
 const coverage=JSON.parse(saved);
 const opts=JSON.parse(preOptions);
 const now=Date.parse(coverage.generated_at)+5*60*1000;
 vi.useFakeTimers();
 vi.setSystemTime(now);
 try {
   const view={
      integrity:"sealed",
      kind:"snapshot",
      hasSealedObject:(key:string)=>key===OPTIONS_KEY||key===OPTIONS_COVERAGE_KEY,
      text:async(keys:string[])=>keys[0]===OPTIONS_KEY?preOptions:keys[0]===OPTIONS_COVERAGE_KEY?saved:null,
   } as any;
   const result=await loadOptionsCoverage(view,now);
   const coverageText=msgText(buildOptionsCoverageMessages(result,true));
   const all:string[]=[];
   const rows:any[]=[];
   for(const [ticker,periods] of Object.entries(opts.options) as [string,any][]){
     for(const period of ["weekly","monthly"] as const){
       const raw=periods?.[period];
       if(!raw)continue;
       const valid=validateCoveredCallCycle(raw,now,opts.generated_at,period);
       let method="unavailable",text="";
       if(valid){
         try{
           text=msgText(buildCoveredCallMessages(valid,period==="monthly"?"每月期權":"每週期權","text"));
           method="accepted";
         }catch{
           method="rights_rejected";
           text=msgText(optionsUnavailableReport(ticker,period,"未通過獨立公開權限審查",true));
         }
       }else{
         method=typeof raw.unavailable==="string"?"producer_unavailable":"invalid_cycle";
         text=msgText(optionsUnavailableReport(ticker,period,
           method==="invalid_cycle"?"封存資料未通過契約與日期驗證":raw.unavailable,true));
       }
       const calendar=period==="monthly"?monthlyCalendarKind(raw?.expiry,raw?.monthly_rule):null;
       const nonstandard=calendar==="nonstandard";
       const accepted=method==="accepted";
       rows.push({symbol:ticker,period,method,expiry:raw?.expiry??null,
         has_cc:accepted&&!!valid?.suggestions?.length,
         has_csp:accepted&&!!valid?.strategies?.csp&&!("unavailable" in valid.strategies.csp),
         has_collar:accepted&&!!valid?.strategies?.collar&&!("unavailable" in valid.strategies.collar),
         monthly_line_present:period==="monthly"&&(calendar==="standard"||calendar==="declared_shift")
           &&datedMonthlyContent(text,valid?.expiry,accepted),
         monthly_observation:period==="monthly"&&accepted&&!!valid?.quote_observation,
         monthly_nonstandard:nonstandard,
         monthly_calendar:calendar,
         monthly_nonstandard_rejected:nonstandard&&!accepted,
         monthly_nonstandard_accepted:nonstandard&&accepted,
         mentions_old_text:text.includes("舊版資料"),mentions_old_window:/21\s*[-–]\s*45|21–45/u.test(text)});
       all.push("【"+ticker+" "+period+"】\n"+normalizedText([{type:"text",text}]));
     }
   }
   const counts=(field:string)=>rows.filter(row=>row.method===field).length;
   const summary={stage,source:"copied original sealed public options blob",raw_schema_accepted:validateOptionsCoverage(coverage)!==null,
     coverage_status:result.status,coverage_rendered_ok:result.status==="OK"&&coverageText.includes("全球期權來源"),
     total_rows:rows.length,rendered:counts("accepted"),unavailable:counts("producer_unavailable"),
     invalid:counts("invalid_cycle"),rights_rejected:counts("rights_rejected"),
     legacy_phrase_rows:rows.filter(row=>row.mentions_old_text).length,
     old_month_window_rows:rows.filter(row=>row.mentions_old_window).length,
     monthly_rendered:rows.filter(row=>row.period==="monthly"&&row.method==="accepted").length,
     monthly_symbols: Object.keys(opts.options).length,
     monthly_line_present: rows.filter(row=>row.period==="monthly"&&row.monthly_line_present).length,
     monthly_nonstandard: rows.filter(row=>row.monthly_nonstandard).length,
     monthly_nonstandard_accepted: rows.filter(row=>row.monthly_nonstandard_accepted).length,
     monthly_nonstandard_rejected: rows.filter(row=>row.monthly_nonstandard_rejected).length,
     monthly_observation:rows.filter(row=>row.monthly_observation).length,
     cc_available:rows.filter(row=>row.has_cc).length,
     csp_available:rows.filter(row=>row.has_csp).length,
     collar_available:rows.filter(row=>row.has_collar).length
   };
   // Operator-only evidence output; regular test runs never overwrite BEFORE/AFTER measurements.
   if(process.env.R2A_STAGE==="BEFORE"||process.env.R2A_STAGE==="AFTER"){
     const folder=resolve(root,"render");mkdirSync(folder,{recursive:true});
     writeFileSync(resolve(folder,stage+"_renderer_counts.json"),JSON.stringify(summary,null,2)+"\n");
     writeFileSync(resolve(folder,stage+"_coverage_text.txt"),coverageText);
     writeFileSync(resolve(folder,stage+"_all_options_text.txt"),all.join("\n\n"));
     writeFileSync(resolve(folder,stage+"_option_rows.json"),JSON.stringify(rows,null,2)+"\n");
   }
   expect(rows.length).toBeGreaterThan(500);
   if(stage==="AFTER"){
     expect(result.status).toBe("OK");
     expect(summary.monthly_line_present).toBeLessThanOrEqual(summary.monthly_rendered);
     expect(summary.monthly_nonstandard_accepted).toBe(0);
     expect(rows.filter(row=>row.method!=="accepted").every(row=>!row.monthly_line_present)).toBe(true);
   }
 }finally{
   vi.useRealTimers();
 }
});
