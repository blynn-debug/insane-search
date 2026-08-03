# -*- coding: utf-8 -*-
"""화이트박스(단위) 테스트 - 네트워크·AWS·브라우저 없이 순수 함수만 본다.

    py -3.14 -m unittest discover -s tests -v
"""
import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_cookies as bc  # noqa: E402
import session_keeper as sk  # noqa: E402

TOKEN = "__Secure-nf.session-token"


class 쿠키파싱(unittest.TestCase):
    def test_헤더_왕복(self):
        raw = "a=1; b=2; c=3"
        self.assertEqual(sk.to_cookie_header(sk.parse_cookie_header(raw)), raw)

    def test_공백과_빈조각_무시(self):
        jar = sk.parse_cookie_header("  a=1 ;; ; b=2  ;")
        self.assertEqual(jar, {"a": "1", "b": "2"})

    def test_값에_등호가_있어도_유지(self):
        # JWT/base64 값에 '=' 패딩이 흔하다. 첫 '=' 에서만 잘라야 한다.
        jar = sk.parse_cookie_header("t=eyJhbGc=xyz==; b=2")
        self.assertEqual(jar["t"], "eyJhbGc=xyz==")

    def test_이름중복은_뒤엣것이_이긴다(self):
        # 같은 이름이 호스트별로 두 번 오는 경우(_kmpid). Cookie 헤더에선 하나만 보낸다.
        jar = sk.parse_cookie_header("k=first; k=second")
        self.assertEqual(jar["k"], "second")


class 쿠키회전(unittest.TestCase):
    def test_회전된_값을_반영(self):
        jar = {TOKEN: "OLD"}
        ch = sk.merge_set_cookie(jar, [f"{TOKEN}=NEW; Path=/; Secure; HttpOnly"])
        self.assertEqual(jar[TOKEN], "NEW")
        self.assertIn(f"~{TOKEN}", ch)

    def test_동일값은_변경으로_치지_않는다(self):
        jar = {"a": "1"}
        self.assertEqual(sk.merge_set_cookie(jar, ["a=1; Path=/"]), [])

    def test_삭제지시_반영(self):
        jar = {"gone": "x", "stay": "y"}
        sk.merge_set_cookie(jar, ["gone=; Max-Age=0; Path=/"])
        self.assertNotIn("gone", jar)
        self.assertIn("stay", jar)

    def test_깨진_set_cookie_는_무시하고_계속(self):
        jar = {"a": "1"}
        sk.merge_set_cookie(jar, ["!!! 이건 쿠키가 아니다", "b=2"])
        self.assertEqual(jar.get("b"), "2")


class 생존판정(unittest.TestCase):
    def test_200은_유효(self):
        alive, _ = sk.is_alive(200, {})
        self.assertTrue(alive)

    def test_로그인_리다이렉트는_만료(self):
        alive, why = sk.is_alive(307, {"Location": "/login?redirectUrl=%2Fnewsroom"})
        self.assertFalse(alive)
        self.assertIn("만료", why)

    def test_소문자_location_헤더도_인식(self):
        alive, _ = sk.is_alive(302, {"location": "/login"})
        self.assertFalse(alive)

    def test_예상밖_응답은_보수적으로_실패(self):
        # 500 을 '살아있음' 으로 보면 죽은 세션을 못 잡는다.
        for code in (403, 404, 500, 503):
            self.assertFalse(sk.is_alive(code, {})[0], f"{code} 를 유효로 판정")


