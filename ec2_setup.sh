#!/usr/bin/env bash
# EC2 에 무개입 세션 자동 재발급 환경을 만든다. (구조 B: 로컬 PC 없이 24/7)
#
# 전제: valley 세션(5일)만 만료되고 Google 세션(수개월)은 이 프로필에 남는다.
#       그래서 Google 로그인을 EC2 에서 "딱 한 번" 해두면 이후는 자동이다.
#
#   bash ec2_setup.sh            # 설치 + Chrome 상시 기동
#   bash ec2_setup.sh --cron     # 위 + 12시간마다 자동 재발급 등록
#
# 설치 후 사람이 할 일은 아래 "1회 Google 로그인" 뿐이다.
set -euo pipefail

# CloudShell 에서 잘못 실행하는 걸 막는다. 여기는 24/7 도 아니고 systemd 도 없다.
if [ -n "${AWS_EXECUTION_ENV:-}" ] && [ "${AWS_EXECUTION_ENV}" = "CloudShell" ] \
   || [ "$(id -un)" = "cloudshell-user" ] || [ -d /aws/mde ]; then
  echo "!! 여기는 CloudShell 이다. 이 스크립트는 24/7 로 켜져 있는 EC2 에서 돌려야 한다." >&2
  echo "   CloudShell 은 세션이 끝나면 사라지고 systemd 도 없다." >&2
  exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
  echo "!! systemd 가 없는 환경이다. EC2 인스턴스에서 실행해라." >&2
  exit 1
fi

REPO_DIR="${REPO_DIR:-$HOME/insane-search}"
PROFILE="${PROFILE:-$HOME/.config/chrome-cdp-profile}"
PORT="${PORT:-9222}"
STORE="${STORE:-ssm:/valley/session}"
PYBIN="${PYBIN:-python3}"

echo "== 1/5 패키지 설치"
if command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y git python3-pip xdg-utils liberation-fonts >/dev/null
  if ! command -v google-chrome >/dev/null 2>&1; then
    sudo dnf install -y https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
  fi
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y git python3-pip fonts-liberation >/dev/null
  if ! command -v google-chrome >/dev/null 2>&1; then
    curl -fsSL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt-get install -y /tmp/chrome.deb
  fi
else
  echo "!! dnf/apt 를 못 찾았다. Chrome 을 수동 설치해라." >&2; exit 1
fi
# venv 안에서는 --user 가 거부된다. 되는 쪽으로 알아서 넘어간다.
$PYBIN -m pip install --quiet --user websocket-client boto3 2>/dev/null \
  || $PYBIN -m pip install --quiet websocket-client boto3

echo "== 2/5 저장소"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" pull --ff-only
else
  git clone --depth 1 -b insane-search \
    https://github.com/blynn-debug/insane-search.git "$REPO_DIR"
fi

echo "== 3/5 메모리 여유 확인"
# Chrome 을 상시 기동하지 않는다. 여유 메모리가 적은 인스턴스에서 24/7 로 띄우면
# 기존 프로세스가 OOM 으로 죽을 수 있다. auto_relogin.py 가 필요할 때만 띄우고 정리한다.
AVAIL=$(free -m | awk '/^Mem:/{print $7}')
SWAP=$(free -m | awk '/^Swap:/{print $2}')
echo "   사용가능 메모리 ${AVAIL}MB / 스왑 ${SWAP}MB"
if [ "$AVAIL" -lt 900 ] && [ "$SWAP" -lt 2048 ]; then
  # 기존 스왑은 절대 건드리지 않는다. 별도 파일을 추가로 붙인다.
  # (이전 버전은 기존 스왑을 먼저 지운 뒤 생성에 실패해 스왑이 0 이 된 적이 있다)
  if [ ! -f /swapfile2 ]; then
    echo "   여유가 빠듯하다. 스왑 2GB 를 추가한다(기존 스왑은 유지)."
    if sudo dd if=/dev/zero of=/swapfile2 bs=1M count=2048 status=none \
       && sudo chmod 600 /swapfile2 && sudo mkswap /swapfile2 >/dev/null; then
      sudo swapon /swapfile2
      grep -q '^/swapfile2' /etc/fstab || echo '/swapfile2 none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
      echo "   스왑 합계: $(free -m | awk '/^Swap:/{print $2}')MB"
    else
      echo "   !! 스왑 추가 실패. 기존 스왑은 그대로다." >&2
      sudo rm -f /swapfile2
    fi
  else
    echo "   /swapfile2 가 이미 있다. 건너뛴다."
  fi
