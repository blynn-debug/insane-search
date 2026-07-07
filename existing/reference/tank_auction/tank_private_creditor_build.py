# -*- coding: utf-8 -*-
import json, datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter
SCR=r'C:\Users\user\AppData\Local\Temp\claude\C--Users-user-PycharmProjects-insane-search\b8a6fed3-a188-4b45-a8d0-32eaf5dc520f\scratchpad'
picks=json.load(open(SCR+r'\optA_picks.json',encoding='utf-8'))
allit={it['tid']:it for it in json.load(open(SCR+r'\list_all.json',encoding='utf-8'))}
detail=json.load(open(SCR+r'\detail_raw.json',encoding='utf-8'))
arr=json.load(open(SCR+r'\arrays.json',encoding='utf-8'))
sise=json.load(open(SCR+r'\sise_out.json',encoding='utf-8'))
crt=arr['crtSptArr']; dpt=arr['dptArr']; ctg=arr['ctgrArr']; spl=arr['splCdtnArr']
TYPE={'아파트':'APT','오피스텔(주거)':'OPST','다세대주택':'VL','연립주택':'VL',
 '단독주택':'DDDGG','다가구주택':'DDDGG','상가주택':'SGJT','주상복합':'APT','기숙사':'VL'}
def court(it):
    s=str(it.get('spt')); dd=str(it.get('dpt'))
    return (crt.get(s,'')+' '+dpt.get(s,{}).get(dd,'')).strip()
def sano(it):
    s=f"{it.get('sn1')}타경{it.get('sn2')}"; pn=it.get('pn') or 0
    if pn and pn>1: s+=f"(물건{pn})"
    return s
def spcdtn(it):
    codes=[c.strip() for c in (it.get('sp_cdtn') or '').split(',') if c.strip()]
    return ', '.join(spl.get(c,'') for c in codes if spl.get(c))
def sise_won(it):
    dc=str(it['lst_pnu'])[:10]
    if not dc.startswith(('11','41')) or len(dc)<10: return None,0
    ct=ctg.get(str(it.get('cat3')),''); t=TYPE.get(ct)
    d=sise.get(dc,{}).get('types',{}).get(t) if t else None
    if d and d.get('median_manwon'): return d['median_manwon']*10000, d.get('count',0)
    return None, 0
import re as _re
GUAR_CODES={'31','32'}  # 31=HUG 임차권 인수조건변경, 32=HF 임차권 인수조건변경
def is_guarantee(it):
    codes=[c.strip() for c in (it.get('sp_cdtn') or '').split(',') if c.strip()]
    if GUAR_CODES & set(codes): return True
    dec=' '.join(spl.get(c,'') for c in codes)
    return bool(_re.search(r'HUG|HF|SGI|보증', dec))
rows=[]; excl_guar=0
for p in picks:
    tid=p['tid']; it=allit[tid]
    if is_guarantee(it): excl_guar+=1; continue  # 보증기관(HUG/HF/SGI 등) 관련 물건 제외
    apsl=it.get('apsl_amt') or 0; minb=it.get('minb_amt') or 0
    rank=p['rank']; tot=p.get('total_geun',1)
    rank_s=f"{rank}순위"+(f" (총{tot}건)" if tot>1 else "")
    others=[g for g in p['all_priv'] if not (g['prsn']==p['prsn'] and g['cAmt']==p['cAmt'])]
    others_s='; '.join(f"{g['prsn']}({g['cAmt']:,})" for g in others)
    npl=detail.get(str(tid),{}).get('npl')
    bigo=[]
    if '말소기준' in (p['note'] or ''): bigo.append('말소기준')
    if npl: bigo.append('NPL')
    sc=spcdtn(it)
    if sc: bigo.append(sc)
    sw,scnt=sise_won(it)
    rows.append({'사건번호':sano(it),'법원':court(it),'물건종류':ctg.get(str(it.get('cat3')),''),
        '소재지':it.get('adrs',''),'채권자':p['prsn'],'구분':p['kind'],'순위':rank_s,'_rank':rank,
        '채권최고액':p['cAmt'],'감정가':apsl,'최저가':minb,'최저가율':round(minb/apsl,4) if apsl else 0,
        '시세':sw,'시세건수':scnt,'유찰':it.get('fb_cnt') or 0,'설정일':p['rcDt'],'입찰일':it.get('bid_dt',''),
        '공동근저당':others_s,'비고':' / '.join(bigo)})
