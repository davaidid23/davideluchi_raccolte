#!/usr/bin/env python3
"""
build_poems.py — Genera le pagine HTML delle poesie dai file .tex
e aggiorna gli indici delle raccolte.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

COLLECTIONS = {
    "Autopsie": {"page": "Autopsie.html", "name": "Autopsie"},
    "Diario_di_notte": {"page": "Diario_di_notte.html", "name": "Diario di notte"},
    "Tramonti_da_una_panchina": {"page": "Tramonti_da_una_panchina.html", "name": "Tramonti da una panchina"},
}

POEM_INDEX_START = "<!-- POEM-INDEX-START -->"
POEM_INDEX_END = "<!-- POEM-INDEX-END -->"

TITLE_RE = re.compile(r"\\(?:addtoindex|poemtitle)\{(.*?)\}", re.DOTALL)
VERSE_RE = re.compile(r"\\begin\{verse\}(.*?)\\end\{verse\}", re.DOTALL)
MAKEBOX_RE = re.compile(r"(?:\\noindent\s*)?\\makebox\[[^\]]*\]\[s\]\{(.*?)\}", re.DOTALL)
NEWPAGE_RE = re.compile(r"\\newpage")
LINEBREAK_RE = re.compile(r"\\\\[!,'`]?")
SUSPICIOUS_LINE = re.compile(r"^[^\w]{1,2}$")


def strip_latex_comments(tex: str) -> str:
    """Rimuove i commenti LaTeX (%) che non sono preceduti da backslash."""
    out_lines = []
    for line in tex.split("\n"):
        out_lines.append(re.sub(r"(?<!\\)%.*", "", line))
    return "\n".join(out_lines)


def tex_inline_to_html(text: str) -> str:
    """Converte i comandi inline LaTeX in equivalenti HTML."""
    text = re.sub(r"\\textit\{(.*?)\}", r"<em>\1</em>", text, flags=re.DOTALL)
    text = re.sub(r"\\textbf\{(.*?)\}", r"<strong>\1</strong>", text, flags=re.DOTALL)
    text = re.sub(r"\\emph\{(.*?)\}", r"<em>\1</em>", text, flags=re.DOTALL)
    text = re.sub(
        r"\\hspace\{(-?[\d.]+(?:cm|mm|in|pt|em|ex))\}",
        r'<span style="display:inline-block;width:\1;"></span>',
        text,
    )
    text = text.replace("\\&", "&amp;").replace("\\%", "%").replace("\\_", "_")
    text = text.replace("---", "—").replace("--", "–")
    text = text.replace("``", "“").replace("''", "”")
    text = re.sub(r"(\w)'(\w)", r"\1’\2", text)
    text = re.sub(r"\\[,:;]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slugify(title: str, fallback_filename: str) -> str:
    """Genera uno slug pulito per l'URL basato sul titolo o sul nome file."""
    clean_title = title.lower().strip().replace("’", "'")
    for a, b in {"à": "a", "á": "a", "è": "e", "é": "e", "ì": "i", "í": "i", "ò": "o", "ó": "o", "ù": "u", "ú": "u"}.items():
        clean_title = clean_title.replace(a, b)
    slug = re.sub(r"[^a-z0-9]+", "-", clean_title).strip("-")
    
    if not slug or slug == "senza-titolo":
        # Usa il nome del file .tex come fallback per evitare duplicati
        slug = re.sub(r"[^a-z0-9]+", "-", fallback_filename.lower()).strip("-")
    return slug


def is_hfill_aside(block: str):
    stripped = block.strip()
    if not stripped.startswith("\\hfill"):
        return None
    rest = stripped[len("\\hfill"):].strip()
    m = re.fullmatch(r"\\textit\{(.*)\}", rest, flags=re.DOTALL)
    if m:
        return tex_inline_to_html(m.group(1)), True
    return tex_inline_to_html(rest), False


def split_body_line(raw_line: str):
    stripped = raw_line.strip()
    m = MAKEBOX_RE.fullmatch(stripped)
    if m:
        return {"type": "stretch", "html": tex_inline_to_html(m.group(1))}
    if "\\hfill" not in raw_line:
        return {"type": "text", "html": tex_inline_to_html(raw_line)}
    idx = raw_line.index("\\hfill")
    left = raw_line[:idx]
    right = raw_line[idx + len("\\hfill"):]
    left_html = tex_inline_to_html(left)
    right_html = tex_inline_to_html(right)
    if left_html:
        return {"type": "split", "left": left_html, "right": right_html}
    return {"type": "text", "html": right_html}


