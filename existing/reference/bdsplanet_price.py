"""
부동산플래닛(bdsplanet) 공시가격 조회 스크래퍼
- 주소 + 동/호 입력 → 공시가격(pblntfpc) 추출

API 플로우:
  1) 카카오 주소 검색 → WGS84 좌표 + 건물명
  2) WGS84 → EPSG:5179 좌표 변환
  3) bdsplanet landArea API → pnu (건물 고유ID) 획득
  4) bdsplanet officialPriceDetailInfo API → honm 매칭 → pblntfpc 추출
"""

import requests
import urllib.parse
from pyproj import Transformer

# ============================================================
# 설정
# ============================================================
KAKAO_API_KEY = "YOUR_KAKAO_REST_KEY"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bdsplanet.com/",
    "Accept": "*/*",
}

# 좌표 변환기: WGS84(경위도) → EPSG:5179(한국 TM)
transformer = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


# ============================================================
# Step 1: 카카오 주소 검색 API
# ============================================================
def kakao_search_address(address: str) -> dict | None:
    """
    주소 텍스트로 카카오 API 검색
    반환: {"x": lon, "y": lat, "building_name": "더빌", "address_name": "...", ...}
    """
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    params = {"query": address}

    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    docs = data.get("documents", [])
    if not docs:
        print(f"[✗] 카카오 주소 검색 결과 없음: {address}")
        return None

    doc = docs[0]
    result = {
        "x": float(doc["x"]),             # 경도 (WGS84)
        "y": float(doc["y"]),             # 위도 (WGS84)
        "address_name": doc.get("address_name", ""),
    }

    # 도로명주소에서 건물명 추출
    road = doc.get("road_address")
    if road:
        result["building_name"] = road.get("building_name", "")
        result["road_address"] = road.get("address_name", "")
    else:
        result["building_name"] = ""
        result["road_address"] = ""

    print(f"[✓] 카카오 주소 검색 완료")
    print(f"    지번: {result['address_name']}")
    print(f"    도로명: {result['road_address']}")
    print(f"    건물명: {result['building_name']}")
    print(f"    좌표: ({result['x']}, {result['y']})")

    return result


