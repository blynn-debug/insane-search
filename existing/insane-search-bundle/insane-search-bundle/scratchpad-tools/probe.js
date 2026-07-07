const { chromium } = require('playwright');
(async () => {
  const url = "https://new.land.naver.com/offices?ms=2AVb4R,3zkBSy,15&a=SG:SMS:GJCG:APTHGJ:GM:TJ&e=RETAIL";
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    locale: 'ko-KR',
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    viewport: { width: 1440, height: 900 },
  });
  const page = await ctx.newPage();
  const api = [];
  page.on('request', r => {
    const u = r.url();
    if (/\/api\/|graphql|\.json/.test(u) && /naver/.test(u)) {
      api.push({ method: r.method(), url: u, auth: r.headers()['authorization'] || null });
    }
  });
  const apiResp = {};
  page.on('response', async resp => {
    const u = resp.url();
    if (/new\.land\.naver\.com\/api\//.test(u)) {
      try { apiResp[u] = (await resp.text()).slice(0, 1500); } catch(e){}
    }
  });
  await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 }).catch(e=>console.log('goto:', e.message));
  await page.waitForTimeout(3000);
  console.log("=== FINAL URL ===");
  console.log(page.url());
  console.log("\n=== API REQUESTS (naver) ===");
  for (const a of api) console.log(`${a.method} ${a.url}${a.auth ? '  [AUTH:'+a.auth.slice(0,20)+'...]' : ''}`);
  console.log("\n=== sample API responses ===");
  for (const [u, body] of Object.entries(apiResp).slice(0, 6)) {
    console.log("\n--- " + u + "\n" + body);
  }
  await browser.close();
})();
