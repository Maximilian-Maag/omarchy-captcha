#!/bin/bash
# Shell tests for bin/omarchy-captcha-transcribe. Stubs ffmpeg + the STT backends so no
# real transcription runs; the real ffmpeg decode is covered by the e2e kind.
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
TRANS="$ROOT/bin/omarchy-captcha-transcribe"

# $STUBS: the fake backends. $CORE: symlinks to the handful of real tools the script needs (bash,
# tr, mktemp, python3, rm). HOME is pinned to $CORE too: the model search looks in
# $HOME/.local/share/whisper.cpp/models, so without that a model installed on the machine shadows
# the "no model" case. Together they are a HERMETIC environment - the script is run with
# `HOME="$CORE" PATH="$STUBS:$CORE"`, NOT `$STUBS:$PATH`. Appending the real PATH let a genuinely
# installed tool leak in and change the outcome: once whisper-cli existed on this machine,
# "whisper unavailable" and "no backend" stopped holding and auto-selection picked the real binary
# over the stub. A test whose result depends on what happens to be installed is not a test.
STUBS="$(mktemp -d)"
CORE="$(mktemp -d)"
trap 'rm -rf "$STUBS" "$CORE"' EXIT

pass=0
fail=0
ok() { printf '  PASS %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL %s\n' "$1"; fail=$((fail + 1)); }
check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (want '$2' got '$3')"; fi
}

