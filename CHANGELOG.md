# Changelog

## 1.1.0

- `,ca` (the userscript's audio mode) now FINDS the challenge when no file is given, instead of
  only printing guidance: the current URL when it is itself an audio file, else an
  `<audio>`/`<source>` on the page, else a captcha/audio-hinted `<a href>`. A `blob:`/`data:`
  source is skipped rather than passed to the transcriber to fail on. That removes the manual
  copy step for an inline audio challenge. A reCAPTCHA/hCaptcha widget still lives in a
  cross-origin iframe the page HTML does not contain, so its audio must be handed over
  (`:devtools` > Network -> the `.mp3`); the guidance now says exactly that.
- The transcribe shell test now runs the CLI on a HERMETIC PATH (`$STUBS:$CORE`) rather than
  `$STUBS:$PATH`. Appending the real PATH let a genuinely installed backend leak in: once
  whisper-cli existed on this machine, the "whisper unavailable" and "no backend" assertions
  stopped holding and auto-selection picked the real binary over the stub. A test whose result
  depends on what happens to be installed is not a test.

## 1.0.0

- `omarchy-captcha-solve`: local image-captcha OCR (tesseract) with optional ImageMagick
  preprocessing and URL fetching; `--status`, `--json`, `--lang`.
- `omarchy-captcha-transcribe`: local reCAPTCHA audio transcription via whisper.cpp, vosk or
  a local OpenAI-compatible endpoint; `--status`, `--json`, `--backend`.
- `qute-captcha` userscript: finds a captcha image, solves it, fills the field and reports the
  guess for confirmation. Never submits. Falls back to guidance for cross-origin widgets.
- Keybindings `,cc` / `,ca` / `,cs`; installer writes the fragment, links the tools and the
  userscript, and refuses to edit a `config.py` owned by another plugin.
- Full harness: policy as code, unit / regression / integration / e2e / shell tests, and
  mutation testing over the two CLIs and the userscript.
