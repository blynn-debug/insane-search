#!/usr/bin/env python3
"""
탱크옥션 + 실거래가 데이터 최종 가공

출력 열:
- no: 순번
- 사건번호
- 주소
- 감정가: 만원 단위로 변환
- 매매가(만원)
- 매매일자
- 감정가-매매가 차이: (감정가 - 매매가) 만원, 양수면 감정가가 높음
- 차이율(%): (감정가 - 매매가) / 매매가 * 100
- 비고: 평형오차 또는 면적환산 정보

사용법:
    python process_final.py [입력CSV] [출력CSV]
"""

import csv
import sys


def process_csv(input_csv: str, output_csv: str):
    """CSV 최종 가공"""

    results = []

    with open(input_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for idx, row in enumerate(rows, start=1):
        # 기본 정보
        sa_no = row.get('사건번호', '')
        address = row.get('주소', '')

        # 감정가 (원 → 만원)
        gamjeong_raw = row.get('감정가', '0')
        try:
            gamjeong = int(gamjeong_raw) // 10000  # 원 → 만원
        except:
            gamjeong = 0

        # 매매가 (이미 만원 단위)
        maemae_raw = row.get('매매가(만원)', '')
        try:
            maemae = int(float(maemae_raw)) if maemae_raw else 0
        except:
            maemae = 0

        # 매매일자
        maemae_date = row.get('매매일자', '')

        # 가격유형
        price_type = row.get('가격유형', '')

        # 차이 계산
        diff = 0
        diff_rate = 0
        if gamjeong > 0 and maemae > 0:
            diff = gamjeong - maemae  # 양수: 감정가 > 매매가 (저렴)
            diff_rate = round((diff / maemae) * 100, 1)

        # 비고 (평형오차 또는 면적환산)
        note = ''

        # 면적환산인 경우 참고정보 표시
        if price_type == '면적환산':
            ref_info = row.get('참고정보', '')
            note = f"[면적환산] {ref_info}"
        else:
            # 평형 오차 계산
            m2_raw = row.get('m2', '')
            trade_area_raw = row.get('거래면적', '')

            try:
                m2 = float(m2_raw) if m2_raw else 0
                trade_area = float(trade_area_raw) if trade_area_raw else 0

                if m2 > 0 and trade_area > 0:
                    area_diff = round(m2 - trade_area, 2)
                    if abs(area_diff) >= 0.1:
                        note = f"면적차: {area_diff:+.1f}㎡"
            except:
                pass

        # 가격 없는 경우 표시
        if not maemae:
            note = "[가격정보 없음]"

        results.append({
            'no': idx,
            '사건번호': sa_no,
            '주소': address,
            '감정가(만원)': f"{gamjeong:,}" if gamjeong else '',
            '매매가(만원)': f"{maemae:,}" if maemae else '',
            '매매일자': maemae_date,
            '차이(만원)': f"{diff:+,}" if diff else '0',
            '차이율(%)': f"{diff_rate:+.1f}%" if diff_rate else '0%',
            '비고': note
        })

    # CSV 저장
    fieldnames = ['no', '사건번호', '주소', '감정가(만원)', '매매가(만원)',
                  '매매일자', '차이(만원)', '차이율(%)', '비고']

    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"✅ {output_csv} 저장 완료 ({len(results)}건)")

    # 요약 통계
    with_price = [r for r in results if r['매매가(만원)']]
    cheaper = [r for r in with_price if r['차이(만원)'].startswith('+')]
    expensive = [r for r in with_price if r['차이(만원)'].startswith('-')]

    print(f"\n📊 요약:")
    print(f"  전체: {len(results)}건")
    print(f"  가격 있음: {len(with_price)}건")
    print(f"  감정가 > 매매가 (저렴): {len(cheaper)}건")
    print(f"  감정가 < 매매가 (비쌈): {len(expensive)}건")

    return output_csv


def main():
    if len(sys.argv) >= 3:
        inp, out = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 2:
        inp = sys.argv[1]
        out = inp.replace('.csv', '_final.csv')
    else:
        inp = 'tankauction_with_price.csv'
        out = 'auction_analysis.csv'

    print("=" * 60)
    print("📋 경매 데이터 최종 가공")
    print(f"   입력: {inp}")
    print(f"   출력: {out}")
    print("=" * 60)

    process_csv(inp, out)


if __name__ == "__main__":
    main()