cat > "$STUBS/ffmpeg" <<'EOF'
#!/bin/bash
out=""
while (( $# > 0 )); do
  if [[ $1 == "-y" ]]; then out="prev"; fi
  if [[ $1 == "-f" ]]; then out="next"; shift; fi
  prev="$1"
  shift
done
exit 0
EOF
chmod +x "$STUBS/ffmpeg"
for tool in bash tr mktemp python3 rm; do   # rm: the script's temp-dir cleanup
  ln -sf "$(command -v "$tool")" "$CORE/$tool"
done

audio="$(mktemp)"; printf 'fake-audio' > "$audio"
model="$(mktemp)"; printf 'fake-model' > "$model"

# --- status ---------------------------------------------------------------
out=$(HOME="$CORE" PATH="$STUBS:$CORE" "$TRANS" --status)
check "status reports ffmpeg ok" "yes" "$(grep -q '^ffmpeg: ok' <<<"$out" && echo yes || echo no)"
check "status reports whisper unavailable" "yes" "$(grep -q '^whisper: unavailable' <<<"$out" && echo yes || echo no)"

# --- help / args ----------------------------------------------------------
HOME="$CORE" PATH="$STUBS:$CORE" "$TRANS" --help >/dev/null 2>&1
check "help exits 0" "0" "$?"
HOME="$CORE" PATH="$STUBS:$CORE" "$TRANS" --nope >/dev/null 2>&1
check "unknown option exits 2" "2" "$?"
HOME="$CORE" PATH="$STUBS:$CORE" "$TRANS" >/dev/null 2>&1
check "no audio exits 2" "2" "$?"

# --- missing ffmpeg -------------------------------------------------------
out=$(PATH="$CORE" "$TRANS" "$audio" 2>&1); rc=$?
check "missing ffmpeg exits 3" "3" "$rc"
check "missing ffmpeg is explained" "yes" "$(grep -q 'ffmpeg required' <<<"$out" && echo yes || echo no)"

# --- no backend -----------------------------------------------------------
out=$(HOME="$CORE" PATH="$STUBS:$CORE" "$TRANS" "$audio" 2>&1); rc=$?
check "no backend exits 3" "3" "$rc"
check "no backend is explained" "yes" "$(grep -q 'no usable backend' <<<"$out" && echo yes || echo no)"

# --- forced backend not ready --------------------------------------------
HOME="$CORE" PATH="$STUBS:$CORE" "$TRANS" --backend http "$audio" >/dev/null 2>&1
check "forced http without URL exits 3" "3" "$?"

# --- whisper success ------------------------------------------------------
printf '#!/bin/bash\necho "  Ab, 12  cd!! "\n' > "$STUBS/whisper-cli"
chmod +x "$STUBS/whisper-cli"
out=$(HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_WHISPER_MODEL="$model" "$TRANS" "$audio")
check "whisper transcribes" "Ab 12 cd" "$out"
out=$(HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_WHISPER_MODEL="$model" "$TRANS" --json "$audio")
check "json carries backend" "yes" "$(grep -q '"backend":"whisper"' <<<"$out" && echo yes || echo no)"
out=$(HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_WHISPER_MODEL="$model" "$TRANS" --status)
check "whisper ready when model set" "yes" "$(grep -q '^whisper: ready' <<<"$out" && echo yes || echo no)"

# --- missing file ---------------------------------------------------------
HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_WHISPER_MODEL="$model" "$TRANS" /no/such/audio.wav >/dev/null 2>&1
check "missing audio exits 5" "5" "$?"

# --- empty backend output -------------------------------------------------
printf '#!/bin/bash\nexit 0\n' > "$STUBS/whisper-cli"; chmod +x "$STUBS/whisper-cli"
HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_WHISPER_MODEL="$model" "$TRANS" "$audio" >/dev/null 2>&1
check "empty transcription exits 1" "1" "$?"

# --- http backend ---------------------------------------------------------
printf '#!/bin/bash\necho "{\\"text\\":\\"zz9\\"}"\n' > "$STUBS/curl"
chmod +x "$STUBS/curl"
printf '#!/bin/bash\nexit 0\n' > "$STUBS/whisper-cli"; chmod +x "$STUBS/whisper-cli"
out=$(HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_WHISPER_URL="http://127.0.0.1:9/v1/audio/transcriptions" "$TRANS" --backend http "$audio")
check "http backend transcribes" "zz9" "$out"

# --- vosk backend ---------------------------------------------------------
printf '#!/bin/bash\necho "hf 51"\n' > "$STUBS/vosk-transcriber"; chmod +x "$STUBS/vosk-transcriber"
out=$(HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_VOSK_MODEL="$STUBS/vosk-model" "$TRANS" --backend vosk "$audio")
check "vosk transcribes" "hf 51" "$out"

# --- auto backend selection (exercises the detect chains) -----------------
# Only the python `whisper` binary (whisper-cli absent) -> whisper
rm -f "$STUBS/whisper-cli" "$STUBS/curl" "$STUBS/vosk-transcriber"
printf '#!/bin/bash\necho "py 9"\n' > "$STUBS/whisper"; chmod +x "$STUBS/whisper"
out=$(HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_WHISPER_MODEL="$model" "$TRANS" "$audio")
check "auto picks the python whisper binary" "py 9" "$out"
rm -f "$STUBS/whisper"

# No whisper at all, vosk present -> vosk
printf '#!/bin/bash\necho "vk 7"\n' > "$STUBS/vosk-transcriber"; chmod +x "$STUBS/vosk-transcriber"
out=$(HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_VOSK_MODEL="$STUBS/vosk-model" "$TRANS" "$audio")
check "auto picks vosk" "vk 7" "$out"
rm -f "$STUBS/vosk-transcriber"

# Only a local http endpoint -> http
printf '#!/bin/bash\necho "{\\"text\\":\\"zz9\\"}"\n' > "$STUBS/curl"; chmod +x "$STUBS/curl"
out=$(HOME="$CORE" PATH="$STUBS:$CORE" CAPTCHA_WHISPER_URL="http://127.0.0.1:9/v1/audio/transcriptions" "$TRANS" "$audio")
check "auto picks the http endpoint" "zz9" "$out"

printf '\nshell test_transcribe: %s passed, %s failed\n' "$pass" "$fail"
(( fail == 0 ))
