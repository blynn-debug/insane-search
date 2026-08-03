# valley.town 세션 keepalive 운영 문서

로컬 PC 전원과 무관하게 valley.town 로그인 세션을 살려두는 구조.
Google 로그인은 사람이 로컬에서 1회만 하고, 서버는 사이트 세션 쿠키만 들고 돈다.

```
[로컬 PC]  Chrome 전용 프로필 (Google 로그인 1회)
              │  browser_cookies.py 로 쿠키 추출
              ↓  session_keeper.py push
        [SSM SecureString /valley/session]
              ↑ 회전된 쿠키 저장        │ get
              │                        ↓
        [Lambda valley-keepalive]   [스크래퍼]
         6시간마다 valley.town 접속
         실패 시 SNS 이메일
```

## 무엇이 어디에 있나 (헷갈리기 쉬움)

| 무엇 | 위치 | 24/7 유지되나 |
|---|---|---|
| Google 계정 로그인 | 로컬 Chrome 전용 프로필**에만** | 아니오. AWS 에는 없고, 옮길 수도 없다 |
| valley.town 세션 쿠키 | SSM `/valley/session` | **예.** Lambda 가 6시간마다 갱신 |
| 기존 EC2 의 다른 봇들 | 해당 EC2 | 별개. 이 구조와 무관 |

- Google 로그인은 valley.town 쿠키를 받아내기 위한 **문**일 뿐이다. 유지 대상은 valley.town 쿠키다.
- `deploy_aws.sh` 는 **EC2 에 아무것도 설치하지 않는다.** CloudShell 에서 실행해
  Lambda / SSM / EventBridge / 알람을 만든다. 기존 EC2 와는 별개다.
- **로컬 컴퓨터는 어느 것이든 상관없다.** 맥이든 윈도우든, 심지어 전부 꺼져 있어도
  SSM ↔ Lambda 는 계속 돈다. 로컬이 필요한 건 재로그인할 때뿐이다.

## AWS 리소스

리전 `ap-northeast-2`. 계정 ID는 `aws sts get-caller-identity` 로 확인.

| 종류 | 이름 |
|---|---|
| SSM Parameter (SecureString) | `/valley/session` |
| Lambda | `valley-keepalive` (python3.12, handler `session_keeper.handler`) |
| EventBridge Rule | `valley-keepalive-6h` — `rate(6 hours)` |
| IAM Role | `valley-keepalive-role` |
| SNS Topic | `valley-keepalive-alert` |
| CloudWatch Alarm | `valley-keepalive-errors`, `valley-keepalive-not-running` |

전체 배포/재배포는 `deploy_aws.sh` 하나로 끝난다(멱등).
CloudShell 에 `session_keeper.py`, `cookies.txt`, `deploy_aws.sh` 를 올리고:

```bash
EMAIL=<알림받을주소> bash deploy_aws.sh
```

## 일상 사용

스크래퍼에서 최신 쿠키 꺼내기:

```bash
python session_keeper.py get --store ssm:/valley/session -o cookies.txt
```

상태 확인:

```bash
aws logs tail /aws/lambda/valley-keepalive --since 24h
aws lambda invoke --function-name valley-keepalive /tmp/out.json && cat /tmp/out.json
```

## 재로그인 (5일마다 / 알림이 왔을 때)

Google 로그인은 자동화가 막혀 있어 이 부분만 사람이 해야 한다.
**`relogin.py` 가 전 과정을 한 명령으로 묶는다:**

```bash
py -3.14 relogin.py valley.town
#   1) 전용 Chrome 창이 열린다 -> 로그인하고 Enter
#   2) 쿠키 추출 (만료 시각 포함)
#   3) 저장소 반영
#   4) 확인
```

로컬에 boto3/자격증명이 없으면 3단계에서 `cookies.json` 까지만 만들고
CloudShell 절차를 안내한다. 아래는 그 수동 절차다.

```bash
py -3.14 browser_cookies.py valley.town --open
#   창이 뜨면 Google 계정으로 로그인.
#   "Chrome에 로그인하시겠습니까?" 팝업은 브라우저 동기화라 무시할 것.

py -3.14 browser_cookies.py valley.town --format json -o cookies.json --require "__Secure-nf.session-token"
#   exit 0 이면 성공. json 으로 뽑아야 만료 시각이 같이 담겨 사전 경고를 받을 수 있다.

# cookies.json 을 CloudShell 에 올린 뒤 (같은 이름 파일이 있으면 rm 후 업로드)
python3 session_keeper.py push --store ssm:/valley/session --from cookies.json
```

## 만료 임박 사전 경고

