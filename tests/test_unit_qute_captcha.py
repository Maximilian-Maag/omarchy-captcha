#!/usr/bin/env python3
"""Unit tests for the qute-captcha userscript.

The userscript binds QUTE_* / CAPTCHA_* from os.environ at import time, so every test
sets the environment BEFORE exec()-ing it (patching globals afterwards is a no-op for
module-level names). The helper CLIs are stubbed with tiny scripts so no real OCR / STT
runs here - the real tools are exercised by the integration and e2e kinds.
"""
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urljoin

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "userscripts" / "qute-captcha"

PAGE_WITH_CAPTCHA = (
    '<html><body><form>'
    '<img src="/captcha.png?r=1" alt="Enter the code">'
    '<input name="captcha_code" type="text">'
    '</form></body></html>'
)


def load(env):
    """exec the userscript with `env` set, return its globals dict."""
    saved = dict(os.environ)
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        source = SRC.read_text()
        g = {"__name__": "__not_main__", "json": json, "re": re, "os": os,
             "subprocess": subprocess, "sys": sys, "urljoin": urljoin, "print": print}
        exec(compile(source, str(SRC), "exec"), g)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return g


def make_stub(directory, name, body):
    path = pathlib.Path(directory) / name
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fifo = os.path.join(self.tmp, "fifo")
        self.html = os.path.join(self.tmp, "page.html")
        pathlib.Path(self.html).write_text(PAGE_WITH_CAPTCHA)

    def load(self, **over):
        env = {
            "QUTE_URL": "https://example.com/login",
            "QUTE_HTML": self.html,
            "QUTE_FIFO": self.fifo,
            "CAPTCHA_SOLVER": make_stub(self.tmp, "solver", 'echo "Ab12"'),
            "CAPTCHA_TRANSCRIBER": make_stub(self.tmp, "trans", 'echo "cd 34"'),
        }
        env.update(over)
        return load(env)

    def sent(self):
        if not os.path.exists(self.fifo):
            return []
        with open(self.fifo) as fh:
            return [line.rstrip("\n") for line in fh if line.strip()]


class Detection(Base):
    def test_finds_relative_captcha_image(self):
        g = self.load()
        url = g["find_captcha_image"](PAGE_WITH_CAPTCHA, "https://example.com/login")
        self.assertEqual(url, "https://example.com/captcha.png?r=1")

    def test_keeps_absolute_url(self):
        g = self.load()
        html = '<img src="https://cdn.example.org/verify-code.jpg">'
        self.assertEqual(g["find_captcha_image"](html, "https://example.com/"),
                         "https://cdn.example.org/verify-code.jpg")

    def test_keeps_absolute_http_url(self):
        # http:// (not just https://) must be returned verbatim, not urljoin-ed
        g = self.load()
        html = '<img src="http://cdn.example.org/captcha.jpg">'
        self.assertEqual(g["find_captcha_image"](html, "https://example.com/"),
                         "http://cdn.example.org/captcha.jpg")

    def test_ignores_unrelated_images(self):
        g = self.load()
        html = '<img src="/logo.png" alt="home"><img src="/banner.jpg">'
        self.assertEqual(g["find_captcha_image"](html, "https://example.com/"), "")

    def test_matches_hint_in_class_or_id(self):
        g = self.load()
        html = '<img class="securimage" src="/img/9ab.png">'
        self.assertEqual(g["find_captcha_image"](html, "https://example.com/"),
                         "https://example.com/img/9ab.png")

    def test_empty_html_is_safe(self):
        g = self.load()
        self.assertEqual(g["find_captcha_image"]("", "https://example.com/"), "")


class FillJs(Base):
    def test_is_a_single_line(self):
        g = self.load()
        js = g["fill_js"]("Ab12")
        self.assertNotIn("\n", js)

    def test_embeds_the_answer_as_json(self):
        g = self.load()
        self.assertIn('"Ab12"', g["fill_js"]("Ab12"))

    def test_quotes_in_answer_are_json_escaped(self):
        g = self.load()
        self.assertIn(r'"a\"b"', g["fill_js"]('a"b'))