def build_body_stanzas(body_blocks, warnings):
    stanzas = [[]]
    for block in body_blocks:
        whole_line_right = is_hfill_aside(block)
        if whole_line_right is not None:
            text, italic = whole_line_right
            stanzas[-1].append({"type": "right", "html": text, "italic": italic})
            continue

        chunks = re.split(r"\n[ \t]*\n", block.strip())
        for i, chunk in enumerate(chunks):
            if i > 0:
                stanzas.append([])
            raw_lines = LINEBREAK_RE.split(chunk)
            for raw_line in raw_lines:
                if raw_line.strip() == "":
                    continue
                line = split_body_line(raw_line)
                text_to_check = line.get("html") or (line.get("left", "") + line.get("right", ""))
                if SUSPICIOUS_LINE.match(text_to_check):
                    warnings.append(f'Riga sospetta: "{text_to_check}"')
                    continue
                stanzas[-1].append(line)
    return [s for s in stanzas if s]


def parse_poem(tex: str, filename: str):
    tex = strip_latex_comments(tex)
    warnings = []

    if NEWPAGE_RE.search(tex):
        tex = NEWPAGE_RE.split(tex, maxsplit=1)[0]
        warnings.append("Trovato \\newpage: usata solo la prima parte del file.")

    title_match = TITLE_RE.search(tex)
    if title_match:
        title = tex_inline_to_html(title_match.group(1))
    else:
        # Pulisce il nome del file per usarlo come titolo di fallback (es. "01_titolo.tex" -> "Titolo")
        clean_name = re.sub(r"^\d+[-_]?", "", Path(filename).stem).replace("_", " ").title()
        title = clean_name or "Senza titolo"
        warnings.append(f"Nessun \\poemtitle trovato, titolo derivato dal file: '{title}'")

    blocks = VERSE_RE.findall(tex)
    asides = [is_hfill_aside(b) for b in blocks]

    start = 0
    epigraph = []
    while start < len(blocks) and asides[start] is not None:
        epigraph.append(asides[start])
        start += 1

    end = len(blocks)
    coda = []
    while end > start and asides[end - 1] is not None:
        coda.append(asides[end - 1])
        end -= 1
    coda.reverse()

    body_blocks = blocks[start:end]
    stanzas = build_body_stanzas(body_blocks, warnings)

    return {
        "title": title,
        "epigraph": epigraph,
        "coda": coda,
        "stanzas": stanzas,
        "warnings": warnings,
    }


# Template HTML
POEM_TEMPLATE = """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — Davide Luchi</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400;1,9..144,500&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="style.css">
</head>
<body>

    <input type="checkbox" id="nav-toggle" class="nav-toggle-checkbox">
    <label for="nav-toggle" class="nav-toggle-label" aria-label="Apri il menu"><span></span></label>

    <nav class="sidebar">
        <div>
            <a href="index.html" class="sidebar-brand">Davide Luchi</a>
            <ul class="sidebar-nav">
                <li><a href="index.html">Home</a></li>
                <li class="sidebar-section-label">Raccolte</li>
                <li><a href="Autopsie.html"{autopsie_active}>Autopsie</a></li>
                <li><a href="Diario_di_notte.html"{diario_active}>Diario di notte</a></li>
                <li><a href="Tramonti_da_una_panchina.html"{tramonti_active}>Tramonti da una panchina</a></li>
            </ul>
        </div>
        <div class="sidebar-bottom">
            <span>© 2026</span>
        </div>
    </nav>

    <main class="content">
        <div class="content-inner">

            <a href="{collection_page}" class="back-link">← Torna a {collection_name}</a>

            <h1 class="page-title">{title}</h1>
{epigraph_html}
            <div class="poesia-content">
{body_html}
            </div>
{coda_html}
        </div>
    </main>

</body>
</html>
"""


def render_aside(items, css_class):
    if not items:
        return ""
    lines = []
    for text, italic in items:
        tag_open, tag_close = ("<em>", "</em>") if italic else ("", "")
        lines.append(f"                <p>{tag_open}{text}{tag_close}</p>")
    inner = "\n".join(lines)
    return f'            <div class="{css_class}">\n{inner}\n            </div>\n'


