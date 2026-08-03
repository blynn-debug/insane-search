# -*- coding: utf-8 -*-
"""사람 개입 없이 valley.town 세션을 재발급받는다.

전용 Chrome 프로필의 Google 세션은 수개월 유지되는 반면 valley.town 세션은 5일이다.
그래서 만료된 valley 세션만 Google OAuth 로 다시 받아오면 된다.
실측(2026-08-03): /login -> '다른 방법으로 로그인' -> '구글로 계속하기' 클릭 두 번으로
비밀번호·2FA 없이 4초 만에 새 세션이 발급됐다.

    py -3.14 auto_relogin.py valley.town --store ssm:/valley/session

Google 세션까지 죽으면 이 스크립트로는 복구할 수 없다(사람이 로그인해야 한다).
그 경우 exit 4 로 끝나며, relogin.py 로 수동 로그인해야 한다.
"""
import argparse
import base64
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from browser_cookies import (  # noqa: E402
    DEFAULT_PROFILE, cdp_call, find_chrome, launch_chrome, log_line,
    match_domain, port_open, wait_for_cdp,
)

TOKEN = "__Secure-nf.session-token"
# 화면 문구로 버튼을 찾는다. 사이트가 문구를 바꾸면 여기만 고치면 된다.
MORE_RE = r"다른 방법|다른방법|other"
IDP_RE = r"google|구글"


def http(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


class Tab:
    """페이지 타깃 하나를 열고 CDP 로 조작한다."""

    def __init__(self, port):
        self.port = port
        t = http(port, "/json/new?about:blank", method="PUT")
        self.id = t["id"]
        from websocket import create_connection
        self.ws = create_connection(t["webSocketDebuggerUrl"], timeout=90,
                                    max_size=64 * 1024 * 1024, suppress_origin=True)
        self.n = 0

    def send(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})

    def js(self, expr):
        return self.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": True
        }).get("result", {}).get("value")

    def click_by_text(self, pattern):
        """보이는 버튼/링크 중 문구가 맞는 첫 요소를 클릭한다."""
        return self.js("""
          (() => {
            const re = new RegExp(%s, 'i');
            const els = Array.from(document.querySelectorAll('button,a[href],[role=button]'))
              .filter(e => e.offsetParent !== null);
            const e = els.find(x => re.test(x.innerText || '') ||
                                    re.test(x.getAttribute('href') || ''));
            if (!e) return false;
            e.click();
            return true;
          })()
        """ % json.dumps(pattern))

    def shot(self, path):
        try:
            data = self.send("Page.captureScreenshot", {"format": "png"})["data"]
            with open(path, "wb") as f:
                f.write(base64.b64decode(data))
            return path
        except Exception:
            return None

    def close(self):
        try:
            self.ws.close()
        finally:
            try:
                http(self.port, f"/json/close/{self.id}")
            except Exception:
                pass


def session_cookie(bws):
    for c in cdp_call(bws, "Storage.getCookies")["cookies"]:
        if c["name"] == TOKEN:
            return c
    return None


def google_alive(bws):
    return any(c["name"] == "__Secure-3PSID" and "google" in c["domain"]
               for c in cdp_call(bws, "Storage.getCookies")["cookies"])


def drop_session(tab, cookie):
    """만료 임박한 세션만 지운다. url 이 아니라 정확한 domain+path 를 줘야 지워진다."""
    tab.send("Network.enable")
    tab.send("Network.deleteCookies",
             {"name": TOKEN, "domain": cookie["domain"], "path": cookie.get("path", "/")})


