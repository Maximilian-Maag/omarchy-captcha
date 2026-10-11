# Changelog

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
