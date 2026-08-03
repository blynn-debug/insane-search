# -*- coding: utf-8 -*-
"""블랙박스(CLI) + 회귀 테스트 - 프로세스를 실제로 돌려 종료코드와 파일 효과만 본다.

네트워크가 필요한 항목은 VALLEY_LIVE=1 일 때만 돈다(기본은 건너뜀).

    py -3.14 -m unittest discover -s tests -v
    set VALLEY_LIVE=1 && py -3.14 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TOKEN = "__Secure-nf.session-token"
LIVE = os.environ.get("VALLEY_LIVE") == "1"


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def read_json(path):
    return json.loads(read(path))


def run(*args, **kw):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([PY, *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=env, timeout=kw.pop("timeout", 120), **kw)


def cookie_json(path, token="LIVE_LOOKING_TOKEN", expires=1786000000, extra=True):
    data = [{"name": TOKEN, "value": token, "domain": ".valley.town",
             "path": "/", "expires": expires, "httpOnly": True, "secure": True}]
    if extra:
        data.append({"name": "_ga", "value": "GA1.1", "domain": ".valley.town",
                     "path": "/", "expires": expires})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


class 인자처리(unittest.TestCase):
    def test_R6_log_축약이_login_으로_붙지_않는다(self):
        """회귀: --log 가 --login/--log-file 중 하나로 조용히 해석되면 안 된다."""
        r = run("browser_cookies.py", "valley.town", "--log")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unrecognized argument", (r.stderr + r.stdout))

    def test_없는_옵션은_거부(self):
        r = run("browser_cookies.py", "valley.town", "--clone-default")
        self.assertNotEqual(r.returncode, 0)

    def test_도움말은_정상종료(self):
        for mod in ("browser_cookies.py", "session_keeper.py",
                    "auto_relogin.py", "relogin.py"):
            self.assertEqual(run(mod, "--help").returncode, 0, mod)


class push동작(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.store = "file:" + os.path.join(self.d, "c.txt")

    def test_세션토큰_없으면_거부(self):
        p = os.path.join(self.d, "no.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump([{"name": "_ga", "value": "x"}], f)
        r = run("session_keeper.py", "push", "--store", self.store, "--from", p)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("c.txt", os.listdir(self.d))

    def test_json이면_만료까지_기록(self):
        p = cookie_json(os.path.join(self.d, "c.json"))
        self.assertEqual(run("session_keeper.py", "push", "--store", self.store,
                             "--from", p).returncode, 0)
        meta = read_json(os.path.join(self.d, "c.txt.expiry.json"))
        self.assertIn("expires_at", meta)

    def test_평문이면_만료를_모른다고_알린다(self):
        p = os.path.join(self.d, "c.header")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"{TOKEN}=x; _ga=1")
        r = run("session_keeper.py", "push", "--store", self.store, "--from", p)
        self.assertEqual(r.returncode, 0)
        self.assertIn("만료 시각을 모른다", r.stderr + r.stdout)

    def test_미러파일은_0600(self):
        p = cookie_json(os.path.join(self.d, "c.json"))
        m = os.path.join(self.d, "mirror", "cookies.txt")
        self.assertEqual(run("session_keeper.py", "push", "--store", self.store,
                             "--from", p, "--mirror-file", m).returncode, 0)
        self.assertTrue(os.path.exists(m))
        self.assertIn(TOKEN, read(m))
        if os.name != "nt":
            self.assertEqual(oct(os.stat(m).st_mode)[-3:], "600")


class get동작(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "c.txt")
        self.store = "file:" + self.path

    def test_빈_저장소는_exit3(self):
        self.assertEqual(run("session_keeper.py", "get", "--store", self.store).returncode, 3)

    def test_값을_그대로_돌려준다(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("a=1; b=2\n")
        r = run("session_keeper.py", "get", "--store", self.store)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "a=1; b=2")


class 회귀_저장소보호(unittest.TestCase):
    """회귀: 세션이 죽었을 때 낡은 쿠키를 빈 값으로 덮어쓰면 안 된다."""

    @unittest.skipUnless(LIVE, "네트워크 필요 (VALLEY_LIVE=1)")
    def test_R9_만료감지시_저장소_미변경(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "c.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{TOKEN}=DEAD_TOKEN_FOR_TEST; _ga=1\n")
        before = read(path)
        r = run("session_keeper.py", "keepalive", "--store", "file:" + path)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("만료", r.stderr + r.stdout)
        self.assertEqual(read(path), before)


class 회귀_사전경고(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "c.txt")
        self.store = "file:" + self.path

    def _seed(self, hours_left):
        import datetime
        exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours_left)
        cookie_json(os.path.join(self.d, "c.json"), expires=exp.timestamp())
        run("session_keeper.py", "push", "--store", self.store,
            "--from", os.path.join(self.d, "c.json"))
        return exp

    @unittest.skipUnless(LIVE, "네트워크 필요 (VALLEY_LIVE=1)")
    def test_임계값_밖이면_조용(self):
        self._seed(200)
        run("session_keeper.py", "keepalive", "--store", self.store, "--warn-hours", "48")
        meta = read_json(self.path + ".expiry.json")
        self.assertNotIn("warned_at", meta)

    def test_메타에_만료가_기록된다(self):
        self._seed(100)
        meta = read_json(self.path + ".expiry.json")
        self.assertIn("expires_at", meta)


class 회귀_auto_relogin(unittest.TestCase):
    """회귀: 저장소 만료가 넉넉하면 Chrome 을 아예 띄우지 않아야 한다(메모리)."""

    @unittest.skipUnless(LIVE, "네트워크 필요 (VALLEY_LIVE=1)")
    def test_R2_여유있으면_브라우저_미기동(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "c.txt")
        # 실제 살아있는 쿠키가 없으므로 이 테스트는 '죽은 세션' 경로를 탄다.
        # 여기서는 '존재하지 않는 포트' 를 줘서, 사전 확인 단계에서 끝나는지만 본다.
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{TOKEN}=x; _ga=1\n")
        import datetime
        exp = (datetime.datetime.now(datetime.timezone.utc)
               + datetime.timedelta(days=30)).isoformat()
        with open(path + ".expiry.json", "w", encoding="utf-8") as f:
            json.dump({"expires_at": exp}, f)
        r = run("auto_relogin.py", "valley.town", "--store", "file:" + path,
                "--port", "9998", timeout=180)
        out = r.stderr + r.stdout
        # 세션이 죽었으므로 재발급을 시도하다 브라우저가 없어 실패하거나,
        # 살아있다면 미기동으로 끝난다. 어느 쪽이든 '메타만 보고 통과' 는 아니어야 한다.
        self.assertTrue("세션이 죽어있다" in out or "세션도 살아있다" in out,
                        f"생존 확인을 건너뛰었다: {out[:300]}")


class 배포스크립트(unittest.TestCase):
    def _bash(self, *args):
        bash = r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else "bash"
        if os.name == "nt" and not os.path.exists(bash):
            self.skipTest("bash 없음")
        return subprocess.run([bash, *args], cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=60)

    def test_문법(self):
        for s in ("deploy_aws.sh", "ec2_setup.sh"):
            r = self._bash("-n", s)
            self.assertEqual(r.returncode, 0, f"{s}: {r.stderr}")

    def test_R4_기존스왑을_먼저_지우지_않는다(self):
        """회귀: swapoff+rm 을 먼저 해서 스왑이 0 이 된 사고가 있었다."""
        src = read(os.path.join(ROOT, "ec2_setup.sh"))
        self.assertNotIn("swapoff /swapfile &&", src)
        self.assertIn("/swapfile2", src)          # 별도 파일로 추가
        self.assertNotIn("mkswap -q", src)        # 이 버전에 없는 옵션

    def test_CloudShell_오실행_차단(self):
        src = read(os.path.join(ROOT, "ec2_setup.sh"))
        self.assertIn("cloudshell-user", src)


class 비밀값보호(unittest.TestCase):
    def test_R8_쿠키파일들이_gitignore_에_있다(self):
        ig = read(os.path.join(ROOT, ".gitignore"))
        for pat in ("cookies.txt", "cookies.json", "*.expiry.json"):
            self.assertIn(pat, ig, f"{pat} 가 .gitignore 에 없다")

    def test_소스에_토큰값이_없다(self):
        import re
        bad = []
        for f in os.listdir(ROOT):
            if not f.endswith((".py", ".mjs", ".sh", ".md")):
                continue
            txt = read(os.path.join(ROOT, f))
            if re.search(r"eyJhbGciOiJkaXI|__Secure-3PSID=|AKIA[A-Z0-9]{16}", txt):
                bad.append(f)
        self.assertEqual(bad, [], f"실제 토큰/키가 들어있다: {bad}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