rows.sort(key=lambda r:(r['채권최고액'], r['감정가']))
cols=['순번','사건번호','법원','물건종류','소재지','채권자(근저당권자)','구분','근저당순위',
      '채권최고액','감정가','최저가','최저가율','네이버추정시세','유찰','설정일','입찰일','공동근저당권자','비고']
widths=[6,15,12,13,40,24,6,13,15,15,15,8,16,6,11,10,30,24]
wb=Workbook(); ws=wb.active; ws.title='물건목록'
thin=Side(style='thin',color='BFBFBF'); border=Border(left=thin,right=thin,top=thin,bottom=thin)
navy=PatternFill('solid',fgColor='1F4E78'); hdr2=PatternFill('solid',fgColor='2E75B6')
alt=PatternFill('solid',fgColor='EAF1FB'); lowfill=PatternFill('solid',fgColor='C6EFCE')
titlefill=PatternFill('solid',fgColor='DDEBF7'); sisefill=PatternFill('solid',fgColor='FFF2CC')
today=datetime.date(2026,7,7)
ws.merge_cells(start_row=1,start_column=1,end_row=1,end_column=len(cols))
t=ws.cell(1,1,f'탱크옥션 · 서울·경기 주거용 · 개인/법인 근저당권자 물건  (진행중 · 채권최고액 오름차순)   총 {len(rows):,}건 · 기준일 {today:%Y-%m-%d}')
t.font=Font(name='맑은 고딕',size=13,bold=True,color='1F4E78'); t.fill=titlefill
t.alignment=Alignment(horizontal='center',vertical='center'); ws.row_dimensions[1].height=28
for c,name in enumerate(cols,1):
    cell=ws.cell(2,c,name); cell.font=Font(name='맑은 고딕',size=9,bold=True,color='FFFFFF')
    cell.fill=hdr2 if name in('네이버추정시세','근저당순위') else navy
    cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True); cell.border=border
ws.row_dimensions[2].height=30
CEN={1,7,8,12,14,15,16}; RIGHT={9,10,11,13}
for i,r in enumerate(rows):
    rr=3+i; low=r['채권최고액']<=100000000
    vals=[i+1,r['사건번호'],r['법원'],r['물건종류'],r['소재지'],r['채권자'],r['구분'],r['순위'],
          r['채권최고액'],r['감정가'],r['최저가'],r['최저가율'],r['시세'],r['유찰'],r['설정일'],r['입찰일'],r['공동근저당'],r['비고']]
    for c,v in enumerate(vals,1):
        cell=ws.cell(rr,c,v); cell.border=border; cell.font=Font(name='맑은 고딕',size=9)
        if c in (9,10,11,13): cell.number_format='#,##0'
        if c==12: cell.number_format='0.0%'
        if c in CEN: cell.alignment=Alignment(horizontal='center',vertical='center')
        elif c in RIGHT: cell.alignment=Alignment(horizontal='right',vertical='center')
        else: cell.alignment=Alignment(horizontal='left',vertical='center',wrap_text=(c in(5,17,18)))
        if c==9: cell.font=Font(name='맑은 고딕',size=9,bold=True,color='C00000' if low else '1F4E78')
        if c==8 and r['_rank']==1: cell.font=Font(name='맑은 고딕',size=9,bold=True,color='2E7D32')
        if c==13: cell.fill=sisefill  # 시세 열 강조
        elif c==9:
            if low: cell.fill=PatternFill('solid',fgColor='9BE7A8')
        elif low: cell.fill=lowfill
        elif i%2==1: cell.fill=alt
