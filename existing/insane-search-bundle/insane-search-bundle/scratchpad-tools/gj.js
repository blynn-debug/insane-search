const { chromium } = require('playwright');
const fs = require('fs');
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const LAT = 37.5477996, LON = 127.1073716; // 광장동 336-7
const TYPES = "SG:SMS:GM"; // 근린생활시설: 상가/사무실/건물
const ALPH = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
function enc(c){ let n=Math.round(c*1e7)+2e9, s=""; while(n>0){ s=ALPH[n%62]+s; n=Math.floor(n/62);} return s; }
const MS = `${enc(LAT)},${enc(LON)},16`;
function hav(a,b,c,d){const R=6371000,t=Math.PI/180,dx=(c-a)*t,dy=(d-b)*t,la=a*t,lc=c*t;const h=Math.sin(dx/2)**2+Math.cos(la)*Math.cos(lc)*Math.sin(dy/2)**2;return 2*R*Math.asin(Math.sqrt(h));}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const page = await (await browser.newContext({locale:'ko-KR', userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})).newPage();
  let token=null; page.on('request', r=>{const a=r.headers()['authorization']; if(a&&!token)token=a;});
  await page.goto(`https://new.land.naver.com/offices?ms=${MS}&a=${TYPES}&e=RETAIL`, {waitUntil:'networkidle', timeout:60000}).catch(e=>{});
  await page.waitForTimeout(2500);
  if(!token){console.log("NO TOKEN"); await browser.close(); return;}
  const api = (p)=>page.evaluate(async({p,token})=>{const r=await fetch("https://new.land.naver.com"+p,{headers:{authorization:token,accept:'application/json'}});try{return await r.json();}catch(e){return null;}},{p,token});

  const cort = await api(`/api/cortars?zoom=16&centerLat=${LAT}&centerLon=${LON}`);
  const cortarNo = cort && cort.cortarNo;
  console.log("cortarNo", cortarNo);

  let arts = {};
  for(const tt of ["A1","B1","B2"]){
    for(let pg=1; pg<=15; pg++){
      const b = await api(`/api/articles?cortarNo=${cortarNo}&realEstateType=${TYPES}&order=rank&priceType=RETAIL&page=${pg}&tradeType=${tt}`);
      if(!b||!b.articleList){break;}
      for(const a of b.articleList) arts[a.articleNo]=a;
      if(!b.isMoreData) break;
    }
  }
  const all = Object.values(arts).map(a=>({...a, dist: (a.latitude&&a.longitude)?hav(LAT,LON,+a.latitude,+a.longitude):9999}));
  const near = all.filter(a=>a.dist<=300);
  console.log("TOTAL", all.length, "WITHIN300", near.length);
  fs.writeFileSync(process.argv[2], JSON.stringify(near,null,1),'utf-8');
  await browser.close();
})();
