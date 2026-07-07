const a = require(process.argv[2]);
const g = {};
for (const x of a) { const t = x.tradeTypeName; (g[t]=g[t]||[]).push(x); }
function won(s){ if(!s) return 0; let v=0; const m=s.match(/(\d+)억/); if(m)v+=+m[1]*10000; const r=s.replace(/.*억/,'').replace(/[^\d]/g,''); if(r)v+=+r; return v; }
function pyung(area){ return area? area/3.3058 : 0; }
for (const t of Object.keys(g)) {
  console.log("\n=== " + t + " (" + g[t].length + "건) ===");
  const rows = g[t].map(x=>{
    const area = +(x.area2||x.area1)||0;
    const py = pyung(area);
    const deal = won(x.dealOrWarrantPrc);
    const rent = x.rentPrc? won(x.rentPrc): 0;
    const ppp = (t==='매매' && py) ? Math.round(deal/py) : 0; // 평당 만원
    return {nm:x.articleName, fl:x.floorInfo, area:area.toFixed(0), py:py.toFixed(1), deal:x.dealOrWarrantPrc, rent:x.rentPrc||'', ppp, d:Math.round(x.dist)};
  });
  // 평당가 통계 (매매)
  const ppps = rows.filter(r=>r.ppp>0).map(r=>r.ppp).sort((a,b)=>a-b);
  if(ppps.length){ const med=ppps[Math.floor(ppps.length/2)]; console.log(`  평당 매매가(만원): 최저 ${ppps[0]} / 중간 ${med} / 최고 ${ppps[ppps.length-1]}  (n=${ppps.length})`); }
  for (const r of rows.slice(0,8)) console.log(`  ${r.d}m ${r.nm} ${r.fl} 전용${r.area}㎡(${r.py}평) ${r.deal}${r.rent?'/'+r.rent:''}${r.ppp?'  ▶'+r.ppp+'만/평':''}`);
}
