#!/bin/bash
# Round-trip test for `install.sh --uninstall`.
#
# Runs the real install.sh over a throwaway HOME/XDG with a stub `sudo`, then `--uninstall`, and
# asserts that the user's own config.py comes back byte-identical, that every artifact install.sh
# created is gone, and that a file which is not ours is left alone. Every assertion below fails if
# the matching removal is reverted in install.sh, so the suite is the guard for the uninstall path.
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
INSTALL="$ROOT/install.sh"

pass=0
fail=0
ok() { printf '  PASS %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL %s\n' "$1"; fail=$((fail + 1)); }
check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (want '$2' got '$3')"; fi
}
sha() { sha256sum "$1" | cut -d' ' -f1; }

# A hermetic HOME/XDG, plus a stub sudo so the real /usr/local/bin is never touched.
SANDBOX="$(mktemp -d)"
STUBS="$(mktemp -d)"
trap 'rm -rf "$SANDBOX" "$STUBS"' EXIT

export HOME="$SANDBOX/home"
export XDG_CONFIG_HOME="$SANDBOX/config"
export XDG_DATA_HOME="$SANDBOX/data"
export OMARCHY_CAPTCHA_BIN="$SANDBOX/bin"
mkdir -p "$HOME" "$XDG_CONFIG_HOME/qutebrowser" "$XDG_DATA_HOME/qutebrowser/userscripts" "$OMARCHY_CAPTCHA_BIN"

# sudo stub: run the command directly — nothing here needs privilege.
printf '#!/bin/bash\nexec "$@"\n' > "$STUBS/sudo"
chmod +x "$STUBS/sudo"

# The default python3 here is a broken mise shim that cannot run check_bindings.py; the system one
# can. This is a HERMETIC PATH: the stub dir first, then the system binaries.
export PATH="$STUBS:/usr/bin:/bin:/usr/local/bin"

QUTE="$XDG_CONFIG_HOME/qutebrowser"
CONFIG="$QUTE/config.py"
FRAGMENT="$QUTE/captcha-bindings.py"
DATA_LINK="$XDG_DATA_HOME/qutebrowser/userscripts/qute-captcha"
CONFIG_LINK="$QUTE/userscripts/qute-captcha"
CLI_LINK="$OMARCHY_CAPTCHA_BIN/omarchy-captcha-solve"

cat > "$CONFIG" <<'PY'
# the user's own qutebrowser config
config.load_autoconfig()
c.url.start_pages = ["https://example.com"]
PY
BEFORE="$(sha "$CONFIG")"

# A file that is not ours, in a directory uninstall visits: it must survive untouched.
FOREIGN="$QUTE/reader-notes.txt"
printf 'not ours\n' > "$FOREIGN"
FOREIGN_SHA="$(sha "$FOREIGN")"

# ── install ────────────────────────────────────────────────────────────────
if "$INSTALL" >/dev/null 2>&1; then ok "install exits 0"; else bad "install exits 0"; fi
check "config.py now sources the fragment" "yes" \
  "$(grep -qF 'config.source("captcha-bindings.py")' "$CONFIG" && echo yes || echo no)"
check "the fragment was written" "yes" "$([[ -f $FRAGMENT ]] && echo yes || echo no)"
check "the userscript is linked (data dir)" "yes" "$([[ -L $DATA_LINK ]] && echo yes || echo no)"
check "the userscript is linked (config dir)" "yes" "$([[ -L $CONFIG_LINK ]] && echo yes || echo no)"
check "the CLI tool is linked" "yes" "$([[ -L $CLI_LINK ]] && echo yes || echo no)"

# Plant a foreign file where one of our links was, to model "somebody else's qute-captcha".
rm -f "$CONFIG_LINK"
printf 'someone else\n' > "$CONFIG_LINK"

# ── uninstall ──────────────────────────────────────────────────────────────
if "$INSTALL" --uninstall >/dev/null 2>&1; then ok "uninstall exits 0"; else bad "uninstall exits 0"; fi
check "config.py is byte-identical after the round trip" "$BEFORE" "$(sha "$CONFIG")"
check "the source line is gone" "no" \
  "$(grep -qF 'captcha-bindings.py' "$CONFIG" && echo yes || echo no)"
check "no marker left behind in config.py" "no" \
  "$(grep -q 'omarchy-captcha' "$CONFIG" && echo yes || echo no)"
check "the fragment is gone" "no" "$([[ -e $FRAGMENT ]] && echo yes || echo no)"
check "the data-dir userscript link is gone" "no" "$([[ -e $DATA_LINK ]] && echo yes || echo no)"
check "the CLI tool link is gone" "no" "$([[ -e $CLI_LINK ]] && echo yes || echo no)"
check "a foreign userscript is left alone" "yes" \
  "$([[ -f $CONFIG_LINK ]] && grep -q 'someone else' "$CONFIG_LINK" && echo yes || echo no)"
check "the unrelated file is untouched" "$FOREIGN_SHA" "$(sha "$FOREIGN")"

# ── a config.py ending without a newline also comes back byte-identical ─────
printf 'x = 1' > "$CONFIG"        # no trailing newline
NN_BEFORE="$(sha "$CONFIG")"
"$INSTALL" >/dev/null 2>&1
"$INSTALL" --uninstall >/dev/null 2>&1
check "a config with no trailing newline is restored exactly" "$NN_BEFORE" "$(sha "$CONFIG")"

# ── uninstall alone leaves a foreign artifact alone ────────────────────────
printf 'foreign\n' > "$CLI_LINK"  # a real file where our link would be
"$INSTALL" --uninstall >/dev/null 2>&1
check "uninstall does not remove a foreign bin file" "yes" "$([[ -f $CLI_LINK ]] && echo yes || echo no)"

# ── sensitivity: with one removal reverted, the round trip must FAIL ────────
# Neutralise the config.py rewrite in a copy of install.sh and show the byte-identity assertion
# above is exactly what catches a reverted removal: config.py is then left changed.
MUTANT="$SANDBOX/install-mutant.sh"
sed 's|mv "\$kept_file" "\$target_py"|:|' "$INSTALL" > "$MUTANT"
chmod +x "$MUTANT"
printf 'y = 1\n' > "$CONFIG"
PRE="$(sha "$CONFIG")"
"$INSTALL" >/dev/null 2>&1                 # install with the real script
"$MUTANT" --uninstall >/dev/null 2>&1      # uninstall with the removal disabled
check "a reverted removal would fail the round-trip assertion" "different" \
  "$([[ "$(sha "$CONFIG")" == "$PRE" ]] && echo same || echo different)"

printf '\nshell test_install: %s passed, %s failed\n' "$pass" "$fail"
(( fail == 0 ))
