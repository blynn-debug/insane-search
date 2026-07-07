const { chromium } = require('playwright');
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const ALPH="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const enc=c=>{let n=Math.round(c*1e7)+2e9,s="";while(n>0){s=ALPH[n%62]+s;n=Math.floor(n/62);}return s;};
const LAT=37.4291564, LON=127.2507534;
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const page = await (await browser.newContext({locale:'ko-KR', userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})).newPage();
  const clusters=[];
  page.on('request', r=>{const u=r.url(); if(/\/api\/articles\/clusters/.test(u)) clusters.push(u);});
  const ms=`${enc(LAT)},${enc(LON)},12`;
  await page.goto(`https://new.land.naver.com/offices?ms=${ms}&a=GM:SG&e=RETAIL&b=A1`, {waitUntil:'networkidle', timeout:60000}).catch(()=>{});
  await page.waitForTimeout(4000);
  console.log("N clusters req", clusters.length);
  if(clusters[0]) console.log(decodeURIComponent(clusters[0]));
  await browser.close();
})();
