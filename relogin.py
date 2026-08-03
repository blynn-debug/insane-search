# -*- coding: utf-8 -*-
"""세션 재로그인을 한 번에 끝낸다.

valley.town 은 세션을 갱신해주지 않는다(실측: 5일 고정, 재발급 엔드포인트 없음).
그래서 만료 전에 사람이 재로그인해야 하고, 그 반복 작업을 한 명령으로 묶는다.

    py -3.14 relogin.py valley.town

    1) 전용 Chrome 프로필 창을 연다  -> 사람이 Google 로그인
    2) 쿠키를 json 으로 뽑는다(만료 시각 포함)
    3) 저장소에 push (boto3+자격증명이 있으면 SSM 까지 바로,
       없으면 파일만 만들고 CloudShell 절차를 안내)
    4) 살아있는지 확인
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def say(msg):
    """하위 프로세스가 stderr 로 먼저 쏟아내면 단계 표시가 뒤로 밀린다. 즉시 내보낸다."""
    print(msg, flush=True)
    sys.stderr.flush()


def run(args, **kw):
    return subprocess.run([PY] + args, cwd=HERE, **kw)


def has_boto3():
    try:
        import boto3  # noqa: F401
        return True
    except ImportError:
        return False


def main():
    ap = argparse.ArgumentParser(description="재로그인 -> 쿠키 추출 -> 저장소 반영", allow_abbrev=False)
    ap.add_argument("domain", nargs="?", default="valley.town")
    ap.add_argument("--store", default="ssm:/valley/session", help="기본 ssm:/valley/session")
    ap.add_argument("--require", default="__Secure-nf.session-token")
    ap.add_argument("--out", default="cookies.json")
    ap.add_argument("--skip-open", action="store_true",
                    help="이미 로그인돼 있으면 창 여는 단계를 건너뛴다")
    args = ap.parse_args()

    if not args.skip_open:
        say("\n[1/4] 전용 Chrome 창을 연다. 창에서 로그인해라.")
        say("      ('Chrome에 로그인하시겠습니까?' 팝업은 브라우저 동기화라 무시할 것)")
        run(["browser_cookies.py", args.domain, "--open"])
        input("\n      로그인이 끝났으면 Enter: ")

    say("\n[2/4] 쿠키 추출")
    r = run(["browser_cookies.py", args.domain, "--format", "json",
             "-o", args.out, "--require", args.require])
    if r.returncode != 0:
        say("\n[X] 세션 쿠키를 못 얻었다. 로그인이 안 끝났거나 실패했다.")
        say("    창을 다시 확인하고 --skip-open 없이 재실행해라.")
        return 3

    say("\n[3/4] 저장소 반영")
    kind = args.store.partition(":")[0]
    if kind == "ssm" and not has_boto3():
        say("[!] boto3/자격증명이 없어 SSM 에 직접 못 올린다.")
        say(f"    {os.path.join(HERE, args.out)} 를 CloudShell 에 올린 뒤:")
        say(f"      python3 session_keeper.py push --store {args.store} --from {args.out}")
        say("    (CloudShell 은 덮어쓰기가 안 되니 같은 이름 파일은 먼저 rm)")
        return 0
    r = run(["session_keeper.py", "push", "--store", args.store,
             "--from", args.out, "--require", args.require])
    if r.returncode != 0:
        say("\n[X] push 실패")
        return r.returncode

    say("\n[4/4] 확인")
    r = run(["session_keeper.py", "check", "--store", args.store, "--require", args.require])
    if r.returncode == 0:
        say("\n완료. 다음 만료 48시간 전에 다시 알림이 온다.")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
