const a = require(process.argv[2]);
function won(s){ if(!s) return 0; let v=0; const m=s.match(/(\d+)\s*억/); if(m)v+=+m[1]*10000; const r=s.replace(/.*억/,'').replace(/[^\d]/g,''); if(r)v+=+r; return v; } // 만원
const py = ar=> ar? ar/3.3058 : 0;
const med = arr=>{const s=[...arr].sort((x,y)=>x-y); return s.length? s[Math.floor(s.length/2)]:0;};
const sale=[], rent=[];
for(const x of a){
  const area=+(x.area2||x.area1)||0; const p=py(area); if(!p) continue;
  if(x.tradeTypeName==='매매'){ sale.push({nm:x.articleName,fl:x.floorInfo,p,ppp:won(x.dealOrWarrantPrc)/p, raw:x.dealOrWarrantPrc, d:Math.round(x.dist)}); }
  else if(x.tradeTypeName==='월세'){ rent.push({nm:x.articleName,fl:x.floorInfo,p, dep:won(x.dealOrWarrantPrc)/p, mon:won(x.rentPrc)/p, raw:x.dealOrWarrantPrc+'/'+x.rentPrc, d:Math.round(x.dist)}); }
}
const salePpp = sale.map(s=>s.ppp).filter(v=>v>0);
const monPp = rent.map(r=>r.mon).filter(v=>v>0);
const depPp = rent.map(r=>r.dep);
const medSale=med(salePpp), medMon=med(monPp), medDep=med(depPp);
console.log("매매 n="+sale.length+"  월세 n="+rent.length);
console.log("매매 평당가(만원): 최저",Math.round(Math.min(...salePpp)),"중간",Math.round(medSale),"최고",Math.round(Math.max(...salePpp)));
console.log("월세 평당 월세(만원): 최저",(Math.min(...monPp)).toFixed(1),"중간",medMon.toFixed(1),"최고",(Math.max(...monPp)).toFixed(1));
console.log("월세 평당 보증금(만원): 중간",medDep.toFixed(0));
const gross = (medMon*12)/medSale*100;
const adj = (medMon*12)/(medSale-medDep)*100;
console.log("\n=== 월세 수익률(중간값 기준) ===");
console.log("Gross(보증금 무시): "+gross.toFixed(2)+"%");
console.log("보증금 차감 후: "+adj.toFixed(2)+"%");
console.log("\n층별 1층(상가) vs 상층(사무실) 평당월세:");
const f1=rent.filter(r=>/^1\//.test(r.fl)).map(r=>r.mon).filter(v=>v>0);
const up=rent.filter(r=>!/^B|^1\//.test(r.fl)).map(r=>r.mon).filter(v=>v>0);
console.log("  1층 중간 "+med(f1).toFixed(1)+"만/평 (n="+f1.length+")");
console.log("  상층 중간 "+med(up).toFixed(1)+"만/평 (n="+up.length+")");
console.log("\n[매매 샘플]");
for(const s of sale.sort((x,y)=>x.d-y.d).slice(0,6)) console.log("  "+s.d+"m "+s.nm+" "+s.fl+" "+s.p.toFixed(0)+"평 "+s.raw+"  ▶"+Math.round(s.ppp)+"만/평");
console.log("[월세 샘플]");
for(const r of rent.sort((x,y)=>x.d-y.d).slice(0,8)) console.log("  "+r.d+"m "+r.nm+" "+r.fl+" "+r.p.toFixed(0)+"평 "+r.raw+"  ▶월"+r.mon.toFixed(1)+"만/평");
