#!/usr/bin/env python3
"""
Laster ned åpne data fra Bokmålsordboka/Nynorskordboka (ord.uib.no, CC BY 4.0)
og skriver et utvalg artikler om til lesbar tekst som passer i en RAG-kunnskapsbase.

Bruk:
    pip install requests
    python hent_ordbok.py --dict bm --ordliste mine_ord.txt      # ett ord per linje
    python hent_ordbok.py --dict bm --maks 3000                  # første 3000 lemma (alfabetisk)
    python hent_ordbok.py --dict bm --bare-last-ned              # bare last ned råfilene

Utdata:
    data/ordbok/<dict>/article.json.gz, lemma_expanded.json, concepts.json (råfiler)
    kunnskapsbase/ordbok/<dict>/<bokstav>.md   (én fil per forbokstav, ~50–200 ord per fil)

Kreditering (påkrevd av CC BY 4.0):
    «Ordboksdata fra Bokmålsordboka / Nynorskordboka (Universitetet i Bergen og
    Språkrådet), lisens CC BY 4.0, hentet fra ord.uib.no.»

NB: JSON-strukturen i artiklene er ikke offisielt dokumentert. Rendereren under
er skrevet defensivt og faller tilbake til ren tekst hvis noe er ukjent.
Sjekk alltid noen ferdige filer mot ordbokene.no før du laster dem inn.
"""

import argparse
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

import requests

BASE = "https://ord.uib.no"
RÅ = Path("data/ordbok")
UT = Path("kunnskapsbase/ordbok")

ORDKLASSE_NO = {
    "NOUN": "substantiv", "VERB": "verb", "ADJ": "adjektiv", "ADV": "adverb",
    "PRON": "pronomen", "DET": "determinativ", "ADP": "preposisjon",
    "CCONJ": "konjunksjon", "SCONJ": "subjunksjon", "INTJ": "interjeksjon",
    "NUM": "tallord", "PROPN": "egennavn", "SYM": "symbol", "X": "annet",
    "ABBR": "forkortelse", "EXPR": "uttrykk", "PFX": "prefiks",
    "COMPPFX": "sammensetningsledd",
}
KJØNN = {"Masc": "hankjønn", "Fem": "hunkjønn", "Neuter": "intetkjønn"}


# ---------- nedlasting ----------

