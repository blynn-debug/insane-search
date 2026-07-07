const { chromium } = require('playwright');
const fs = require('fs');
const OUT = "C:\\Users\\user\\AppData\\Local\\Temp\\claude\\C--Users-user-PycharmProjects-insane-search\\832e47d4-b1d9-4858-b3c9-070f0ccd5a10\\scratchpad\\naver_out.json";
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const CORTAR = "5011012200"; // 노형동
// commercial types per memory: SG 상가, SMS 사무실, GM 건물, TJ 토지, APTHGJ 지산, GJCG 공장창고
const TYPES = "SG:SMS:GM:TJ:APTHGJ:GJCG";

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const ctx = await browser.newContext({
    locale: 'ko-KR',
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    viewport: { width: 1440, height: 900 },
  });
  const page = await ctx.newPage();
  let token = null;
  page.on('request', r => { const a = r.headers()['authorization']; if (a && !token) token = a; });
  // center on 노형동 (ms decode of original)
  const url = "https://new.land.naver.com/offices?ms=2y0EZ6,3yWIOW,16&a=SG:SMS:APTHGJ:GM:TJ&e=RETAIL";
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 }).catch(e=>console.log('goto:', e.message));
  await page.waitForTimeout(3000);
  if (!token) { console.log("NO TOKEN"); await browser.close(); return; }
  console.log("token ok");

  async function apiGet(path) {
    return await page.evaluate(async ({path, token}) => {
      const r = await fetch("https://new.land.naver.com" + path, {
        headers: { 'authorization': token, 'accept': 'application/json' }
      });
      const status = r.status;
      let body = null; try { body = await r.json(); } catch(e){ body = {_text: await r.text()}; }
      return { status, body };
    }, { path, token });
  }

  // 1) list articles across trade types (매매=A1, 전세=B1, 월세=B2) — articles endpoint returns all tradeTypes if omitted
  const tradeTypes = ["", "A1", "B1", "B2"];
  let articles = {};
  for (const tt of tradeTypes) {
    for (let pageNo = 1; pageNo <= 25; pageNo++) {
      const q = `/api/articles?cortarNo=${CORTAR}&realEstateType=${TYPES}` +
                `&order=rank&priceType=RETAIL&page=${pageNo}` +
                (tt ? `&tradeType=${tt}` : "");
      const { status, body } = await apiGet(q);
      if (status !== 200 || !body || !body.articleList) { console.log(`list ${tt||'ALL'} p${pageNo} status=${status}`); break; }
      for (const a of body.articleList) articles[a.articleNo] = a;
      const more = body.isMoreData;
      console.log(`list ${tt||'ALL'} p${pageNo}: +${body.articleList.length} (total uniq ${Object.keys(articles).length}) more=${more}`);
      if (!more) break;
    }
  }
  const articleNos = Object.keys(articles);
  console.log("UNIQUE ARTICLES:", articleNos.length);

  // 2) detail for each
  const details = {};
  let i = 0;
  for (const no of articleNos) {
    i++;
    const { status, body } = await apiGet(`/api/articles/${no}?complexNo=`);
    if (status === 200) details[no] = body;
    else details[no] = { _status: status };
    if (i % 10 === 0) console.log(`detail ${i}/${articleNos.length}`);
    await page.waitForTimeout(120);
  }

  fs.writeFileSync(OUT, JSON.stringify({ listMeta: articles, details }, null, 1), 'utf-8');
  console.log("WROTE", OUT, "details:", Object.keys(details).length);
  await browser.close();
})();