재로그인에는 사람과 로컬 브라우저가 필요하다. 죽은 뒤에 알리면 늦으므로
만료 **48시간 전**에 미리 SNS 로 알린다(`--warn-hours`, 기본 48).

- 만료 시각은 `push` 할 때 `cookies.json` 에서 읽어 `/valley/session-expiry` 에 기록한다.
  `cookies.txt` 로 push 하면 만료를 알 수 없어 사전 경고가 비활성된다.
- 회전이 일어나 만료가 밀리면 자동으로 갱신되고 경고 플래그도 풀린다.
- 경고는 만료 주기당 **한 번만** 발송된다(`warned_at` 으로 중복 차단).
- 메타가 깨졌거나 읽히지 않으면 로그에 남긴다. 조용히 비활성되지 않는다.

현재 상태 확인:

```bash
aws ssm get-parameter --name /valley/session-expiry --with-decryption --query Parameter.Value --output text
```

`--with-decryption` 을 빠뜨리면 SecureString 암호문(base64 덩어리)이 그대로 나온다.
쿠키 조회도 마찬가지다.

## 새 컴퓨터에서 시작할 때

```bash
git clone <이 저장소>
pip install websocket-client          # browser_cookies.py 의 유일한 의존성
aws configure                          # 스크래퍼/배포용
```

그리고 위 "재로그인" 절차를 그대로 밟는다. **기존 PC의 Chrome 프로필을 복사해 오려 하지 말 것**
(아래 제약 참고). 새 PC에서 새로 로그인하면 되고, push 하면 SSM 이 갱신되어 서버도 새 세션을 쓴다.

AWS 인프라는 이미 떠 있으므로 `deploy_aws.sh` 를 다시 돌릴 필요는 없다.

`browser_cookies.py` 는 Windows / macOS / Linux 의 Chrome 경로를 모두 찾는다.
전용 프로필 위치는 OS 마다 다르다:

| OS | 전용 프로필 |
|---|---|
| Windows | `%LOCALAPPDATA%\chrome-cdp-profile` |
| macOS | `~/Library/Application Support/chrome-cdp-profile` |
| Linux | `~/.config/chrome-cdp-profile` |

(macOS 경로는 코드상 반영만 했고 실기 검증은 아직 못 했다.)

## keepalive 를 EC2 cron 으로 옮기려면

기본은 Lambda 다. EC2 가 꺼지거나 재부팅해도 안 멈추기 때문이다.
**단, 스크래퍼가 특정 EC2 에서 돈다면** 거기로 합치는 편이 낫다.
Lambda 는 실행마다 다른 IP 를 쓰는데, 일부 사이트는 같은 세션이 여러 IP 에서
제시되는 걸 이상 징후로 본다. 스크래퍼와 keepalive 의 IP 를 하나로 통일하는 효과가 있다.

"AWS 차단을 피하려고" 옮기는 건 의미가 없다. Lambda 도 EC2 도 똑같은 AWS 대역이다.
그리고 keepalive 는 하루 4회 요청이라 차단 대상이 될 수준이 아니다.

옮길 때는 **반드시 Lambda 스케줄을 먼저 끈다.** 둘 다 돌면 토큰 회전 시 경합이 생겨
한쪽이 낡은 토큰으로 새 토큰을 덮어쓸 수 있다.

```bash
aws events disable-rule --name valley-keepalive-6h
aws cloudwatch delete-alarms --alarm-names valley-keepalive-not-running

# EC2 에서 (권한은 액세스 키 대신 인스턴스 역할로 주는 걸 권장)
crontab -e
0 */6 * * * cd ~/insane-search && SNS_TOPIC_ARN=<토픽ARN> /usr/bin/python3 session_keeper.py keepalive --store ssm:/valley/session >> /var/log/valley-keepalive.log 2>&1
```

cron 은 조용히 죽어도 아무도 모른다. `SNS_TOPIC_ARN` 을 반드시 넣어 세션 만료 알림은 살려둘 것.

## 실측으로 확인된 제약 (2026-07-31)

**1. Chrome 쿠키를 외부에서 직접 복호화할 수 없다.**
Chrome 127+ App-Bound Encryption 때문에 `browser_cookie3` 류는 Chrome 에서 동작하지 않는다.
그래서 CDP(원격 디버깅)로 Chrome 자신에게 복호화를 시킨다.

**2. 프로필 복사도 안 된다. 다시 시도하지 말 것.**
평소 프로필의 쿠키 DB를 전용 프로필로 복사해봤으나:
복사 직후 655개 → Chrome 기동 후 **0개** (파일 크기는 그대로).
Chrome 이 복호화 실패한 쿠키 DB를 통째로 비운다. `Local State`(키)까지 같이 복사해도 동일.
=> 로그인 세션을 다른 프로필/다른 PC 로 "가져오는" 방법은 없다. 그 프로필에서 직접 로그인해야 한다.