def last_ned(dict_: str):
    mappe = RÅ / dict_
    mappe.mkdir(parents=True, exist_ok=True)
    for fil in ["article.json.gz", "lemma_expanded.json", "concepts.json"]:
        mål = mappe / fil
        if mål.exists():
            print(f"  {fil} finnes fra før")
            continue
        url = f"{BASE}/{dict_}/fil/{fil}" if fil != "concepts.json" else f"{BASE}/{dict_}/concepts.json"
        print(f"  laster ned {url}")
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(mål, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    return mappe


def les_artikler(mappe: Path):
    with gzip.open(mappe / "article.json.gz", "rt", encoding="utf-8") as f:
        data = json.load(f)
    # Filen kan være en liste av artikler eller et objekt {id: artikkel}
    if isinstance(data, dict):
        data = list(data.values())
    return {a.get("article_id") or a.get("id"): a for a in data}


def les_konsepter(mappe: Path):
    try:
        d = json.loads((mappe / "concepts.json").read_text(encoding="utf-8"))
        # forventet {"concepts": {id: {"expansion": "..."}}} eller {id: {...}}
        d = d.get("concepts", d)
        return {k: (v.get("expansion") if isinstance(v, dict) else str(v)) for k, v in d.items()}
    except Exception:
        return {}


# ---------- rendering ----------

def gjengi_innhold(node, konsepter) -> str:
    """Setter inn 'items' der det står $ i 'content'. Tåler ukjente typer."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(gjengi_innhold(n, konsepter) for n in node).strip()
    if not isinstance(node, dict):
        return str(node)

    t = node.get("type_", "")
    if t == "usage":
        return node.get("text", "")
    if t == "article_ref":
        return ", ".join(l.get("lemma", "") for l in node.get("lemmas", []))
    if t in ("entity", "relation", "domain", "grammar", "language", "rhetoric", "temporal"):
        return konsepter.get(node.get("id", ""), node.get("id", ""))
    if t == "fraction":
        return node.get("text", "")

    content = node.get("content")
    items = node.get("items", [])
    if content is not None:
        deler = content.split("$")
        ut = deler[0]
        for i, item in enumerate(items):
            ut += gjengi_innhold(item, konsepter)
            if i + 1 < len(deler):
                ut += deler[i + 1]
        return ut
    if "quote" in node:
        return gjengi_innhold(node["quote"], konsepter)
    if "text" in node:
        return node["text"]
    return ""


def gjengi_definisjoner(elementer, konsepter, nivå=1):
    """Returnerer liste av (forklaringer, eksempler) per betydning."""
    ut = []
    for el in elementer or []:
        t = el.get("type_", "")
        if t == "definition":
            forkl, eks, under = [], [], []
            for sub in el.get("elements", []):
                st = sub.get("type_", "")
                if st == "explanation":
                    forkl.append(gjengi_innhold(sub, konsepter))
                elif st == "example":
                    eks.append(gjengi_innhold(sub, konsepter))
                elif st == "definition":
                    under.extend(gjengi_definisjoner([sub], konsepter, nivå + 1))
            ut.append((forkl, eks))
            ut.extend(under)
        elif t == "explanation":
            ut.append(([gjengi_innhold(el, konsepter)], []))
        elif t == "example":
            ut.append(([], [gjengi_innhold(el, konsepter)]))
    return ut


def bøying(lemma_obj):
    """Henter bøyingsformer fra paradigm_info hvis de finnes i artikkelen."""
    former = []
    for p in lemma_obj.get("paradigm_info", []) or []:
        rad = []
        for inf in p.get("inflection", []) or []:
            w = inf.get("word_form")
            if w and w not in rad:
                rad.append(w)
        if rad:
            former.append(", ".join(rad))
    return former


def kjønn_fra_tags(lemma_obj):
    for p in lemma_obj.get("paradigm_info", []) or []:
        for tag in p.get("tags", []) or []:
            if tag in KJØNN:
                return KJØNN[tag]
            if tag == "Masc/Fem":
                return "hankjønn/hunkjønn"
    return ""


def ordklasse_fra_lemma(lemma_obj):
    """Finn ordklassen både i eldre og i dagens datastruktur."""
    kode = lemma_obj.get("word_class", "")
    if not kode:
        for p in lemma_obj.get("paradigm_info", []) or []:
            kode = next((tag for tag in p.get("tags", []) or [] if tag in ORDKLASSE_NO), "")
            if kode:
                break
    return ORDKLASSE_NO.get(kode, kode).lower()


def gjengi_artikkel(art, konsepter, dict_):
    lemmas = art.get("lemmas", []) or []
    if not lemmas:
        return None
    hoved = lemmas[0]
    ordklasse = ordklasse_fra_lemma(hoved)
    ord_ = hoved.get("lemma", "")
    alle_former = "/".join(dict.fromkeys(l.get("lemma", "") for l in lemmas))
    linjer = [f"### {alle_former}"]
    info = ordklasse
    k = kjønn_fra_tags(hoved)
    if k:
        info += f", {k}"
    linjer.append(f"Ordklasse: {info}")
    b = bøying(hoved)
    if b:
        linjer.append("Bøying: " + " | ".join(b))

    betydninger = gjengi_definisjoner(art.get("body", {}).get("definitions", []), konsepter)
    n = 0
    for forkl, eks in betydninger:
        forkl = [f.strip() for f in forkl if f.strip()]
        eks = [e.strip() for e in eks if e.strip()]
        if forkl:
            n += 1
            linjer.append(f"Betydning {n}: " + "; ".join(forkl))
        if eks:
            linjer.append("Eksempel: " + " | ".join(eks[:4]))
    if n == 0 and not any(e for _, e in betydninger):
        # Ingen tolkbar struktur – legg ved kort råtekst så ordet ikke forsvinner
        rå = re.sub(r"\s+", " ", json.dumps(art.get("body", {}), ensure_ascii=False))[:300]
        linjer.append("Innhold (rå): " + rå)
    linjer.append(f"Kilde: https://ordbokene.no/nob/{dict_}/{art.get('article_id') or art.get('id')}")
    return "\n".join(linjer) + "\n"


# ---------- hoved ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dict", default="bm", choices=["bm", "nn"])
    ap.add_argument("--ordliste", help="fil med ett ord per linje; bare disse tas med")
    ap.add_argument("--maks", type=int, default=0, help="maks antall lemma (0 = alle i ordlista)")
    ap.add_argument("--bare-last-ned", action="store_true")
    args = ap.parse_args()

    print(f"Laster ned råfiler for {args.dict} ...")
    mappe = last_ned(args.dict)
    if args.bare_last_ned:
        return

    print("Leser artikler ...")
    artikler = les_artikler(mappe)
    konsepter = les_konsepter(mappe)
    print(f"  {len(artikler)} artikler, {len(konsepter)} konseptforklaringer")

    ønsket = None
    if args.ordliste:
        ønsket = {l.strip().lower() for l in Path(args.ordliste).read_text(encoding="utf-8").splitlines() if l.strip()}
        print(f"  filtrerer på {len(ønsket)} ord fra {args.ordliste}")

    per_bokstav = defaultdict(list)
    antall = 0
    for aid, art in sorted(artikler.items(), key=lambda kv: (kv[1].get("lemmas") or [{}])[0].get("lemma", "")):
        lemmas = art.get("lemmas") or []
        if not lemmas:
            continue
        ord_ = lemmas[0].get("lemma", "")
        if ønsket is not None and ord_.lower() not in ønsket:
            continue
        if ønsket is None and not ord_[:1].isalpha():
            continue
        tekst = gjengi_artikkel(art, konsepter, args.dict)
        if not tekst:
            continue
        per_bokstav[ord_[:1].lower() or "_"].append(tekst)
        antall += 1
        if args.maks and antall >= args.maks:
            break

    ut = UT / args.dict
    ut.mkdir(parents=True, exist_ok=True)
    for gammel_fil in ut.glob("*.md"):
        gammel_fil.unlink()
    navn = "Bokmålsordboka" if args.dict == "bm" else "Nynorskordboka"
    topp = (
        f"---\nkilde: {navn} (Universitetet i Bergen og Språkrådet)\n"
        f"lisens: CC BY 4.0\nhentet_fra: https://ord.uib.no\n---\n\n"
        f"# {navn} – utvalg\n\n"
    )
    for bokstav, tekster in sorted(per_bokstav.items()):
        (ut / f"{bokstav}.md").write_text(topp + "\n".join(tekster), encoding="utf-8")
    print(f"Ferdig: {antall} ord i {len(per_bokstav)} filer under {ut}/")
    print("Kontroller 5–10 oppslag mot ordbokene.no før du laster opp.")


if __name__ == "__main__":
    main()
