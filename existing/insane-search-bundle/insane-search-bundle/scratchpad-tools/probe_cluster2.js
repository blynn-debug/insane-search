const { chromium } = require('playwright');
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const page = await (await browser.newContext({locale:'ko-KR', userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})).newPage();
  const urls=[];
  page.on('request', r=>{const u=r.url(); if(/\/api\/(articles\/clusters|regions|cortars)/.test(u)) urls.push(u);});
  // zoom 13 center 광주시청
  await page.goto(`https://new.land.naver.com/offices?ms=127.2507534,37.4291564,12&a=GM:SG&e=RETAIL&b=A1`, {waitUntil:'networkidle', timeout:60000}).catch(()=>{});
  await page.waitForTimeout(4000);
  for(const u of urls) console.log(u);
  await browser.close();
})();
