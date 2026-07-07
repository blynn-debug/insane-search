const { chromium } = require('playwright');
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const PNU="ZyOqekN3XxE";
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const page = await (await browser.newContext({locale:'ko-KR', userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36'})).newPage();
  const jsonHits=[];
  page.on('response', async resp=>{
    const u=resp.url();
    if(/bdsplanet\.com/.test(u) && /\.ytp/.test(u)){
      const ct=resp.headers()['content-type']||'';
      if(/json/.test(ct)){ let t=''; try{t=await resp.text();}catch(e){} jsonHits.push({u, len:t.length, head:t.slice(0,120)}); }
    }
  });
  const urls=[
    `https://www.bdsplanet.com/sales/detail/realprice/${PNU}/D.ytp`,
    `https://www.bdsplanet.com/map/realprice_map.ytp?pnu=${PNU}`,
  ];
  for(const url of urls){
    await page.goto(url, {waitUntil:'networkidle', timeout:45000}).catch(e=>console.log('goto err', e.message));
    await page.waitForTimeout(3500);
    console.log("\n### after", url);
  }
  console.log("\n=== JSON .ytp XHRs ===");
  const seen=new Set();
  for(const h of jsonHits){ if(seen.has(h.u))continue; seen.add(h.u);
    console.log(`[${h.len}] ${h.u.replace('https://www.bdsplanet.com','')}\n   ${h.head.replace(/\s+/g,' ')}`); }
  await browser.close();
})();
