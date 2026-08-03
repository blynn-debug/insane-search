# -*- coding: utf-8 -*-
"""valley.town 세션 쿠키를 로컬 PC와 무관하게 살려두는 keepalive.

구조 A: Google 로그인은 로컬에서 1회만 하고, 서버는 사이트 세션 쿠키만 들고 돈다.
Google 쿠키는 기기/IP에 묶여서 서버로 못 옮기지만, 사이트의 NextAuth 세션 쿠키
(__Secure-nf.session-token)는 그런 바인딩이 없어 어디서든 쓸 수 있다.

    [로컬] browser_cookies.py 로 로그인 -> push 로 저장소에 올림
    [서버] keepalive 를 주기 실행 -> 접속으로 세션 갱신 + 회전된 쿠키 저장
    [서버] get 으로 스크래퍼가 최신 쿠키를 꺼내 씀

생존 판별: /newsroom 이 200이면 살아있음, /login 으로 307이면 죽음.
(접속 행위 자체가 롤링 세션의 만료를 뒤로 민다)

명령:
    python session_keeper.py check     --store file:cookies.txt
    python session_keeper.py keepalive --store ssm:/valley/session
    python session_keeper.py push      --store ssm:/valley/session --from cookies.txt
    python session_keeper.py get       --store ssm:/valley/session -o cookies.txt

AWS Lambda 로 쓸 땐 handler 를 진입점으로 지정하고 STORE 환경변수만 주면 된다.
의존성 없음(표준 라이브러리). boto3 는 Lambda 런타임에 이미 있다.
"""
import argparse
import datetime
import http.cookies
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_PROBE = "https://www.valley.town/newsroom"
LOGIN_HINT = "/login"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")


def log(msg):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"{stamp}  {msg}", file=sys.stderr)


# ---------------------------------------------------------------- 저장소

