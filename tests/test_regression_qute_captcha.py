#!/usr/bin/env python3
"""Regression tests for the qute-captcha userscript.

These pin behaviour that was correct once and must not silently change: the exact
attributes we do and do not treat as a captcha, ordering, and the cleaning the fill
path relies on. They are deliberately written against real page shapes seen in the
wild (uppercased attributes, single quotes, lazy-loading data-src, JS string noise).
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urljoin

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "userscripts" / "qute-captcha"


def load(env):
    saved = dict(os.environ)
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        source = SRC.read_text()
        g = {"__name__": "__not_main__", "json": json, "re": re, "os": os,
             "subprocess": subprocess, "sys": sys, "urljoin": urljoin}
        exec(compile(source, str(SRC), "exec"), g)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return g


class Regression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fifo = os.path.join(self.tmp, "fifo")
        self.g = load({"QUTE_URL": "https://shop.example.com/checkout",
                       "QUTE_HTML": os.path.join(self.tmp, "none.html"),
                       "QUTE_FIFO": self.fifo})

    def find(self, html, base="https://shop.example.com/checkout"):
        return self.g["find_captcha_image"](html, base)

    def test_uppercase_attributes_and_single_quotes(self):
        html = "<IMG SRC='/img/Captcha.php' ALT='code'>"
        self.assertEqual(self.find(html), "https://shop.example.com/img/Captcha.php")

    def test_first_captcha_image_wins(self):
        html = ('<img src="/logo.png"><img src="/c1.png" id="captcha1">'
                '<img src="/c2.png" id="captcha2">')
        self.assertEqual(self.find(html), "https://shop.example.com/c1.png")

    def test_plain_product_image_is_not_a_captcha(self):
        html = '<img src="/products/verify-set.jpg" alt="verifier kit">'
        # 'verify' is a hint, so this one IS matched on purpose - capture the rule
        self.assertEqual(self.find(html), "https://shop.example.com/products/verify-set.jpg")

    def test_image_without_hints_is_ignored(self):
        html = '<img src="/hero.jpg" alt="welcome" class="banner">'
        self.assertEqual(self.find(html), "")

    def test_data_src_lazy_images_are_not_matched(self):
        # Only the real src is read; a lazy placeholder must not be handed to tesseract
        html = '<img data-src="/captcha.png" src="/loading.gif">'
        self.assertEqual(self.find(html), "")

    def test_absolute_url_is_preserved_verbatim(self):
        html = '<img src="http://legacy.example.net/captcha?id=7">'
        self.assertEqual(self.find(html), "http://legacy.example.net/captcha?id=7")

    def test_protocol_relative_url_gets_scheme_from_base(self):
        html = '<img src="//cdn.example.com/captcha.png">'
        self.assertEqual(self.find(html), "https://cdn.example.com/captcha.png")

    def test_hint_match_is_case_insensitive(self):
        html = '<img src="/a.png" ALT="SECURITY-CODE">'
        self.assertEqual(self.find(html), "https://shop.example.com/a.png")

    def test_fill_js_targets_a_captcha_field_not_a_password(self):
        js = self.g["fill_js"]("Ab12")
        self.assertIn("input[name*='captcha' i]", js)
        self.assertNotIn("password", js.lower())

    def test_fill_js_focuses_before_writing(self):
        js = self.g["fill_js"]("Ab12")
        self.assertLess(js.index("focus()"), js.index(".value="))


if __name__ == "__main__":
    unittest.main()