**3. Chrome 136+ 는 기본 프로필에 `--remote-debugging-port` 를 거부한다.**
그래서 `%LOCALAPPDATA%\chrome-cdp-profile` 전용 프로필을 따로 쓴다.

**4. CDP WebSocket 은 `Origin` 헤더가 붙으면 403.**
Chrome 을 `--remote-allow-origins=*` 로 여는 대신 클라이언트에서 Origin 을 억제한다
(`suppress_origin=True`). 브라우저를 열어두는 쪽이 더 위험하다.

**5. valley.town 은 세션을 IP 에 묶지 않는다.**
AWS 데이터센터 IP(CloudShell)에서 동일 쿠키로 `200` 확인.
덕분에 Google 로그인을 서버로 옮기지 않고도 목적을 달성했다.

**6. 세션 토큰은 NextAuth JWT(JWE) 방식이다.**
서버측 세션 저장소가 없으므로 로그아웃해도 토큰이 만료 전까지 유효할 수 있다.
관측된 만료: 발급 시점 + **5일**. 토큰 값 취급에 주의.

**7. Google 로그인은 서버로 옮기지 않는다.**
Google 쿠키는 기기/IP 에 묶이고(`__Secure-3PSIDTS` 는 수십 분마다 회전),
데이터센터 IP 에서의 로그인은 추가 인증·차단을 부른다. 서버에는 valley.town 쿠키만 둔다.

## 점검 (테스트와 구분)

**운영 중 점검은 `health_check.sh` 로 한다.** 읽기만 하고 아무것도 바꾸지 않는다.
`valley-health.timer` 가 12시간마다(09,21시 UTC) 돌린다.
재발급 타이머(03,15시)와 6시간 어긋나 있어, 갱신 직후가 아니라
"갱신이 제때 됐는지" 를 보는 시점이 된다.

보는 것: 타이머 활성 / 마지막 재발급 결과 / SSM 쿠키 존재 /
**실제 인증 요청 200** / 세션 만료 잔여 / **Google 세션 잔여** /
미러 파일 일치·권한 / 메모리·디스크 여유 / Chrome·Xvfb 존재.

이상이 있으면 SNS 로 알리고 exit 1. 알림이 나가려면 EC2 역할에 권한이 필요하다:

```bash
aws iam put-role-policy --role-name valley-cookie-reader --policy-name valley-sns-publish \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
    "Action":"sns:Publish","Resource":"arn:aws:sns:ap-northeast-2:<계정ID>:valley-keepalive-alert"}]}'
```

수동 점검:

```bash
cd ~/insane-search && bash health_check.sh
journalctl -u valley-health -n 40 --no-pager
```

**`tests/ec2_suite.sh` 는 점검용이 아니다.** SSM 을 일부러 망가뜨렸다 복구하는
파괴적 테스트라 배포 검증 때만 수동으로 돌린다. 주기 실행에 걸면 안 된다.

## 생존 판정 방식

`https://www.valley.town/newsroom` 응답으로 판단한다.

- `200` → 세션 유효
- `307 → /login?redirectUrl=...` → 만료

접속 행위 자체가 롤링 세션의 만료를 뒤로 민다. 만료를 감지하면 저장소를 **덮어쓰지 않고**
exit 3 으로 죽는다(낡은 쿠키를 빈 값으로 날리지 않기 위해).

## 미확정 사항

~~롤링 갱신이 도는지 미확인~~ → **2026-08-03 확정: 롤링 갱신은 없다.**

3일간 관측 결과 만료 시각이 전혀 밀리지 않았다(`expires_at` 이 발급 시점 그대로).
인증된 페이지(`/newsroom`, `/premium/lounge`, `/live-narratives`)가 200 을 주면서도
세션 쿠키를 재발급하지 않고, 세션 재발급용 엔드포인트도 없다
(`/api/auth/session`, `/api/auth/csrf` 등 후보 7개 전부 404).

**세션은 발급 후 5일 고정이고, HTTP 로 연장할 방법이 없다.**

### 다만 재발급은 자동화된다 (2026-08-03 확인)

만료되는 건 valley 세션(5일)이지 **Google 세션(수개월)이 아니다.**
전용 프로필의 Google 세션이 살아 있으면 OAuth 를 다시 타는 것만으로
비밀번호·2FA 없이 새 세션이 나온다. 실측: 클릭 2번, 4초.

```
/login -> '다른 방법으로 로그인' -> '구글로 계속하기' -> 새 세션 (5일)
```

`auto_relogin.py` 가 이걸 자동으로 한다:

