# 네이버 부동산(new.land) API 스크래핑 레시피 — 2026-07 검증

> 요지: 네이버 부동산 API는 폐지되지 않았다. `new.land.naver.com`의 `/api/articles`·`/api/cortars`는 정상 작동한다. 단, 자동화 브라우저는 안티봇에 걸려 **토큰 발급에 실패**하므로 Playwright에 **스텔스 한 줄**을 추가하는 것이 관건이다.

## 살아있음 증거 (curl_cffi, `impersonate=chrome`)
- `new.land.naver.com/offices` → 200 (SPA HTML). `land.naver.com/` → 200.
- `/api/cortars?zoom=16&centerLat=&centerLon=` → **200 정상 JSON** (토큰 없이도, Referer만 있으면).
- `/api/articles?...` → 토큰 없으면 **429 TOO_MANY_REQUESTS**, Referer 없으면 **403 Invalid referrer**.
  → **404(폐지)가 아니라 게이트일 뿐이다.**

## 흔한 오진 2가지
1. **자동화 브라우저를 위장하지 않으면** new.land/offices SPA가 클라이언트단에서 `/404`로 튕겨서 `/api/*` 요청이 아예 안 나간다 → 토큰 발급 실패("TOKEN NO").
2. curl로 토큰 없이 호출해 나온 429/403을 SPA의 /404 튕김과 합쳐 "죽었다"고 성급히 결론내기 쉽다.

## 해결 (확정 레시피)
Playwright에 **스텔스**를 추가하면 토큰이 정상 캡처된다:

```python
b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
ctx = b.new_context(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    locale="ko-KR",
    extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"},
)
ctx.add_init_script(
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "window.chrome={runtime:{}};"
)
```

흐름:
1. `new.land.naver.com/offices` 로드 → 페이지가 스스로 `/api/cortars`를 호출.
2. `request.headers['authorization']`(Bearer 토큰)를 request 리스너로 캡처.
3. 그 토큰으로 **같은 페이지 컨텍스트에서** `pg.evaluate` fetch:
   `/api/articles?cortarNo=&order=rank&realEstateType=SG:SMS:GM&tradeType=B2&page=N` (`isMoreData`가 false일 때까지 루프).
   - 동일 페이지 컨텍스트에서 fetch하면 **쿠키가 자동 첨부**되어 429가 안 난다(토큰만 헤더로 보내면 429).

검증: 거여동(cortarNo=1171011300) 월세 매물 **400건 수신 성공**.

## 파라미터 코드
- **tradeType**: `A1`=매매 · `B1`=전세 · `B2`=월세
- **realEstateType**: `SG`=상가 · `SMS`=사무실 · `GM`=건물 · `TJ`=토지 · `GJCG`=공장창고 · `APTHGJ`=지식산업센터
- `e=RETAIL` = 상업용
- **cortarNo = 법정동코드** (예: 거여동 1171011300). 동별 cortarNo는
  `m.land.naver.com/map/getRegionList?cortarNo=<구코드>`로 확인.

## 참고
- `fin.land.naver.com`은 신규 Npay 부동산 앱(별개로 존재, 안티봇 강함). **옛 new.land가 멀쩡하므로 굳이 fin.land를 쓸 필요 없다.**
