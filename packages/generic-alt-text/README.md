# Alt Text & Long Description Generator

Generates AI-written alt text and long-description pages for images in any
folder of HTML files. For each `<img>` it finds, it writes a short `alt`
attribute and a separate linked page with a fuller, bulleted description —
using an LLM you choose and supply an API key for.

Unlike the HELM-specific version this is based on, this script works on
**any folder of HTML files** — no filename filter, no assumptions about a
particular site layout or stylesheet.

## What it does

For every `.html` file found recursively under `--root` (skipping any
`longdesc` folders it has already created):

1. Every `<img>` is resolved to a local image file.
2. If the image is an SVG and no PNG version exists yet, one is generated
   (via Inkscape or ImageMagick, whichever is on `PATH`) into a
   `png_converted/` subfolder next to it.
3. The PNG is sent to an LLM, along with surrounding page context (existing
   `alt`/`title` attributes, nearby text), to generate:
   - `alt` — a one-sentence alt text, written into the `<img alt="...">` attribute.
   - `long_description` — a longer, bulleted description, written to a new,
     self-contained page under a `longdesc/` subfolder next to the source
     HTML file, with a "Long description" link inserted after the image.
4. Progress is logged to a CSV file (`--log-file`, default
   `alt_longdesc_progress.csv`) so runs can be resumed — images whose
   long-description page already exists are skipped on later runs.

The generated long-description pages are self-contained: a small built-in
stylesheet and MathJax loaded from a CDN (for any LaTeX in the description),
with no dependency on local CSS files. The script only ever reads existing
images; it never generates or edits images themselves.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Then install the SDK for whichever LLM provider you want to use:

| Provider | Install | API key env var |
|---|---|---|
| Ollama (local, free) | `pip install ollama` + a running local Ollama server with a vision model pulled | none needed |
| Anthropic (Claude) | `pip install anthropic` | `ANTHROPIC_API_KEY` |
| OpenAI (GPT) | `pip install openai` | `OPENAI_API_KEY` |
| Google (Gemini) | `pip install google-genai` | `GOOGLE_API_KEY` |

If any images are SVGs without an existing PNG version, you'll also need
`inkscape` or ImageMagick's `convert` available on `PATH`.

## Usage

```bash
# Quick test: dry run on the first 5 HTML files found, no files written
python add_alt_and_longdesc_generic.py --root /path/to/html_folder --sample 5 --dry-run

# Full run using local Ollama (default provider)
python add_alt_and_longdesc_generic.py --root /path/to/html_folder

# Full run using Claude, with a feedback link on every long-description page
export ANTHROPIC_API_KEY=sk-ant-...
python add_alt_and_longdesc_generic.py --root /path/to/html_folder \
  --provider anthropic --model claude-sonnet-5 \
  --feedback-form-url https://forms.example.com/feedback

# Chunked run against a paid API, 50 images at a time — re-run the same
# command to continue where it left off
python add_alt_and_longdesc_generic.py --root /path/to/html_folder --provider openai --max-images 50
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--root` | `.` | Root directory to scan |
| `--sample N` | (all) | Only process the first N HTML files found — useful for a quick test run |
| `--dry-run` | off | Report what would change without writing any files |
| `--log-file` | `alt_longdesc_progress.csv` | CSV file tracking processed/skipped/errored images, for resumable runs |
| `--max-images N` | (no limit) | Stop after processing N images in this run |
| `--provider` | `ollama` | LLM backend: `ollama`, `anthropic`, `openai`, or `gemini` |
| `--model` | provider-specific | Override the default model for the chosen provider |
| `--feedback-form-url` | (none) | If set, adds a "Give feedback on this description" link to each long-description page pointing at this URL |

Cloud providers read their key only from the environment variable listed
above — there is no `--api-key` flag.

## Before a large run

Cloud providers charge per image and rate-limit requests. Start with
`--sample N --dry-run` to check the output looks right, then use
`--max-images` to run in manageable, resumable chunks.
