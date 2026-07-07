const { chromium } = require('playwright');
(async () => {
  const articleNo = "2633661320";
  const url = "https://new.land.naver.com/offices?ms=2y0EZ6,3yWIOW,17&a=SG:SMS:APTHGJ:GM:TJ&b=A1:B2&e=RETAIL&articleNo=" + articleNo;
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe" });
  const ctx = await browser.newContext({
    locale: 'ko-KR',
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    viewport: { width: 1440, height: 900 },
  });
  const page = await ctx.newPage();
  let token = null;
  const captured = {};
  page.on('request', r => {
    const a = r.headers()['authorization'];
    if (a && !token) token = a;
  });
  page.on('response', async resp => {
    const u = resp.url();
    if (/new\.land\.naver\.com\/api\/articles\//.test(u)) {
      try { captured[u] = await resp.json(); } catch(e){}
    }
  });
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 }).catch(e=>console.log('goto:', e.message));
  await page.waitForTimeout(3500);

  // If detail not captured by passive nav, replay with token
  let detail = captured[Object.keys(captured).find(k=>k.includes('/api/articles/'+articleNo)) || ''];
  if (!detail && token) {
    detail = await page.evaluate(async ({articleNo, token}) => {
      const r = await fetch('https://new.land.naver.com/api/articles/'+articleNo+'?complexNo=', {
        headers: { 'authorization': token, 'accept': 'application/json' }
      });
      return await r.json();
    }, { articleNo, token });
  }
  console.log("TOKEN_PRESENT=" + !!token);
  console.log("CAPTURED_KEYS=" + JSON.stringify(Object.keys(captured)));
  console.log("=====DETAIL_JSON=====");
  console.log(JSON.stringify(detail, null, 2));
  await browser.close();
})();
