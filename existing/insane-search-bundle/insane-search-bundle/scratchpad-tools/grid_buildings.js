const { chromium } = require('playwright');
const fs = require('fs');
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const OUT = process.argv[2];
const LAT=37.4291564, LON=127.2507534, RAD=10000;
const ALPH="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const enc=c=>{let n=Math.round(c*1e7)+2e9,s="";while(n>0){s=ALPH[n%62]+s;n=Math.floor(n/62);}return s;};
function hav(a,b,c,d){const R=6371000,t=Math.PI/180,dx=(c-a)*t,dy=(d-b)*t,la=a*t,lc=c*t;const h=Math.sin(dx/2)**2+Math.cos(la)*Math.cos(lc)*Math.sin(dy/2)**2;return 2*R*Math.asin(Math.sqrt(h));}
const TYPES="GM:SG"; // 건물 + 상가(통매매 포함)

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const page = await (await browser.newContext({locale:'ko-KR', userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})).newPage();
  let token=null; page.on('request', r=>{const a=r.headers()['authorization']; if(a&&!token)token=a;});
  await page.goto(`https://new.land.naver.com/offices?ms=${enc(LAT)},${enc(LON)},14&a=${TYPES}&e=RETAIL&b=A1`, {waitUntil:'networkidle', timeout:60000}).catch(()=>{});
  await page.waitForTimeout(2500);
  if(!token){console.log("NO TOKEN");await browser.close();return;}
  const api=(p)=>page.evaluate(async({p,token})=>{const r=await fetch("https://new.land.naver.com"+p,{headers:{authorization:token,accept:'application/json'}});try{return await r.json();}catch(e){return null;}},{p,token});

  // 1) grid → unique cortarNo
  const cortars={};
  const dLat=0.018, dLon=0.020; // ~2km steps
  for(let la=LAT-0.092; la<=LAT+0.092; la+=dLat){
    for(let lo=LON-0.115; lo<=LON+0.115; lo+=dLon){
      if(hav(LAT,LON,la,lo)>RAD+1500) continue;
      const c=await api(`/api/cortars?zoom=16&centerLat=${la.toFixed(6)}&centerLon=${lo.toFixed(6)}`);
      if(c&&c.cortarNo) cortars[c.cortarNo]={no:c.cortarNo,name:c.cortarName,lat:c.centerLat,lon:c.centerLon};
    }
  }
  const list=Object.values(cortars);
  console.log("unique cortars:", list.length);

  // 2) articles per cortar (매매만)
  let arts={};
  for(const c of list){
    for(let pg=1; pg<=10; pg++){
      const b=await api(`/api/articles?cortarNo=${c.no}&realEstateType=${TYPES}&order=rank&priceType=RETAIL&page=${pg}&tradeType=A1`);
      if(!b||!b.articleList){break;}
      for(const a of b.articleList) arts[a.articleNo]={...a, _cortar:c.name};
      if(!b.isMoreData) break;
    }
  }
  const all=Object.values(arts).map(a=>({...a, dist:(a.latitude&&a.longitude)?hav(LAT,LON,+a.latitude,+a.longitude):9999}));
  const near=all.filter(a=>a.dist<=RAD);
  console.log("매매 articles total", all.length, "within10km", near.length);
  fs.writeFileSync(OUT, JSON.stringify(near,null,1),'utf-8');
  await browser.close();
})();
