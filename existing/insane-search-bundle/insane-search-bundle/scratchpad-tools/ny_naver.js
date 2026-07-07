const { chromium } = require('playwright');
const fs = require('fs');
const OUT = "C:\\Users\\user\\AppData\\Local\\Temp\\claude\\C--Users-user-PycharmProjects-insane-search\\832e47d4-b1d9-4858-b3c9-070f0ccd5a10\\scratchpad\\ny\\naver.json";
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const CORTAR = "4136026521"; // 퇴계원리
const TYPES = "SG:SMS:GM:TJ:APTHGJ:GJCG";
// base62 encode for ms (coord*1e7 + 2e9)
const A="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
function enc(coord){let n=Math.round(coord*1e7)+2000000000,s="";if(n===0)return"0";while(n>0){s=A[n%62]+s;n=Math.floor(n/62);}return s;}
const ms = `${enc(37.64829)},${enc(127.14037)},15`;

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME });
  const ctx = await browser.newContext({ locale:'ko-KR',
    userAgent:'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    viewport:{width:1440,height:900}});
  const page = await ctx.newPage();
  let token=null;
  page.on('request',r=>{const a=r.headers()['authorization']; if(a&&!token)token=a;});
  const url=`https://new.land.naver.com/offices?ms=${ms}&a=SG:SMS:APTHGJ:GM:TJ&e=RETAIL`;
  console.log("URL",url);
  await page.goto(url,{waitUntil:'networkidle',timeout:60000}).catch(e=>console.log('goto',e.message));
  await page.waitForTimeout(3000);
  if(!token){console.log("NO TOKEN");await browser.close();return;}
  console.log("token ok");
  async function api(path){return await page.evaluate(async({path,token})=>{
    const r=await fetch("https://new.land.naver.com"+path,{headers:{'authorization':token,'accept':'application/json'}});
    let b=null;try{b=await r.json();}catch(e){b={_t:await r.text()};}return{status:r.status,body:b};},{path,token});}
  // discover real cortarNo at center
  const cz=await api(`/api/cortars?zoom=15&centerLat=37.64829&centerLon=127.14037`);
  console.log("CORTARS:",JSON.stringify(cz.body).slice(0,500));
  let cortar=CORTAR;
  if(cz.body&&cz.body.cortarNo)cortar=String(cz.body.cortarNo);
  console.log("using cortar",cortar);
  let arts={};
  for(const tt of ["","A1","B1","B2"]){
    for(let p=1;p<=25;p++){
      const q=`/api/articles?cortarNo=${cortar}&realEstateType=${TYPES}&order=rank&priceType=RETAIL&page=${p}`+(tt?`&tradeType=${tt}`:"");
      const{status,body}=await api(q);
      if(status!==200||!body||!body.articleList){console.log(`list ${tt||'ALL'} p${p} st=${status}`);break;}
      for(const a of body.articleList)arts[a.articleNo]=a;
      console.log(`list ${tt||'ALL'} p${p}: +${body.articleList.length} uniq${Object.keys(arts).length} more=${body.isMoreData}`);
      if(!body.isMoreData)break;
    }
  }
  const nos=Object.keys(arts); console.log("UNIQUE",nos.length);
  const det={}; let i=0;
  for(const no of nos){i++;const{status,body}=await api(`/api/articles/${no}?complexNo=`);det[no]=status===200?body:{_s:status};
    if(i%10===0)console.log(`detail ${i}/${nos.length}`);await page.waitForTimeout(110);}
  fs.writeFileSync(OUT,JSON.stringify({listMeta:arts,details:det},null,1),'utf-8');
  console.log("WROTE",OUT,"details",Object.keys(det).length);
  await browser.close();
})();
