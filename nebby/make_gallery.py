#!/usr/bin/env python3
"""
Put many cwnd graphs on one HTML page.

    python3 nebby/make_gallery.py results/index.html results/*/cwnd.png

Captions come from a meta.json next to each image (results/<name>/meta.json),
or from a same-named .json file, or from the file name.
"""
import argparse
import html
import json
import os


def caption(png):
    d = os.path.dirname(png)
    stem = os.path.splitext(png)[0]
    meta = {}
    for cand in (os.path.join(d, "meta.json"), stem + ".json"):
        if os.path.exists(cand):
            meta = json.load(open(cand))
            break
    name = meta.get("name") or os.path.basename(stem)
    if os.path.basename(png) == "cwnd.png":
        name = meta.get("name") or os.path.basename(d)
    sub = meta.get("url", "")
    return name, sub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--title", default="Nebby cwnd graphs")
    a = ap.parse_args()

    outdir = os.path.dirname(os.path.abspath(a.out))
    cards = []
    for png in sorted(a.images):
        if not os.path.exists(png):
            continue
        name, sub = caption(png)
        rel = os.path.relpath(os.path.abspath(png), outdir)
        cards.append(
            f'<figure><a href="{html.escape(rel)}"><img loading="lazy" src="{html.escape(rel)}" '
            f'alt="{html.escape(name)}"></a><figcaption><b>{html.escape(name)}</b>'
            f'<span>{html.escape(sub)}</span></figcaption></figure>')

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(a.title)}</title>
<style>
 body{{margin:0;padding:24px;font:15px/1.4 system-ui,sans-serif;background:#fcfcfb;color:#0b0b0b}}
 h1{{font-size:22px;margin:0 0 16px}}
 main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(560px,1fr));gap:20px}}
 figure{{margin:0;background:#fff;border:1px solid #e6e5e1;border-radius:8px;padding:10px}}
 img{{width:100%;height:auto;display:block}}
 figcaption{{display:flex;flex-direction:column;gap:2px;padding-top:6px}}
 figcaption span{{color:#52514e;font-size:13px;word-break:break-all}}
 @media (max-width:640px){{body{{padding:16px}} main{{grid-template-columns:1fr}}}}
</style></head><body><h1>{html.escape(a.title)}</h1><main>
{chr(10).join(cards)}
</main></body></html>"""
    with open(a.out, "w") as fh:
        fh.write(page)
    print(f"[+] {len(cards)} graphs -> {a.out}")


if __name__ == "__main__":
    main()
