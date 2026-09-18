#!/usr/bin/env python3
"""
build_poems.py — genera le pagine HTML delle poesie a partire dai file .tex
e ricostruisce l'indice di ciascuna raccolta.

USO:
    python3 build_poems.py

Struttura attesa, nella cartella da cui viene lanciato (la root del repo):

    Autopsie/
        01_qualcosa.tex
    Diario_di_notte/
        ...tex
    Tramonti_da_una_panchina/
        ...tex
    Autopsie.html
    Diario_di_notte.html
    Tramonti_da_una_panchina.html
    style.css

Per ogni raccolta genera una pagina poesia-<slug>.html per ogni .tex trovato,
e aggiorna il blocco <!-- POEM-INDEX-START --> ... <!-- POEM-INDEX-END -->
nella pagina della raccolta corrispondente.

COSA RICONOSCE NEI .tex
------------------------
- \\addtoindex{Titolo}  oppure  \\poemtitle{Titolo}   -> titolo della poesia
- \\begin{verse} ... \\end{verse}                     -> un blocco di versi.
  Più blocchi consecutivi, separati solo da \\vspace{...} (senza riga vuota),
  vengono uniti nella stessa strofa: si assume che l'autore li abbia spezzati
  solo per stringere lo spaziato tipografico, non per iniziare una strofa
  nuova. Una riga vuota VERA (dentro un blocco) genera invece una nuova strofa.
- \\\\   (o  \\\\!)                                    -> a capo dentro una strofa.
  "\\!" (spazio negativo) dopo un a capo viene trattato come parte del
  comando di a capo stesso, non come testo.
- Un blocco che INIZIA con \\hfill (da solo, tutto il blocco) viene trattato
  come "a parte": se è tra i primi blocchi della poesia è un'epigrafe
  (prima del titolo), se è tra gli ultimi è una chiusa (dopo il corpo).
  Se il testo dentro è avvolto in \\textit{...}, resta in corsivo;
  altrimenti resta testo normale, per rispettare quello che hai scritto tu.
- \\hfill IN MEZZO a una riga (non a inizio blocco) -> riga divisa in due
  metà, una a sinistra e una a destra, sulla stessa riga (come in "Autopsia").
- \\textit{...}, \\textbf{...}, \\emph{...}           -> <em>, <strong>
- -- / ---                                            -> – / —
- `` / ''                                             -> “ / ”
- apostrofi tra lettere                               -> apostrofo tipografico ’

Se un file .tex usa costrutti che questo script non conosce ancora, avvisa
in console invece di indovinare: meglio controllare a mano che rischiare
di alterare una poesia senza che tu te ne accorga.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

COLLECTIONS = {
    "Autopsie": "Autopsie.html",
    "Diario_di_notte": "Diario_di_notte.html",
    "Tramonti_da_una_panchina": "Tramonti_da_una_panchina.html",
}

POEM_INDEX_START = "<!-- POEM-INDEX-START -->"
POEM_INDEX_END = "<!-- POEM-INDEX-END -->"

TITLE_RE = re.compile(r"\\(?:addtoindex|poemtitle)\{(.*?)\}", re.DOTALL)
VERSE_RE = re.compile(r"\\begin\{verse\}(.*?)\\end\{verse\}", re.DOTALL)
MAKEBOX_RE = re.compile(r"(?:\\noindent\s*)?\\makebox\[[^\]]*\]\[s\]\{(.*?)\}", re.DOTALL)
NEWPAGE_RE = re.compile(r"\\newpage")
# a capo: \\ seguito facoltativamente da un comando di spazio negativo (!,`,')
LINEBREAK_RE = re.compile(r"\\\\[!,'`]?")
SUSPICIOUS_LINE = re.compile(r"^[^\w]{1,2}$")


def strip_latex_comments(tex: str) -> str:
    """Rimuove tutto ciò che segue un % non preceduto da backslash, riga per riga."""
    out_lines = []
    for line in tex.split("\n"):
        out_lines.append(re.sub(r"(?<!\\)%.*", "", line))
    return "\n".join(out_lines)


# ---------- utilità di testo ----------

def tex_inline_to_html(text: str) -> str:
    text = re.sub(r"\\textit\{(.*?)\}", r"<em>\1</em>", text, flags=re.DOTALL)
    text = re.sub(r"\\textbf\{(.*?)\}", r"<strong>\1</strong>", text, flags=re.DOTALL)
    text = re.sub(r"\\emph\{(.*?)\}", r"<em>\1</em>", text, flags=re.DOTALL)
    # \hspace{1.52cm} -> rientro equivalente (le unità cm/mm/pt/em funzionano anche in CSS)
    text = re.sub(
        r"\\hspace\{(-?[\d.]+(?:cm|mm|in|pt|em|ex))\}",
        r'<span style="display:inline-block;width:\1;"></span>',
        text,
    )
    text = text.replace("\\&", "&amp;")
    text = text.replace("\\%", "%")
    text = text.replace("\\_", "_")
    text = text.replace("---", "—")
    text = text.replace("--", "–")
    text = text.replace("``", "“").replace("''", "”")
    text = re.sub(r"(\w)'(\w)", r"\1’\2", text)
    text = re.sub(r"\\[,:;]", "", text)  # comandi di spaziatura residui
    text = re.sub(r"\s+", " ", text)     # collassa newline/indentazione interni
    return text.strip()


def slugify(title: str) -> str:
    title = title.lower().strip().replace("’", "'")
    for a, b in {"à": "a", "á": "a", "è": "e", "é": "e", "ì": "i", "í": "i",
                 "ò": "o", "ó": "o", "ù": "u", "ú": "u"}.items():
        title = title.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", title).strip("-") or "poesia"


# ---------- parsing ----------

def is_hfill_aside(block: str):
    """Se l'INTERO blocco è un \\hfill (da solo), restituisce (testo, corsivo)."""
    stripped = block.strip()
    if not stripped.startswith("\\hfill"):
        return None
    rest = stripped[len("\\hfill"):].strip()
    m = re.fullmatch(r"\\textit\{(.*)\}", rest, flags=re.DOTALL)
    if m:
        return tex_inline_to_html(m.group(1)), True
    return tex_inline_to_html(rest), False


