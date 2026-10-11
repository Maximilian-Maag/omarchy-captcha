#!/bin/bash
# End-to-end: the real tools, real ImageMagick fixture, a real FIFO for the userscript.
# No stubs here - this is the one test that proves the pieces work together on a host
# with tesseract + imagemagick + ffmpeg installed.
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
SOLVE="$ROOT/bin/omarchy-captcha-solve"
TRANS="$ROOT/bin/omarchy-captcha-transcribe"
USERSCRIPT="$ROOT/userscripts/qute-captcha"

pass=0
fail=0
ok() { printf '  PASS %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL %s\n' "$1"; fail=$((fail + 1)); }
check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (want '$2' got '$3')"; fi
}

for tool in tesseract ffmpeg; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'e2e: %s is not installed - skipping the end-to-end run\n' "$tool"
    exit 0
  fi
done
IM="magick"
command -v "$IM" >/dev/null 2>&1 || IM="convert"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# --- 1. real OCR through the solver ---------------------------------------
"$IM" -size 300x100 xc:white -gravity center -pointsize 56 -fill black \
  -annotate +0+0 '7391' "$work/captcha.png" 2>/dev/null
solved=$(PATH="$PATH" "$SOLVE" "$work/captcha.png")
check "solver reads a real captcha image" "7391" "$solved"

json=$("$SOLVE" --json "$work/captcha.png")
check "solver json has ok:true" "yes" "$(grep -q '"ok":true' <<<"$json" && echo yes || echo no)"

# --- 2. real ffmpeg decode + backend selection ----------------------------
ffmpeg -loglevel error -f lavfi -i "sine=frequency=440:duration=0.3" \
  -ar 16000 -ac 1 -y "$work/chal.wav" 2>/dev/null
status=$("$TRANS" --status)
check "transcriber status mentions ffmpeg" "yes" "$(grep -q 'ffmpeg: ok' <<<"$status" && echo yes || echo no)"
if grep -q '^whisper: unavailable' <<<"$status" && grep -q '^vosk: unavailable' <<<"$status"; then
  out=$("$TRANS" "$work/chal.wav" 2>&1); rc=$?
  check "transcriber explains a missing backend" "3" "$rc"
  check "...with install guidance" "yes" "$(grep -q 'no usable backend' <<<"$out" && echo yes || echo no)"
else
  ok "transcriber has a backend (skipping the missing-backend assertion)"
fi

# --- 3. the userscript against the real solver, over a real FIFO ----------
# Served over loopback so the page URL (and the image src) are http://, exactly like
# a real captcha page - the userscript hands the image URL to the solver, which fetches it.
cat > "$work/page.html" <<'HTML'
<html><body><form>
<img src="captcha.png" alt="Enter the code"><input name="captcha" type="text">
</form></body></html>
HTML
port=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')
python3 -m http.server "$port" --bind 127.0.0.1 --directory "$work" >/dev/null 2>&1 &
server=$!
trap 'rm -rf "$work"; kill "$server" 2>/dev/null' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$port/page.html" >/dev/null 2>&1; then break; fi
  sleep 0.3
done

fifo="$work/fifo"
mkfifo "$fifo"
# Read-write open so the reader never sees EOF between the userscript's two writes
# (qutebrowser keeps its end open the same way). A plain `cat > out` would exit after
# the first command and the second open would block forever.
cat <>"$fifo" > "$work/sent" &
reader=$!
QUTE_URL="http://127.0.0.1:$port/page.html" QUTE_HTML="$work/page.html" QUTE_FIFO="$fifo" \
  CAPTCHA_SOLVER="$SOLVE" CAPTCHA_TRANSCRIBER="$TRANS" \
  python3 "$USERSCRIPT" solve
sleep 0.6
kill "$reader" 2>/dev/null
sent="$(cat "$work/sent" 2>/dev/null)"

check "userscript fills the field with the solved text" "yes" \
  "$(grep -q 'jseval' <<<"$sent" && grep -q '7391' <<<"$sent" && echo yes || echo no)"
check "userscript reports the guess" "yes" \
  "$(grep -q 'captcha guess: 7391' <<<"$sent" && echo yes || echo no)"
check "userscript never submits the form" "no" \
  "$(grep -E '^jseval' <<<"$sent" | grep -qiE 'submit\(|\.click\(|requestSubmit' && echo yes || echo no)"

printf '\ne2e test_captcha: %s passed, %s failed\n' "$pass" "$fail"
(( fail == 0 ))
