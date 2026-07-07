#!/usr/bin/env python3
"""
국토교통부 실거래가 시스템 API v4

수정사항:
1. 면적 매칭: 동일 평형(±5㎡) 우선, 없으면 평당가 환산 추정
2. 제304동 → 304동 변환 (숫자 동호수 제외)
3. 좌표 기반 검색 지원 (/pt/gis/getMarker.do)
4. 읍면동 API 파라미터 수정 (code=11260)

사용법:
    python molit_price_fetcher_v4.py [입력CSV] [출력CSV]
"""

import requests
import re
import csv
import time
import sys
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEBUG = os.environ.get('DEBUG', '0') == '1'


class MolitPriceFetcher:
    """국토교통부 실거래가 시스템 API"""

    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://rt.molit.go.kr"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'ko-KR,ko;q=0.9',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://rt.molit.go.kr',
            'Referer': 'https://rt.molit.go.kr/pt/gis/gis.do?srhThingSecd=A&mobileAt=',
        }

        self.signgu_cache: Dict[str, str] = {}
        self.emd_cache: Dict[str, Dict[str, str]] = {}
        self.danji_cache: Dict[str, List[dict]] = {}

    def _post(self, endpoint: str, data: dict, desc: str = "") -> dict:
        """POST 요청"""
        url = f"{self.base_url}{endpoint}"

        if DEBUG:
            print(f"\n  [DEBUG] POST {endpoint}")
            print(f"  [DEBUG] Data: {data}")

        try:
            resp = self.session.post(url, headers=self.headers, data=data, verify=False, timeout=30)

            if DEBUG:
                print(f"  [DEBUG] Status: {resp.status_code}")
                print(f"  [DEBUG] Response: {resp.text[:500]}")

            resp.raise_for_status()
            return resp.json() if resp.text else {}

        except Exception as e:
            if DEBUG:
                print(f"  [DEBUG] Error: {e}")
            return {}

    # ========================
    # 기본 코드 조회
    # ========================

    def get_signgu_list(self) -> Dict[str, str]:
        """서울시 시군구 목록"""
        if self.signgu_cache:
            return self.signgu_cache

        result = self._post('/cmm/signguList.do', {'sidoCd': '11'}, '시군구')

        for item in result.get('signguList', []):
            code = item.get('code')
            name = item.get('codeNm')
            if code and name and code.startswith('11'):
                self.signgu_cache[name] = code

        print(f"✅ 시군구 {len(self.signgu_cache)}개 로드")
        return self.signgu_cache

    def get_emd_list(self, signgu_code: str) -> Dict[str, str]:
        """읍면동 목록"""
        if signgu_code in self.emd_cache:
            return self.emd_cache[signgu_code]

        # 파라미터: code=11260 (signguCd 아님!)
        result = self._post('/cmm/emdList.do', {'code': signgu_code}, '읍면동')

        emd_dict = {}
        for item in result.get('emdList', []):
            code = item.get('code')  # 예: 1126010500
            name = item.get('codeNm')  # 예: 망우동
            if code and name:
                emd_dict[name] = code

        self.emd_cache[signgu_code] = emd_dict

        if DEBUG:
            print(f"  [DEBUG] 읍면동: {list(emd_dict.keys())}")

        return emd_dict

    # ========================
    # 단지 검색
    # ========================

    def get_danji_list(self, signgu_code: str, emd_code: str, bldg_name: str = '') -> List[dict]:
        """
        단지 목록 조회 (지번 기반)
        """
        cache_key = f"{emd_code}_{bldg_name}"
        if cache_key in self.danji_cache:
            return self.danji_cache[cache_key]

        all_danji = []
        page = 1
        current_year = datetime.now().year

        while page <= 10:
            data = {
                'srhThingSecd': 'A',
                'srhYear': str(current_year),
                'srhLadSecd': '1',  # 지번
                'srhLedCd': emd_code,  # 전체코드: 1126010500
                'srhRoadCd': '',
                'srhBldgNm': bldg_name,
                'pageIndex': str(page),
                'mobileAt': ''
            }

            result = self._post('/pt/gis/ptDanjiList.do', data, f'단지 p{page}')
            danji_list = result.get('danjiList', [])
            all_danji.extend(danji_list)

            tot_cnt = result.get('totCnt', 0)

            if DEBUG:
                print(f"  [DEBUG] 페이지{page}: {len(danji_list)}건 (총 {tot_cnt})")

            if len(all_danji) >= tot_cnt or not danji_list:
                break

            page += 1
            time.sleep(0.2)

        self.danji_cache[cache_key] = all_danji
        return all_danji

    def get_danji_by_coords(self, lat: float, lng: float, delta: float = 0.005) -> List[dict]:
        """
        좌표 기반 단지 검색
        /pt/gis/getMarker.do

        Args:
            lat: 위도 (dy)
            lng: 경도 (dx)
            delta: 검색 반경 (약 500m = 0.005)
        """
        current_year = datetime.now().year

        data = {
            'minX': str(lng - delta),
            'maxX': str(lng + delta),
            'minY': str(lat - delta),
            'maxY': str(lat + delta),
            'srhYear': str(current_year),
            'poiType': 'A'  # 아파트
        }

        result = self._post('/pt/gis/getMarker.do', data, '좌표검색')
        return result.get('list', [])

    # ========================
    # 거래내역 조회
    # ========================

    def get_trade_years(self, aprpn_code: str, trade_type: str = '1') -> List[str]:
        """거래 연도 목록"""
        data = {
            'srhThingSecd': 'A',
            'srhDelngSecd': trade_type,
            'srhAprpnHsmpCode': aprpn_code
        }

        result = self._post('/pt/gis/ptDtlYear.do', data, '연도')
        years = [item.get('year') for item in result.get('danjiList', []) if item.get('year')]
        return years

    def get_trade_list(self, aprpn_code: str, emd_code: str, year: str,
                       trade_type: str = '1') -> List[dict]:
        """
        거래내역 조회
        /pt/gis/ptDtl.do
        """
        short_emd = emd_code[-5:] if len(emd_code) > 5 else emd_code

        data = {
            'srhThingSecd': 'A',
            'srhDelngSecd': trade_type,
            'srhAprpnHsmpCode': aprpn_code,
            'dtlLi': short_emd,
            'dtlYear': year,
            'dtlMon': '',
            'dtlArea': '',
            'dtlAmount': '0',
            'dtlLfstsMtht': '',
            'mobileAt': ''
        }

        result = self._post('/pt/gis/ptDtl.do', data, f'거래 {year}')
        return result.get('danjiList', [])

    def get_all_trades(self, aprpn_code: str, emd_code: str,
                       trade_type: str = '1', max_years: int = 3) -> List[dict]:
        """전체 거래내역 (최근 N년)"""
        all_trades = []

        years = self.get_trade_years(aprpn_code, trade_type)

        if not years:
            return []

        if DEBUG:
            print(f"  [DEBUG] 연도: {years[:5]}")

        for year in years[:max_years]:
            time.sleep(0.2)
            trades = self.get_trade_list(aprpn_code, emd_code, year, trade_type)

            for t in trades:
                if 'cntrctDe' in t:
                    t['_date_str'] = t['cntrctDe']
                else:
                    m = t.get('cntrctMm', t.get('mon', '01'))
                    d = t.get('cntrctDd', '15')
                    t['_date_str'] = f"{year}{str(m).zfill(2)}{str(d).zfill(2)}"

                all_trades.append(t)

        return all_trades

    # ========================
    # 주소 파싱
    # ========================

    def extract_gu_dong(self, address: str) -> Tuple[Optional[str], Optional[str]]:
        """주소에서 구/동 추출"""
        if not address:
            return None, None

        # "제503동" → 제거 (아파트 동호수)
        addr_clean = re.sub(r'제(\d+)동', '', address)
        addr_clean = re.sub(r'(\d+)동\s', ' ', addr_clean)  # 숫자동 제거

        # 구
        gu_match = re.search(r'([가-힣]+구)', addr_clean)
        gu = gu_match.group(1) if gu_match else None

        # 동 (행정동)
        dong_patterns = [
            r'([가-힣]+\d+동)',  # 상도1동
            r'([가-힣]+동\d+가)',  # 금호동1가
            r'([가-힣]+\d+가)',  # 남대문로1가
            r'구\s+([가-힣]+동)',  # 구 뒤의 동
            r'([가-힣]+동)(?:\s|\d|,|$)',  # 일반 동
        ]

        dong = None
        for p in dong_patterns:
            m = re.search(p, addr_clean)
            if m:
                candidate = m.group(1)
                # 숫자로만 된 동은 제외
                if not re.match(r'^\d+동$', candidate):
                    dong = candidate
                    break

        return gu, dong

    def extract_apt_name(self, address: str) -> Optional[str]:
        """주소에서 아파트명 추출"""
        if not address:
            return None

        # 괄호 안 이름 먼저: (풍납동,갑을아파트)
        paren = re.search(r'\(([^)]+)\)', address)
        if paren:
            inner = paren.group(1)
            parts = inner.split(',')
            for part in parts:
                part = part.strip()
                if any(kw in part for kw in ['아파트', '타워', '파크', '빌', '힐', '시티']):
                    return part

        # 패턴 매칭
        patterns = [
            r'([가-힣]+아파트)',
            r'(래미안[가-힣]*)',
            r'(자이[가-힣]*)',
            r'(힐스테이트[가-힣]*)',
            r'(푸르지오[가-힣]*)',
            r'(아이파크[가-힣]*)',
            r'(롯데캐슬[가-힣]*)',
            r'(금호어울림[가-힣]*)',
            r'(데시앙[가-힣]*)',
            r'(위브[가-힣]*)',
            r'(트레지움[가-힣]*)',
            r'(그린파크[가-힣]*)',
            r'(리버파크[가-힣]*)',
            r'(리엔파크[가-힣]*)',
            r'(현대[가-힣]*)',
            r'(삼성[가-힣]*)',
            r'(두산[가-힣]*)',
            r'(우성[가-힣]*)',
            r'(청솔[가-힣]*)',
            r'(청구[가-힣]*)',
            r'(한양[가-힣]*)',
            r'(한신[가-힣]*)',
            r'(무지개[가-힣]*)',
            r'(풍림[가-힣]*)',
            r'(주공[가-힣]*)',
            r'(시영[가-힣]*)',
            r'(반포자이)',
            r'(타워팰리스)',
            r'([가-힣]+파크[가-힣]*)',
            r'([가-힣]+타워[가-힣]*)',
            r'([가-힣]+빌[가-힣]*)',
            r'([가-힣]+하이츠)',
            r'([가-힣]+캐슬)',
        ]

        for p in patterns:
            m = re.search(p, address)
            if m:
                return m.group(1)

        return None

    def extract_jibun(self, address: str) -> Tuple[Optional[str], Optional[str]]:
        """주소에서 지번 추출"""
        # "동 123" 또는 "동 123-4" 패턴
        # 층/호수 앞의 숫자는 제외

        # 층, 호 앞의 숫자 제외하고 파싱
        addr_clean = re.sub(r'\d+층', '', address)
        addr_clean = re.sub(r'\d+호', '', addr_clean)

        matches = re.findall(r'(\d+)(?:-(\d+))?(?:,|\s|$)', addr_clean)

        for m in matches:
            main_num = m[0]
            sub_num = m[1] if m[1] else None
            # 지번은 보통 4자리 이하
            if 1 <= int(main_num) <= 9999:
                return main_num, sub_num

        return None, None

    def find_matching_danji(self, address: str, danji_list: List[dict]) -> Optional[dict]:
        """단지 매칭"""
        apt_name = self.extract_apt_name(address)
        main_num, sub_num = self.extract_jibun(address)

        # 핵심 키워드 추출: "한신아파트" → "한신"
        apt_keyword = None
        if apt_name:
            apt_keyword = apt_name.replace('아파트', '').strip()
            apt_keyword = re.sub(r'\d+차?$', '', apt_keyword).strip()  # "우성2차" → "우성"

        if DEBUG:
            print(f"    [DEBUG] 추출: apt={apt_name}, keyword={apt_keyword}, 지번={main_num}-{sub_num}")

        best_match = None
        best_score = 0

        for danji in danji_list:
            danji_name = danji.get('aprpnHsmpNm', '')
            mnnm_raw = str(danji.get('mnnm', ''))

            # 본번/부번 분리
            if '-' in mnnm_raw:
                parts = mnnm_raw.split('-')
                danji_mnnm = parts[0].lstrip('0')
                danji_slno = parts[1].lstrip('0') if len(parts) > 1 else ''
            else:
                danji_mnnm = mnnm_raw.lstrip('0')
                danji_slno = str(danji.get('slno', '')).lstrip('0')

            score = 0

            # 지번 매칭
            if main_num and danji_mnnm:
                if main_num == danji_mnnm:
                    score += 15
                    if sub_num and danji_slno and sub_num == danji_slno:
                        score += 10
                    elif not sub_num and (not danji_slno or danji_slno in ['0', '0000']):
                        score += 5

            # 아파트명 매칭
            if apt_name and danji_name:
                clean_danji = re.sub(r'\([^)]*\)', '', danji_name).strip()

                # 완전 일치
                if apt_name == clean_danji or apt_name == danji_name:
                    score += 15
                # 포함 관계
                elif apt_name in clean_danji or clean_danji in apt_name:
                    score += 10
                elif apt_name in danji_name or danji_name in apt_name:
                    score += 8
                # 핵심 키워드 매칭: "한신" in "한신아파트" or "한신" in "노원한신"
                elif apt_keyword and len(apt_keyword) >= 2:
                    if apt_keyword in danji_name or apt_keyword in clean_danji:
                        score += 7
                    # 단지명에서 핵심 추출해서 비교
                    danji_keyword = re.sub(r'아파트|빌라|\d+차?|\([^)]*\)', '', danji_name).strip()
                    if apt_keyword == danji_keyword:
                        score += 8
                    elif apt_keyword in danji_keyword or danji_keyword in apt_keyword:
                        score += 5

            if score > best_score:
                best_score = score
                best_match = danji

        if DEBUG and best_match:
            print(f"    [DEBUG] 매칭: {best_match.get('aprpnHsmpNm')} (점수: {best_score})")

        return best_match if best_score >= 5 else None

    # ========================
    # 가격 조회
    # ========================

    def parse_date(self, trade: dict) -> Optional[datetime]:
        """거래 날짜 파싱"""
        date_str = trade.get('_date_str') or trade.get('cntrctDe') or ''

        if date_str:
            date_str = str(date_str).replace('.', '').replace('-', '')
            try:
                if len(date_str) >= 8:
                    return datetime.strptime(date_str[:8], '%Y%m%d')
            except:
                pass
        return None

    def parse_price(self, trade: dict) -> Optional[int]:
        """거래 가격 파싱"""
        price = trade.get('thingAmount') or trade.get('dealAmt')
        if price:
            try:
                return int(str(price).replace(',', '').replace(' ', ''))
            except:
                pass
        return None

    def get_latest_price(self, aprpn_code: str, emd_code: str,
                         target_area: float = None) -> dict:
        """
        최근 매매가 조회

        우선순위:
        1. 동일 면적(±5㎡) 최근 1년 내 매매가
        2. 동일 면적(±5㎡) 1년 초과 매매가
        3. 다른 면적 매매가 → 평당가로 환산 추정
        4. 전세로 추정 (÷0.65)
        5. 월세로 추정
        """
        result = {
            'price': None,
            'price_date': None,
            'price_type': None,
            'area': None,
            'floor': None,
            'dong': None,
            'is_estimated': False,
            'ref_info': ''
        }

        now = datetime.now()
        one_year_ago = now - timedelta(days=365)

        # 1. 매매 데이터
        sales = self.get_all_trades(aprpn_code, emd_code, '1', max_years=3)

        if sales:
            # 날짜/면적 파싱
            for s in sales:
                s['_date'] = self.parse_date(s)
                area = s.get('prvuseAr')
                s['_area'] = float(area) if area else None

            # 면적별 분류
            same_area = []
            diff_area = []

            for s in sales:
                if s['_date'] and self.parse_price(s):
                    if target_area and s['_area']:
                        if abs(s['_area'] - target_area) <= 5:
                            same_area.append(s)
                        else:
                            diff_area.append(s)
                    else:
                        same_area.append(s)

            # 동일 면적 최근 매매
            recent_same = [s for s in same_area if s['_date'] >= one_year_ago]
            if recent_same:
                recent_same.sort(key=lambda x: x['_date'], reverse=True)
                t = recent_same[0]
                price = self.parse_price(t)
                if price:
                    result.update({
                        'price': price,
                        'price_date': t['_date'].strftime('%Y-%m-%d'),
                        'price_type': 'sale',
                        'area': t.get('prvuseAr'),
                        'floor': t.get('floorCo'),
                        'dong': t.get('dongName')
                    })
                    return result

            # 동일 면적 1년전 매매
            old_same = [s for s in same_area if s['_date'] < one_year_ago]
            if old_same:
                old_same.sort(key=lambda x: x['_date'], reverse=True)
                t = old_same[0]
                price = self.parse_price(t)
                if price:
                    result.update({
                        'price': price,
                        'price_date': t['_date'].strftime('%Y-%m-%d'),
                        'price_type': 'sale_1year',
                        'area': t.get('prvuseAr'),
                        'floor': t.get('floorCo'),
                        'dong': t.get('dongName')
                    })
                    return result

            # 다른 면적 → 평당가 환산
            if target_area and diff_area:
                diff_area.sort(key=lambda x: x['_date'], reverse=True)
                t = diff_area[0]
                price = self.parse_price(t)
                ref_area = t['_area']

                if price and ref_area and ref_area > 0:
                    price_per_m2 = price / ref_area
                    estimated = int(price_per_m2 * target_area)

                    result.update({
                        'price': estimated,
                        'price_date': t['_date'].strftime('%Y-%m-%d'),
                        'price_type': 'estimated_area',
                        'area': target_area,
                        'floor': t.get('floorCo'),
                        'dong': t.get('dongName'),
                        'is_estimated': True,
                        'ref_info': f"{ref_area}㎡={price:,}만→{target_area}㎡환산"
                    })
                    return result

        # 2. 전세
        time.sleep(0.2)
        jeonse = self.get_all_trades(aprpn_code, emd_code, '2', max_years=1)

        if jeonse:
            # 동일 면적 우선
            candidates = []
            for item in jeonse:
                d = self.parse_date(item)
                if not d:
                    continue

                area = item.get('prvuseAr')
                item['_date'] = d
                item['_area'] = float(area) if area else None

                if target_area and item['_area']:
                    if abs(item['_area'] - target_area) <= 10:
                        candidates.append(item)
                else:
                    candidates.append(item)

            if not candidates:
                candidates = [j for j in jeonse if self.parse_date(j)]

            if candidates:
                candidates.sort(key=lambda x: x.get('_date', datetime.min), reverse=True)
                t = candidates[0]
                price = self.parse_price(t)
                if price:
                    estimated = int(price / 0.65)
                    result.update({
                        'price': estimated,
                        'price_date': t['_date'].strftime('%Y-%m-%d'),
                        'price_type': 'estimated_jeonse',
                        'area': t.get('prvuseAr'),
                        'floor': t.get('floorCo'),
                        'dong': t.get('dongName'),
                        'is_estimated': True,
                        'ref_info': f"전세{price:,}만÷0.65"
                    })
                    return result

        # 3. 월세
        time.sleep(0.2)
        wolse = self.get_all_trades(aprpn_code, emd_code, '3', max_years=1)

        if wolse:
            latest = None
            latest_date = datetime.min

            for item in wolse:
                d = self.parse_date(item)
                if d and d > latest_date:
                    latest_date = d
                    latest = item

            if latest:
                deposit = latest.get('deposit') or latest.get('thingAmount') or 0
                monthly = latest.get('monthlyRent') or latest.get('rent') or 0

                try:
                    deposit = int(str(deposit).replace(',', '') or '0')
                    monthly = int(str(monthly).replace(',', '') or '0')
                except:
                    deposit, monthly = 0, 0

                if deposit or monthly:
                    eq = deposit + (monthly * 100)
                    estimated = int(eq / 0.65)
                    result.update({
                        'price': estimated,
                        'price_date': latest_date.strftime('%Y-%m-%d'),
                        'price_type': 'estimated_wolse',
                        'area': latest.get('prvuseAr'),
                        'floor': latest.get('floorCo'),
                        'dong': latest.get('dongName'),
                        'is_estimated': True,
                        'ref_info': f"보{deposit}/월{monthly}→환산"
                    })
                    return result

        return result


