const a = require(process.argv[2]);
const py = ar=> ar? ar/3.3058 : 0;
const rows = a.map(x=>({
  d: Math.round(x.dist), t: x.tradeTypeName, nm: x.articleName, fl: x.floorInfo,
  p: py(+(x.area2||x.area1)||0), deal: x.dealOrWarrantPrc, rent: x.rentPrc||''
})).sort((a,b)=>a.d-b.d);
for(const r of rows.slice(0, +process.argv[3]||14))
  console.log(`${String(r.d).padStart(3)}m | ${r.t} | ${r.nm} | ${r.fl} | ${r.p.toFixed(0)}평 | ${r.deal}${r.rent?' / '+r.rent:''}`);
