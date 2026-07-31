# -*- coding: utf-8 -*-
"""로그인된 Chrome 프로필에서 쿠키를 자동으로 뽑아온다.

Chrome을 CDP(원격 디버깅)로 붙어서 Chrome 자신이 복호화한 쿠키를 받으므로
Chrome 127+ App-Bound Encryption(외부 프로세스의 쿠키 DB 직접 복호화 차단)에 걸리지 않는다.
browser_cookie3 처럼 Network\\Cookies 를 직접 뜯는 방식은 Chrome에서 더 이상 안 된다.

Google 소셜 로그인처럼 자동화가 막힌 로그인은 --login 으로 한 번만 사람이 로그인해두면
전용 프로필에 세션이 남아 이후로는 자동으로 재사용된다.

    py -3.14 browser_cookies.py valley.town --login    # 최초 1회: 창 띄워서 직접 로그인
    py -3.14 browser_cookies.py valley.town            # 이후: 쿠키만 뽑아서 출력
    py -3.14 browser_cookies.py valley.town -o cookies.txt

의존성: pip install websocket-client
"""
import argparse
import datetime
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

DEFAULT_PROFILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "chrome-cdp-profile"
)
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
]


# [시도했다가 폐기] 평소 Chrome 프로필의 쿠키 DB를 이 프로필로 복사하는 방법.
# 다시 시도하지 말 것. 2026-07-31 실측 결과:
#   복사 직후 대상 DB = 쿠키 655개  ->  Chrome 기동 후 = 0개 (파일 크기는 그대로)
# Chrome 127+ App-Bound Encryption이 다른 위치로 옮겨진 쿠키 DB를 복호화하지 못하고
# 내용을 통째로 폐기한다. Local State(키)까지 같이 복사해도 동일하다.
# => 로그인 세션을 이 프로필로 "가져오는" 방법은 없다. 이 프로필에서 직접 로그인해야 한다.


def find_chrome():
    for p in CHROME_CANDIDATES:
        if p and os.path.exists(p):
            return p
    p = shutil.which("chrome")
    if p:
        return p
    raise SystemExit("chrome.exe 를 못 찾았다. --chrome 으로 경로를 지정해라.")


def port_open(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def launch_chrome(chrome, profile, port, url, show):
    """전용 프로필로 Chrome을 띄운다.

    Chrome 136+ 는 기본 프로필 디렉터리에 --remote-debugging-port 를 붙이면 거부한다.
    그래서 기본 프로필을 건드리지 않고 전용 프로필을 따로 쓴다.
    """
    os.makedirs(profile, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-features=Translate,OptimizationHints",
    ]
    if not show:
        # 창을 화면 밖으로 보내 눈에 안 띄게 한다. headless 는 로그인 세션 재사용이
        # 불안정한 경우가 있어 기본값으로 쓰지 않는다.
        args += ["--window-position=-32000,-32000", "--window-size=1200,900"]
    args.append(url)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def wait_for_cdp(port, timeout=30):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return json.load(r)
        except Exception as e:  # 아직 안 떴다
            last = e
            time.sleep(0.4)
    raise SystemExit(f"CDP 포트 {port} 가 안 열렸다: {last}")


def cdp_call(ws_url, method, params=None, timeout=30):
    try:
        from websocket import create_connection
    except ImportError:
        raise SystemExit("websocket-client 가 없다:  pip install websocket-client")
    # suppress_origin: Origin 헤더가 붙으면 Chrome이 핸드셰이크를 403으로 막는다.
    # (--remote-allow-origins=* 로 Chrome을 열어주는 것보다 이쪽이 안전하다)
    ws = create_connection(
        ws_url, timeout=timeout, max_size=64 * 1024 * 1024, suppress_origin=True
    )
    try:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]
    finally:
        ws.close()


def get_all_cookies(port):
    info = wait_for_cdp(port)
    ws_url = info["webSocketDebuggerUrl"]
    # 브라우저 타깃에서 Storage.getCookies 로 전체 컨텍스트의 쿠키를 한 번에 받는다.
    return cdp_call(ws_url, "Storage.getCookies")["cookies"]


def match_domain(cookie_domain, want):
    d = cookie_domain.lstrip(".").lower()
    w = want.lstrip(".").lower()
    return d == w or d.endswith("." + w)


def as_header(cookies):
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def as_netscape(cookies):
    lines = ["# Netscape HTTP Cookie File", ""]
    for c in cookies:
        dom = c["domain"]
        lines.append(
            "\t".join(
                [
                    dom,
                    "TRUE" if dom.startswith(".") else "FALSE",
                    c.get("path", "/"),
                    "TRUE" if c.get("secure") else "FALSE",
                    str(int(c.get("expires", 0)) if c.get("expires", -1) > 0 else 0),
                    c["name"],
                    c["value"],
                ]
            )
        )
    return "\n".join(lines) + "\n"


