#!/usr/bin/env python3
"""
build_poems.py — genera le pagine HTML delle poesie a partire dai file .tex
e ricostruisce l'indice e il menu laterale di ogni raccolta.

USO:
    python3 build_poems.py            # lanciato dalla root del repository
    python3 build_poems.py /percorso  # oppure specificando la root a mano

STRUTTURA ATTESA (quella attuale della repo):

    <CartellaRaccolta>/
        Testi/
            Difetti.tex
            Certezza.tex
            ...
        Pagine_web/
            (qui lo script scrive Difetti.html, Certezza.html, ...)
        <PaginaRaccolta>.html      <- es. Autopsie.html
    index.html
    style.css
    build_poems.py

Il nome del file .html generato per ogni poesia è IDENTICO al nome del
file .tex, solo con estensione diversa: "Difetti.tex" -> "Difetti.html",
scritto dentro Pagine_web/. Nessuno slug, nessuna rinumerazione: il nome
che dai al .tex è il nome che avrà la pagina web.

Per aggiungere una raccolta nuova basta aggiungerla al dizionario
COLLECTIONS qui sotto (nome cartella, nome del file html della raccolta,
nome leggibile da mostrare nel menu): lo script si occupa da solo di:

  - generare/aggiornare la pagina di ogni poesia trovata in Testi/
  - ricostruire l'indice delle poesie nella pagina della raccolta
    (dentro i marcatori <!-- POEM-INDEX-START --> ... POEM-INDEX-END -->,
    che devono già esistere nel file: se mancano lo script avvisa e non
    tocca l'indice)
  - ricostruire IL MENU LATERALE (sidebar-nav), IDENTICO su index.html,
    su tutte le pagine di raccolta e su tutte le pagine di poesia, con i
    percorsi relativi corretti in base a quanto la pagina è "in profondità"
    rispetto alla root del sito (0 per index.html, 1 per una pagina di
    raccolta, 2 per una pagina di poesia dentro Pagine_web/)
  - correggere anche il link del logo ("Davide Luchi" in alto nella
    sidebar), il link del foglio di stile e il link "torna alla home",
    sempre in base alla profondità della pagina

Cose che lo script NON tocca (contenuto scritto a mano):
  - il testo dentro <section class="hero"> e la lista "Le raccolte" di
    index.html
  - il paragrafo <p class="intro"> di ogni pagina di raccolta
  - qualsiasi altro contenuto fuori dai blocchi sopra elencati

Se vuoi un ordine specifico delle poesie diverso dall'ordine alfabetico
dei file, la via più semplice è anteporre un numero al nome del file
(es. "01_Ispirazione.tex", "02_Inchiostro.tex", ...): lo script le
elenca nell'ordine dei nomi dei file, ma il file .html generato mantiene
comunque lo stesso nome del .tex (quindi "01_Ispirazione.tex" ->
"01_Ispirazione.html" — se non vuoi il numero anche nell'URL, non usare
questa scorciatoia e gestisci l'ordine a mano nell'indice).

COSA RICONOSCE NEI .tex
------------------------
- \\addtoindex{Titolo}  oppure  \\poemtitle{Titolo}   -> titolo della poesia
- \\begin{verse} ... \\end{verse}                     -> un blocco di versi.
  Più blocchi consecutivi, separati solo da \\vspace{...} (senza riga vuota),
  vengono uniti nella stessa strofa. Una riga vuota VERA dentro un blocco
  genera invece una nuova strofa.
- \\\\   (o  \\\\!)                                    -> a capo dentro una strofa.
- Un blocco che INIZIA con \\hfill (da solo) viene trattato come "a parte":
  se è tra i primi blocchi della poesia è un'epigrafe, se è tra gli ultimi
  è una chiusa.
- \\hfill IN MEZZO a una riga -> riga divisa in due metà sulla stessa riga.
- \\textit{...}, \\textbf{...}, \\emph{...}           -> <em>, <strong>
- -- / ---, `` / '', apostrofi tra lettere            -> tipografia corretta

Se un file .tex usa costrutti che lo script non conosce, avvisa in console
invece di indovinare.
"""

import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent

# Chiave = nome della cartella della raccolta nel repo.
# "page"  = nome del file html della raccolta, dentro quella cartella.
# "nome"  = nome leggibile, usato nel menu laterale e nei "torna a".
COLLECTIONS = {
    "Autopsie_cartella": {
        "page": "Autopsie.html",
        "nome": "Autopsie",
    },
    "Diario_di_notte_cartella": {
        "page": "Diario_di_notte.html",
        "nome": "Diario di notte",
    },
    "Tramonti_da_una_panchina": {
        "page": "Tramonti_da_una_panchina.html",
        "nome": "Tramonti da una panchina",
    },
}

TESTI_DIRNAME = "Testi"
WEB_DIRNAME = "Pagine_web"