fi

# boto3 는 리전을 모르면 실패한다. EC2 라면 메타데이터에서 가져온다.
if [ -z "${AWS_DEFAULT_REGION:-}" ]; then
  TOK=$(curl -s -m 3 -X PUT "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
  AWS_DEFAULT_REGION=$(curl -s -m 3 -H "X-aws-ec2-metadata-token: $TOK" \
        http://169.254.169.254/latest/meta-data/placement/region || true)
  export AWS_DEFAULT_REGION
fi
echo "   리전: ${AWS_DEFAULT_REGION:-(못 찾음)}"
mkdir -p "$PROFILE"

echo "== 4/5 상태 확인 (Chrome 은 갱신이 필요할 때만 뜬다)"
cd "$REPO_DIR"
$PYBIN auto_relogin.py valley.town --port "$PORT" --profile "$PROFILE" --store "$STORE" || true

if [ "${1:-}" = "--cron" ]; then
  echo "== 5/5 cron 등록 (12시간마다)"
  if ! command -v crontab >/dev/null 2>&1; then
    echo "   crontab 이 없다. cronie 를 설치한다."
    sudo dnf install -y cronie >/dev/null
    sudo systemctl enable --now crond
  fi
  LINE="0 */12 * * * cd $REPO_DIR && AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION $PYBIN auto_relogin.py valley.town --port $PORT --profile $PROFILE --store $STORE --log-file $HOME/valley-relogin.log >> $HOME/valley-relogin.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v auto_relogin.py ; echo "$LINE" ) | crontab -
  crontab -l | grep auto_relogin.py
else
  echo "== 5/5 cron 은 건너뜀 (--cron 으로 등록)"
fi

cat <<'MSG'

────────────────────────────────────────────────────────
1회 Google 로그인 (이것만 사람이 한다)

EC2 에서 Chrome 을 잠깐 띄워둔다(로그인하는 동안만):

    cd ~/insane-search
    google-chrome --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
      --user-data-dir=$HOME/.config/chrome-cdp-profile --no-first-run \
      --no-default-browser-check --disable-gpu --no-sandbox \
      --disable-dev-shm-usage --window-position=-32000,-32000 about:blank &

로컬 PC 에서 터널을 연다. SSH 키가 없으면 SSM 으로 열 수 있다:

    aws ssm start-session --target <인스턴스ID> \
      --document-name AWS-StartPortForwardingSession \
      --parameters '{"portNumber":["9222"],"localPortNumber":["9333"]}'

    # 키가 있으면 SSH 로도 된다
    ssh -i 키.pem -N -L 9333:127.0.0.1:9222 ec2-user@<EC2 주소>

로컬 Chrome 에서 chrome://inspect 를 열고
  Configure... > localhost:9333 추가 > 잠시 뒤 Remote Target 에 나타남
  about:blank 옆 [inspect] 클릭 -> 원격 브라우저 화면이 열린다
  (로컬 Chrome 도 9222 를 쓰므로 9333 을 써야 헷갈리지 않는다)

그 화면에서 https://www.valley.town/login 으로 이동해
Google 로그인을 끝낸다. (데이터센터 IP 라 추가 인증을 요구할 수 있다)

로그인 후 EC2 에서 확인:

    cd ~/insane-search
    python3 auto_relogin.py valley.town --force --store ssm:/valley/session

'새 세션 발급 완료' 가 나오면 이후로는 cron 이 알아서 한다.
────────────────────────────────────────────────────────
MSG
