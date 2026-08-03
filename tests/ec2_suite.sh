#!/usr/bin/env bash
# EC2 에서 도는 E2E 스위트. 실제 브라우저·SSM·네트워크를 다 쓴다.
#
#   bash tests/ec2_suite.sh            # 전체
#   bash tests/ec2_suite.sh --quick    # 파괴적 시나리오 제외
#
# 로컬에서는 못 돌린다(프로필/SSM/systemd 필요). 로컬 테스트는 tests/test_*.py.
cd "$(dirname "$0")/.." || exit 1
REPO=$(pwd)
R="sudo -u ec2-user AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-ap-northeast-2}"
MIRROR=${MIRROR_FILE:-/home/ec2-user/.valley/cookies.txt}
PARAM=${PARAM:-/valley/session}
QUICK=${1:-}
PASS=0; FAIL=0
ok(){ echo "  PASS  $1"; PASS=$((PASS+1)); }
ng(){ echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
sec(){ echo; echo "##### $1"; }

meta(){ $R aws ssm get-parameter --name ${PARAM}-expiry --with-decryption \
        --query Parameter.Value --output text 2>/dev/null; }
cookie(){ $R aws ssm get-parameter --name $PARAM --with-decryption \
          --query Parameter.Value --output text 2>/dev/null; }
svc_log(){ journalctl -u valley-relogin.service -n 20 --no-pager; }

sec "A. 구성 점검 (화이트박스)"
[ "$(systemctl is-enabled valley-relogin.timer 2>/dev/null)" = "enabled" ] \
  && ok "A1 타이머 부팅 시 자동 시작" || ng "A1 타이머 disabled"
grep -q "Persistent=true" /etc/systemd/system/valley-relogin.timer \
  && ok "A2 놓친 실행 따라잡기" || ng "A2 Persistent 없음"
grep -q "xvfb-run" /etc/systemd/system/valley-relogin.service \
  && ok "A3 가상 디스플레이 자동 기동" || ng "A3 xvfb-run 없음"
grep -q "MemoryMax" /etc/systemd/system/valley-relogin.service \
  && ok "A4 메모리 상한 설정" || ng "A4 MemoryMax 없음"
[ "$(stat -c %a $MIRROR 2>/dev/null)" = "600" ] && ok "A5 미러 파일 0600" || ng "A5 권한 이상"
command -v google-chrome >/dev/null && ok "A6 Chrome 설치됨" || ng "A6 Chrome 없음"
command -v xvfb-run >/dev/null && ok "A7 Xvfb 설치됨" || ng "A7 Xvfb 없음"

sec "B. 평상시 동작 (블랙박스)"
BEFORE_MEM=$(free -m | awk '/^Mem:/{print $7}')
systemctl start valley-relogin.service; sleep 6
[ "$(systemctl show valley-relogin.service -p Result --value)" = "success" ] \
  && ok "B1 서비스 정상 종료" || ng "B1 실패"
svc_log | grep -q "Chrome 띄우지 않음" && ok "B2 불필요한 브라우저 미기동" || ng "B2 낭비 기동"
[ "$(pgrep -cf chrome-cdp-profile)" = "0" ] && ok "B3 잔여 프로세스 없음" || ng "B3 잔류"

sec "C. Google 세션 지속성 (핵심)"
# valley 세션(5일)은 짧지만 Google 세션은 수개월이다. 그 수명을 실측한다.
cat > /tmp/gsession.py <<'PYEOF'
import json, os, subprocess, sys, time, urllib.request, datetime
sys.path.insert(0, "/home/ec2-user/insane-search")
from browser_cookies import cdp_call, find_chrome, launch_chrome, wait_for_cdp
PORT = 9466
p = launch_chrome(find_chrome(), "/home/ec2-user/.config/chrome-cdp-profile",
                  PORT, "about:blank", show=False)
try:
    wait_for_cdp(PORT); time.sleep(3)
    bws = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version"))["webSocketDebuggerUrl"]
    cs = cdp_call(bws, "Storage.getCookies")["cookies"]
    g = [c for c in cs if "google.com" in c["domain"]]
    key = {c["name"]: c for c in g}
    now = time.time()
    print(f"  Google 쿠키 {len(g)}개")
    worst = None
    for n in ("__Secure-3PSID", "__Secure-1PSID", "SID", "NID", "__Secure-3PSIDTS"):
        c = key.get(n)
        if not c:
            print(f"    {n:22s} 없음")
            continue
        e = c.get("expires", -1)
        if e and e > 0:
            days = (e - now) / 86400
            print(f"    {n:22s} 만료까지 {days:7.1f}일")
            if n in ("__Secure-3PSID", "SID") and (worst is None or days < worst):
                worst = days
        else:
            print(f"    {n:22s} 세션쿠키(만료없음)")
    print(f"GOOGLE_LIFETIME_DAYS={worst if worst is not None else -1}")
finally:
    subprocess.run(["pkill", "-f", f"remote-debugging-port={PORT}"], capture_output=True)
PYEOF
GOUT=$($R xvfb-run -a python3 /tmp/gsession.py 2>&1 | grep -vE "PythonDeprecation|warnings.warn")
echo "$GOUT" | grep -v GOOGLE_LIFETIME
LIFE=$(echo "$GOUT" | grep -oP 'GOOGLE_LIFETIME_DAYS=\K[-0-9.]+')
echo "  => Google 세션 잔여: ${LIFE}일"
awk -v l="$LIFE" 'BEGIN{exit !(l > 30)}' \
  && ok "C1 Google 세션이 30일 이상 남음 (valley 5일보다 훨씬 김)" \
  || ng "C1 Google 세션 잔여 ${LIFE}일 - 곧 재로그인 필요"
rm -f /tmp/gsession.py

if [ "$QUICK" = "--quick" ]; then
  echo; echo "(--quick: 파괴적 시나리오 생략)"
else
sec "D. 세션 조기 사망 -> 자동 복구 (파괴적)"
BEFORE_MIRROR=$(md5sum $MIRROR 2>/dev/null | cut -d' ' -f1)
GOOD=$(cookie)
$R aws ssm put-parameter --name $PARAM --type SecureString --overwrite \
   --value "$(echo "$GOOD" | sed 's/__Secure-nf.session-token=[^;]*/__Secure-nf.session-token=DEAD_FOR_TEST/')" >/dev/null
echo "  SSM 쿠키를 죽은 값으로 바꿨다 (메타는 여유 있다고 말하는 상태)"
( for i in $(seq 1 45); do free -m | awk '/^Mem:/{print $7}'; sleep 1.5; done > /tmp/m.log ) & MON=$!
systemctl start valley-relogin.service
RES=$(systemctl show valley-relogin.service -p Result --value)
wait $MON 2>/dev/null
MIN=$(sort -n /tmp/m.log | head -1); rm -f /tmp/m.log
[ "$RES" = "success" ] && ok "D1 서비스 정상 종료" || ng "D1 $RES"
svc_log | grep -q "세션이 죽어있다" && ok "D2 메타를 맹신하지 않고 실제 생존 확인" || ng "D2 감지 실패"
svc_log | grep -q "새 세션 발급 완료" && ok "D3 자동 재발급" || ng "D3 재발급 안 됨"
cookie | grep -q "DEAD_FOR_TEST" && ng "D4 SSM 복구 안 됨" || ok "D4 SSM 쿠키 복구"
[ "$BEFORE_MIRROR" != "$(md5sum $MIRROR | cut -d' ' -f1)" ] && ok "D5 미러 갱신" || ng "D5 미러 그대로"
awk -v m="$MIN" 'BEGIN{exit !(m > 150)}' && ok "D6 메모리 안전(최저 ${MIN}MB)" || ng "D6 위험(${MIN}MB)"
[ "$(pgrep -cf chrome-cdp-profile)" = "0" ] && ok "D7 잔여 없음" || ng "D7 잔류"

sec "E. 메타 드리프트 자가 교정 (파괴적)"
$R aws ssm put-parameter --name ${PARAM}-expiry --type SecureString --overwrite \
   --value '{"expires_at": "2030-01-01T00:00:00.000000+00:00"}' >/dev/null
systemctl start valley-relogin.service; sleep 8
meta | grep -q "2030" && ng "E1 틀린 메타가 그대로" || ok "E1 실제값으로 교정됨"
fi

sec "F. 최종 인증 확인 (블랙박스)"
cat > /tmp/f.mjs <<'EOF'
import { valleyFetch } from "/home/ec2-user/insane-search/valley_cookie.mjs";
let bad = 0;
for (const p of ["/premium/lounge","/newsroom","/live-narratives","/premium/wsaj-column"]) {
  try {
    const r = await valleyFetch("https://www.valley.town" + p);
    const h = await r.text();
    const li = /좋은 하루 보내세요|프리미엄/.test(h);
    console.log(`    ${p.padEnd(24)} ${r.status} ${String(h.length).padStart(7)}B 로그인=${li?"O":"X"}`);
    if (r.status !== 200 || !li) bad++;
  } catch (e) { console.log(`    ${p} 예외: ${e.message.slice(0,60)}`); bad++; }
}
process.exit(bad ? 1 : 0);
EOF
$R node /tmp/f.mjs && ok "F1 인증 콘텐츠 전부 정상" || ng "F1 일부 실패"
rm -f /tmp/f.mjs

sec "G. 부작용 없음"
N=$(pgrep -cf "poly-live|outcome-live" || echo 0)
awk -v n="$N" 'BEGIN{exit !(n >= 7)}' && ok "G1 기존 봇 ${N}개 정상" || ng "G1 봇 ${N}개로 감소"
AFTER_MEM=$(free -m | awk '/^Mem:/{print $7}')
echo "  메모리: 시작 ${BEFORE_MEM}MB -> 종료 ${AFTER_MEM}MB"

echo
echo "=================================================="
echo "  통과 $PASS / 실패 $FAIL"
echo "=================================================="
echo "만료: $(meta)"
free -m | head -2; df -h / | tail -1
[ "$FAIL" -eq 0 ]
