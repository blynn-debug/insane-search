"""
통합 시세 조회 스크래퍼
  - 하우스머치: 상하한시세, 중위시세
  - 부동산플래닛: 공시가격, AI추정가

사용법:
  1) 아래 SETTINGS 섹션에서 쿠키/입력파일 설정
  2) python combined_scraper.py
  3) 결과: combined_results.csv 자동 생성
"""

import requests
import json
import time
import re
import csv
import os
import sys
from datetime import datetime

try:
    from pyproj import Transformer
except ImportError:
    print("[!] pyproj 미설치. 설치 명령어: pip install pyproj")
    sys.exit(1)


# ╔══════════════════════════════════════════════════════════════╗
# ║                     ★ SETTINGS ★                           ║
# ╚══════════════════════════════════════════════════════════════╝

# ── 입력 파일 경로 (주소 목록 텍스트 파일, 한 줄에 하나) ──
INPUT_FILE = "input_addresses.txt"

# ── 출력 파일 경로 ──
OUTPUT_CSV = "combined_results.csv"
OUTPUT_JSON = "combined_results.json"

# ── 하우스머치 쿠키 (로그인 필수) ──
# 브라우저 개발자도구(F12) → Network 탭 → 아무 요청 → Cookie 헤더에서 복사
HOWSMUCH_COOKIES = {
    "GID_SES": "여기에_GID_SES값_붙여넣기",  # ← 핵심! 만료 시 교체
    # "_gid": "",   # (선택) GA 쿠키
    # "_ga": "",    # (선택) GA 쿠키
}

# ── 카카오 API 키 (부동산플래닛 좌표 검색용) ──
KAKAO_API_KEY = "YOUR_KAKAO_REST_KEY"

# ── 요청 간 대기 시간 (초) ──
DELAY_BETWEEN_ITEMS = 1.5      # 주소 간 대기
DELAY_BETWEEN_REQUESTS = 0.5   # API 호출 간 대기


# ╔══════════════════════════════════════════════════════════════╗
# ║                    주소 파서                                 ║
# ╚══════════════════════════════════════════════════════════════╝

def parse_address(raw: str) -> dict:
    """
    다양한 형식의 주소에서 검색주소, 건물명, 동, 호를 추출

    지원 형식:
      - 지번: "서울특별시 구로구 개봉동 318-12 토브하우스 제3층 제301호"
      - 도로명+괄호: "서울특별시 구로구 경인로35길 52-10, 제5층 제501호 (개봉동, 더시그니처)"
      - 동 포함: "서울특별시 구로구 개봉동 334-4 상떼그린힐 제101동 제4층 제403호"
    """
    raw = raw.strip()
    if not raw:
        return None

    # ── 호 추출 ──
    ho_match = re.search(r'제?(\d+)호', raw)
    ho = ho_match.group(1) if ho_match else ''

    # ── 동(건물 내 동) 추출 ──
    dong = ''
    dong_patterns = [
        r'제?(\d+)동\s+제?\d+층',       # 제101동 제4층
        r'제([가-힣]+동)\s+제?\d+',      # 제에이동 제3층
        r'\s([가-힣]+동)\s+\d+층',       # 비동 4층
        r'\s(\d+동)\s+\d+층',           # 102동 2층
    ]
    for pat in dong_patterns:
        m = re.search(pat, raw)
        if m:
            dong = m.group(1)
            break

    # ── 괄호 안 건물명 ──
    bldg_name = ''
    paren_match = re.search(r'\(.*?,\s*(.+?)\)', raw)
    if paren_match:
        bldg_name = paren_match.group(1).strip()

    # ── 검색 주소 추출 ──
    jibun_match = re.search(r'([가-힣]+동)\s+(\d+(?:-\d+)?)', raw)

    if paren_match:
        # 도로명 주소 → 괄호 앞 부분
        paren_start = raw.index('(')
        search_addr = raw[:paren_start].rstrip(' ,')
        search_addr = re.sub(r',?\s*제?\d+동.*', '', search_addr)
        search_addr = re.sub(r',?\s*제?[가-힣]+동\s+제?\d+.*', '', search_addr)
        search_addr = re.sub(r',?\s*제?\d+층.*', '', search_addr)
        search_addr = search_addr.strip().rstrip(',').strip()
    elif jibun_match:
        # 지번 주소 → 동 + 번지까지
        dong_name = jibun_match.group(1)
        jibun_num = jibun_match.group(2)
        idx = raw.index(dong_name)
        search_addr = raw[:idx] + dong_name + ' ' + jibun_num

        # 건물명 추출 (지번 뒤 ~ 동/층/호 전)
        if not bldg_name:
            after_pos = idx + len(dong_name) + 1 + len(jibun_num)
            after_jibun = raw[after_pos:].strip()
            bldg_part = re.split(
                r'\s*제?\d+동|\s*제?\d+층|\s*\d+층|\s*제?[가-힣]+동\s+\d+',
                after_jibun
            )
            if bldg_part and bldg_part[0].strip():
                candidate = bldg_part[0].strip()
                # '지상', 숫자만 등 제거
                if candidate and candidate not in ('지상', '외') and not re.match(r'^\d+$', candidate):
                    bldg_name = candidate
    else:
        search_addr = raw

    return {
        'raw': raw,
        'search_addr': search_addr.strip(),
        'building_name': bldg_name.strip(),
        'dong': dong.strip(),
        'ho': ho.strip(),
    }


