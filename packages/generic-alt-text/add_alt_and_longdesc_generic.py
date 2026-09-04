#!/usr/bin/env python3
"""
Generic version of add_alt_and_longdesc.py that works on any folder of HTML
files, not just the HELM course layout. Recursively scans a folder for HTML
files, generates alt text and long descriptions for their images using an
LLM, overwrites `alt` attributes, and creates long-description pages with
links back to the source page.

Usage:
  python add_alt_and_longdesc_generic.py --root /path/to/html_folder [--sample N]
  python add_alt_and_longdesc_generic.py --root /path/to/html_folder --provider anthropic --model claude-sonnet-5

Options:
  --root: Root directory to scan (default: current directory)
  --sample N: Test on only the first N HTML files instead of all
  --provider {ollama,anthropic,openai,gemini}: Which LLM backend to use (default: ollama)
  --model: Override the default model for the chosen provider
  --feedback-form-url: Optional URL to link to from each long-description page
    ("Give feedback on this description"). Omitted entirely if not set.

Cloud providers read their API key from the standard environment variable for
that SDK: ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY. Ollama runs
locally and needs no key.
"""

import argparse
import base64
import csv
import functools
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

OLLAMA_DEFAULT_MODEL = 'gemma4:e4b'
ANTHROPIC_DEFAULT_MODEL = 'claude-sonnet-5'
OPENAI_DEFAULT_MODEL = 'gpt-4o'
GEMINI_DEFAULT_MODEL = 'gemini-2.0-flash'

def fix_latex_delimiters(text):
    """Normalise LaTeX delimiters to \\( \\) regardless of what the model output."""
    # Display math first: $$...$$ → \[...\]
    text = re.sub(r'\$\$(.+?)\$\$', r'\\[\1\\]', text, flags=re.DOTALL)
    # Inline math: $...$ → \(...\)
    text = re.sub(r'\$(.+?)\$', r'\\(\1\\)', text, flags=re.DOTALL)
    return text


def fix_json_latex_escapes(text):
    """Repair LaTeX commands broken by json.loads() consuming unescaped backslashes.

    json.loads() converts \\t→TAB, \\f→FF, \\r→CR, \\b→BS. LLMs frequently emit
    LaTeX commands like \\text, \\frac, \\right without doubling the backslash in JSON,
    so these arrive in parsed output as control characters rather than backslashes.
    """
    repairs = [
        ('\text',        r'\text'),
        ('\theta',       r'\theta'),
        ('\tau',         r'\tau'),
        ('\times',       r'\times'),
        ('\tfrac',       r'\tfrac'),
        ('\frac',        r'\frac'),
        ('\forall',      r'\forall'),
        ('\right',       r'\right'),
        ('\rho',         r'\rho'),
        ('\beta',        r'\beta'),
        ('\bar',         r'\bar'),
        ('\binom',       r'\binom'),
        ('\boldsymbol',  r'\boldsymbol'),
    ]
    for broken, fixed in repairs:
        text = text.replace(broken, fixed)
    return text


