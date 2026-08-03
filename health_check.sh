#!/usr/bin/env bash
# valley 세션 유지 시스템 점검 에이전트 (비파괴).
#
# 12시간마다 돌면서 "지금 정상인가" 만 본다. 아무것도 바꾸지 않는다.
# E2E 스위트(tests/ec2_suite.sh)는 SSM 을 일부러 망가뜨렸다 복구하는
# 파괴적 테스트라 운영 중에 반복해서는 안 된다. 그래서 별도로 둔다.
#
#   bash health_check.sh              # 점검만
#   SNS_TOPIC_ARN=arn:... bash health_check.sh    # 이상 시 메일까지
#
# 종료코드 0=정상, 1=이상(알림 발송)
cd "$(dirname "$0")" || exit 1
REGION=${AWS_DEFAULT_REGION:-ap-northeast-2}
PARAM=${PARAM:-/valley/session}
MIRROR=${MIRROR_FILE:-$HOME/.valley/cookies.txt}
PROBE=${PROBE_URL:-https://www.valley.town/newsroom}
GOOGLE_WARN_DAYS=${GOOGLE_WARN_DAYS:-30}
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"

PROB=()          # 발견된 문제
note(){ echo "  OK    $1"; }
bad(){  echo "  ISSUE $1"; PROB+=("$1"); }

ssmget(){ aws ssm get-parameter --region "$REGION" --name "$1" --with-decryption \
          --query Parameter.Value --output text 2>/dev/null; }

echo "===== valley 세션 점검  $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="

# 1) 스케줄러가 살아있는가
if [ "$(systemctl is-enabled valley-relogin.timer 2>/dev/null)" = "enabled" ] \
   && [ "$(systemctl is-active valley-relogin.timer 2>/dev/null)" = "active" ]; then
  note "타이머 활성"
else
  bad "재발급 타이머가 꺼져 있다 (systemctl status valley-relogin.timer)"
fi

LASTRES=$(systemctl show valley-relogin.service -p Result --value 2>/dev/null)
if [ -z "$LASTRES" ] || [ "$LASTRES" = "success" ]; then
  note "마지막 재발급 실행 결과 정상"
else
  bad "마지막 재발급이 실패했다 (Result=$LASTRES)"
fi

# 2) 저장소에 쿠키가 있는가
COOKIE=$(ssmget "$PARAM")
if [ -z "$COOKIE" ] || [ "$COOKIE" = "None" ]; then
  bad "SSM $PARAM 이 비어 있다"
elif ! echo "$COOKIE" | grep -q "__Secure-nf.session-token"; then
  bad "SSM 쿠키에 세션 토큰이 없다"
else
  note "SSM 쿠키 존재 ($(echo "$COOKIE" | tr ';' '\n' | wc -l)개)"
fi

# 3) 실제로 로그인 상태인가 (가장 중요)
if [ -n "$COOKIE" ] && [ "$COOKIE" != "None" ]; then
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 20 \
         -H "Cookie: $COOKIE" -H "User-Agent: $UA" "$PROBE")
  if [ "$CODE" = "200" ]; then
    note "인증 요청 200 (실제 로그인 상태)"
  else
    bad "인증 요청이 $CODE 다. 세션이 죽었을 수 있다 ($PROBE)"
  fi
fi

# 4) 만료까지 남은 시간
META=$(ssmget "${PARAM}-expiry")
if echo "$META" | grep -q expires_at; then
  LEFT=$(python3 -c "
import json,sys,datetime
m=json.loads('''$META''')
d=datetime.datetime.fromisoformat(m['expires_at'])-datetime.datetime.now(datetime.timezone.utc)
print(round(d.total_seconds()/86400,2))" 2>/dev/null)
  if [ -n "$LEFT" ]; then
    awk -v l="$LEFT" 'BEGIN{exit !(l > 1)}' \
      && note "세션 만료까지 ${LEFT}일" \
      || bad "세션 만료까지 ${LEFT}일 - 곧 갱신되어야 한다"
  fi
  # 5) Google 세션 (사람이 개입해야 하는 유일한 지점)
  GLEFT=$(python3 -c "
import json,datetime
m=json.loads('''$META''')
g=m.get('google_expires_at')
if g:
    d=datetime.datetime.fromisoformat(g)-datetime.datetime.now(datetime.timezone.utc)
    print(round(d.total_seconds()/86400))" 2>/dev/null)
  if [ -n "$GLEFT" ]; then
    awk -v l="$GLEFT" -v w="$GOOGLE_WARN_DAYS" 'BEGIN{exit !(l > w)}' \
      && note "Google 세션 잔여 ${GLEFT}일" \
      || bad "Google 세션 잔여 ${GLEFT}일 - 사람이 재로그인해야 한다(noVNC 절차)"
  else
    note "Google 세션 만료 정보 없음 (다음 재발급 때 기록된다)"
  fi
else
  bad "SSM ${PARAM}-expiry 를 읽지 못했다"
fi

# 6) 미러 파일이 저장소와 맞는가
if [ ! -f "$MIRROR" ]; then
  bad "미러 파일이 없다: $MIRROR"
elif [ "$(stat -c %a "$MIRROR")" != "600" ]; then
  bad "미러 파일 권한이 $(stat -c %a "$MIRROR") 다 (600 이어야 함)"
elif [ "$(cat "$MIRROR")" != "$COOKIE" ]; then
  bad "미러 파일이 저장소와 다르다 (봇이 낡은 쿠키를 쓸 수 있다)"
else
  note "미러 파일 일치 / 권한 600"
fi

# 7) 자원 여유 (Chrome 이 뜰 수 있어야 한다)
AVAIL=$(free -m | awk '/^Mem:/{print $7}')
DISK=$(df -m / | awk 'NR==2{print $4}')
awk -v a="$AVAIL" 'BEGIN{exit !(a > 400)}' \
  && note "메모리 여유 ${AVAIL}MB" || bad "메모리 여유 ${AVAIL}MB - 갱신 시 실패할 수 있다"
awk -v d="$DISK" 'BEGIN{exit !(d > 300)}' \
  && note "디스크 여유 ${DISK}MB" || bad "디스크 여유 ${DISK}MB - 볼륨 확장이 필요하다"

# 8) 필수 도구
for c in google-chrome xvfb-run; do
  command -v $c >/dev/null && note "$c 있음" || bad "$c 가 없다"
done

echo
if [ ${#PROB[@]} -eq 0 ]; then
  echo "===== 이상 없음 ====="
  exit 0
fi

echo "===== 이상 ${#PROB[@]}건 ====="
printf '  - %s\n' "${PROB[@]}"

if [ -n "${SNS_TOPIC_ARN:-}" ]; then
  BODY=$(printf 'valley 세션 점검에서 이상이 발견됐다.\n\n'; printf -- '- %s\n' "${PROB[@]}"; \
         printf '\n호스트: %s\n시각: %s\n로그: journalctl -u valley-health -n 50\n' \
         "$(hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
  aws sns publish --region "$REGION" --topic-arn "$SNS_TOPIC_ARN" \
    --subject "valley 세션 점검 이상 ${#PROB[@]}건" --message "$BODY" >/dev/null 2>&1 \
    && echo "  (SNS 알림 발송)" || echo "  (SNS 발송 실패 - sns:Publish 권한 확인)"
fi
exit 1