def load_addresses(filepath: str) -> list[dict]:
    """텍스트 파일에서 주소 목록 로드 + 파싱"""
    if not os.path.exists(filepath):
        print(f"[✗] 파일 없음: {filepath}")
        return []

    addresses = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parsed = parse_address(line)
            if parsed:
                parsed['line_num'] = line_num
                addresses.append(parsed)

    print(f"[✓] {len(addresses)}개 주소 로드 완료 ({filepath})")
    return addresses


# ╔══════════════════════════════════════════════════════════════╗
# ║              하우스머치 스크래퍼                               ║
# ╚══════════════════════════════════════════════════════════════╝

class HowsMuchScraper:
    BASE_URL = "https://www.howsmuch.com"

    def __init__(self, cookies: dict):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Cache-Control": "no-cache",
            "Origin": self.BASE_URL,
            "Referer": f"{self.BASE_URL}/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/146.0.0.0",
        })
        self.session.cookies.update(cookies)
        self.enabled = bool(cookies.get("GID_SES", "")) and cookies["GID_SES"] != "여기에_GID_SES값_붙여넣기"

    def query(self, search_addr: str, ho: str = "") -> dict | None:
        """주소 + 호 → 시세 조회 (단축 플로우)"""
        if not self.enabled:
            return None

        try:
            # Step 1: 주소 검색
            resp = self.session.post(
                f"{self.BASE_URL}/common/search",
                data={"text": search_addr}, timeout=10
            )
            if resp.status_code != 200 or not resp.json():
                return None

            addr_data = resp.json()[0]
            pnu = addr_data["PNU"]
            road_cd = addr_data["ROAD_CD"]
            time.sleep(DELAY_BETWEEN_REQUESTS)

            # Step 2: 건물(동) 조회
            resp = self.session.post(
                f"{self.BASE_URL}/common/building",
                data={"code": pnu, "road": road_cd}, timeout=10
            )
            if resp.status_code != 200 or not resp.json():
                return None

            buildings = resp.json()
            dong_code = buildings[0]["DONG"]
            time.sleep(DELAY_BETWEEN_REQUESTS)

            # Step 3: 세대(호) 목록
            resp = self.session.post(
                f"{self.BASE_URL}/common/household",
                data={"code": dong_code}, timeout=10
            )
            if resp.status_code != 200 or not resp.json():
                return None

            households = resp.json()

            # 호 매칭
            target = None
            if ho:
                for h in households:
                    if str(h.get("HO_NAME", "")) == str(ho):
                        target = h
                        break
            if not target and households:
                target = households[0]  # 매칭 실패 시 첫번째 호

            if not target:
                return None

            time.sleep(DELAY_BETWEEN_REQUESTS)

            # Step 4: 시세 조회
            resp = self.session.post(
                f"{self.BASE_URL}/common/information",
                data={"code": target["NUM_KEY"]}, timeout=15
            )

            if resp.status_code == 401:
                print("  [하우스머치] ✗ 401 — GID_SES 쿠키 만료! 갱신 필요")
                self.enabled = False
                return None
            if resp.status_code != 200:
                return None

            pop = resp.json().get("population")
            if not pop:
                return None

            return {
                "hm_호명": target.get("HO_NAME", ""),
                "hm_주소": pop.get("R_ADDRESS", ""),
                "hm_주택유형": pop.get("TYPE_NAME", ""),
                "hm_전유면적": pop.get("PRIV_AREA", ""),
                "hm_해당층": pop.get("FLOOR", ""),
                "hm_하한시세_만원": pop.get("PRICE_MIN", ""),
                "hm_상한시세_만원": pop.get("PRICE_MAX", ""),
                "hm_중위시세_만원": pop.get("PRICE", ""),
                "hm_단가_만원": pop.get("PRICE_UNIT", ""),
                "hm_기준일": pop.get("DATA_DATE", ""),
                "hm_가격불가": pop.get("NA_TYPE", ""),
            }

        except Exception as e:
            print(f"  [하우스머치] ✗ 에러: {e}")
            return None