class 만료메타(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.store = "file:" + os.path.join(self.d, "c.txt")

    def test_저장소별_메타경로(self):
        self.assertTrue(sk.meta_spec("file:/a/b.txt").endswith("b.txt.expiry.json"))
        self.assertEqual(sk.meta_spec("ssm:/valley/session"), "ssm:/valley/session-expiry")

    def test_왕복(self):
        sk.meta_write(self.store, {"expires_at": "2026-08-08T00:00:00+00:00"})
        self.assertEqual(sk.meta_read(self.store)["expires_at"],
                         "2026-08-08T00:00:00+00:00")

    def test_없으면_빈dict(self):
        self.assertEqual(sk.meta_read(self.store), {})

    def test_BOM_이_붙어도_읽는다(self):
        # 윈도우 도구가 UTF-8 BOM 을 붙이는 경우가 있다(실제로 겪음).
        p = sk.meta_spec(self.store).partition(":")[2]
        with open(p, "w", encoding="utf-8") as f:
            f.write("﻿" + json.dumps({"expires_at": "2026-01-01T00:00:00+00:00"}))
        self.assertIn("expires_at", sk.meta_read(self.store))

    def test_깨진JSON은_조용히_넘어가지_않는다(self):
        p = sk.meta_spec(self.store).partition(":")[2]
        with open(p, "w", encoding="utf-8") as f:
            f.write("{broken")
        # 빈 값을 돌려주되(사전 경고만 비활성), 로그로 알린다.
        self.assertEqual(sk.meta_read(self.store), {})


class 만료추출(unittest.TestCase):
    @staticmethod
    def _json(cookies):
        p = os.path.join(tempfile.mkdtemp(), "c.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cookies, f)
        return p

    def test_json쿠키에서_만료(self):
        exp = 1786000000
        got = sk.expiry_from_cookie_json(
            self._json([{"name": TOKEN, "value": "x", "expires": exp}]))
        self.assertEqual(int(got.timestamp()), exp)

    def test_세션쿠키_없으면_None(self):
        self.assertIsNone(sk.expiry_from_cookie_json(
            self._json([{"name": "_ga", "value": "x", "expires": 1786000000}])))

    def test_set_cookie_의_max_age(self):
        got = sk.expiry_from_set_cookie([f"{TOKEN}=v; Max-Age=3600; Path=/"])
        delta = got - datetime.datetime.now(datetime.timezone.utc)
        self.assertAlmostEqual(delta.total_seconds(), 3600, delta=60)

    def test_set_cookie_의_expires(self):
        got = sk.expiry_from_set_cookie(
            [f"{TOKEN}=v; Expires=Wed, 08 Aug 2026 06:40:29 GMT; Path=/"])
        self.assertEqual(got.year, 2026)
        self.assertEqual(got.month, 8)
        self.assertEqual(got.day, 8)

    def test_삭제용_set_cookie_는_만료로_치지_않는다(self):
        self.assertIsNone(sk.expiry_from_set_cookie([f"{TOKEN}=; Max-Age=0"]))


class 도메인매칭(unittest.TestCase):
    def test_정확일치와_서브도메인(self):
        for dom in (".valley.town", "valley.town", "www.valley.town", ".www.valley.town"):
            self.assertTrue(bc.match_domain(dom, "valley.town"), dom)

    def test_다른도메인은_거른다(self):
        # 'evilvalley.town' 이 'valley.town' 으로 잡히면 안 된다.
        for dom in ("evilvalley.town", "valley.town.attacker.com", "othertown.com"):
            self.assertFalse(bc.match_domain(dom, "valley.town"), dom)


class 출력형식(unittest.TestCase):
    def test_헤더형식(self):
        self.assertEqual(bc.as_header([{"name": "a", "value": "1"},
                                       {"name": "b", "value": "2"}]), "a=1; b=2")

    def test_netscape_형식(self):
        out = bc.as_netscape([{"name": "a", "value": "1", "domain": ".x.com",
                               "path": "/", "secure": True, "expires": 1786000000}])
        line = [l for l in out.splitlines() if l and not l.startswith("#")][0]
        cols = line.split("\t")
        self.assertEqual(len(cols), 7)
        self.assertEqual(cols[0], ".x.com")
        self.assertEqual(cols[1], "TRUE")      # 앞에 점 -> 서브도메인 포함
        self.assertEqual(cols[5:7], ["a", "1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