class Solve(Base):
    def test_fills_when_solver_succeeds(self):
        g = self.load()
        self.assertEqual(g["cmd_solve"](), 0)
        commands = self.sent()
        self.assertTrue(any("jseval" in c and "Ab12" in c for c in commands), commands)
        self.assertTrue(any("captcha guess: Ab12" in c for c in commands), commands)

    def test_reports_error_when_solver_fails(self):
        g = self.load(CAPTCHA_SOLVER=make_stub(self.tmp, "bad", 'echo "boom" >&2; exit 1'))
        self.assertEqual(g["cmd_solve"](), 1)
        commands = self.sent()
        self.assertTrue(any("message-error" in c and "boom" in c for c in commands), commands)

    def test_no_image_reports_and_returns_zero(self):
        pathlib.Path(self.html).write_text("<html><body>no captcha here</body></html>")
        g = self.load()
        self.assertEqual(g["cmd_solve"](), 0)
        self.assertTrue(any("no captcha image" in c for c in self.sent()))

    def test_missing_html_file_is_handled(self):
        g = self.load(QUTE_HTML=os.path.join(self.tmp, "nope.html"))
        self.assertEqual(g["cmd_solve"](), 1)
        self.assertTrue(any("no page HTML" in c for c in self.sent()))


class Audio(Base):
    def test_guides_when_no_file_given(self):
        g = self.load()
        self.assertEqual(g["cmd_audio"](""), 0)
        self.assertTrue(any("pass a downloaded audio file" in c for c in self.sent()))

    def test_reports_transcription(self):
        g = self.load()
        self.assertEqual(g["cmd_audio"]("/tmp/x.mp3"), 0)
        self.assertTrue(any("captcha audio: cd 34" in c for c in self.sent()))

    def test_reports_backend_failure(self):
        g = self.load(CAPTCHA_TRANSCRIBER=make_stub(self.tmp, "badtrans", 'exit 3'))
        self.assertEqual(g["cmd_audio"]("/tmp/x.mp3"), 1)
        self.assertTrue(any("message-error" in c for c in self.sent()))


class Status(Base):
    def test_reports_both_tools(self):
        g = self.load()
        self.assertEqual(g["cmd_status"](), 0)
        self.assertTrue(any("solver ok" in c and "transcriber ok" in c for c in self.sent()))


class Dispatch(Base):
    def test_main_defaults_to_solve(self):
        g = self.load()
        self.assertEqual(g["main"]([]), 0)
        self.assertTrue(any("captcha guess" in c for c in self.sent()))

    def test_main_audio_without_file_does_not_crash(self):
        g = self.load()
        self.assertEqual(g["main"](["audio"]), 0)
        self.assertTrue(any("pass a downloaded audio file" in c for c in self.sent()))

    def test_main_audio_with_file(self):
        g = self.load()
        self.assertEqual(g["main"](["audio", "/tmp/y.mp3"]), 0)
        self.assertTrue(any("cd 34" in c for c in self.sent()))

    def test_main_unknown_mode(self):
        g = self.load()
        self.assertEqual(g["main"](["frobnicate"]), 2)
        self.assertTrue(any("unknown mode" in c for c in self.sent()))


class HelperFailure(Base):
    def test_missing_solver_binary_is_reported(self):
        # an absent solver must be a FAILURE, never treated as an empty success
        g = self.load(CAPTCHA_SOLVER="/nonexistent/omarchy-captcha-solve-xyz")
        self.assertEqual(g["cmd_solve"](), 1)
        self.assertTrue(any("message-error" in c for c in self.sent()), self.sent())

    def test_missing_transcriber_binary_is_reported(self):
        g = self.load(CAPTCHA_TRANSCRIBER="/nonexistent/omarchy-captcha-transcribe-xyz")
        self.assertEqual(g["cmd_audio"]("/tmp/x.mp3"), 1)
        self.assertTrue(any("message-error" in c for c in self.sent()), self.sent())


class Escaping(Base):
    def test_escape_protects_the_fifo_command(self):
        g = self.load()
        self.assertEqual(g["_escape"]("it's"), "it\\'s")


if __name__ == "__main__":
    unittest.main()