# ╔══════════════════════════════════════════════════════════════╗
# ║            부동산플래닛 스크래퍼                                ║
# ╚══════════════════════════════════════════════════════════════╝

class BdsPlanetScraper:
    def __init__(self, kakao_key: str):
        self.kakao_key = kakao_key
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/146.0.0.0",
            "Referer": "https://www.bdsplanet.com/",
            "Accept": "*/*",
        }
        self.transformer = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    def query(self, search_addr: str, building_name: str = "", ho: str = "") -> dict | None:
        """주소 + 건물명 + 호 → 공시가격 조회"""
        try:
            # Step 1: 카카오 주소 검색
            resp = requests.get(
                "https://dapi.kakao.com/v2/local/search/address.json",
                headers={"Authorization": f"KakaoAK {self.kakao_key}"},
                params={"query": search_addr}, timeout=10
            )
            docs = resp.json().get("documents", [])
            if not docs:
                return None

            doc = docs[0]
            lon = float(doc["x"])
            lat = float(doc["y"])

            # 건물명 우선순위: 파라미터 > 카카오 결과
            if not building_name:
                road = doc.get("road_address")
                if road:
                    building_name = road.get("building_name", "")

            time.sleep(DELAY_BETWEEN_REQUESTS)

            # Step 2: 좌표 변환
            x5179, y5179 = self.transformer.transform(lon, lat)

            # Step 3: landArea → pnu
            resp = requests.get(
                "https://www.bdsplanet.com/sales/detail/realprice/plg/landArea.ytp",
                headers=self.headers,
                params={"lat": y5179, "lng": x5179}, timeout=10
            )
            data = resp.json()
            polygon_c = data.get("polygonC")
            if not polygon_c:
                return None

            pnu = polygon_c.get("pnu", "")
            if not pnu:
                return None

            time.sleep(DELAY_BETWEEN_REQUESTS)

            # Step 4: 공시가격 조회 (건물 유형별 엔드포인트 자동 탐색)
            # A.ytp = 아파트/빌라(일반), D.ytp = 연립다세대
            params = {}
            if building_name:
                params["dongnm"] = building_name

            detail_info = []
            date_info = {}

            for suffix in ["D.ytp", "A.ytp"]:
                resp = requests.get(
                    f"https://www.bdsplanet.com/sales/detail/realprice/officialPriceDetailInfo/{pnu}/{suffix}",
                    headers=self.headers,
                    params=params, timeout=10
                )
                data = resp.json()
                detail_info = data.get("detailInfo", [])
                date_info = data.get("dateInfo", {})

                if not detail_info and building_name:
                    # 건물명 없이 재시도
                    resp = requests.get(
                        f"https://www.bdsplanet.com/sales/detail/realprice/officialPriceDetailInfo/{pnu}/{suffix}",
                        headers=self.headers, timeout=10
                    )
                    data = resp.json()
                    detail_info = data.get("detailInfo", [])
                    date_info = data.get("dateInfo", {})

                if detail_info:
                    break

            if not detail_info:
                return None

            # 호 매칭
            matched = None
            if ho:
                for d in detail_info:
                    if str(d.get("honm", "")) == str(ho):
                        matched = d
                        break
            if not matched and detail_info:
                matched = detail_info[0]  # 매칭 실패 시 첫번째

            if not matched:
                return None

            gong_date = date_info.get("gongDate", {}).get("gongdate", "")
            assum_date = date_info.get("assumDate", "")

            return {
                "bp_호명": matched.get("honm", "") or "",
                "bp_동명": matched.get("dongnm", "") or "",
                "bp_층": matched.get("floor_num", "") or "",
                "bp_전용면적_m2": matched.get("prvusear", "") or "",
                "bp_전용면적_py": matched.get("prvusear_py", "") or "",
                "bp_공시가격": int(matched.get("pblntfpc") or 0),
                "bp_공시가격_m2": matched.get("pblntfpc_m2") or "",
                "bp_AI추정가": int(matched.get("prediction_price") or 0),
                "bp_AI추정가_m2": matched.get("prediction_price_m2") or "",
                "bp_대지지분_m2": matched.get("land_share_area_m2", "") or "",
                "bp_대지지분비율": matched.get("land_share_ratio_percent", "") or "",
                "bp_공시일": gong_date,
                "bp_AI추정일": assum_date,
            }

        except Exception as e:
            print(f"  [부동산플래닛] ✗ 에러: {e}")
            return None


