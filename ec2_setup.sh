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

echo "== 3/5 Chrome 상시 기동 (systemd, CDP 는 localhost 에만 연다)"
mkdir -p "$PROFILE"
sudo tee /etc/systemd/system/valley-chrome.service >/dev/null <<EOF
[Unit]
Description=Chrome with CDP for valley session
After=network-online.target

[Service]
User=$USER
# --headless=new 는 Google 로그인에서 막힐 수 있어 쓰지 않는다.
# 화면이 없으므로 가상 디스플레이 대신 오프스크린 창으로 띄운다.
ExecStart=/usr/bin/google-chrome \\
  --remote-debugging-port=$PORT \\
  --remote-debugging-address=127.0.0.1 \\
  --user-data-dir=$PROFILE \\
  --no-first-run --no-default-browser-check \\
  --disable-gpu --no-sandbox \\
  --window-position=-32000,-32000 --window-size=1280,900 \\
  --disable-background-networking \\
  about:blank
Restart=always
RestartSec=5
Environment=DISPLAY=

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now valley-chrome.service
sleep 5
if curl -sf "http://127.0.0.1:$PORT/json/version" >/dev/null; then
  echo "   CDP $PORT 응답 OK"
else
  echo "!! CDP 가 안 열렸다:  sudo journalctl -u valley-chrome -n 50" >&2; exit 1
fi

echo "== 4/5 상태 확인"
cd "$REPO_DIR"
$PYBIN auto_relogin.py valley.town --port "$PORT" --profile "$PROFILE" || true

if [ "${1:-}" = "--cron" ]; then
  echo "== 5/5 cron 등록 (12시간마다)"
  LINE="0 */12 * * * cd $REPO_DIR && $PYBIN auto_relogin.py valley.town --port $PORT --profile $PROFILE --store $STORE --log-file $HOME/valley-relogin.log >> $HOME/valley-relogin.log 2>&1"
  ( crontab -l 2>/dev/null | grep -v auto_relogin.py ; echo "$LINE" ) | crontab -
  crontab -l | grep auto_relogin.py
else
  echo "== 5/5 cron 은 건너뜀 (--cron 으로 등록)"
fi

cat <<'MSG'

────────────────────────────────────────────────────────
1회 Google 로그인 (이것만 사람이 한다)

로컬 PC 에서 SSH 터널을 연다:

    ssh -N -L 9222:127.0.0.1:9222 <user>@<EC2 주소>

로컬 Chrome 에서 chrome://inspect 를 열고
  Configure... > localhost:9222 추가 > 잠시 뒤 Remote Target 에 나타남
  about:blank 옆 [inspect] 클릭 -> 원격 브라우저 화면이 열린다

그 화면에서 https://www.valley.town/login 으로 이동해
Google 로그인을 끝낸다. (데이터센터 IP 라 추가 인증을 요구할 수 있다)

로그인 후 EC2 에서 확인:

    cd ~/insane-search
    python3 auto_relogin.py valley.town --force --store ssm:/valley/session

'새 세션 발급 완료' 가 나오면 이후로는 cron 이 알아서 한다.
────────────────────────────────────────────────────────
MSG
