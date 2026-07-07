const { chromium } = require('playwright');
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const LAT=37.4291564, LON=127.2507534;
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const page = await (await browser.newContext({locale:'ko-KR', userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})).newPage();
  let token=null; page.on('request', r=>{const a=r.headers()['authorization']; if(a&&!token)token=a;});
  await page.goto(`https://new.land.naver.com/offices?ms=${'2AVb4R'},${'3zkBSy'},13&a=GM:SG&e=RETAIL`, {waitUntil:'networkidle', timeout:60000}).catch(()=>{});
  await page.waitForTimeout(2500);
  const api = (p)=>page.evaluate(async({p,token})=>{const r=await fetch("https://new.land.naver.com"+p,{headers:{authorization:token,accept:'application/json'}});const s=r.status;let b=null;try{b=await r.json();}catch(e){b={_t:(await r.text()).slice(0,300)};}return{s,b};},{p,token});
  const bbox = `leftLon=${LON-0.113}&rightLon=${LON+0.113}&topLat=${LAT+0.09}&bottomLat=${LAT-0.09}`;
  const q = `/api/articles/clusters?cortarNo=0&zoom=13&priceType=RETAIL&realEstateType=GM%3ASG&tradeType=A1&${bbox}`;
  const {s,b} = await api(q);
  console.log("status", s);
  console.log(JSON.stringify(b).slice(0,2000));
  await browser.close();
})();
