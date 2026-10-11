#!/bin/bash
# Shell tests for bin/omarchy-captcha-solve. Stubs tesseract/convert/curl so no real
# OCR runs; the real tesseract path is covered by the e2e kind.
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
SOLVE="$ROOT/bin/omarchy-captcha-solve"

STUBS="$(mktemp -d)"     # fake tools, first on PATH
CORE="$(mktemp -d)"      # coreutils only - NO tesseract (to test the missing path)
trap 'rm -rf "$STUBS" "$CORE"' EXIT

pass=0
fail=0
ok() { printf '  PASS %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL %s\n' "$1"; fail=$((fail + 1)); }
check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (want '$2' got '$3')"; fi
}

printf '#!/bin/bash\necho "y7k2p"\n' > "$STUBS/tesseract"
printf '#!/bin/bash\nexit 0\n' > "$STUBS/convert"
cat > "$STUBS/curl" <<'EOF'
#!/bin/bash
dest=""
while (( $# > 0 )); do
  if [[ $1 == "-o" ]]; then shift; dest="$1"; fi
  shift
done
printf 'stub-image' > "$dest"
exit 0
EOF
chmod +x "$STUBS"/*

for tool in bash tr cp mktemp; do
  ln -sf "$(command -v "$tool")" "$CORE/$tool"
done

img="$(mktemp)"; printf 'x' > "$img"

# --- status ---------------------------------------------------------------
out=$(PATH="$STUBS:$PATH" "$SOLVE" --status)
check "status lists tesseract ok" "yes" "$(grep -q '^tesseract: ok' <<<"$out" && echo yes || echo no)"

# --- help -----------------------------------------------------------------
PATH="$STUBS:$PATH" "$SOLVE" --help >/dev/null 2>&1
check "help exits 0" "0" "$?"

# --- argument errors ------------------------------------------------------
PATH="$STUBS:$PATH" "$SOLVE" --nope >/dev/null 2>&1
check "unknown option exits 2" "2" "$?"
PATH="$STUBS:$PATH" "$SOLVE" >/dev/null 2>&1
check "no image exits 2" "2" "$?"
PATH="$STUBS:$PATH" "$SOLVE" /no/such/file.png >/dev/null 2>&1
check "missing file exits 5" "5" "$?"

# --- dependencies ---------------------------------------------------------
out=$(PATH="$CORE" "$SOLVE" "$img" 2>&1); rc=$?
check "missing tesseract exits 3" "3" "$rc"
check "missing tesseract is explained" "yes" "$(grep -q 'tesseract required' <<<"$out" && echo yes || echo no)"

# --- success --------------------------------------------------------------
out=$(PATH="$STUBS:$PATH" "$SOLVE" "$img"); rc=$?
check "ocr success exits 0" "0" "$rc"
check "ocr reads the captcha" "y7k2p" "$out"
out=$(PATH="$STUBS:$PATH" "$SOLVE" --json "$img")
check "json carries the text" "yes" "$(grep -q '"text":"y7k2p"' <<<"$out" && echo yes || echo no)"

# --- url ------------------------------------------------------------------
out=$(PATH="$STUBS:$PATH" "$SOLVE" "https://example.com/c.png"); rc=$?
check "url fetch exits 0" "0" "$rc"
check "url fetch reads the captcha" "y7k2p" "$out"

# --- unreadable -----------------------------------------------------------
printf '#!/bin/bash\nexit 0\n' > "$STUBS/tesseract"; chmod +x "$STUBS/tesseract"
PATH="$STUBS:$PATH" "$SOLVE" "$img" >/dev/null 2>&1
check "no readable text exits 1" "1" "$?"

# --- lang option ----------------------------------------------------------
printf '#!/bin/bash\necho "y7k2p"\n' > "$STUBS/tesseract"; chmod +x "$STUBS/tesseract"
out=$(PATH="$STUBS:$PATH" "$SOLVE" --lang deu "$img")
check "lang option still solves" "y7k2p" "$out"

printf '\nshell test_solve: %s passed, %s failed\n' "$pass" "$fail"
(( fail == 0 ))
