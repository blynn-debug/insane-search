const { chromium } = require('playwright');
const fs=require('fs');
const CHROME = process.env.USERPROFILE + "\\AppData\\Local\\ms-playwright\\chromium-1208\\chrome-win64\\chrome.exe";
const KEY="YOUR_KAKAO_REST_KEY";
const TARGETS=[
 ["신길동 856(여의대방로207)","서울 영등포구 신길동 856"],
 ["퇴계원리 311-1(퇴계원로13)","경기 남양주시 퇴계원읍 퇴계원리 311-1"],
 ["장곡동 904-2 장현노블레스","경기 시흥시 장곡동 904-2"],
 ["주교동 608-4(고양대로1337)","경기 고양시 덕양구 주교동 608-4"],
 ["여의도동 81-8(여의서로160)","서울 영등포구 여의도동 81-8"],
 ["송정동 362-25(행정타운로68)","경기 광주시 송정동 362-25"],
];
const ALPH="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const enc=c=>{let n=Math.round(c*1e7)+2e9,s="";while(n>0){s=ALPH[n%62]+s;n=Math.floor(n/62);}return s;};
function hav(a,b,c,d){const R=6371000,t=Math.PI/180,dx=(c-a)*t,dy=(d-b)*t;return 2*R*Math.asin(Math.sqrt(Math.sin(dx/2)**2+Math.cos(a*t)*Math.cos(c*t)*Math.sin(dy/2)**2));}
const med=a=>{const s=[...a].sort((x,y)=>x-y);return s.length?s[Math.floor(s.length/2)]:0;};
const won=s=>{if(!s)return 0;let v=0;const m=s.match(/(\d+)\s*억/);if(m)v+=+m[1]*10000;const r=s.replace(/.*억/,'').replace(/[^\d]/g,'');if(r)v+=+r;return v;};
const TYPES="SG:SMS:GM";
(async()=>{
 const geo=[];
 for(const [nm,q] of TARGETS){
   const r=await fetch("https://dapi.kakao.com/v2/local/search/address.json?query="+encodeURIComponent(q),{headers:{Authorization:"KakaoAK "+KEY}});
   const d=(await r.json()).documents[0];
   geo.push({nm, lat:+d.y, lon:+d.x, bcode:d.address.b_code});
 }
 const browser=await chromium.launch({headless:true,executablePath:CHROME});
 const page=await(await browser.newContext({locale:'ko-KR',userAgent:'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'})).newPage();
 let token=null;page.on('request',r=>{const a=r.headers()['authorization'];if(a&&!token)token=a;});
 await page.goto(`https://new.land.naver.com/offices?ms=${enc(geo[0].lat)},${enc(geo[0].lon)},15&a=${TYPES}&e=RETAIL`,{waitUntil:'networkidle',timeout:60000}).catch(()=>{});
 await page.waitForTimeout(2500);
 const api=p=>page.evaluate(async({p,token})=>{const r=await fetch("https://new.land.naver.com"+p,{headers:{authorization:token,accept:'application/json'}});try{return await r.json();}catch(e){return null;}},{p,token});
 const out=[];
 for(const g of geo){
   const cort=await api(`/api/cortars?zoom=16&centerLat=${g.lat}&centerLon=${g.lon}`);
   const cortarNo=cort&&cort.cortarNo;
   let arts={};
   for(const tt of["A1","B2"]){for(let pg=1;pg<=10;pg++){
     const b=await api(`/api/articles?cortarNo=${cortarNo}&realEstateType=${TYPES}&order=rank&priceType=RETAIL&page=${pg}&tradeType=${tt}`);
     if(!b||!b.articleList)break;for(const a of b.articleList)arts[a.articleNo]=a;if(!b.isMoreData)break;}}
   const all=Object.values(arts).map(a=>({...a,dist:(a.latitude&&a.longitude)?hav(g.lat,g.lon,+a.latitude,+a.longitude):9e9}));
   // nearest-first: take within expanding radius until enough
   let rad=300; let near=all.filter(a=>a.dist<=rad);
   while(near.length<8 && rad<1500){rad+=300;near=all.filter(a=>a.dist<=rad);}
   const sale=near.filter(a=>a.tradeTypeName==='매매'), rent=near.filter(a=>a.tradeTypeName==='월세');
   const salePpp=sale.map(a=>{const ar=+(a.area2||a.area1)||0;const py=ar/3.3058;return py?won(a.dealOrWarrantPrc)/py:0;}).filter(v=>v>0&&v<40000);
   const rentPpp=rent.map(a=>{const ar=+(a.area2||a.area1)||0;const py=ar/3.3058;return py?won(a.rentPrc)/py:0;}).filter(v=>v>0&&v<200);
   out.push({nm:g.nm,bcode:g.bcode,rad,nSale:salePpp.length,nRent:rentPpp.length,salePpp:Math.round(med(salePpp)),rentPpp:+med(rentPpp).toFixed(1)});
 }
 fs.writeFileSync(process.argv[2],JSON.stringify({geo,out},null,1));
 for(const o of out)console.log(`${o.nm} | r${o.rad}m | 매매 ${o.salePpp}만/평(n${o.nSale}) | 월세 ${o.rentPpp}만/평(n${o.nRent}) | b_code ${o.bcode}`);
 await browser.close();
})();