def main():
    ap = argparse.ArgumentParser(description="무개입 세션 재발급", allow_abbrev=False)
    ap.add_argument("domain", nargs="?", default="valley.town")
    ap.add_argument("--store", default="", help="지정하면 성공 후 session_keeper push 까지 한다")
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--login-url", default="https://www.valley.town/login")
    ap.add_argument("--probe-url", default="",
                    help="세션 생존 확인용 URL. 비우면 session_keeper 기본값을 쓴다")
    ap.add_argument("--force", action="store_true",
                    help="아직 안 죽었어도 새로 발급받는다")
    ap.add_argument("--renew-before", type=float, default=48,
                    help="만료 N시간 전이면 갱신한다 (기본 48)")
    ap.add_argument("--max-trust-days", type=float, default=7,
                    help="저장소 만료가 N일보다 멀면 틀어진 것으로 보고 "
                         "실제 값을 확인한다 (valley 세션은 최대 5일, 기본 7)")
    ap.add_argument("--mirror-file", default=os.environ.get("MIRROR_FILE"),
                    metavar="PATH",
                    help="갱신 후 쿠키를 로컬 파일에도 쓴다(0600). AWS SDK 없는 봇용")
    ap.add_argument("--log-file")
    ap.add_argument("--shot-dir", default="", help="단계별 스크린샷을 남길 디렉터리")
    args = ap.parse_args()

    # 저장소 쪽 세션이 죽어있다고 판명되면 표시해둔다. 프로필 세션이 멀쩡하더라도
    # 저장소는 다시 맞춰줘야 하기 때문이다(재로그인은 필요 없다).
    store_dead = False

    # 저장소에 기록된 만료를 먼저 본다. 아직 여유가 있으면 Chrome 을 아예 띄우지 않는다.
    # 메모리가 빠듯한 서버(t3.small 등)에서 12시간마다 Chrome 을 띄우는 건 낭비이자 위험이다.
    if args.store and not args.force:
        try:
            from session_keeper import (DEFAULT_PROBE, is_alive, meta_read,  # noqa: E402
                                        probe, store_read)
            exp_raw = meta_read(args.store).get("expires_at")
            if exp_raw:
                left = (datetime.datetime.fromisoformat(exp_raw)
                        - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600
                if left > args.max_trust_days * 24:
                    # valley 세션은 발급 후 5일이 최대다. 그보다 긴 값은 메타가
                    # 틀어진 것이므로 믿지 않고 Chrome 으로 실제 만료를 확인·교정한다.
                    # (안 그러면 틀린 메타가 영영 안 고쳐지고 만료 경고도 안 나간다)
                    log_line(args.log_file,
                             f"[!] 저장소 만료가 비정상적으로 멀다({left/24:.0f}일). "
                             "실제 값을 확인해 교정한다")
                elif left > args.renew_before:
                    # 만료까지 여유가 있어도 실제로 살아있는지 한 번 확인한다.
                    # 메타만 믿으면, 서버가 세션을 조기 무효화했을 때 영영 못 알아챈다
                    # (전수 테스트에서 실제로 이 구멍이 드러났다).
                    # HTTP 요청 한 번이라 Chrome 을 띄우는 것보다 훨씬 싸다.
                    raw = store_read(args.store)
                    if raw:
                        status, headers, _ = probe(args.probe_url or DEFAULT_PROBE, raw)
                        alive, why = is_alive(status, headers)
                        if alive:
                            log_line(args.log_file,
                                     f"[o] 만료까지 {left/24:.1f}일, 세션도 살아있다 - Chrome 띄우지 않음")
                            return 0
                        store_dead = True
                        log_line(args.log_file,
                                 f"[!] 만료 전인데 저장소 세션이 죽어있다 ({why})")
                    else:
                        store_dead = True
                        log_line(args.log_file, "[!] 저장소가 비었다")
                else:
                    log_line(args.log_file, f"[.] 만료까지 {left:.1f}시간. 갱신을 시작한다")
        except Exception as e:
            log_line(args.log_file, f"[!] 저장소 만료 확인 실패({e}). Chrome 을 띄워 직접 확인한다")

    proc = None
    if not port_open(args.port):
        proc = launch_chrome(find_chrome(), args.profile, args.port, "about:blank", show=False)
        wait_for_cdp(args.port)
        time.sleep(3)

    tab = None
    try:
        bws = http(args.port, "/json/version")["webSocketDebuggerUrl"]
        if not google_alive(bws):
            log_line(args.log_file,
                     "[X] Google 세션이 없다. 자동 재발급 불가 - relogin.py 로 사람이 로그인해야 한다.")
            return 4

        cur = session_cookie(bws)
        need_login = True
        if cur and not args.force:
            left = (cur.get("expires", 0) - time.time()) / 3600
            if left > args.renew_before:
                if store_dead:
                    # 프로필 세션은 멀쩡한데 저장소만 망가진 경우.
                    # 재로그인 없이 지금 쿠키를 저장소에 다시 넣어주면 된다.
                    # (이걸 안 하면 저장소가 죽은 채 방치돼 스크래퍼만 계속 실패한다)
                    log_line(args.log_file,
                             f"[!] 프로필 세션은 유효하다({left/24:.1f}일). "
                             "재로그인 없이 저장소만 다시 맞춘다")
                    need_login = False
                else:
                    log_line(args.log_file,
                             f"[o] 아직 {left/24:.1f}일 남았다. 갱신 불필요 (--force 로 강제 가능)")
                    # 저장소 메타가 실제 쿠키와 어긋나 있으면 바로잡는다.
                    # 안 그러면 매번 여기까지 와서 Chrome 을 띄우고(메모리 낭비),
                    # 만료 경고도 엉뚱한 시점에 나간다. 스스로 못 고치는 상태가 된다.
                    if args.store and cur.get("expires"):
                        real = datetime.datetime.fromtimestamp(
                            cur["expires"], datetime.timezone.utc).isoformat()
                        try:
                            from session_keeper import meta_read, meta_write
                            if meta_read(args.store).get("expires_at") != real:
                                meta_write(args.store, {"expires_at": real})
                                log_line(args.log_file, "[o] 저장소 만료 정보를 실제값으로 바로잡았다")
                        except Exception as e:
                            log_line(args.log_file, f"[!] 만료 정보 보정 실패: {e}")
                    return 0

        if not need_login:
            got = cur     # 저장소만 다시 맞추면 되는 경우. 로그인 흐름을 건너뛴다.
        else:
            tab = Tab(args.port)
            tab.send("Page.enable")
            if cur:
                drop_session(tab, cur)

            tab.send("Page.navigate", {"url": args.login_url})
            time.sleep(6)
            if args.shot_dir:
                tab.shot(os.path.join(args.shot_dir, "1_login.png"))

            # Google 버튼이 처음부터 보이면 그대로, 아니면 '다른 방법으로 로그인' 을 편다.
            if not tab.click_by_text(IDP_RE):
                if not tab.click_by_text(MORE_RE):
                    log_line(args.log_file,
                             "[X] '다른 방법으로 로그인' 을 못 찾았다. 페이지 구조가 바뀌었다.")
                    if args.shot_dir:
                        tab.shot(os.path.join(args.shot_dir, "err_no_more.png"))
                    return 5
                time.sleep(2.5)
                if not tab.click_by_text(IDP_RE):
                    log_line(args.log_file,
                             "[X] '구글로 계속하기' 를 못 찾았다. 페이지 구조가 바뀌었다.")
                    if args.shot_dir:
                        tab.shot(os.path.join(args.shot_dir, "err_no_idp.png"))
                    return 5

            for _ in range(12):
                time.sleep(2.5)
                if session_cookie(bws):
                    break
            got = session_cookie(bws)
            if args.shot_dir:
                tab.shot(os.path.join(args.shot_dir, "2_after.png"))

            if not got:
                log_line(args.log_file,
                         f"[X] 30초 안에 세션이 안 나왔다. URL={tab.js('location.href')} "
                         "Google 이 재인증을 요구했을 수 있다 - 사람이 확인해야 한다.")
                return 4

            left = (got.get("expires", 0) - time.time()) / 86400
            log_line(args.log_file, f"[o] 새 세션 발급 완료 ({left:.1f}일짜리)")

        # 쿠키는 Chrome 이 살아있는 동안 꺼내야 한다.
        # 종료 후 별도 프로세스로 다시 띄워 읽으면, 방금 받은 세션이 아직 디스크에
        # 안 내려가 있어 '쿠키 없음' 으로 실패한다(실측).
        if args.store:
            jar = [c for c in cdp_call(bws, "Storage.getCookies")["cookies"]
                   if match_domain(c["domain"], args.domain)]
            cookie_json = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "_auto_cookies.json")
            with open(cookie_json, "w", encoding="utf-8") as f:
                json.dump(jar, f, ensure_ascii=False)
            log_line(args.log_file, f"[o] 쿠키 {len(jar)}개 추출 (Chrome 종료 전)")
    finally:
        if tab:
            tab.close()
        if proc:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True)
            else:
                proc.terminate()

    if args.store:
        here = os.path.dirname(os.path.abspath(__file__))
        tmp = os.path.join(here, "_auto_cookies.json")
        if not os.path.exists(tmp):
            log_line(args.log_file, "[X] 추출된 쿠키 파일이 없다")
            return 3
        push = [sys.executable, "session_keeper.py", "push",
                "--store", args.store, "--from", tmp, "--require", TOKEN]
        # 미러 경로를 환경변수에만 의존하면 수동 실행 때 미러가 낡은 채 남는다.
        # 명시적으로 넘긴다(값이 없으면 session_keeper 가 MIRROR_FILE 을 본다).
        if args.mirror_file:
            push += ["--mirror-file", args.mirror_file]
        r = subprocess.run(push, cwd=here)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