def bullets_to_html(text):
    """Convert a *-bulleted string (with or without newlines) to a <ul> list."""
    items = [i.strip() for i in re.split(r'\s*\*\s*', text) if i.strip()]
    if not items:
        return f'<p>{text}</p>'
    return '<ul>\n' + ''.join(f'  <li>{item}</li>\n' for item in items) + '</ul>'


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "alt": {"type": "string"},
        "long_description": {"type": "string"}
    },
    "required": ["alt", "long_description"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are an assistant that produces structured accessibility descriptions for images.

Rules (must be strictly followed):
- Output must be valid JSON
- Always use LaTeX for mathematical expressions with \\( and \\)
- Do not use plain text math
- The long_description must be a bulleted list
- Do not explain concepts, only describe what is visible
- Spell out all abbreviated units
"""


def build_user_prompt(context):
    return f"""Describe the image for a visually impaired person.
Use this context to support interpretation:
{context}
Return JSON with:
- "alt": single sentence
- "long_description": detailed multi-sentence bulleted description
"""


def postprocess_result(result):
    result['alt'] = fix_json_latex_escapes(fix_latex_delimiters(result.get('alt', '')))
    result['long_description'] = fix_json_latex_escapes(fix_latex_delimiters(result.get('long_description', '')))
    return result


def encode_image_base64(image_path):
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def describe_image_ollama(image_path, context, model=OLLAMA_DEFAULT_MODEL):
    try:
        from ollama import chat
    except ImportError:
        raise SystemExit("The 'ollama' package is required for --provider ollama. Install with: pip install ollama")

    response = chat(
        model=model,
        format=RESPONSE_SCHEMA,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(context),
                "images": [image_path],
            },
        ]
    )
    result = json.loads(response.message.content)
    return postprocess_result(result)


def describe_image_anthropic(image_path, context, model=ANTHROPIC_DEFAULT_MODEL):
    try:
        import anthropic
    except ImportError:
        raise SystemExit("The 'anthropic' package is required for --provider anthropic. Install with: pip install anthropic")

    if not os.environ.get('ANTHROPIC_API_KEY'):
        raise SystemExit("Set the ANTHROPIC_API_KEY environment variable to use --provider anthropic.")

    client = anthropic.Anthropic()

    tool = {
        "name": "describe_image",
        "description": "Return a structured accessibility description for the image.",
        "input_schema": RESPONSE_SCHEMA,
    }
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": "describe_image"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": encode_image_base64(image_path),
                    },
                },
                {"type": "text", "text": build_user_prompt(context)},
            ],
        }],
    )
    tool_use = next(b for b in response.content if b.type == 'tool_use')
    result = dict(tool_use.input)
    return postprocess_result(result)


def describe_image_openai(image_path, context, model=OPENAI_DEFAULT_MODEL):
    try:
        import openai
    except ImportError:
        raise SystemExit("The 'openai' package is required for --provider openai. Install with: pip install openai")

    try:
        client = openai.OpenAI()
    except openai.OpenAIError as e:
        raise SystemExit(f"OpenAI client error: {e}\nSet the OPENAI_API_KEY environment variable.")

    response = client.chat.completions.create(
        model=model,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "image_description",
                "schema": RESPONSE_SCHEMA,
                "strict": True,
            },
        },
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_user_prompt(context)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encode_image_base64(image_path)}"},
                    },
                ],
            },
        ],
    )
    result = json.loads(response.choices[0].message.content)
    return postprocess_result(result)


def describe_image_gemini(image_path, context, model=GEMINI_DEFAULT_MODEL):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise SystemExit("The 'google-genai' package is required for --provider gemini. Install with: pip install google-genai")

    if not os.environ.get('GOOGLE_API_KEY'):
        raise SystemExit("Set the GOOGLE_API_KEY environment variable to use --provider gemini.")

    client = genai.Client()
    with open(image_path, 'rb') as f:
        image_bytes = f.read()

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type='image/png'),
            build_user_prompt(context),
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    result = json.loads(response.text)
    return postprocess_result(result)


PROVIDERS = {
    'ollama': (describe_image_ollama, OLLAMA_DEFAULT_MODEL),
    'anthropic': (describe_image_anthropic, ANTHROPIC_DEFAULT_MODEL),
    'openai': (describe_image_openai, OPENAI_DEFAULT_MODEL),
    'gemini': (describe_image_gemini, GEMINI_DEFAULT_MODEL),
}

def find_html_files(root_dir):
    files = []
    for root, dirs, names in os.walk(root_dir):
        if os.path.basename(root) == 'longdesc':
            dirs[:] = []
            continue
        for n in names:
            if n.endswith('.html'):
                files.append(os.path.join(root, n))
    return sorted(files)


def resolve_image_path(html_file, image_src):
    html_dir = os.path.dirname(html_file)
    # strip any query or fragment
    src = image_src.split('?')[0].split('#')[0]
    candidate = os.path.normpath(os.path.join(html_dir, src))
    if os.path.isfile(candidate):
        return candidate
    return None


def find_png_for_image(resolved_path):
    """Look for an existing PNG for the image. If not found, return None.
    Search order:
      1. Same directory, same basename + .png
      2. png_converted subdir, same basename + .png
    """
    base = os.path.splitext(os.path.basename(resolved_path))[0]
    dirp = os.path.dirname(resolved_path)
    cand1 = os.path.join(dirp, base + '.png')
    cand2 = os.path.join(dirp, 'png_converted', base + '.png')
    if os.path.isfile(cand1):
        return cand1
    if os.path.isfile(cand2):
        return cand2
    return None


def shutil_which(cmd):
    try:
        import shutil
        return shutil.which(cmd)
    except Exception:
        return None


def convert_svg_to_png(svg_path, output_png, converter=None):
    # prefer Inkscape if available, otherwise ImageMagick convert
    if converter is None:
        converter = shutil_which('convert') or shutil_which('inkscape')
    try:
        os.makedirs(os.path.dirname(output_png), exist_ok=True)
        print(f"DEBUG: converter={converter}, cwd={os.getcwd()}, svg_path={svg_path}")
        if converter and 'inkscape' in os.path.basename(converter):
            # this is an unsafe way to call inkscape, but easier for now
            result = subprocess.run(f"{converter} --export-type=png --export-filename={output_png} {svg_path}", shell=True, check=True, timeout=30, capture_output=True, text=True, env=os.environ.copy())
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            print(f'used inkscape: {converter} and converted {svg_path} to {output_png}')
        else:
            result = subprocess.run([converter, '-verbose', '-depth','8', svg_path, output_png], check=True, timeout=300, capture_output=True, text=True, env=os.environ.copy())
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            print(f'used convert: {converter} and converted {svg_path} to {output_png}')
        return os.path.isfile(output_png)
    except Exception as e:
        print(f"Conversion error {svg_path} -> {output_png}: {e}", file=sys.stderr)
        return False


def get_context_for_image(img_tag):
    # Provide some textual context to the generator: alt, title, and surrounding text
    ctx = {}
    ctx['orig_alt'] = img_tag.get('alt', '')
    ctx['title'] = img_tag.get('title', '')
    parent = img_tag.parent
    if parent:
        txt = parent.get_text(separator=' ', strip=True)
        ctx['parent_text'] = txt[:1000]
    else:
        ctx['parent_text'] = ''
    return ctx


def make_longdesc_page(html_file, img_basename, long_description, png_path=None, alt_text=None, feedback_form_url=None):
    html_dir = os.path.dirname(html_file)
    longdir = os.path.join(html_dir, 'longdesc')
    os.makedirs(longdir, exist_ok=True)
    page_name = f"{Path(html_file).stem}__{img_basename}_longdesc.html"
    page_path = os.path.join(longdir, page_name)
    title = f"Long description: {img_basename}"

    # Prepare image HTML if png_path is provided
    image_html = ""
    if png_path:
        img_rel_path = os.path.relpath(png_path, start=longdir).replace(os.path.sep, '/')
        alt = alt_text if alt_text else img_basename
        image_html = f'<figure>\n<img src="{img_rel_path}" alt="{alt}"/>\n</figure>\n'

    alt_display_html = ""
    if alt_text:
        alt_display_html = f'<p><strong>Alt text:</strong> {alt_text}</p>'

    back_href = f"../{Path(html_file).name}"
    back_link_html = f'<p><a href="{back_href}">&#8592; Return to source page</a></p>'

    feedback_html = ""
    if feedback_form_url:
        feedback_html = f'<hr/>\n<p><a href="{feedback_form_url}" target="_blank">Give feedback on this description</a></p>'

    content = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<style type="text/css">
body {{ font-family: sans-serif; max-width: 45em; margin: 2em auto; padding: 0 1em; line-height: 1.5; }}
figure {{ margin: 1em 0; }}
figure img {{ max-width: 100%; }}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.0/MathJax.js?config=TeX-AMS-MML_HTMLorMML-full" type="text/javascript">
</script>
</head>
<body>
<main>
<h1>{title}</h1>
{back_link_html}
{image_html}
{alt_display_html}
<div class="long-description">
<p><strong>This description was generated by AI and has not been verified by a human.{' If you spot an error, please use the feedback link below.' if feedback_form_url else ''}</strong></p>
{bullets_to_html(long_description)}
</div>
{feedback_html}
</main>
</body>
</html>
"""
    with open(page_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return page_path


def relative_href(from_html, to_path):
    return os.path.relpath(to_path, start=os.path.dirname(from_html)).replace(os.path.sep, '/')


def log_entry(log_file, status, html_file, image_name):
    with open(log_file, 'a', newline='') as f:
        csv.writer(f).writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            status, html_file, image_name
        ])


