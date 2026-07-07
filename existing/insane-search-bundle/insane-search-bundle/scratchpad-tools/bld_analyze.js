const a = require(process.argv[2]);
function won(s){ if(!s) return 0; let v=0; const m=s.match(/(\d+)\s*억/); if(m)v+=+m[1]*10000; const r=s.replace(/.*억/,'').replace(/[^\d]/g,''); if(r)v+=+r; return v; }
const med=arr=>{const s=[...arr].sort((x,y)=>x-y);return s.length?s[Math.floor(s.length/2)]:0;};
// area fields
const s0=a[0]; console.log("sample keys:", Object.keys(s0).filter(k=>/area|Area|Name|Type|dist|price|Prc/.test(k)).join(","));
console.log("sample:", JSON.stringify({t:s0.realEstateTypeName, nm:s0.articleName, a1:s0.area1, a2:s0.area2, p:s0.dealOrWarrantPrc, d:Math.round(s0.dist)}));

// GM = 건물(통건물). area1=대지, area2=연면적 (통상). 평당가 = 매매가/연면적평
const gm = a.filter(x=>x.realEstateTypeName && /건물/.test(x.realEstateTypeName));
const sgB = a.filter(x=>/상가/.test(x.realEstateTypeName||'') && /(빌딩|건물|상가건물|상업|통)/.test(x.articleName||''));
console.log("\nGM(건물) n=", gm.length, " | SG-통건물류 n=", sgB.length);

function rows(arr, areaPick){
  return arr.map(x=>{
    const area = areaPick(x);
    const py = area? area/3.3058 : 0;
    const price = won(x.dealOrWarrantPrc);
    return {nm:x.articleName, t:x.realEstateTypeName, area, py, price, ppp: py? price/py:0, d:Math.round(x.dist), cortar:x._cortar, raw:x.dealOrWarrantPrc};
  }).filter(r=>r.ppp>0 && r.py>=50); // 통건물급(50평↑)
}
// 연면적 기준: use max(area1,area2) as 연면적 proxy for buildings
const G = rows(gm, x=>Math.max(+x.area1||0,+x.area2||0)).filter(r=>r.ppp<30000); // drop garbage
const ppps = G.map(r=>r.ppp);
console.log("\n=== 통건물(건물) 평당가(만원/연면적평), 10km, 50평↑, n="+G.length+" ===");
console.log("최저", Math.round(Math.min(...ppps)), "25%", Math.round([...ppps].sort((a,b)=>a-b)[Math.floor(ppps.length*0.25)]), "중간", Math.round(med(ppps)), "75%", Math.round([...ppps].sort((a,b)=>a-b)[Math.floor(ppps.length*0.75)]), "최고", Math.round(Math.max(...ppps)));

// distance bands
for(const [lo,hi] of [[0,2000],[2000,5000],[5000,10000]]){
  const band=G.filter(r=>r.d>=lo&&r.d<hi).map(r=>r.ppp);
  if(band.length) console.log(`  ${lo/1000}~${hi/1000}km: 중간 ${Math.round(med(band))}만/평 (n=${band.length})`);
}
console.log("\n[가까운 통건물 매매 comp 12건]");
for(const r of G.sort((a,b)=>a.d-b.d).slice(0,12))
  console.log(`  ${String(r.d).padStart(4)}m | ${r.cortar} | ${r.nm} | 연면적 ${r.py.toFixed(0)}평 | ${r.raw} | ▶${Math.round(r.ppp)}만/평`);
console.log("\n[대형 통건물(300평↑) comp]");
for(const r of G.filter(r=>r.py>=300).sort((a,b)=>a.d-b.d).slice(0,12))
  console.log(`  ${String(r.d).padStart(4)}m | ${r.cortar} | ${r.nm} | 연면적 ${r.py.toFixed(0)}평 | ${r.raw} | ▶${Math.round(r.ppp)}만/평`);
