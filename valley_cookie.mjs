// valley.town 세션 쿠키를 가져다 쓰는 헬퍼 (node ESM)
//
// 세션은 EC2 의 systemd 타이머가 4~5일마다 자동 재발급해 SSM 에 넣는다.
// 봇은 그걸 읽기만 하면 된다. 로그인도, 사람 개입도 필요 없다.
//
//   import { valleyFetch, valleyCookie } from "./valley_cookie.mjs";
//   const res = await valleyFetch("https://www.valley.town/premium/lounge");
//
// 쿠키 출처는 두 가지를 순서대로 시도한다:
//   1) SSM /valley/session   (@aws-sdk/client-ssm 가 설치돼 있을 때. 항상 최신)
//   2) 로컬 미러 파일        (의존성 없음. 재발급 때마다 갱신된다)
//
// 의존성을 안 늘리려면 2번만 써도 된다. VALLEY_COOKIE_FILE 로 경로를 바꿀 수 있다.

import { readFile } from "node:fs/promises";

const PARAM = process.env.VALLEY_SSM_PARAM || "/valley/session";
const REGION = process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || "ap-northeast-2";
const FILE = process.env.VALLEY_COOKIE_FILE || `${process.env.HOME}/.valley/cookies.txt`;
const TTL_MS = Number(process.env.VALLEY_COOKIE_TTL_MS || 60_000);

let cache = { value: null, at: 0 };

async function fromSSM() {
  // SDK 가 없으면 조용히 넘어간다(파일 경로로 대체).
  let mod;
  try {
    mod = await import("@aws-sdk/client-ssm");
  } catch {
    return null;
  }
  const { SSMClient, GetParameterCommand } = mod;
  const ssm = new SSMClient({ region: REGION });
  const { Parameter } = await ssm.send(
    new GetParameterCommand({ Name: PARAM, WithDecryption: true })
  );
  return Parameter?.Value?.trim() || null;
}

async function fromFile() {
  try {
    const s = (await readFile(FILE, "utf8")).trim();
    return s || null;
  } catch {
    return null;
  }
}

/** 최신 쿠키 헤더 문자열. 짧게 캐시해 SSM 호출을 줄이되 갱신은 놓치지 않는다. */
export async function valleyCookie({ force = false } = {}) {
  if (!force && cache.value && Date.now() - cache.at < TTL_MS) return cache.value;
  const v = (await fromSSM()) || (await fromFile());
  if (!v) {
    throw new Error(
      `valley 쿠키를 못 찾았다. SSM ${PARAM} 또는 ${FILE} 을 확인해라.`
    );
  }
  if (!v.includes("__Secure-nf.session-token")) {
    throw new Error("valley 쿠키에 세션 토큰이 없다. 재로그인이 필요하다.");
  }
  cache = { value: v, at: Date.now() };
  return v;
}

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36";

/**
 * 로그인 상태로 요청한다. 세션이 죽었으면 /login 리다이렉트가 오므로
 * 조용히 빈 페이지를 받지 않도록 예외로 올린다.
 */
export async function valleyFetch(url, init = {}) {
  const cookie = await valleyCookie();
  const res = await fetch(url, {
    ...init,
    redirect: "manual",
    headers: {
      cookie,
      "user-agent": UA,
      "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8",
      ...(init.headers || {}),
    },
  });
  const loc = res.headers.get("location") || "";
  if ([301, 302, 303, 307, 308].includes(res.status) && loc.includes("/login")) {
    // 캐시가 낡았을 수 있으니 한 번만 새로 읽어 재시도한다.
    const fresh = await valleyCookie({ force: true });
    if (fresh !== cookie) return valleyFetch(url, init);
    throw new Error(`valley 세션 만료 (${res.status} -> ${loc}). 재로그인 필요.`);
  }
  return res;
}