# ╔══════════════════════════════════════════════════════════════╗
# ║                    통합 실행                                 ║
# ╚══════════════════════════════════════════════════════════════╝

def run_combined(addresses: list[dict]):
    """전체 주소 리스트에 대해 두 스크래퍼를 실행하고 결과 병합"""

    hm = HowsMuchScraper(HOWSMUCH_COOKIES)
    bp = BdsPlanetScraper(KAKAO_API_KEY)

    if hm.enabled:
        print("[✓] 하우스머치: 쿠키 세팅 완료 (GID_SES 인증)")
    else:
        print("[!] 하우스머치: GID_SES 미설정 — 부동산플래닛만 조회됩니다")

    print(f"[✓] 부동산플래닛: 카카오 API 키 세팅 완료")
    print(f"\n{'━' * 70}")
    print(f"  총 {len(addresses)}건 조회 시작")
    print(f"{'━' * 70}\n")

    all_results = []

    for i, addr in enumerate(addresses):
        print(f"[{i+1}/{len(addresses)}] {addr['raw'][:65]}")
        print(f"  → 검색: {addr['search_addr']}  |  호: {addr['ho']}  |  건물: {addr['building_name']}")

        row = {
            "No": i + 1,
            "원본주소": addr['raw'],
            "검색주소": addr['search_addr'],
            "파싱_건물명": addr['building_name'],
            "파싱_동": addr['dong'],
            "파싱_호": addr['ho'],
        }

        # ── 하우스머치 조회 ──
        hm_result = hm.query(addr['search_addr'], addr['ho'])
        if hm_result:
            row.update(hm_result)
            price_str = hm_result.get('hm_중위시세_만원', '')
            if price_str and not hm_result.get('hm_가격불가'):
                print(f"  [하우스머치] ✓ 중위시세: {price_str}만원  |  상하한: {hm_result.get('hm_하한시세_만원','')}~{hm_result.get('hm_상한시세_만원','')}만원")
            else:
                print(f"  [하우스머치] △ 가격 추정 불가")
        else:
            if hm.enabled:
                print(f"  [하우스머치] ✗ 조회 실패")

        time.sleep(DELAY_BETWEEN_REQUESTS)

        # ── 부동산플래닛 조회 ──
        bp_result = bp.query(addr['search_addr'], addr['building_name'], addr['ho'])
        if bp_result:
            row.update(bp_result)
            pblntfpc = bp_result.get('bp_공시가격', 0)
            pred = bp_result.get('bp_AI추정가', 0)
            print(f"  [부동산플래닛] ✓ 공시가격: {pblntfpc:,}원  |  AI추정가: {pred:,}원")
        else:
            print(f"  [부동산플래닛] ✗ 조회 실패")

        all_results.append(row)
        print()

        if i < len(addresses) - 1:
            time.sleep(DELAY_BETWEEN_ITEMS)

    return all_results


