const { chromium } = require('playwright');
const fs=require('fs');
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const KEY="YOUR_KAKAO_REST_KEY";
const SP="C:\\Users\\user\\AppData\\Local\\Temp\\claude\\C--Users-user-PycharmProjects-insane-search\\cbcaeb30-f10c-4d2e-9e3c-9ca616c51173\\scratchpad\\";
const rows=JSON.parse(fs.readFileSync(SP+"rows.json","utf-8")).filter(x=>!x.filled && x.jibun);
const ALPH="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const enc=c=>{let n=Math.round(c*1e7)+2e9,s="";while(n>0){s=ALPH[n%62]+s;n=Math.floor(n/62);}return s;};
const hav=(a,b,c,d)=>{const R=6371000,t=Math.PI/180,dx=(c-a)*t,dy=(d-b)*t;return 2*R*Math.asin(Math.sqrt(Math.sin(dx/2)**2+Math.cos(a*t)*Math.cos(c*t)*Math.sin(dy/2)**2));};
const med=a=>{const s=[...a].sort((x,y)=>x-y);return s.length?s[Math.floor(s.length/2)]:0;};
const won=s=>{if(!s)return 0;let v=0;const m=s.match(/(\d+)\s*억/);if(m)v+=+m[1]*10000;const r=s.replace(/.*억/,'').replace(/[^\d]/g,'');if(r)v+=+r;return v;};
const TYPES="SG:SMS:GM";
async function geocode(q){
  for(const query of [q, q.replace(/만세구\s*/,''), q.replace(/\s*\S+구\s/,' ')]){
    try{const r=await fetch("https://dapi.kakao.com/v2/local/search/address.json?query="+encodeURIComponent(query),{headers:{Authorization:"KakaoAK "+KEY}});
      const d=(await r.json()).documents;if(d&&d[0])return {lat:+d[0].y,lon:+d[0].x,bcode:d[0].address.b_code};}catch(e){}
  }
  return null;
}
(async()=>{
 for(const x of rows){ x.geo=await geocode(x.jibun); }
 const browser=await chromium.launch({headless:true,executablePath:CHROME});
 const page=await(await browser.newContext({locale:'ko-KR',userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})).newPage();
 let token=null;page.on('request',r=>{const a=r.headers()['authorization'];if(a&&!token)token=a;});
 const g0=rows.find(x=>x.geo);
 await page.goto(`https://new.land.naver.com/offices?ms=${enc(g0.geo.lat)},${enc(g0.geo.lon)},15&a=${TYPES}&e=RETAIL`,{waitUntil:'networkidle',timeout:60000}).catch(()=>{});
 await page.waitForTimeout(2500);
 const api=p=>page.evaluate(async({p,token})=>{const r=await fetch("https://new.land.naver.com"+p,{headers:{authorization:token,accept:'application/json'}});try{return await r.json();}catch(e){return null;}},{p,token});
 for(const x of rows){
   if(!x.geo){x.salePpp=0;x.rentPpp=0;continue;}
   const g=x.geo;
   const cort=await api(`/api/cortars?zoom=16&centerLat=${g.lat}&centerLon=${g.lon}`);
   const cortarNo=cort&&cort.cortarNo; if(!cortarNo){x.salePpp=0;x.rentPpp=0;continue;}
   let arts={};
   for(const tt of["A1","B2"]){for(let pg=1;pg<=6;pg++){
     const b=await api(`/api/articles?cortarNo=${cortarNo}&realEstateType=${TYPES}&order=rank&priceType=RETAIL&page=${pg}&tradeType=${tt}`);
     if(!b||!b.articleList)break;for(const a of b.articleList)arts[a.articleNo]=a;if(!b.isMoreData)break;}}
   const all=Object.values(arts).map(a=>({...a,dist:(a.latitude&&a.longitude)?hav(g.lat,g.lon,+a.latitude,+a.longitude):9e9}));
   let rad=400,near=all.filter(a=>a.dist<=rad);
   while(near.length<6&&rad<1200){rad+=400;near=all.filter(a=>a.dist<=rad);}
   const sale=near.filter(a=>a.tradeTypeName==='매매'),rent=near.filter(a=>a.tradeTypeName==='월세');
   const sp=sale.map(a=>{const ar=+(a.area2||a.area1)||0,py=ar/3.3058;return py?won(a.dealOrWarrantPrc)/py:0;}).filter(v=>v>0&&v<40000);
   const rp=rent.map(a=>{const ar=+(a.area2||a.area1)||0,py=ar/3.3058;return py?won(a.rentPrc)/py:0;}).filter(v=>v>0&&v<300);
   x.rad=rad;x.salePpp=Math.round(med(sp));x.rentPpp=+med(rp).toFixed(1);x.nSale=sp.length;x.nRent=rp.length;
   console.log(`r${x.row} ${x.jibun} | b${g.bcode} r${rad} | 매매 ${x.salePpp}(n${sp.length}) 월세 ${x.rentPpp}(n${rp.length})`);
 }
 fs.writeFileSync(SP+"collected.json",JSON.stringify(rows,null,1));
 await browser.close();
})();
