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

**결론: 세션은 발급 후 5일 고정이고, HTTP 로 연장할 방법이 없다.**
5일마다 사람이 재로그인해야 한다. keepalive 의 역할은 "유지"가 아니라
**만료 감지와 48시간 전 사전 경고**다.

**valley.town 의 동시접속 제한 여부도 미확인.**
제한이 있다면 로컬 전용 창에서 valley.town 을 다시 쓸 때 서버 쪽 세션이 끊길 수 있다.
안전하게 가려면 사람이 볼 때는 평소 쓰던 일반 Chrome 을 쓰고,
전용 프로필은 서버용으로만 둔다.

## 주의

`cookies.txt` 는 `.gitignore` 로 제외되어 있다(`**/cookies.txt`). 절대 커밋하지 말 것.
CloudShell 에 올렸다면 작업 후 `rm cookies.txt`.