def process_file(html_file, generator, dry_run=False, log_file=None, feedback_form_url=None) -> int:
    changed = False
    images_processed = 0
    with open(html_file, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    imgs = soup.find_all('img')
    for img in imgs:
        src = img.get('src')
        if not src:
            continue
        resolved = resolve_image_path(html_file, src)
        if not resolved:
            print(f"Image not found for src {src} in {html_file}", file=sys.stderr)
            continue

        png_path = find_png_for_image(resolved)
        if not png_path and resolved.lower().endswith('.svg'):
            # attempt conversion into png_converted
            base = os.path.splitext(os.path.basename(resolved))[0]
            outdir = os.path.join(os.path.dirname(resolved), 'png_converted')
            os.makedirs(outdir, exist_ok=True)
            outpng = os.path.join(outdir, f"{base}.png")
            ok = convert_svg_to_png(resolved, outpng)
            if ok:
                png_path = outpng

        if not png_path:
            print(f"No PNG available for {resolved} (skipping)")
            continue

        base = os.path.splitext(os.path.basename(png_path))[0]
        expected_longdesc = os.path.join(
            os.path.dirname(html_file), 'longdesc',
            f"{Path(html_file).stem}__{base}_longdesc.html"
        )
        if os.path.isfile(expected_longdesc):
            print(f"  Skipping {base} (longdesc already exists)")
            if log_file:
                log_entry(log_file, 'skipped', html_file, base)
            continue

        context = get_context_for_image(img)
        context.update({'html_file': html_file, 'image_src': src})

        try:
            result = generator(png_path, context)
        except Exception as e:
            print(f"Generator error for {png_path}: {e}", file=sys.stderr)
            if log_file:
                log_entry(log_file, 'error', html_file, base)
            continue

        if not isinstance(result, dict):
            print(f"Generator must return dict for {png_path}", file=sys.stderr)
            if log_file:
                log_entry(log_file, 'error', html_file, base)
            continue

        alt = result.get('alt')
        long_description = result.get('long_description')
        if alt:
            img['alt'] = alt
            changed = True

        if long_description:
            page_path = make_longdesc_page(html_file, base, long_description, png_path, alt, feedback_form_url)
            if log_file:
                log_entry(log_file, 'processed', html_file, base)
            images_processed += 1
            href = relative_href(html_file, page_path)
            # insert link after the image
            a = soup.new_tag('a', href=href)
            a.string = 'Long description'
            #parent = img.parent
            #sp = soup.new_tag('strong')
            #sp.string = f'Inserted after parent of image: {alt}'
            img.parent.insert_after(a)
            #img.insert_after(a)
            changed = True

    if changed:
        if not dry_run:
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(str(soup))
            print(f"Updated {html_file}")
        else:
            print(f"[DRY RUN] Would update {html_file}")

    return images_processed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.', help='Root directory to scan')
    parser.add_argument('--sample', type=int, help='Test on only the first N HTML files')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without modifying files')
    parser.add_argument('--log-file', default='alt_longdesc_progress.csv', help='CSV file to log processed images')
    parser.add_argument('--max-images', type=int, default=None,
                        help='Stop after processing this many images (for chunked runs)')
    parser.add_argument('--provider', choices=list(PROVIDERS), default='ollama',
                        help='LLM backend to use (default: ollama)')
    parser.add_argument('--model', default=None,
                        help='Override the default model for the chosen provider')
    parser.add_argument('--feedback-form-url', default=None,
                        help='Optional URL to link to from each long-description page')
    args = parser.parse_args()

    generator_fn, default_model = PROVIDERS[args.provider]
    generator = functools.partial(generator_fn, model=args.model or default_model)

    if not os.path.isfile(args.log_file):
        with open(args.log_file, 'w', newline='') as f:
            csv.writer(f).writerow(['timestamp', 'status', 'html_file', 'image'])

    html_files = find_html_files(args.root)
    print(f"Found {len(html_files)} HTML files")

    if args.sample:
        html_files = html_files[:args.sample]
        print(f"Testing on sample of {len(html_files)} files")

    if args.dry_run:
        print("[DRY RUN MODE] - Files will not be modified")

    print("-" * 80)

    total_processed = 0
    for hf in html_files:
        n = process_file(hf, generator, dry_run=args.dry_run, log_file=args.log_file,
                          feedback_form_url=args.feedback_form_url)
        total_processed += n
        if args.max_images and total_processed >= args.max_images:
            print(f"\nReached --max-images limit ({args.max_images}). Re-run to continue.")
            break

    print("-" * 80)
    print(f"Session complete: {total_processed} image(s) processed.")
    if args.max_images and total_processed >= args.max_images:
        print("There may be more images remaining. Re-run with the same command to continue.")


if __name__ == '__main__':
    main()