```bash
py -3.14 auto_relogin.py valley.town --store ssm:/valley/session
#   만료 48시간 이내일 때만 갱신한다(--force 로 강제)
```

- Google 세션까지 죽으면 **exit 4**. 이때만 사람이 `relogin.py` 로 로그인한다.
- 페이지 문구가 바뀌면 **exit 5** + 스크린샷(`--shot-dir`). 조용히 실패하지 않는다.
- 버튼은 화면 문구로 찾는다(`MORE_RE`, `IDP_RE`). 사이트가 문구를 바꾸면 거기만 고친다.

### 24/7 무인 운영 (구조 B) — 2026-08-03 구축 완료

EC2 에 Chrome 을 올리고 Google 로그인을 1회만 해두면 로컬 PC 와 완전히 무관해진다.
**데이터센터 IP 에서도 Google 로그인이 통과했다.**

현재 구성 (인스턴스 `i-0cdab85ab7b2918ec`, t3.small):

| 항목 | 값 |
|---|---|
| systemd 타이머 | `valley-relogin.timer` — 매일 03,15시 UTC (재발급) |
| 점검 타이머 | `valley-health.timer` — 매일 09,21시 UTC (비파괴 점검) |
| 서비스 | `valley-relogin.service` — `xvfb-run` 으로 감싸 실행 |
| 프로필 | `/home/ec2-user/.config/chrome-cdp-profile` |
| 저장소 | `ssm:/valley/session` |
| 로그 | `/home/ec2-user/valley-relogin.log`, `journalctl -u valley-relogin` |

**Chrome 을 상시 띄우지 않는다.** 타이머가 돌 때마다 SSM 의 만료 시각을 먼저 읽고,
여유가 있으면 그대로 끝낸다. 실제로 Chrome 이 뜨는 건 4~5일에 한 번, 몇 초뿐이다.
그때만 `xvfb-run` 이 가상 디스플레이를 띄우고 끝나면 정리한다(잔여 프로세스 0).

t3.small 은 여유 메모리가 500~900MB 뿐이고 node 봇 7개가 상주하므로
Chrome 상시 기동은 OOM 위험이 있다. 그래서 이 구조를 택했다.

#### 1회 Google 로그인 (구축 시에만)

SSH 키가 없어도 SSM 으로 된다. 로컬에 AWS CLI + Session Manager 플러그인이 필요하다.

```bash
# EC2: Xvfb + Chrome + VNC 를 임시로 띄운다
Xvfb :99 -screen 0 1280x900x24 -nolisten tcp &
DISPLAY=:99 google-chrome --remote-debugging-port=9222 \
  --user-data-dir=$HOME/.config/chrome-cdp-profile --no-sandbox \
  --disable-dev-shm-usage about:blank &
x0vncserver -display :99 -rfbport 5900 -SecurityTypes None -localhost &
/opt/novnc/utils/websockify/run --web /opt/novnc 127.0.0.1:6080 localhost:5900 &

# 로컬: 터널
aws ssm start-session --target <인스턴스ID> \
  --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=6080,localPortNumber=6080

# 브라우저에서 http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale
# -> valley.town/login -> '다른 방법으로 로그인' -> '구글로 계속하기'
```

끝나면 임시 프로세스(Xvfb, Chrome, x0vncserver, websockify)를 모두 정리한다.
Google 세션은 프로필 디스크에 남으므로 이후 타이머가 알아서 쓴다.

막힌 지점들:
- `chrome://inspect` 의 자동 탐지는 동작하지 않았다. DevTools 직접 URL 도 DOM 이 안 떴다.
  noVNC 가 유일하게 확실했다.
- 로컬 브라우저의 MetaMask 확장이 noVNC 페이지에 끼어들어 에러창을 띄운다. 시크릿 창에서 열면 된다.
- AL2023 에 `x11vnc` 는 없다. `tigervnc-server` 의 `x0vncserver` 를 쓴다.
- PowerShell 에서 `--parameters '{"json"}'` 은 따옴표가 깨진다. `portNumber=6080,localPortNumber=6080` 축약형을 쓴다.

**valley.town 의 동시접속 제한 여부도 미확인.**
제한이 있다면 로컬 전용 창에서 valley.town 을 다시 쓸 때 서버 쪽 세션이 끊길 수 있다.
안전하게 가려면 사람이 볼 때는 평소 쓰던 일반 Chrome 을 쓰고,
전용 프로필은 서버용으로만 둔다.

## 주의

`cookies.txt` 는 `.gitignore` 로 제외되어 있다(`**/cookies.txt`). 절대 커밋하지 말 것.
CloudShell 에 올렸다면 작업 후 `rm cookies.txt`.