# ============================================================
# Step 2: 좌표 변환 (WGS84 → EPSG:5179)
# ============================================================
def convert_to_epsg5179(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 경위도 → EPSG:5179 (한국 TM) 변환"""
    x5179, y5179 = transformer.transform(lon, lat)
    print(f"[✓] 좌표 변환: WGS84({lon}, {lat}) → EPSG:5179(lng={x5179:.4f}, lat={y5179:.4f})")
    return x5179, y5179  # lng, lat 순서


# ============================================================
# Step 3: bdsplanet landArea API → pnu 획득
# ============================================================
def get_land_area(lng_5179: float, lat_5179: float) -> dict | None:
    """
    EPSG:5179 좌표로 토지 정보 조회 → pnu (건물ID) 획득
    ※ bdsplanet URL에서 lat/lng 파라미터명이 실제 좌표와 반대임 주의
       lat= 파라미터에 y5179(northing) 값, lng= 파라미터에 x5179(easting) 값
    """
    url = "https://www.bdsplanet.com/sales/detail/realprice/plg/landArea.ytp"
    params = {"lat": lat_5179, "lng": lng_5179}

    resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    polygon_c = data.get("polygonC")
    if not polygon_c:
        print(f"[✗] 토지 정보 없음 (좌표: {lat_5179}, {lng_5179})")
        return None

    pnu = polygon_c.get("pnu", "")
    eais_pk = polygon_c.get("eais_pk", "")
    origin_pnu = data.get("origin_pnu", "")

    print(f"[✓] 토지 정보 조회 완료")
    print(f"    PNU: {pnu}")
    print(f"    EAIS_PK: {eais_pk}")
    print(f"    원본 PNU: {origin_pnu}")

    return {"pnu": pnu, "eais_pk": eais_pk, "origin_pnu": origin_pnu}


# ============================================================
# Step 4: 공시가격 상세 조회 → honm 매칭 → pblntfpc 추출
# ============================================================
def get_official_price(pnu: str, dongnm: str = "", honm: str = None) -> dict | None:
    """
    공시가격 상세 조회

    Args:
        pnu: 건물 고유 ID (landArea에서 획득)
        dongnm: 동명 (건물명 또는 동명, 단일동이면 빈 문자열 가능)
        honm: 호명 (예: "203"). None이면 전체 호 반환

    Returns:
        honm 지정 시 → 해당 호 정보 dict
        honm 미지정 시 → 전체 호 리스트
    """
    url = f"https://www.bdsplanet.com/sales/detail/realprice/officialPriceDetailInfo/{pnu}/D.ytp"
    params = {}
    if dongnm:
        params["dongnm"] = dongnm

    resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    detail_info = data.get("detailInfo", [])
    date_info = data.get("dateInfo", {})

    if not detail_info:
        print(f"[✗] 공시가격 정보 없음 (PNU: {pnu})")
        return None

    print(f"[✓] 공시가격 조회 완료 — 총 {len(detail_info)}개 호실")

    # 날짜 정보
    gong_date = date_info.get("gongDate", {}).get("gongdate", "")
    assum_date = date_info.get("assumDate", "")
    print(f"    공시일: {gong_date} | AI추정일: {assum_date}")

    if honm is not None:
        # 특정 호 매칭
        target_honm = str(honm)
        matched = [d for d in detail_info if str(d.get("honm", "")) == target_honm]

        if not matched:
            print(f"[✗] '{target_honm}'호 매칭 실패. 존재하는 호:")
            for d in detail_info:
                print(f"       {d.get('honm')}호 (공시가: {d.get('pblntfpc'):,.0f}원)")
            return None

        unit = matched[0]
        result = _format_unit(unit, gong_date, assum_date)
        _print_unit(result)
        return result
    else:
        # 전체 호 반환
        results = []
        for unit in detail_info:
            r = _format_unit(unit, gong_date, assum_date)
            results.append(r)
            _print_unit(r)
        return results


def _format_unit(unit: dict, gong_date: str, assum_date: str) -> dict:
    """호실 데이터 포매팅"""
    return {
        "호명": unit.get("honm", ""),
        "동명": unit.get("dongnm", ""),
        "층": unit.get("floor_num", ""),
        "라인": unit.get("line_num", ""),
        "전용면적_m2": unit.get("prvusear", 0),
        "전용면적_py": unit.get("prvusear_py", 0),
        # ── 핵심: 공시가격 ──
        "공시가격": int(unit.get("pblntfpc", 0)),
        "공시가격_m2": unit.get("pblntfpc_m2", 0),
        "공시가격_py": unit.get("pblntfpc_py", 0),
        # ── AI추정가 ──
        "AI추정가": unit.get("prediction_price", 0),
        "AI추정가_m2": unit.get("prediction_price_m2", 0),
        "AI추정가_py": unit.get("prediction_price_py", 0),
        # ── 대지지분 ──
        "대지지분_m2": unit.get("land_share_area_m2", ""),
        "대지지분_py": unit.get("land_share_area_py", ""),
        "대지지분비율": unit.get("land_share_ratio_percent", ""),
        # ── 기준일 ──
        "공시일": gong_date,
        "AI추정일": assum_date,
    }


def _print_unit(info: dict):
    """호실 정보 출력"""
    print(f"    ┌──────────────────────────────────────")
    print(f"    │ {info['동명'] + ' ' if info['동명'] else ''}{info['호명']}호 ({info['층']}층)")
    print(f"    │ 전용면적: {info['전용면적_m2']}㎡ ({info['전용면적_py']}평)")
    print(f"    │ ★ 공시가격:  {info['공시가격']:>15,}원")
    print(f"    │   AI추정가:  {info['AI추정가']:>15,}원")
    print(f"    │ 대지지분: {info['대지지분_m2']}㎡ (비율 {info['대지지분비율']}%)")
    print(f"    └──────────────────────────────────────")


# ============================================================
# 통합 실행: 주소 + 호 → 공시가격
# ============================================================
def search_price(address: str, dong: str = "", ho: str = None):
    """
    주소와 동/호를 입력하면 공시가격을 조회

    Args:
        address: 검색 주소 (예: "봉천동 41-383", "서울 관악구 은천로35다길 26-4")
        dong: 동명 (예: "더빌", "101동"). 단일동 건물이면 빈 문자열
        ho: 호명 (예: "203"). None이면 전체 호 조회

    Examples:
        # 특정 호 조회
        search_price("봉천동 41-383", dong="더빌", ho="203")

        # 전체 호 조회
        search_price("봉천동 41-383", dong="더빌")
    """
    print("=" * 60)
    print(f"  공시가격 조회: {address}")
    if dong:
        print(f"  동: {dong}")
    if ho:
        print(f"  호: {ho}")
    print("=" * 60)

    # Step 1: 카카오 주소 검색
    kakao = kakao_search_address(address)
    if not kakao:
        return None

    # 동명이 비어있으면 카카오 건물명 사용
    building_name = dong or kakao.get("building_name", "")

    # Step 2: 좌표 변환
    lng_5179, lat_5179 = convert_to_epsg5179(kakao["x"], kakao["y"])

    # Step 3: landArea → pnu 획득
    land = get_land_area(lng_5179, lat_5179)
    if not land:
        return None

    # Step 4: 공시가격 조회
    result = get_official_price(
        pnu=land["pnu"],
        dongnm=building_name,
        honm=ho,
    )

    return result


# ============================================================
# 실행
# ============================================================
if __name__ == "__main__":
    # ── 예시 1: 특정 호 공시가격 조회 ──
    print("\n★★★ 특정 호 조회 ★★★\n")
    result = search_price("봉천동 41-383", dong="더빌", ho="203")

    if result:
        print(f"\n  ✅ 결과: {result['호명']}호 공시가격 = {result['공시가격']:,}원")

    # ── 예시 2: 전체 호 조회 ──
    print("\n\n★★★ 전체 호 조회 ★★★\n")
    results = search_price("봉천동 41-383", dong="더빌")

    if results and isinstance(results, list):
        print(f"\n  ✅ 총 {len(results)}개 호실 조회 완료")
        for r in results:
            print(f"     {r['호명']}호: 공시가격 {r['공시가격']:>13,}원 | AI추정가 {r['AI추정가']:>13,}원")