def render_body(stanzas):
    paragraphs = []
    for stanza in stanzas:
        group = []

        def flush():
            if group:
                paragraphs.append(
                    "                <p>" + "<br>\n                    ".join(group) + "</p>"
                )
                group.clear()

        for line in stanza:
            if line["type"] == "stretch":
                flush()
                paragraphs.append(f'                <p class="stretch-line">{line["html"]}</p>')
            elif line["type"] == "right":
                flush()
                inner = f'<em>{line["html"]}</em>' if line.get("italic") else line["html"]
                paragraphs.append(f'                <p class="line-right">{inner}</p>')
            elif line["type"] == "split":
                group.append(
                    f'<span class="line-split"><span>{line["left"]}</span>'
                    f'<span>{line["right"]}</span></span>'
                )
            else:
                group.append(line["html"])
        flush()
    return "\n".join(paragraphs)


def build_poem_page(poem, collection_folder, collection_page, collection_name):
    active = {"Autopsie": "", "Diario_di_notte": "", "Tramonti_da_una_panchina": ""}
    active[collection_folder] = ' class="active"'

    return POEM_TEMPLATE.format(
        title=poem["title"],
        epigraph_html=render_aside(poem["epigraph"], "epigraph"),
        body_html=render_body(poem["stanzas"]),
        coda_html=render_aside(poem["coda"], "coda"),
        collection_page=collection_page,
        collection_name=collection_name,
        autopsie_active=active["Autopsie"],
        diario_active=active["Diario_di_notte"],
        tramonti_active=active["Tramonti_da_una_panchina"],
    )


def build_index_block(poems):
    if not poems:
        return '<ul class="poem-index">\n                    <!-- nessuna poesia trovata -->\n                </ul>'
    items = "\n".join(f'                    <li><a href="{slug}">{p["title"]}</a></li>' for p, slug in poems)
    return f'<ul class="poem-index">\n{items}\n                </ul>'


def update_collection_page(path: Path, poems):
    if not path.exists():
        print(f"  ! {path.name} non trovato, salto l'aggiornamento dell'indice.")
        return
    html = path.read_text(encoding="utf-8")
    if POEM_INDEX_START not in html or POEM_INDEX_END not in html:
        print(f"  ! {path.name} non contiene i marcatori {POEM_INDEX_START} / {POEM_INDEX_END}.")
        return
    pattern = re.compile(re.escape(POEM_INDEX_START) + r".*?" + re.escape(POEM_INDEX_END), re.DOTALL)
    replacement = f"{POEM_INDEX_START}\n                {build_index_block(poems)}\n                {POEM_INDEX_END}"
    path.write_text(pattern.sub(replacement, html), encoding="utf-8")
    print(f"  ✓ Indice aggiornato in {path.name}")


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    used_slugs = set()

    for folder_name, meta in COLLECTIONS.items():
        tex_dir = root / folder_name
        if not tex_dir.is_dir():
            continue

        print(f"\n📁 Cartella: {folder_name}/")
        tex_files = sorted(tex_dir.glob("*.tex"))
        if not tex_files:
            print("  (nessun file .tex trovato)")
            continue

        collection_page = meta["page"]
        collection_name = meta["name"]
        poems_for_index = []

        for tex_file in tex_files:
            poem = parse_poem(tex_file.read_text(encoding="utf-8"), tex_file.name)
            base_slug = slugify(poem["title"], tex_file.stem)
            
            # Gestione duplicati di slug
            slug = base_slug
            counter = 1
            while slug in used_slugs:
                slug = f"{base_slug}-{counter}"
                counter += 1
            used_slugs.add(slug)

            out_name = f"poesia-{slug}.html"

            html = build_poem_page(poem, folder_name, collection_page, collection_name)
            (root / out_name).write_text(html, encoding="utf-8")
            poems_for_index.append((poem, out_name))
            print(f"  ✓ {tex_file.name} ➔ {out_name} (\"{poem['title']}\")")
            for w in poem["warnings"]:
                print(f"     ⚠ {w}")

        update_collection_page(root / collection_page, poems_for_index)

    print("\n✅ Generazione completata con successo.")


if __name__ == "__main__":
    main()
