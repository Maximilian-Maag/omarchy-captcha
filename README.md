# omarchy-captcha

Solve captchas in [qutebrowser](https://qutebrowser.org) **locally** — no captcha-solving
service, no API key, nothing leaves the machine.

Two solvers ship here:

| Surface | Tool | How |
|---|---|---|
| Image captchas | `omarchy-captcha-solve` | Fetches the image, preprocesses it, reads it with **tesseract** |
| reCAPTCHA audio challenge | `omarchy-captcha-transcribe` | Normalises the audio with **ffmpeg**, then transcribes it with a **local** STT engine |

The `qute-captcha` userscript ties them to the browser: it finds a captcha on the page,
solves it, and fills the field — then **shows you the answer** and stops. It never submits
a form, so you can fix the letters tesseract got wrong before pressing Enter yourself.

## Why local

Captcha-solving APIs (2captcha, anti-captcha) ship your captcha — and often a browser
session — to a third party and need an account and a key. This uses tools already on an
Omarchy box, so there is nothing to sign up for and no traffic off the machine.

## Install

```bash
git clone https://github.com/Maximilian-Maag/omarchy-captcha
cd omarchy-captcha
./install.sh
```

`install.sh` puts the CLIs in `/usr/local/bin`, links the userscript into your qutebrowser
profile, and writes a keybinding fragment. If your `config.py` is a symlink owned by another
plugin it will not touch it — it prints the one line to add instead.

### Dependencies

```bash
omarchy pkg add tesseract        # required for image captchas
omarchy pkg add imagemagick      # recommended: preprocessing improves OCR
omarchy pkg add ffmpeg           # required for the audio challenge
```

For the **audio** challenge you also need a local speech-to-text engine — any one of:

```bash
omarchy pkg add whisper-cpp      # then set CAPTCHA_WHISPER_MODEL to a ggml model
omarchy pkg add vosk-api         # then set CAPTCHA_VOSK_MODEL to a model directory
# or point CAPTCHA_WHISPER_URL at a local OpenAI-compatible transcription endpoint
```

`omarchy-captcha-transcribe --status` reports which backends are ready.

No root for whisper.cpp: it builds into `~/.local` in a few minutes and is found on PATH there,
and the transcriber also looks for a model at `~/.local/share/whisper.cpp/models/ggml-base.en.bin`
- so a ggml model you already have (e.g. from voxtype) can simply be symlinked in, with no
`CAPTCHA_WHISPER_MODEL` to set:

```bash
git clone --depth=1 https://github.com/ggml-org/whisper.cpp ~/.local/share/whisper.cpp-src
cmake -B ~/.local/share/whisper.cpp-src/build -S ~/.local/share/whisper.cpp-src \
      -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF
cmake --build ~/.local/share/whisper.cpp-src/build -j"$(nproc)"
ln -sf ~/.local/share/whisper.cpp-src/build/bin/whisper-cli ~/.local/bin/whisper-cli
mkdir -p ~/.local/share/whisper.cpp/models
ln -sf ~/.local/share/voxtype/models/ggml-base.en.bin ~/.local/share/whisper.cpp/models/
```

## Usage

In qutebrowser:

| Keys | Action |
|---|---|
| `,cc` | Solve the captcha on the current page and fill the field |
| `,ca` | Transcribe a downloaded audio challenge |
| `,cs` | Report which local tools are available |

From a shell:

```bash
omarchy-captcha-solve /tmp/captcha.png          # -> 7391
omarchy-captcha-solve --json https://site/cap.jpg
omarchy-captcha-solve --status

omarchy-captcha-transcribe /tmp/challenge.mp3   # -> "ab 12 cd"
omarchy-captcha-transcribe --status
```

## Notes and limits

- **reCAPTCHA / hCaptcha widgets live in a cross-origin iframe** that page JavaScript cannot
  reach, so the image path cannot drive them. Use the widget's audio option, download the
  audio, and run `,ca`. The userscript says so rather than pretending.
- **The guess is shown, never submitted.** OCR is not perfect; treat the reading as a
  suggestion. That is deliberate — silently submitting a wrong answer is worse than showing it.
- Tesseract is configured for `eng` by default; pass `--lang` for another language.
- Only alphanumeric answers are expected (that is what captchas are); punctuation is stripped.

## Tests

```bash
bash tools/run_tests.sh          # policy + unit/regression/integration/e2e/shell + mutation
SKIP_MUTATION=1 bash tools/run_tests.sh
```

Kinds: unit, regression, integration (real tesseract + real ffmpeg against a generated
fixture), e2e (real tools end-to-end through a real FIFO), shell. Mutation targets the two
CLIs and the userscript.

## License

MIT — see [LICENSE](LICENSE).
