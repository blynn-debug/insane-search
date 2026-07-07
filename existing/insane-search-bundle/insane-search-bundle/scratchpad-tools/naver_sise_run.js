const { chromium } = require('playwright');
const fs = require('fs');
const CHROME = (process.env.USERPROFILE).replace(/\\/g,'/') + "/AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe";
const SCR = (process.env.USERPROFILE).replace(/\\/g,'/') + "/AppData/Local/Temp/claude/C--Users-user-PycharmProjects-insane-search/b8a6fed3-a188-4b45-a8d0-32eaf5dc520f/scratchpad";
const dongs = JSON.parse(fs.readFileSync(SCR+"/dongs.json","utf-8"));
const OUT = SCR+"/sise_out.json";

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const ctx = await browser.newContext({ locale:'ko-KR',
    userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    viewport:{width:1440,height:900}});
  const page = await ctx.newPage();
  let token=null;
  page.on('request', r=>{const a=r.headers()['authorization']; if(a&&!token)token=a;});
  await page.goto("https://new.land.naver.com/houses?ms=37.5,127.0,16",{waitUntil:'networkidle',timeout:60000}).catch(e=>console.log('goto',e.message));
  await page.waitForTimeout(2500);
  if(!token){console.log("NO TOKEN");await browser.close();return;}
  console.log("TOKEN OK");

  // fetch cortarNo + all types' 매매 articles for one dong in a single evaluate (parallel)
  async function fetchDong(d){
    const ev = page.evaluate(async ({d,token})=>{
      const base="https://new.land.naver.com";
      const g=async(p)=>{try{
        const r=await fetch(base+p,{headers:{authorization:token,accept:'application/json'},signal:AbortSignal.timeout(8000)});
        if(r.status!==200)return null;return await r.json();
      }catch(e){return null;}};
      const c=await g(`/api/cortars?zoom=16&centerLat=${d.lat}&centerLon=${d.lon}`);
      const cortarNo = c && c.cortarNo;
      const res={cortarNo, types:{}};
      if(!cortarNo) return res;
      await Promise.all(d.types.map(async t=>{
        const a=await g(`/api/articles?cortarNo=${cortarNo}&realEstateType=${t}&tradeType=A1&page=1`);
        res.types[t]=((a&&a.articleList)||[]).map(x=>x.dealOrWarrantPrc);
      }));
      return res;
    },{d,token});
    // Node-side safety timeout so a hung evaluate can't stall the whole run
    return await Promise.race([ev, new Promise(res=>setTimeout(()=>res(null),25000))]);
  }
  function parseManwon(s){
    if(!s) return null; s=(''+s).replace(/\s/g,'');
    let man=0; const m=s.match(/([\d,]+)억/); if(m) man+=parseInt(m[1].replace(/,/g,''))*10000;
    const rest=s.replace(/[\d,]+억/,''); const r=rest.match(/([\d,]+)/); if(r) man+=parseInt(r[1].replace(/,/g,''));
    return man||null;
  }
  function median(arr){ if(!arr.length)return null; const a=arr.slice().sort((x,y)=>x-y); const m=Math.floor(a.length/2); return a.length%2?a[m]:Math.round((a[m-1]+a[m])/2); }

  const keys=Object.keys(dongs);
  const out={};
  let done=0, t0=Date.now();
  for(const dc of keys){
    let r=null;
    for(let att=0;att<2 && !r;att++){ try{ r=await fetchDong(dongs[dc]); }catch(e){ r=null; await page.waitForTimeout(300);} }
    out[dc]={cortarNo:r&&r.cortarNo, types:{}};
    if(r&&r.types){
      for(const t of Object.keys(r.types)){
        const vals=r.types[t].map(parseManwon).filter(v=>v&&v>=1000&&v<=1000000); // 1천만~100억 만원
        out[dc].types[t]={median_manwon:median(vals), count:vals.length};
      }
    }
    done++;
    if(done%20===0){ fs.writeFileSync(OUT,JSON.stringify(out)); console.log(`  ${done}/${keys.length}  ${((Date.now()-t0)/1000).toFixed(0)}s`); }
    await page.waitForTimeout(60);
  }
  fs.writeFileSync(OUT,JSON.stringify(out));
  console.log("DONE dongs",Object.keys(out).length,"time",((Date.now()-t0)/1000).toFixed(0),"s");
  await browser.close();
})();
