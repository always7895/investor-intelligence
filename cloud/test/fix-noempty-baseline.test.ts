import { test, expect } from "vitest";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { buildBottleneckTop20Messages } from "../src/v213/bottleneck-v3";
import { optionsUnavailableReport } from "../src/v213/options-product";

const work=resolve(process.cwd(),"../..");
const cacheTop=resolve(work,"runtime/bottleneck_top20_v3.json");
const cacheOptions=resolve(work,"runtime/market_quotes_options.json");
// Explicit opt-in: prevents a normal CI run from overwriting the preserved v3.3.0 baseline.
const enabled=process.env.NOEMPTY_STAGE==="AFTER" && existsSync(cacheTop) && existsSync(cacheOptions);
const raw=enabled?JSON.parse(readFileSync(cacheTop,"utf8")):null;
const opts=enabled?JSON.parse(readFileSync(cacheOptions,"utf8")):null;
const bad=/未揭露|無法揭露|無法估價|暫不可用|尚未產生|需新訂單|^—$|^–$/u;
function textNodes(value:unknown,out:string[]=[]):string[]{
 if(Array.isArray(value)) for(const el of value) textNodes(el,out);
 else if(value && typeof value==="object"){
  const node=value as Record<string,unknown>;
  if(typeof node.text==="string")out.push(node.text);
  if(Array.isArray(node.contents))textNodes(node.contents,out);
  if(node.body)textNodes(node.body,out);
 }
 return out;
}
function metrics(rows:string[]){
 const at=(name:RegExp)=>rows.findIndex(x=>name.test(x));
 const get=(name:string,re:RegExp,afterLabel=false)=>{
   const i=at(re); const matched=i>=0?(rows[i]??""):"";
   const scenarioAt=name.startsWith("scenario") ? matched.indexOf("股價情境：") : -1;
   const value=scenarioAt>=0 ? matched.slice(scenarioAt+"股價情境：".length) : afterLabel ? (rows[i+1]??"") : matched.includes("：")?matched.slice(matched.indexOf("：")+1):matched;
   const empty=i<0 || value.trim().length===0 || bad.test(value) || !/[\d]/u.test(value);
   return {name,empty,label_found:i>=0};
 };
 return [
   get("market_6m",/^6個月\s*$/u,true),
   get("revenue_m6",/(?:半年內預計認列|^約半年(?:訂單認列|營收推估|趨勢推估|歷史推估|產業中位數推估)|^半年營收推估)/u),
   get("revenue_m12",/(?:1年內預計認列|^約1年(?:訂單認列|營收推估|趨勢推估|歷史推估|產業中位數推估)|^1年營收推估)/u),
   get("scenario_m6",/(?:^股價情境｜若半年|^若半年|半年股價情境|^約半年股價情境)/u),
   get("scenario_m12",/(?:^若1年|1年股價情境|^約1年股價情境)/u),
 ];
}
test.skipIf(!enabled)("current Top20 and monthly options AFTER are rendered from local runtime copies",()=>{
 if(!raw || !opts) throw new Error("MISSING_LOCAL_RUNTIME_PROBE");
 // Raw producer data isn't a sealed Worker object; read-only adaptation uses v3.3 renderer verbatim.
 const doc:any={generated_at:raw.generated_at,industries:raw.industries,deep_reports:{},
  top:raw.top.map((entry:any)=>({...entry,parts:entry.score_parts}))};
 const messages=buildBottleneckTop20Messages(doc,"flex");
 const cards=messages.flatMap((m:any)=>m.contents?.type==="carousel"?m.contents.contents:[]);
 expect(cards.length).toBe(21);
 const records=doc.top.map((entry:any,i:number)=>({symbol:entry.symbol,fields:metrics(textNodes(cards[i].body))}));
 const errors=records.flatMap((r:any)=>r.fields.filter((f:any)=>f.empty).map((f:any)=>({symbol:r.symbol,field:f.name,found:f.label_found})));
 const month=opts.options?.["SIVE.ST"]?.monthly;
 const unavailable=typeof month?.unavailable==="string"?month.unavailable:"";
 const optionText=optionsUnavailableReport("SIVE.ST","monthly",unavailable,true).map((m:any)=>m.text??"").join("\n");
 const stage=process.env.NOEMPTY_STAGE==="AFTER"?"AFTER":"BASELINE";
 const output={stage,input:"current runtime producer cache, read-only projection through v3.3.0 renderer",generated_at:raw.generated_at,
  top20_count:records.length,expected_fields:records.length*5,empty_count:errors.length,per_symbol:records,
  missing:errors,sive_monthly_line:optionText.slice(0,600),sive_unavailable:!!unavailable};
 writeFileSync(resolve(work,stage+".json"),JSON.stringify(output,null,2)+"\n");
 if(stage==="AFTER")expect(errors.length).toBe(0);
});
