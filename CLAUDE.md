# CLAUDE.md

이 파일은 Claude Code 가 세션 시작 시 자동으로 읽는다.
저장소 전반이 아니라, 맥락이 없으면 시간을 크게 낭비하게 되는 항목만 적는다.

## 환경

- Windows. Python 은 PATH 에 없다. **`py -3.14`** 를 쓴다
  (`curl_cffi`, `websocket-client` 가 이 인터프리터에 설치돼 있다. 3.12 에는 없다).
- 셸은 PowerShell 5.1. `&&`, 삼항 연산자, `??` 없음. `A; if ($?) { B }` 로 쓴다.

## 브라우저 쿠키 / 로그인 세션

`browser_cookies.py`, `session_keeper.py`, `deploy_aws.sh` 는 한 세트다.
**운영 문서: [SESSION_KEEPALIVE.md](SESSION_KEEPALIVE.md)** — AWS 리소스 목록, 재로그인 절차,
새 컴퓨터 셋업, 트러블슈팅이 전부 여기 있다. 이 쪽 작업 전에 먼저 읽을 것.

시간 낭비를 막는 핵심 세 가지:

1. **Chrome 쿠키 DB를 직접 복호화하려 하지 말 것.** Chrome 127+ App-Bound Encryption 때문에
   `browser_cookie3` 류는 동작하지 않는다. CDP 로 Chrome 자신에게 시켜야 한다.
2. **Chrome 프로필 복사로 로그인을 옮기려 하지 말 것.** 실측 결과 복사 직후 쿠키 655개가
   Chrome 기동 후 0개가 된다. 이미 시도해서 실패한 경로다.
3. **Google 로그인은 자동화도 서버 이전도 안 된다.** 사람이 로컬에서 1회 하는 걸 전제로 설계됐다.

## 비밀값

- `cookies.txt` 는 실제 세션 토큰을 담고 있고 `.gitignore` 의 `**/cookies.txt` 로 제외된다.
  **이 저장소는 퍼블릭이다.** 토큰·AWS 계정 ID·개인 이메일을 커밋하거나 채팅에 붙여넣지 말 것.
- 쿠키 값을 확인해야 할 때는 이름/개수만 출력한다.

## 스크래핑 일반

- "API 가 막혔다/폐지됐다" 고 성급히 단정하지 말 것. 상태코드로 게이트(403/429)와
  폐지(404)를 구분하고, 자동화 탐지(`navigator.webdriver`)를 먼저 의심해 스텔스로 재시도한다.
  curl 한 번 실패로 결론 내리지 않는다.