def log_line(path, msg):
    """무인 실행 흔적을 남긴다. 스케줄러로 돌릴 때 실패를 나중에 추적하려면 필요하다."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {msg}"
    print(line, file=sys.stderr)
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        # 메모장/PowerShell이 한글을 ANSI로 잘못 읽지 않도록 새 파일에만 BOM을 붙인다.
        # (append 마다 utf-8-sig 로 열면 BOM이 파일 중간에 끼어든다)
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, "a", encoding="utf-8") as f:
            if new:
                f.write("﻿")
            f.write(line + "\n")


def main():
    # allow_abbrev=False: '--log' 같은 축약이 --login/--log-file 중 하나로 조용히 붙는 걸 막는다.
    ap = argparse.ArgumentParser(description="로그인된 Chrome에서 쿠키 자동 추출 (CDP 경유)",
                                 allow_abbrev=False)
    ap.add_argument("domain", help="쿠키를 뽑을 도메인. 예: valley.town (서브도메인 포함)")
    ap.add_argument("--login", action="store_true",
                    help="창을 띄우고 로그인이 끝날 때까지 기다린다. 최초 1회만 필요")
    ap.add_argument("--url", help="접속할 URL. 기본은 https://<domain>/")
    ap.add_argument("--profile", default=DEFAULT_PROFILE, help=f"전용 프로필 경로 (기본 {DEFAULT_PROFILE})")
    ap.add_argument("--port", type=int, default=9222, help="CDP 포트 (기본 9222)")
    ap.add_argument("--chrome", help="chrome.exe 경로 직접 지정")
    ap.add_argument("--format", choices=["header", "netscape", "json"], default="header",
                    help="header=Cookie 헤더 한 줄(기본), netscape=cookies.txt, json=원본")
    ap.add_argument("-o", "--out", help="파일로 저장 (미지정 시 stdout)")
    ap.add_argument("--show", action="store_true", help="Chrome 창을 화면에 보이게 띄운다")
    ap.add_argument("--keep-open", action="store_true", help="끝나도 Chrome을 닫지 않는다")
    ap.add_argument("--wait", type=float, default=4.0, help="페이지 로드 후 대기 초 (기본 4)")
    ap.add_argument("--require", default="",
                    help="반드시 있어야 하는 쿠키 이름들(쉼표 구분). 없으면 exit 3. "
                         "예: __Secure-nf.session-token")
    ap.add_argument("--jitter", type=float, default=0,
                    help="시작 전 0~N초 랜덤 대기. 스케줄 실행을 불규칙하게 만든다")
    ap.add_argument("--log-file", dest="log", metavar="PATH",
                    help="실행 결과를 append 할 로그 파일 (--login 과 헷갈리지 않게 이름을 분리했다)")
    ap.add_argument("--open", action="store_true",
                    help="이 프로필로 Chrome 창을 열어두고 끝낸다. 평소 이 창에서 해당 사이트를 쓰면 "
                         "세션이 하나로 유지돼 동시접속 제한이 있어도 안 끊긴다")
    args = ap.parse_args()

    if args.jitter > 0:
        delay = random.uniform(0, args.jitter)
        log_line(args.log, f"[.] jitter {delay:.0f}s 대기")
        time.sleep(delay)

    url = args.url or f"https://{args.domain}/"
    chrome = args.chrome or find_chrome()

    if args.open:
        if port_open(args.port):
            log_line(args.log, f"[i] 이미 CDP {args.port} 로 떠 있다. 그 창을 쓰면 된다.")
        else:
            launch_chrome(chrome, args.profile, args.port, url, show=True)
            wait_for_cdp(args.port)
            log_line(args.log, f"[o] {args.profile} 프로필로 창을 열었다. 이 창에서 사이트를 쓰면 된다.")
        return

    proc = None
    if port_open(args.port):
        print(f"[i] 이미 떠 있는 CDP {args.port} 에 붙는다", file=sys.stderr)
    else:
        proc = launch_chrome(chrome, args.profile, args.port, url, show=args.show or args.login)
        wait_for_cdp(args.port)
        time.sleep(args.wait)

    try:
        if args.login:
            print(
                f"\n[!] 창에서 {args.domain} 에 Google 계정으로 로그인해라.\n"
                f"    로그인이 끝나면 여기서 Enter. (프로필: {args.profile})\n",
                file=sys.stderr,
            )
            input()

        cookies = [c for c in get_all_cookies(args.port) if match_domain(c["domain"], args.domain)]
        if not cookies:
            log_line(args.log, f"[!] {args.domain} 쿠키 0개. --login 으로 한 번 로그인해라.")

        # 세션이 끊겼는데 조용히 낡은 쿠키를 덮어쓰는 상황을 막는다.
        # 로그인은 사람이 해야 하므로 스스로 복구할 수 없다 -> 즉시 실패시켜 알린다.
        required = [n.strip() for n in args.require.split(",") if n.strip()]
        if required:
            have = {c["name"] for c in cookies}
            missing = [n for n in required if n not in have]
            if missing:
                log_line(
                    args.log,
                    f"[X] 로그인 끊김 - 필수 쿠키 없음: {', '.join(missing)}. "
                    f"'--login' 으로 다시 로그인해야 한다. (파일은 건드리지 않음)",
                )
                raise SystemExit(3)

        if args.format == "header":
            text = as_header(cookies)
        elif args.format == "netscape":
            text = as_netscape(cookies)
        else:
            text = json.dumps(cookies, ensure_ascii=False, indent=2)

        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text if text.endswith("\n") else text + "\n")
            names = ", ".join(sorted(c["name"] for c in cookies)[:8])
            log_line(args.log,
                     f"[o] {len(cookies)}개 -> {args.out}  "
                     f"({names}{' ...' if len(cookies) > 8 else ''})")
        else:
            print(text)
    finally:
        if proc and not args.keep_open:
            # Chrome은 렌더러/GPU 등 자식 프로세스를 여럿 띄운다. 부모만 terminate() 하면
            # 자식들이 남아 프로필을 계속 점유하고, 다음 실행에서 CDP 포트가 안 열린다.
            # (실측: 테스트 몇 번에 chrome.exe 8개가 잔류) -> 프로세스 트리째 정리한다.
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