def process_csv(input_csv: str, output_csv: str):
    """CSV 처리"""
    fetcher = MolitPriceFetcher()
    fetcher.get_signgu_list()

    if not fetcher.signgu_cache:
        print("❌ 시군구 로드 실패")
        return None

    results = []

    try:
        with open(input_csv, 'r', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"❌ 파일 없음: {input_csv}")
        return None

    print(f"\n📊 {len(rows)}건 처리")
    print("=" * 70)

    for idx, row in enumerate(rows, start=1):
        addr = row.get('주소', '') or row.get('아파트 주소', '') or row.get('address', '')
        sa_no = row.get('사건번호', '') or row.get('saNo', '') or f'#{idx}'

        # 면적 (m2 또는 평)
        target_area = None
        area_m2 = row.get('m2', '')
        area_pyeong = row.get('평', '')

        if area_m2:
            try:
                target_area = float(area_m2)
            except:
                pass
        elif area_pyeong:
            try:
                target_area = float(area_pyeong) * 3.3058
            except:
                pass

        # 좌표
        dx = row.get('dx', '') or row.get('경도(dx)', '')
        dy = row.get('dy', '') or row.get('위도(dy)', '')

        print(f"\n[{idx}/{len(rows)}] {sa_no}")
        print(f"  주소: {addr}")
        if target_area:
            print(f"  면적: {target_area:.1f}㎡")

        result = dict(row)
        result.update({
            '매칭단지명': '', '단지코드': '',
            '매매가(만원)': '', '매매일자': '', '가격유형': '',
            '거래면적': '', '거래층': '', '거래동': '', '참고정보': ''
        })

        if not addr:
            results.append(result)
            continue

        # 1. 구/동 추출
        gu, dong = fetcher.extract_gu_dong(addr)
        print(f"  → {gu} {dong}")

        if not gu or not dong:
            # 좌표 기반 검색 시도
            if dx and dy:
                print(f"  → 좌표 기반 검색 시도...")
                try:
                    danji_list = fetcher.get_danji_by_coords(float(dy), float(dx))
                    if danji_list:
                        print(f"  → 좌표 검색: {len(danji_list)}개 단지")
                        matched = fetcher.find_matching_danji(addr, danji_list)
                        if matched:
                            # 단지 정보에서 emd_code 추출
                            emd_code = matched.get('signguCode', '') + matched.get('emdCode', '')
                            # 이후 로직으로 진행
                            pass
                except:
                    pass

            print(f"  ❌ 구/동 추출 실패")
            results.append(result)
            continue

        # 2. 코드 조회
        signgu_code = fetcher.signgu_cache.get(gu)
        if not signgu_code:
            print(f"  ❌ 구 코드 없음: {gu}")
            results.append(result)
            continue

        time.sleep(0.2)
        emd_dict = fetcher.get_emd_list(signgu_code)

        # 동 매칭
        emd_code = emd_dict.get(dong)
        if not emd_code:
            for name, code in emd_dict.items():
                base_dong = re.sub(r'\d+가?$', '', dong)
                base_emd = re.sub(r'\d+가?$', '', name)
                if base_dong == base_emd or dong in name or name in dong:
                    emd_code = code
                    dong = name
                    break

        if not emd_code:
            print(f"  ❌ 동 코드 없음: {dong}")
            results.append(result)
            continue

        print(f"  → 코드: {emd_code}")

        # 3. 단지 검색 (단계별)
        apt_name = fetcher.extract_apt_name(addr)

        # 검색 키워드 목록 생성
        search_keywords = []
        if apt_name:
            search_keywords.append(apt_name)  # 원본: "한신아파트"
            # "아파트" 제거한 버전
            short_name = apt_name.replace('아파트', '').strip()
            if short_name and short_name != apt_name:
                search_keywords.append(short_name)  # "한신"
            # 숫자/차수 제거: "우성2차" → "우성"
            base_name = re.sub(r'\d+차?$', '', short_name).strip()
            if base_name and base_name not in search_keywords:
                search_keywords.append(base_name)
        search_keywords.append('')  # 전체 검색

        danji_list = []
        used_keyword = ''

        for keyword in search_keywords:
            time.sleep(0.2)
            danji_list = fetcher.get_danji_list(signgu_code, emd_code, bldg_name=keyword)
            if danji_list:
                used_keyword = keyword if keyword else '전체'
                break

        print(f"  → 단지 {len(danji_list)}개 (검색: {used_keyword or apt_name})")

        # 좌표 기반 보완
        if not danji_list and dx and dy:
            try:
                danji_list = fetcher.get_danji_by_coords(float(dy), float(dx))
                print(f"  → 좌표: {len(danji_list)}개")
            except:
                pass

        if not danji_list:
            print(f"  ❌ 단지 없음")
            results.append(result)
            continue

        # 4. 단지 매칭
        matched = fetcher.find_matching_danji(addr, danji_list)

        if not matched:
            print(f"  ⚠️ 매칭 실패")
            results.append(result)
            continue

        danji_name = matched.get('aprpnHsmpNm', '')
        danji_code = matched.get('aprpnHsmpCode', '')
        print(f"  ✅ {danji_name} ({danji_code})")

        result['매칭단지명'] = danji_name
        result['단지코드'] = danji_code

        # 5. 가격 조회
        time.sleep(0.3)
        price_info = fetcher.get_latest_price(danji_code, emd_code, target_area)

        if price_info['price']:
            type_kr = {
                'sale': '최근매매',
                'sale_1year': '1년전매매',
                'estimated_area': '면적환산',
                'estimated_jeonse': '전세추정',
                'estimated_wolse': '월세추정'
            }.get(price_info['price_type'], '')

            result['매매가(만원)'] = price_info['price']
            result['매매일자'] = price_info['price_date']
            result['가격유형'] = type_kr
            result['거래면적'] = price_info['area'] or ''
            result['거래층'] = price_info['floor'] or ''
            result['거래동'] = price_info['dong'] or ''
            result['참고정보'] = price_info.get('ref_info', '')

            print(f"  💰 {type_kr}: {price_info['price']:,}만원 ({price_info['price_date']})")
            if price_info.get('ref_info'):
                print(f"     {price_info['ref_info']}")
        else:
            print(f"  ❌ 가격 없음")

        results.append(result)

    # 저장
    if results:
        with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)

        print(f"\n{'=' * 70}")
        print(f"✅ {output_csv} 저장 ({len(results)}건)")

        # 통계
        s1 = sum(1 for r in results if r.get('가격유형') == '최근매매')
        s2 = sum(1 for r in results if r.get('가격유형') == '1년전매매')
        s3 = sum(1 for r in results if r.get('가격유형') == '면적환산')
        s4 = sum(1 for r in results if r.get('가격유형') == '전세추정')
        s5 = sum(1 for r in results if r.get('가격유형') == '월세추정')
        s6 = sum(1 for r in results if not r.get('매매가(만원)'))

        print(f"\n📋 요약:")
        print(f"  최근매매: {s1} | 1년전: {s2} | 면적환산: {s3}")
        print(f"  전세추정: {s4} | 월세추정: {s5} | 없음: {s6}")

        return output_csv
    return None


def main():
    if len(sys.argv) >= 3:
        inp, out = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 2:
        inp = sys.argv[1]
        out = inp.replace('.csv', '_with_price.csv')
    else:
        inp, out = 'tankauction_data.csv', 'tankauction_with_price.csv'

    print("=" * 70)
    print("📡 국토교통부 실거래가 v4")
    print(f"   입력: {inp} → 출력: {out}")
    print("=" * 70)

    process_csv(inp, out)


if __name__ == "__main__":
    main()