def save_results(results: list[dict]):
    """결과를 CSV + JSON으로 저장"""
    if not results:
        print("[!] 저장할 결과 없음")
        return

    # ── CSV 저장 ──
    # 모든 키 수집 (순서 보장)
    fieldnames = []
    for r in results:
        for k in r.keys():
            if k not in fieldnames:
                fieldnames.append(k)

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"[✓] CSV 저장: {OUTPUT_CSV}")

    # ── JSON 저장 ──
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"[✓] JSON 저장: {OUTPUT_JSON}")


def print_summary(results: list[dict]):
    """결과 요약 출력"""
    total = len(results)
    hm_ok = sum(1 for r in results if r.get('hm_중위시세_만원'))
    bp_ok = sum(1 for r in results if r.get('bp_공시가격') or r.get('bp_AI추정가'))
    both = sum(1 for r in results if r.get('hm_중위시세_만원') and (r.get('bp_공시가격') or r.get('bp_AI추정가')))

    print(f"\n{'━' * 70}")
    print(f"  ★ 조회 결과 요약")
    print(f"{'━' * 70}")
    print(f"  전체 주소:        {total}건")
    print(f"  하우스머치 성공:   {hm_ok}건")
    print(f"  부동산플래닛 성공: {bp_ok}건")
    print(f"  양쪽 모두 성공:   {both}건")
    print(f"{'━' * 70}")

    # 상위 결과 미리보기
    print(f"\n  {'No':>3} | {'호':>5} | {'중위시세(만)':>12} | {'공시가격':>15} | {'AI추정가':>15} | 주소")
    print(f"  {'─'*3}─┼─{'─'*5}─┼─{'─'*12}─┼─{'─'*15}─┼─{'─'*15}─┼─{'─'*30}")

    for r in results[:20]:
        no = r.get('No', '')
        ho = r.get('파싱_호', '')
        hm_price = r.get('hm_중위시세_만원', '-')
        bp_price = r.get('bp_공시가격', 0)
        bp_ai = r.get('bp_AI추정가', 0)
        addr = r.get('검색주소', '')[:30]

        bp_str = f"{bp_price:>13,}" if bp_price else f"{'─':>13}"
        ai_str = f"{bp_ai:>13,}" if bp_ai else f"{'─':>13}"

        print(f"  {no:>3} | {ho:>5} | {str(hm_price):>12} | {bp_str}원 | {ai_str}원 | {addr}")

    if len(results) > 20:
        print(f"  ... 외 {len(results) - 20}건 (CSV 파일 참조)")


# ╔══════════════════════════════════════════════════════════════╗
# ║                      메인                                   ║
# ╚══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          통합 시세 조회 (하우스머치 + 부동산플래닛)            ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # ── 주소 로드 ──
    addresses = load_addresses(INPUT_FILE)
    if not addresses:
        print(f"\n[!] '{INPUT_FILE}' 파일을 생성하고 주소를 입력해주세요.")
        print(f"    (한 줄에 하나, 예시)")
        print(f"    서울특별시 구로구 개봉동 318-12 토브하우스  제3층 제301호")
        sys.exit(1)

    # ── 조회 실행 ──
    results = run_combined(addresses)

    # ── 결과 저장 ──
    save_results(results)

    # ── 요약 출력 ──
    print_summary(results)