POEM_INDEX_START = "<!-- POEM-INDEX-START -->"
POEM_INDEX_END = "<!-- POEM-INDEX-END -->"

TITLE_RE = re.compile(r"\\(?:addtoindex|poemtitle)\{(.*?)\}", re.DOTALL)
VERSE_RE = re.compile(r"\\begin\{verse\}(.*?)\\end\{verse\}", re.DOTALL)
MAKEBOX_RE = re.compile(r"(?:\\noindent\s*)?\\makebox\[[^\]]*\]\[s\]\{(.*?)\}", re.DOTALL)
NEWPAGE_RE = re.compile(r"\\newpage")
# a capo: \\ seguito facoltativamente da un comando di spazio negativo (!,`,')
LINEBREAK_RE = re.compile(r"\\\\[!,'`]?")
SUSPICIOUS_LINE = re.compile(r"^[^\w]{1,2}$")

# regex per correggere in automatico le pagine statiche esistenti
NAV_BLOCK_RE = re.compile(r'<ul class="sidebar-nav">.*?</ul>', re.DOTALL)
BRAND_LINK_RE = re.compile(r'<a href="[^"]*" class="sidebar-brand">')
BACK_LINK_RE = re.compile(r'<a href="[^"]*" class="back-link">.*?</a>')
STYLE_LINK_RE = re.compile(r'<link rel="stylesheet" href="[^"]*">')


# ---------- utilità di testo (identiche a prima) ----------

def strip_latex_comments(tex: str) -> str:
    out_lines = []
    for line in tex.split("\n"):
        out_lines.append(re.sub(r"(?<!\\)%.*", "", line))
    return "\n".join(out_lines)


