const { chromium } = require('playwright');
const CHROME = (process.env.USERPROFILE).replace(/\\/g,'/') + "/AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe";
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const ctx = await browser.newContext({ locale:'ko-KR',
    userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    viewport:{width:1440,height:900}});
  const page = await ctx.newPage();
  let token=null;
  page.on('request', r=>{const a=r.headers()['authorization']; if(a&&!token)token=a;});
  await page.goto("https://new.land.naver.com/houses?ms=37.4896293,126.9418427,16", {waitUntil:'networkidle',timeout:60000}).catch(e=>console.log('goto',e.message));
  await page.waitForTimeout(2500);
  if(!token){console.log("NO TOKEN"); await browser.close(); return;}
  console.log("TOKEN OK");
  async function api(path){
    return await page.evaluate(async ({path,token})=>{
      const r=await fetch("https://new.land.naver.com"+path,{headers:{authorization:token,accept:'application/json'}});
      let b=null; try{b=await r.json()}catch(e){b={_t:await r.text()}}
      return {status:r.status,body:b};
    },{path,token});
  }
  // cortars for center
  const c=await api("/api/cortars?zoom=16&centerLat=37.4896293&centerLon=126.9418427");
  console.log("CORTARS status",c.status,"keys",Object.keys(c.body));
  console.log(JSON.stringify(c.body).slice(0,500));
  const cortarNo = c.body.cortarNo || (c.body.cortarList&&c.body.cortarList[0]&&c.body.cortarList[0].cortarNo);
  console.log("cortarNo=",cortarNo);
  // articles VL 매매
  const a=await api(`/api/articles?cortarNo=${cortarNo}&realEstateType=VL&tradeType=A1&page=1`);
  console.log("ARTICLES status",a.status,"keys",Object.keys(a.body));
  const arts=a.body.articleList||[];
  console.log("count",arts.length,"isMore",a.body.isMoreData);
  if(arts[0]) console.log("SAMPLE ART keys:",Object.keys(arts[0]));
  arts.slice(0,4).forEach(x=>console.log("  ",x.realEstateTypeName,"|",x.dealOrWarrantPrc,"|area1",x.area1,"area2",x.area2,"|",x.articleName));
  await browser.close();
})();