def _boto(service):
    """EC2 안에서는 리전이 설정돼 있지 않은 경우가 많다. 메타데이터에서 찾아 넣는다.

    (실측: EC2 cron 에서 'You must specify a region' 로 실패했다)
    """
    import boto3
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not region:
        try:
            req = urllib.request.Request(
                "http://169.254.169.254/latest/api/token", method="PUT",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
            with urllib.request.urlopen(req, timeout=2) as r:
                token = r.read().decode()
            req = urllib.request.Request(
                "http://169.254.169.254/latest/meta-data/placement/region",
                headers={"X-aws-ec2-metadata-token": token})
            with urllib.request.urlopen(req, timeout=2) as r:
                region = r.read().decode().strip()
        except Exception:
            region = None
    return boto3.client(service, region_name=region) if region else boto3.client(service)


def store_read(spec):
    kind, _, ref = spec.partition(":")
    if kind == "file":
        if not os.path.exists(ref):
            return ""
        with open(ref, encoding="utf-8") as f:
            return f.read().strip()
    if kind == "ssm":
        ssm = _boto("ssm")
        try:
            r = ssm.get_parameter(Name=ref, WithDecryption=True)
            return r["Parameter"]["Value"].strip()
        except ssm.exceptions.ParameterNotFound:
            return ""
    raise SystemExit(f"모르는 저장소: {spec} (file:PATH 또는 ssm:/경로)")


def store_write(spec, value):
    kind, _, ref = spec.partition(":")
    if kind == "file":
        with open(ref, "w", encoding="utf-8", newline="\n") as f:
            f.write(value + "\n")
        return
    if kind == "ssm":
        # SecureString: KMS 기본키로 암호화된다. Standard tier 는 과금 없음.
        _boto("ssm").put_parameter(
            Name=ref, Value=value, Type="SecureString", Overwrite=True
        )
        return
    raise SystemExit(f"모르는 저장소: {spec}")


# ---------------------------------------------------------------- 만료 메타
# 쿠키 값 자체(JWE)는 복호화할 수 없어 만료 시각을 읽을 수 없다.
# 그래서 브라우저가 알려준 만료를 push 할 때 따로 기록해두고, 남은 시간을 보고 미리 알린다.
# 저장 위치는 쿠키와 분리한다(기존 스크래퍼가 읽는 값 형식을 바꾸지 않기 위해).

def meta_spec(spec):
    kind, _, ref = spec.partition(":")
    return f"{kind}:{ref}.expiry.json" if kind == "file" else f"{kind}:{ref}-expiry"


def meta_read(spec):
    try:
        raw = store_read(meta_spec(spec))
    except Exception as e:
        log(f"[!] 만료 메타를 읽지 못했다(사전 경고 비활성): {e}")
        return {}
    if not raw:
        return {}
    try:
        # 윈도우 도구가 BOM 을 붙여놓는 경우가 있어 걷어내고 파싱한다.
        return json.loads(raw.lstrip("﻿"))
    except json.JSONDecodeError as e:
        # 조용히 넘어가면 만료 경고가 영영 안 울린다. 반드시 남긴다.
        log(f"[!] 만료 메타가 깨졌다(사전 경고 비활성): {e}. push 를 다시 해라.")
        return {}


def meta_write(spec, data):
    try:
        store_write(meta_spec(spec), json.dumps(data))
    except Exception as e:
        log(f"[!] 만료 메타 저장 실패(무시하고 진행): {e}")


def expiry_from_cookie_json(path):
    """browser_cookies.py --format json 결과에서 세션 토큰 만료를 뽑는다."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for c in data:
        if "session-token" in c.get("name", ""):
            e = c.get("expires", -1)
            if e and e > 0:
                return datetime.datetime.fromtimestamp(e, datetime.timezone.utc)
    return None


def expiry_from_set_cookie(set_cookie_headers, name_hint="session-token"):
    """회전된 Set-Cookie 에 Expires 가 있으면 만료를 갱신한다."""
    import email.utils
    for raw in set_cookie_headers:
        c = http.cookies.SimpleCookie()
        try:
            c.load(raw)
        except http.cookies.CookieError:
            continue
        for name, morsel in c.items():
            if name_hint not in name or not morsel.value:
                continue
            if morsel.get("max-age"):
                try:
                    return (datetime.datetime.now(datetime.timezone.utc)
                            + datetime.timedelta(seconds=int(morsel["max-age"])))
                except ValueError:
                    pass
            if morsel.get("expires"):
                try:
                    dt = email.utils.parsedate_to_datetime(morsel["expires"])
                    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
                except (TypeError, ValueError):
                    pass
    return None


# ---------------------------------------------------------------- 쿠키

def parse_cookie_header(header):
    """'a=1; b=2' -> {'a': '1', 'b': '2'} (순서 유지)"""
    jar = {}
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        jar[k.strip()] = v.strip()
    return jar


def to_cookie_header(jar):
    return "; ".join(f"{k}={v}" for k, v in jar.items())


def merge_set_cookie(jar, set_cookie_headers):
    """응답의 Set-Cookie 를 반영한다. 롤링 세션은 접속할 때마다 토큰을 새로 준다."""
    changed = []
    for raw in set_cookie_headers:
        c = http.cookies.SimpleCookie()
        try:
            c.load(raw)
        except http.cookies.CookieError:
            continue
        for name, morsel in c.items():
            # max-age=0 / 과거 expires 는 서버가 쿠키를 지우라는 뜻
            if morsel.value == "" or morsel.get("max-age") == "0":
                if name in jar:
                    del jar[name]
                    changed.append(f"-{name}")
                continue
            if jar.get(name) != morsel.value:
                jar[name] = morsel.value
                changed.append(f"~{name}")
    return changed


# ---------------------------------------------------------------- 접속

def probe(url, cookie_header, timeout=20):
    """리다이렉트를 따라가지 않고 상태코드 + Set-Cookie 를 그대로 본다."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={
        "Cookie": cookie_header,
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Cache-Control": "no-cache",
    })
    try:
        resp = opener.open(req, timeout=timeout)
        return resp.status, dict(resp.getheaders()), resp.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        # 3xx/4xx 도 응답이다. 여기서 로그인 리다이렉트를 잡는다.
        return e.code, dict(e.headers.items()), e.headers.get_all("Set-Cookie") or []