for c,w in enumerate(widths,1): ws.column_dimensions[get_column_letter(c)].width=w
ws.freeze_panes='A3'; ws.auto_filter.ref=f'A2:{get_column_letter(len(cols))}2'
# 필터기준 sheet
ws2=wb.create_sheet('필터기준')
from collections import Counter
rc=Counter(r['_rank'] for r in rows)
sise_have=sum(1 for r in rows if r['시세'])
info=[('추출일',f'{today:%Y-%m-%d}'),
 ('지역','서울특별시(siCd=11) · 경기도(siCd=41) — 소재지 기준'),
 ('물건종류(주거용)','단독/다가구/아파트/연립/다세대/기숙사/상가주택/주상복합/도시형생활주택/오피스텔(주거)'),
 ('진행상태','진행중(신건·유찰)'),
 ('보증기관 물건 제외','비고에 HUG·HF·SGI 등 보증(공기업) 인수조건변경 표시된 임차권 물건 제외'),
 ('채권자 정의','등기부상 근저당권자 (개인 또는 사인(私人)법인)'),
 ('정렬','채권최고액 오름차순'),
 ('대표 근저당 선정','개인/법인 근저당 중 최선순위(접수 빠른 순). 근저당순위=물건 전체 근저당 중 접수순 순위'),
 ('근저당순위 분포',f"1순위 {rc[1]} · 2순위 {rc[2]} · 3순위 {rc[3]} · 4순위이하 {sum(v for k,v in rc.items() if k>=4)}"),
 ('네이버추정시세','new.land.naver.com — 동일 법정동·동일유형 매매 매물 호가(dealOrWarrantPrc) 중위값. 물건 개별 아닌 동 단위 참고치(면적 미반영). '+f'{sise_have}/{len(rows)}건 산출'),
 ('제외 채권자','은행/저축은행/캐피탈/카드/보험/증권/금융/유동화/자산관리·운용/대부/리스/HUG·주택도시/LH·토지주택/SH·공사·공단·진흥원/신용·기술보증기금/농협·수협·신협·금고/새출발기금/근로복지·국민연금·건강보험/세무서·지자체(조세) 등'),
 ('유지 채권자','개인, 일반 사업체 법인, 세무·법무법인, 농축산 협동조합, 종중, 외국인'),
 ('원천→최종','서울3,693+경기5,082=8,775건 → 등기부 개인/법인 근저당권자 물건 1,135건'),
 ('데이터 출처','tankauction.com (목록+등기부) / new.land.naver.com (시세)')]
ws2.column_dimensions['A'].width=20; ws2.column_dimensions['B'].width=98
ws2.merge_cells('A1:B1'); h=ws2.cell(1,1,'■ 추출 기준 및 필터 정의')
h.font=Font(name='맑은 고딕',size=12,bold=True,color='FFFFFF'); h.fill=navy
h.alignment=Alignment(horizontal='left',vertical='center'); ws2.row_dimensions[1].height=24
for i,(k,v) in enumerate(info,2):
    a=ws2.cell(i,1,k); b=ws2.cell(i,2,v)
    a.font=Font(name='맑은 고딕',size=9,bold=True,color='1F4E78'); a.fill=PatternFill('solid',fgColor='EAF1FB')
    a.alignment=Alignment(horizontal='left',vertical='top'); a.border=border
    b.font=Font(name='맑은 고딕',size=9); b.alignment=Alignment(horizontal='left',vertical='top',wrap_text=True); b.border=border
    ws2.row_dimensions[i].height=32 if len(str(v))>70 else 18
import glob,os
out=r'C:\Users\user\Downloads\탱크옥션_서울경기_개인법인근저당_물건_20260707.xlsx'
wb.save(out)
print('SAVED',out,round(os.path.getsize(out)/1024),'KB','| rows',len(rows),'| 보증제외',excl_guar,'| 시세보유',sise_have,'| 1순위',rc[1])
PY_DONE=True