def tex_inline_to_html(text: str) -> str:
    text = re.sub(r"\\textit\{(.*?)\}", r"<em>\1</em>", text, flags=re.DOTALL)
    text = re.sub(r"\\textbf\{(.*?)\}", r"<strong>\1</strong>", text, flags=re.DOTALL)
    text = re.sub(r"\\emph\{(.*?)\}", r"<em>\1</em>", text, flags=re.DOTALL)
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
    text = re.sub(r"\\[,:;]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------- parsing (identico a prima) ----------

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


# ---------- menu laterale, comune a tutte le pagine ----------

def sidebar_nav_html(depth, active_cf=None):
    """depth = quante cartelle separano la pagina dalla root (0 = index.html,
    1 = pagina di raccolta, 2 = pagina di poesia). active_cf = chiave della
    raccolta "attiva" da evidenziare, None se siamo sulla home."""
    up = "../" * depth
    home_href = f"{up}index.html" if depth else "index.html"
    home_active = ' class="active"' if active_cf is None else ""
    lines = [
        '<ul class="sidebar-nav">',
        f'                <li><a href="{home_href}"{home_active}>Home</a></li>',
        '                <li class="sidebar-section-label">Raccolte</li>',
    ]
    for cf, info in COLLECTIONS.items():
        href = f"{up}{cf}/{info['page']}"
        active = ' class="active"' if cf == active_cf else ""
        lines.append(f'                <li><a href="{href}"{active}>{info["nome"]}</a></li>')
    lines.append("            </ul>")
    return "\n".join(lines)


# ---------- rendering pagina poesia ----------

POEM_TEMPLATE = """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — Davide Luchi</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400;1,9..144,500&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{style_href}">
</head>
<body>

    <input type="checkbox" id="nav-toggle" class="nav-toggle-checkbox">
    <label for="nav-toggle" class="nav-toggle-label" aria-label="Apri il menu"><span></span></label>

    <nav class="sidebar">
        <div>
            <a href="{home_href}" class="sidebar-brand">Davide Luchi</a>
            {nav_block}
        </div>
        <div class="sidebar-bottom">
            <span>© 2026</span>
        </div>
    </nav>

    <main class="content">
        <div class="content-inner">

            <a href="{collection_href}" class="back-link">← Torna a {collection_name}</a>

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


def build_poem_page(poem, cf_key):
    depth = 2  # <Raccolta>/Pagine_web/Poesia.html
    up = "../" * depth
    info = COLLECTIONS[cf_key]
    return POEM_TEMPLATE.format(
        title=poem["title"],
        style_href=f"{up}style.css",
        home_href=f"{up}index.html",
        nav_block=sidebar_nav_html(depth, active_cf=cf_key),
        collection_href=f"../{info['page']}",
        collection_name=info["nome"],
        epigraph_html=render_aside(poem["epigraph"], "epigraph"),
        body_html=render_body(poem["stanzas"]),
        coda_html=render_aside(poem["coda"], "coda"),
    )


def build_poem_index_block(poems):
    if not poems:
        return '<ul class="poem-index">\n                    <!-- nessuna poesia trovata -->\n                </ul>'
    items = []
    for poem, filename in poems:
        href = f"{WEB_DIRNAME}/{quote(filename)}"
        items.append(f'                    <li><a href="{href}">{poem["title"]}</a></li>')
    return '<ul class="poem-index">\n' + "\n".join(items) + '\n                </ul>'


# ---------- correzione delle pagine statiche esistenti ----------

def patch_static_page(path: Path, depth: int, active_cf=None, has_back_link=False):
    """Aggiorna menu laterale, link del logo, foglio di stile e (se presente)
    il link 'torna alla home', in una pagina html già esistente scritta a mano
    (index.html o la pagina di una raccolta). Ritorna il testo aggiornato, o
    None se il file non esiste."""
    if not path.exists():
        print(f"  ! {path} non trovato, salto.")
        return None
    html = path.read_text(encoding="utf-8")

    up = "../" * depth
    home_href = f"{up}index.html" if depth else "index.html"
    style_href = f"{up}style.css" if depth else "style.css"

    if NAV_BLOCK_RE.search(html):
        html = NAV_BLOCK_RE.sub(sidebar_nav_html(depth, active_cf), html, count=1)
    else:
        print(f'  ! {path.name}: non trovo <ul class="sidebar-nav">, menu non aggiornato.')

    if BRAND_LINK_RE.search(html):
        html = BRAND_LINK_RE.sub(f'<a href="{home_href}" class="sidebar-brand">', html, count=1)

    if STYLE_LINK_RE.search(html):
        html = STYLE_LINK_RE.sub(f'<link rel="stylesheet" href="{style_href}">', html, count=1)

    if has_back_link:
        if BACK_LINK_RE.search(html):
            html = BACK_LINK_RE.sub(
                f'<a href="{home_href}" class="back-link">← Torna alla home</a>', html, count=1
            )
        else:
            print(f"  ! {path.name}: non trovo il back-link, controllalo a mano.")

    return html


# ---------- main ----------

def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT

    for cf_key, info in COLLECTIONS.items():
        tex_dir = root / cf_key / TESTI_DIRNAME
        web_dir = root / cf_key / WEB_DIRNAME

        print(f"\n{cf_key}/")
        if not tex_dir.is_dir():
            print(f"  ! {TESTI_DIRNAME}/ non trovata, salto questa raccolta.")
            continue
        web_dir.mkdir(parents=True, exist_ok=True)

        tex_files = sorted(tex_dir.glob("*.tex"))
        if not tex_files:
            print("  (nessun file .tex trovato)")
            continue

        expected_filenames = set()
        poems_for_index = []
        for tex_file in tex_files:
            poem = parse_poem(tex_file.read_text(encoding="utf-8"))
            filename = tex_file.stem + ".html"
            expected_filenames.add(filename)

            html = build_poem_page(poem, cf_key)
            (web_dir / filename).write_text(html, encoding="utf-8")
            poems_for_index.append((poem, filename))
            print(f"  ✓ {TESTI_DIRNAME}/{tex_file.name} -> {WEB_DIRNAME}/{filename}  (\"{poem['title']}\")")
            for w in poem["warnings"]:
                print(f"      ⚠ {w}")

        # pagine orfane in Pagine_web/ (es. placeholder o poesie rimosse/rinominate)
        for existing in sorted(web_dir.glob("*.html")):
            if existing.name not in expected_filenames:
                print(f"  ⚠ {WEB_DIRNAME}/{existing.name} non corrisponde a nessun .tex attuale: "
                      f"controlla se è un file vecchio/placeholder da eliminare.")

        # aggiorna la pagina della raccolta: menu + indice poesie
        collection_path = root / cf_key / info["page"]
        html = patch_static_page(collection_path, depth=1, active_cf=cf_key, has_back_link=True)
        if html is not None:
            if POEM_INDEX_START in html and POEM_INDEX_END in html:
                pattern = re.compile(re.escape(POEM_INDEX_START) + r".*?" + re.escape(POEM_INDEX_END), re.DOTALL)
                block = build_poem_index_block(poems_for_index)
                replacement = f"{POEM_INDEX_START}\n                {block}\n                {POEM_INDEX_END}"
                html = pattern.sub(replacement, html)
                index_note = " + indice"
            else:
                print(f"  ! {info['page']} non ha i marcatori {POEM_INDEX_START} / {POEM_INDEX_END}: "
                      f"aggiungili nel punto in cui vuoi l'elenco delle poesie, per generarlo in automatico.")
                index_note = ""
            collection_path.write_text(html, encoding="utf-8")
            print(f"  ✓ {info['page']} aggiornata (menu{index_note})")

    # index.html: solo il menu laterale viene toccato
    index_path = root / "index.html"
    html = patch_static_page(index_path, depth=0, active_cf=None, has_back_link=False)
    if html is not None:
        index_path.write_text(html, encoding="utf-8")
        print(f"\n✓ index.html: menu aggiornato")

    print("\nFatto.")


if __name__ == "__main__":
    main()