def split_body_line(raw_line: str):
    """Riconosce \\makebox[...][s]{...} (riga distesa) e \\hfill a metà riga."""
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
    """Unisce i blocchi 'corpo' in strofe, rispettando solo le righe vuote vere."""
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
                    warnings.append(
                        f'riga sospetta: "{text_to_check}" — controlla il .tex, potrebbe essere un refuso'
                    )
                    continue
                stanzas[-1].append(line)
    return [s for s in stanzas if s]


def parse_poem(tex: str):
    tex = strip_latex_comments(tex)

    newpage_warning = None
    if NEWPAGE_RE.search(tex):
        tex = NEWPAGE_RE.split(tex, maxsplit=1)[0]
        newpage_warning = (
            "trovato \\newpage dentro il file: sembra che ci siano due versioni "
            "della stessa poesia nello stesso .tex. Ho usato solo la prima; "
            "cancella dal .tex quella che non ti serve e rilancia lo script."
        )

    title_match = TITLE_RE.search(tex)
    title = tex_inline_to_html(title_match.group(1)) if title_match else "Senza titolo"

    blocks = VERSE_RE.findall(tex)

    asides = [is_hfill_aside(b) for b in blocks]

    # epigrafe: blocchi hfill-only consecutivi dall'inizio
    start = 0
    epigraph = []
    while start < len(blocks) and asides[start] is not None:
        epigraph.append(asides[start])
        start += 1

    # chiusa: blocchi hfill-only consecutivi dalla fine (senza sovrapporsi all'epigrafe)
    end = len(blocks)
    coda = []
    while end > start and asides[end - 1] is not None:
        coda.append(asides[end - 1])
        end -= 1
    coda.reverse()

    body_blocks = blocks[start:end]

    warnings = []
    if newpage_warning:
        warnings.append(newpage_warning)
    stanzas = build_body_stanzas(body_blocks, warnings)

    return {
        "title": title,
        "epigraph": epigraph,
        "coda": coda,
        "stanzas": stanzas,
        "warnings": warnings,
    }


# ---------- rendering HTML ----------

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
        print(f"  ! {path.name} non ha i marcatori {POEM_INDEX_START} / {POEM_INDEX_END}.")
        return
    pattern = re.compile(re.escape(POEM_INDEX_START) + r".*?" + re.escape(POEM_INDEX_END), re.DOTALL)
    replacement = f"{POEM_INDEX_START}\n                {build_index_block(poems)}\n                {POEM_INDEX_END}"
    path.write_text(pattern.sub(replacement, html), encoding="utf-8")
    print(f"  ✓ indice aggiornato in {path.name}")


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT

    for folder_name, collection_page in COLLECTIONS.items():
        tex_dir = root / folder_name
        if not tex_dir.is_dir():
            continue

        print(f"\n{folder_name}/")
        tex_files = sorted(tex_dir.glob("*.tex"))
        if not tex_files:
            print("  (nessun file .tex trovato)")
            continue

        collection_name = collection_page.replace(".html", "").replace("_", " ")
        poems_for_index = []

        for tex_file in tex_files:
            poem = parse_poem(tex_file.read_text(encoding="utf-8"))
            slug = slugify(poem["title"])
            out_name = f"poesia-{slug}.html"

            html = build_poem_page(poem, folder_name, collection_page, collection_name)
            (root / out_name).write_text(html, encoding="utf-8")
            poems_for_index.append((poem, out_name))
            print(f"  ✓ {tex_file.name} -> {out_name}  (\"{poem['title']}\")")
            for w in poem["warnings"]:
                print(f"      ⚠ {w}")

        update_collection_page(root / collection_page, poems_for_index)

    print("\nFatto.")


if __name__ == "__main__":
    main()