def is_alive(status, headers):
    loc = headers.get("Location") or headers.get("location") or ""
    if status in (301, 302, 303, 307, 308) and LOGIN_HINT in loc:
        return False, f"{status} -> {loc} (로그인 만료)"
    if status == 200:
        return True, "200 (세션 유효)"
    return False, f"{status} (예상 밖 응답)"


# ---------------------------------------------------------------- 명령

def cmd_check(args, save=False):
    raw = store_read(args.store)
    if not raw:
        log(f"[X] 저장소가 비었다: {args.store}. 먼저 push 해라.")
        return 3
    jar = parse_cookie_header(raw)
    if args.require and args.require not in jar:
        log(f"[X] 필수 쿠키 없음: {args.require}")
        return 3

    status, headers, set_cookies = probe(args.probe_url, to_cookie_header(jar))
    alive, why = is_alive(status, headers)
    if not alive:
        log(f"[X] {why}  -> 로컬에서 재로그인 후 push 필요")
        notify(args, f"valley 세션 만료: {why}")
        return 3

    changed = merge_set_cookie(jar, set_cookies)
    meta = meta_read(args.store)

    if save and changed:
        store_write(args.store, to_cookie_header(jar))
        # 회전이 일어났으면 만료도 밀렸을 것이다. 새 만료를 알면 갱신하고 경고 플래그를 푼다.
        new_exp = expiry_from_set_cookie(set_cookies)
        if new_exp:
            meta = {"expires_at": new_exp.isoformat()}
            meta_write(args.store, meta)
        elif meta.pop("warned_at", None):
            meta_write(args.store, meta)
        log(f"[o] {why} / 쿠키 갱신 {len(changed)}건: {', '.join(changed[:6])}"
            + (f" / 만료 {new_exp:%Y-%m-%d %H:%M}Z" if new_exp else ""))
    else:
        log(f"[o] {why}" + (" / 회전 없음" if save else ""))

    # 만료 임박 사전 경고. 재로그인에는 사람과 로컬 브라우저가 필요하므로
    # 죽은 뒤에 알리면 늦다. 중복 발송을 막으려고 한 번 보냈으면 표시해둔다.
    exp_raw = meta.get("expires_at")
    if exp_raw:
        try:
            exp = datetime.datetime.fromisoformat(exp_raw)
            left = exp - datetime.datetime.now(datetime.timezone.utc)
            hours = left.total_seconds() / 3600
            log(f"    만료까지 {int(hours // 24)}일 {int(hours % 24)}시간 (예정 {exp:%Y-%m-%d %H:%M}Z)")
            if save and 0 < hours < args.warn_hours and not meta.get("warned_at"):
                notify(args, f"valley 세션이 약 {int(hours)}시간 뒤 만료된다.\n"
                             f"만료 예정: {exp:%Y-%m-%d %H:%M}Z\n"
                             f"로컬에서 재로그인 후 push 필요:\n"
                             f"  browser_cookies.py valley.town --open\n"
                             f"  browser_cookies.py valley.town --format json -o cookies.json\n"
                             f"  session_keeper.py push --store {args.store} --from cookies.json")
                meta["warned_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                meta_write(args.store, meta)
                log(f"[!] 만료 임박 경고 발송 ({int(hours)}시간 남음)")
        except ValueError:
            pass
    return 0


def cmd_push(args):
    src = args.from_file
    if not src or not os.path.exists(src):
        raise SystemExit(f"올릴 쿠키 파일이 없다: {src}")
    with open(src, encoding="utf-8") as f:
        raw = f.read().strip()

    # --format json 으로 뽑은 파일이면 만료 시각까지 얻을 수 있다(사전 경고에 쓴다).
    expiry = None
    if raw.startswith("["):
        expiry = expiry_from_cookie_json(src)
        jar = {}
        for c in json.load(open(src, encoding="utf-8")):
            jar[c["name"]] = c["value"]
    else:
        jar = parse_cookie_header(raw)

    if args.require and args.require not in jar:
        raise SystemExit(f"[X] {src} 에 {args.require} 가 없다. 로그인부터 해라.")
    store_write(args.store, to_cookie_header(jar))

    if expiry:
        meta_write(args.store, {"expires_at": expiry.isoformat()})
        left = expiry - datetime.datetime.now(datetime.timezone.utc)
        log(f"[o] {len(jar)}개 쿠키를 {args.store} 에 올렸다 "
            f"(만료 {expiry:%Y-%m-%d %H:%M}Z, {left.days}일 남음)")
    else:
        log(f"[o] {len(jar)}개 쿠키를 {args.store} 에 올렸다")
        log("    만료 시각을 모른다. 사전 경고를 받으려면 --format json 으로 뽑아서 push 해라:")
        log("      browser_cookies.py <도메인> --format json -o cookies.json")
    return 0


def cmd_get(args):
    raw = store_read(args.store)
    if not raw:
        log("[X] 저장소가 비었다")
        return 3
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(raw + "\n")
        log(f"[o] -> {args.out}")
    else:
        print(raw)
    return 0


def notify(args, message):
    """세션이 죽으면 사람이 개입해야 한다. 조용히 죽지 않게 알린다."""
    topic = args.sns_topic or os.environ.get("SNS_TOPIC_ARN")
    if not topic:
        return
    try:
        _boto("sns").publish(TopicArn=topic, Subject="valley 세션 만료", Message=message)
        log("[i] SNS 알림 발송")
    except Exception as e:
        log(f"[!] SNS 알림 실패: {e}")


def build_parser():
    ap = argparse.ArgumentParser(description="valley.town 세션 keepalive", allow_abbrev=False)
    ap.add_argument("command", choices=["check", "keepalive", "push", "get"])
    ap.add_argument("--store", default=os.environ.get("STORE", "file:cookies.txt"),
                    help="file:경로 또는 ssm:/파라미터경로 (기본 file:cookies.txt)")
    ap.add_argument("--from", dest="from_file", help="push 할 원본 쿠키 파일")
    ap.add_argument("-o", "--out", help="get 결과를 쓸 파일")
    ap.add_argument("--probe-url", default=os.environ.get("PROBE_URL", DEFAULT_PROBE),
                    help=f"생존 확인용 로그인 필요 페이지 (기본 {DEFAULT_PROBE})")
    ap.add_argument("--require", default=os.environ.get("REQUIRE_COOKIE", "__Secure-nf.session-token"),
                    help="반드시 있어야 하는 쿠키 이름")
    ap.add_argument("--sns-topic", help="세션 만료 시 알릴 SNS Topic ARN")
    ap.add_argument("--warn-hours", type=float,
                    default=float(os.environ.get("WARN_HOURS", "48")),
                    help="만료 N시간 전에 미리 알린다 (기본 48). 재로그인은 사람이 해야 하므로 "
                         "죽은 뒤에 알리면 늦다")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return cmd_check(args, save=False)
    if args.command == "keepalive":
        return cmd_check(args, save=True)
    if args.command == "push":
        return cmd_push(args)
    if args.command == "get":
        return cmd_get(args)
    return 1


def handler(event, context):
    """AWS Lambda 진입점. EventBridge 로 주기 실행한다.

    환경변수: STORE=ssm:/valley/session, SNS_TOPIC_ARN=(선택)

    실패 시 예외를 던진다. 그래야 Lambda Errors 지표에 잡혀서 콘솔/알람으로 보인다.
    조용히 성공으로 끝나면 세션이 죽은 걸 몇 주 뒤에 발견하게 된다.
    """
    code = main(["keepalive"])
    if code != 0:
        raise RuntimeError(f"keepalive 실패 (exit {code}) - 로컬에서 재로그인 후 push 필요")
    return {"ok": True}


if __name__ == "__main__":
    sys.exit(main())
