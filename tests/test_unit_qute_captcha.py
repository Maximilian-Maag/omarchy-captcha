#!/usr/bin/env python3
"""Unit tests for the qute-captcha userscript.

The userscript binds QUTE_* / CAPTCHA_* from os.environ at import time, so every test
sets the environment BEFORE exec()-ing it (patching globals afterwards is a no-op for
module-level names). The helper CLIs are stubbed with tiny scripts so no real OCR / STT
runs here - the real tools are exercised by the integration and e2e kinds.
"""
import base64
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


DATA_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


class DataUrlImages(Base):
    """A captcha rendered as an inline data: URL (BotDetect's demo does this). The bytes are in
    the page, so the solver must be handed a real file - passing the raw data: URL failed with
    "No such image", which is what a live browser test caught."""

    def test_image_to_file_leaves_a_url_alone(self):
        g = self.load()
        self.assertEqual(g["image_to_file"]("https://example.com/c.png"),
                         "https://example.com/c.png")

    def test_image_to_file_decodes_a_data_url(self):
        g = self.load()
        path = g["image_to_file"](DATA_PNG)
        try:
            self.assertNotEqual(path, DATA_PNG)
            self.assertTrue(path.endswith(".png"), path)
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), base64.b64decode(DATA_PNG.split(",", 1)[1]))
        finally:
            os.unlink(path)

    def test_cmd_solve_hands_the_solver_the_decoded_bytes(self):
        pathlib.Path(self.html).write_text('<img alt="captcha" src="' + DATA_PNG + '">')
        # the stub reports the SIZE of the file it was given, so the assertion is about the
        # decoded bytes, never the base64 text
        stub = make_stub(self.tmp, "sizesolver", 'printf "size=%s" "$(wc -c < "$1")"')
        g = self.load(CAPTCHA_SOLVER=stub)
        self.assertEqual(g["cmd_solve"](), 0)
        want = len(base64.b64decode(DATA_PNG.split(",", 1)[1]))
        self.assertTrue(any(("captcha guess: size=%d" % want) in c for c in self.sent()),
                        self.sent())

    def test_cmd_solve_removes_its_temp_file(self):
        pathlib.Path(self.html).write_text('<img alt="captcha" src="' + DATA_PNG + '">')
        stub = make_stub(self.tmp, "pathsolver", 'printf "p=%s" "$1"')
        g = self.load(CAPTCHA_SOLVER=stub)
        self.assertEqual(g["cmd_solve"](), 0)
        line = [c for c in self.sent() if "captcha guess: p=" in c][0]
        made = line.split("captcha guess: p=", 1)[1].split(" ", 1)[0].strip("'")
        self.assertFalse(os.path.exists(made), "the temp image must be cleaned up: %s" % made)

    def test_a_normal_image_url_reaches_the_solver_unchanged(self):
        pathlib.Path(self.html).write_text('<img alt="captcha" src="/captcha.png?r=1">')
        stub = make_stub(self.tmp, "urlsolver", 'printf "u=%s" "$1"')
        g = self.load(CAPTCHA_SOLVER=stub)
        self.assertEqual(g["cmd_solve"](), 0)
        self.assertTrue(any("u=https://example.com/captcha.png?r=1" in c for c in self.sent()),
                        self.sent())


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


class AudioAutoDetect(Base):
    """`,va` with no argument should find the challenge itself when it can."""

    def load_with_html(self, html, **over):
        pathlib.Path(self.html).write_text(html)
        return self.load(**over)

    def test_finds_an_audio_element(self):
        g = self.load()
        html = '<audio src="/challenge/captcha.mp3"></audio>'
        self.assertEqual(g["find_captcha_audio"](html, "https://example.com/login"),
                         "https://example.com/challenge/captcha.mp3")

    def test_finds_a_source_child(self):
        g = self.load()
        html = '<audio><source src="/a/audio-1.ogg" type="audio/ogg"></audio>'
        self.assertEqual(g["find_captcha_audio"](html, "https://example.com/"),
                         "https://example.com/a/audio-1.ogg")

    def test_skips_a_blob_source_and_uses_the_next(self):
        # a blob: src is not a URL the transcriber can fetch -> skip it, do not fail on it
        g = self.load()
        html = ('<audio src="blob:https://example.com/zzz"></audio>'
                '<audio src="/captcha/challenge.mp3"></audio>')
        self.assertEqual(g["find_captcha_audio"](html, "https://example.com/"),
                         "https://example.com/captcha/challenge.mp3")

    def test_skips_a_data_source(self):
        g = self.load()
        self.assertEqual(g["find_captcha_audio"](
            '<audio src="data:audio/mp3;base64,AAAA"></audio>', "https://example.com/"), "")

    def test_finds_a_link_that_carries_a_captcha_hint(self):
        g = self.load()
        html = '<a id="captcha" href="/dl/9ab.mp3">download</a>'
        self.assertEqual(g["find_captcha_audio"](html, "https://example.com/"),
                         "https://example.com/dl/9ab.mp3")

    def test_finds_a_link_that_says_audio_without_a_captcha_hint(self):
        g = self.load()
        html = '<a id="audio-dl" href="/dl/9ab.mp3">download</a>'
        self.assertEqual(g["find_captcha_audio"](html, "https://example.com/"),
                         "https://example.com/dl/9ab.mp3")

    def test_ignores_a_plain_music_link(self):
        g = self.load()
        self.assertEqual(g["find_captcha_audio"]('<a href="/song.mp3">music</a>',
                                                 "https://example.com/"), "")

    def test_no_audio_is_empty(self):
        g = self.load()
        self.assertEqual(g["find_captcha_audio"]("<html>nothing</html>", "https://example.com/"), "")

    def test_empty_html_is_safe(self):
        g = self.load()
        self.assertEqual(g["find_captcha_audio"]("", "https://example.com/"), "")

    def test_is_audio_url(self):
        g = self.load()
        self.assertTrue(g["is_audio_url"]("https://x/a/captcha.mp3"))
        self.assertTrue(g["is_audio_url"]("/a/captcha.mp3?r=1"))
        self.assertTrue(g["is_audio_url"]("/a/cap.wav#t"))
        self.assertFalse(g["is_audio_url"]("/a/captcha.png"))
        self.assertFalse(g["is_audio_url"](""))
        self.assertFalse(g["is_audio_url"]("/a/mp3"))

    def test_cmd_audio_uses_the_page_audio(self):
        g = self.load_with_html('<audio src="/captcha/challenge.mp3"></audio>')
        self.assertEqual(g["cmd_audio"](""), 0)
        self.assertTrue(any("cd 34" in c for c in self.sent()), self.sent())

    def test_cmd_audio_uses_the_current_url_when_it_is_audio(self):
        pathlib.Path(self.html).write_text("<html></html>")
        g = self.load(QUTE_URL="https://example.com/captcha/challenge.mp3")
        self.assertEqual(g["cmd_audio"](""), 0)
        self.assertTrue(any("cd 34" in c for c in self.sent()), self.sent())


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
