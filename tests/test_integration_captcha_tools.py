#!/usr/bin/env python3
"""Integration tests: run the REAL CLI tools (real tesseract, real ffmpeg) against
generated inputs, and the real HTTP fetch path against a loopback server. Only the
speech backend is stubbed, because no STT engine is installed on the test host - the
backend selection itself is still exercised for real.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOLVE = ROOT / "bin" / "omarchy-captcha-solve"
TRANSCRIBE = ROOT / "bin" / "omarchy-captcha-transcribe"

HAVE_TESSERACT = shutil.which("tesseract") is not None
HAVE_CONVERT = shutil.which("convert") is not None or shutil.which("magick") is not None
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def run(argv, env=None):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False,
                          env=env)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def make_image(path, text):
    """Render `text` into an image with ImageMagick."""
    tool = "magick" if shutil.which("magick") else "convert"
    subprocess.run([tool, "-size", "300x100", "xc:white", "-gravity", "center",
                    "-pointsize", "56", "-fill", "black", "-annotate", "+0+0", text,
                    str(path)], capture_output=True, check=False)


@unittest.skipUnless(HAVE_TESSERACT and HAVE_CONVERT, "needs tesseract + imagemagick")
class SolveRealOcr(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.img = self.tmp / "captcha.png"

    def test_reads_a_digit_captcha(self):
        make_image(self.img, "4821")
        rc, out, err = run([str(SOLVE), str(self.img)])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "4821")

    def test_json_mode(self):
        make_image(self.img, "9137")
        rc, out, _ = run([str(SOLVE), "--json", str(self.img)])
        self.assertEqual(rc, 0)
        self.assertIn('"text":"9137"', out)
        self.assertIn('"ok":true', out)

    def test_status_is_non_mutating(self):
        rc, out, _ = run([str(SOLVE), "--status"])
        self.assertEqual(rc, 0)
        self.assertIn("tesseract: ok", out)


@unittest.skipUnless(HAVE_TESSERACT, "needs tesseract")
class SolveFetch(unittest.TestCase):
    def test_downloads_and_reads_over_http(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        img = tmp / "c.png"
        if not HAVE_CONVERT:
            self.skipTest("needs imagemagick to build the fixture")
        make_image(img, "5678")
        payload = img.read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = "http://127.0.0.1:%d/captcha.png" % srv.server_address[1]
            rc, out, err = run([str(SOLVE), url])
            self.assertEqual(rc, 0, err)
            self.assertEqual(out, "5678")
        finally:
            srv.shutdown()


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg")
class TranscribeIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.audio = self.tmp / "chal.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=0.3", "-ar", "16000",
                        "-ac", "1", "-y", str(self.audio)], capture_output=True, check=False)

    def _env_with_backend(self, text):
        bindir = self.tmp / "bin"
        bindir.mkdir(exist_ok=True)
        stub = bindir / "whisper-cli"
        stub.write_text("#!/bin/bash\necho \"%s\"\n" % text)
        stub.chmod(0o755)
        model = self.tmp / "model.bin"
        model.write_text("x")
        env = dict(os.environ)
        env["PATH"] = "%s:%s" % (bindir, env.get("PATH", ""))
        env["CAPTCHA_WHISPER_MODEL"] = str(model)
        return env

    def test_normalises_audio_and_transcribes(self):
        env = self._env_with_backend("Ab, 12 cd")
        rc, out, err = run([str(TRANSCRIBE), str(self.audio)], env=env)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "Ab 12 cd")

    def test_picks_whisper_automatically(self):
        env = self._env_with_backend("q7")
        rc, out, _ = run([str(TRANSCRIBE), "--json", str(self.audio)], env=env)
        self.assertEqual(rc, 0)
        self.assertIn('"backend":"whisper"', out)

    def test_reports_no_backend_without_stubs(self):
        env = dict(os.environ)
        for key in ("CAPTCHA_WHISPER_URL", "CAPTCHA_VOSK_MODEL", "CAPTCHA_WHISPER_MODEL"):
            env.pop(key, None)
        rc, _, err = run([str(TRANSCRIBE), str(self.audio)], env=env)
        if shutil.which("whisper-cli") or shutil.which("vosk-transcriber"):
            self.skipTest("a real STT backend is installed on this host")
        self.assertEqual(rc, 3)
        self.assertIn("no usable backend", err)


if __name__ == "__main__":
    unittest.main()
