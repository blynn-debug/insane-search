---
name: naver-land-access
description: How to read new.land.naver.com (네이버페이 부동산) — ms coord encoding + internal JSON API. Candidate addition to references/naver.md.
metadata: 
  node_type: memory
  type: reference
  originSessionId: 1d13e8f5-d5b8-4afa-8b3b-201a8c4074be
---

`new.land.naver.com` is a React SPA: the HTML is an empty shell (`weak_ok`, ~42KB, title "네이버페이 부동산"), all data comes from an internal JSON API under `/api/`. This is the R7 (SPA+WAF) path: render once to capture the bearer token + internal endpoints, then replay with curl_cffi.

**URL `ms` param decode** (`ms=<lat>,<lon>,<zoom>`, e.g. `ms=2AVb4R,3zkBSy,15`):
- base62 alphabet is `0-9a-zA-Z` (lowercase before uppercase)
- `coord = (base62_decode(s) - 2_000_000_000) / 1e7`
- `2AVb4R`→37.7841041, `3zkBSy`→127.0482426, zoom=15. (Encode = inverse.)

**Query params**: `a=` real-estate types colon-joined (`SG`상가 `SMS`사무실 `GJCG`공장·창고 `APTHGJ`지식산업센터(아파트형공장) `GM`건물 `TJ`토지); `e=` → API `priceType` (`RETAIL`=상업용). Path `/offices` = 상업·업무용 섹션.

**Internal API** (all need `Authorization: Bearer <JWT>`; token is generated client-side, session+time scoped):
- `GET /api/cortars?zoom=&centerLat=&centerLon=` → region polygon + `cortarNo` (법정동 code, e.g. 4163010400)
- `GET /api/articles?cortarNo=&realEstateType=SG:SMS:...&tradeType=&priceType=RETAIL&page=1` → listing list (`articleList[]`: dealOrWarrantPrc, area1/2, tradeTypeName, articleFeatureDesc…), `isMoreData` for pagination. **No login needed.**
- `GET /api/articles/clusters?...&leftLon=&rightLon=&topLat=&bottomLat=` → map cluster counts. No login.
- `GET /api/developmentplan/{road,rail,station,jigu}/list` → overlays.
- `GET /api/interests/articles?...` → **requires login** (`errorCode.NotLogin`) — stop here per Boundaries.

Capture token via Playwright (`page.on('request', r => r.headers()['authorization'])`), then curl_cffi `impersonate="chrome"` with that token + `Referer: https://new.land.naver.com/...` replays `/api/articles` directly (verified: HTTP 200, real listings). See [[insane-search-engine]] R7.
