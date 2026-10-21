#!/usr/bin/env python3
"""Refuse keybindings that collide with the config they are added to.

qutebrowser does NOT time out a partial match. If one binding is a PREFIX of another, the shorter
one stops firing immediately and the next keypress is swallowed (basekeyparser.py: on PartialMatch
it keeps the keystring and waits; the following non-matching key then hits NoMatch and is dropped).
Nothing logs an error - `,c` simply goes dead the moment anything binds `,cc`. That is exactly how
omarchy-captcha's `,ca`/`,cc`/`,cs` broke the platform's `,c` (reader-factcheck).

Two collision classes are checked, per mode:

  duplicate  the same key bound more than once (last write silently wins)
  prefix     one key is a prefix of another (the shorter one dead-ends)

usage:
  check_bindings.py --fragment FILE [--config FILE ...]
  check_bindings.py FILE [FILE ...]

exit 0 clean, 1 collisions found, 2 usage or IO error.
"""

import argparse
import re
import sys

BIND_RE = re.compile(r'config\.bind\(\s*["\']([^"\']+)["\']')
MODE_RE = re.compile(r'mode\s*=\s*["\']([^"\']+)["\']')


def parse(path):
    """Return [(mode, key, path, lineno)] for every config.bind() in `path`."""
    out = []
    try:
        with open(path, errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                match = BIND_RE.search(line)
                if not match:
                    continue
                mode_match = MODE_RE.search(line)
                mode = mode_match.group(1) if mode_match else "normal"
                out.append((mode, match.group(1), path, lineno))
    except OSError as err:
        raise SystemExit("check_bindings: cannot read %s: %s" % (path, err))
    return out


def collisions(entries):
    """Return a list of human-readable collision lines (empty when the set is clean)."""
    problems = []
    seen = {}
    for mode, key, path, lineno in entries:
        seen.setdefault((mode, key), []).append("%s:%d" % (path, lineno))

    for (mode, key), where in sorted(seen.items()):
        if len(where) > 1:
            problems.append("duplicate: [%s] %s bound %d times (%s)"
                            % (mode, key, len(where), ", ".join(where)))

    by_mode = {}
    for mode, key, _path, _lineno in entries:
        by_mode.setdefault(mode, set()).add(key)
    for mode, keys in sorted(by_mode.items()):
        for short in sorted(keys):
            longer = sorted(k for k in keys if k != short and k.startswith(short))
            if longer:
                problems.append("prefix: [%s] %r is a prefix of %s - %r stops firing and the next "
                                "key is swallowed" % (mode, short, longer, short))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="refuse colliding qutebrowser keybindings")
    parser.add_argument("--fragment", help="the keybinding fragment being installed")
    parser.add_argument("--config", action="append", default=[],
                        help="a config the fragment is added to (repeatable)")
    parser.add_argument("files", nargs="*", help="files to check together")
    args = parser.parse_args(argv)

    paths = list(args.config) + list(args.files)
    if args.fragment:
        paths.insert(0, args.fragment)
    if not paths:
        parser.error("nothing to check: pass --fragment, --config or file arguments")

    entries = []
    for path in paths:
        entries.extend(parse(path))

    problems = collisions(entries)
    if not problems:
        print("check_bindings: %d binding(s) in %d file(s), no collisions"
              % (len(entries), len(paths)))
        return 0
    print("check_bindings: REFUSING - %d collision(s):" % len(problems), file=sys.stderr)
    for problem in problems:
        print("  " + problem, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
