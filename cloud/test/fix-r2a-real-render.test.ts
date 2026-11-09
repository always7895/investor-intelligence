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
       const nonstandard=period==="monthly" && valid?.monthly_nonstandard===true;
       rows.push({symbol:ticker,period,method,expiry:raw?.expiry??null,has_csp:!!raw?.strategies?.csp&&!raw.strategies.csp.unavailable,
         has_collar:!!raw?.strategies?.collar&&!raw.strategies.collar.unavailable,
         monthly_line_present:period==="monthly" ? text.includes("每月期權") : false,
         monthly_nonstandard:nonstandard,
         monthly_nonstandard_labeled:nonstandard && text.includes("非標準月到期 "+raw.expiry),
         monthly_nonstandard_order_error:nonstandard && text.includes("建議賣出限價"),
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
     monthly_nonstandard_labeled: rows.filter(row=>row.monthly_nonstandard_labeled).length,
     monthly_nonstandard_order_error: rows.filter(row=>row.monthly_nonstandard_order_error).length,
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
     expect(summary.monthly_line_present).toBe(summary.monthly_symbols);
     expect(summary.monthly_nonstandard_labeled).toBe(summary.monthly_nonstandard);
     expect(summary.monthly_nonstandard_order_error).toBe(0);
   }
 }finally{
   vi.useRealTimers();
 }
});
