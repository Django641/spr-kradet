#!/usr/bin/env python3
"""
Henter regelsider og ordlister fra sprakradet.no og lagrer dem som
RAG-klare markdown-filer (én fil per side, med metadata øverst).

Bruk:
    pip install requests beautifulsoup4 markdownify
    python hent_sprakradet.py                 # henter alle sider i SIDER
    python hent_sprakradet.py --bare-test     # henter bare de tre første

Strategi:
  1. Prøver WordPress REST-API (/wp-json/wp/v2/pages?slug=...), som gir ren
     innholds-HTML uten meny og bunntekst.
  2. Faller tilbake til vanlig HTML-henting og klipper ut hovedinnholdet.

Vær snill mot serveren: 1 sekund pause mellom hver side.
"""

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

BASE = "https://sprakradet.no"
UT = Path("kunnskapsbase/sprakradet")
HEADERS = {"User-Agent": "NAFO-kunnskapsbase (kontakt: post@nafo.oslomet.no)"}

# (kategori, url) – legg til/fjern etter behov
SIDER = [
    # Rettskriving og grammatikk
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/kommaregler/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/tall-tid-dato/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/stor-eller-liten-forbokstav/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/eitt-eller-fleire-ord/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/tegn/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/forkortelser/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/orddeling-ved-linjeskift/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/a-eller-og/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/da-eller-nar/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/de-eller-dem/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/adjektiver-og-partisipper/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/grammatiske-termar/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/mellomrom/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/punktlister/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/imperativ/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/s-verb/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/bindebokstaver-i-sammensatte-ord/"),
    ("rettskriving", "/godt-og-korrekt-sprak/rettskriving-og-grammatikk/preposisjonsbruk/"),
    # Ordlister
    ("ordlister", "/godt-og-korrekt-sprak/ordlister-og-ordboker/ord-og-uttrykk-som-ofte-forveksles/"),
    ("ordlister", "/godt-og-korrekt-sprak/ordlister-og-ordboker/pa-godt-norsk-avloserord/"),
    ("ordlister", "/godt-og-korrekt-sprak/praktisk-sprakbruk/nynorskhjelp/administrativ-ordliste-bokmal-nynorsk/"),
    ("ordlister", "/godt-og-korrekt-sprak/ordlister-og-ordboker/datatermar/"),
    ("ordlister", "/spraklova/ord-som-blir-brukte-i-spraklova/"),
    # Nynorskhjelp og praktisk språkbruk
    ("nynorsk", "/godt-og-korrekt-sprak/praktisk-sprakbruk/nynorskhjelp/"),
    ("praktisk", "/godt-og-korrekt-sprak/praktisk-sprakbruk/"),
    # Klarspråk (skriveråd)
    ("klarsprak", "/klarsprak/sprak-i-lover-og-forskrifter/skriverad/tegnsetting/komma/"),
]

STØY = [
    "nav", "header", "footer", "form", "script", "style", "noscript",
    ".breadcrumb", ".breadcrumbs", ".site-header", ".site-footer",
    ".feedback", ".tilbakemelding", ".related", ".relaterte-sider",
    ".wp-block-create-block-link-columns", ".link-columns",
]
STØY_OVERSKRIFTER = re.compile(
    r"^(Relaterte (?:sider|artikler)|Fra svarbasen|Fant du det du lette etter\?)", re.I
)


def slug_fra_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def hent_via_wpjson(slug: str):
    """Returnerer (tittel, html, endret) eller None hvis API ikke er åpent."""
    try:
        r = requests.get(
            f"{BASE}/wp-json/wp/v2/pages",
            params={"slug": slug, "_fields": "title,content,modified"},
            headers=HEADERS, timeout=20,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not data:
            return None
        p = data[0]
        return p["title"]["rendered"], p["content"]["rendered"], p.get("modified", "")[:10]
    except Exception:
        return None


def hent_via_html(url: str):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    tittel = soup.find("h1")
    tittel = tittel.get_text(strip=True) if tittel else slug_fra_url(url)
    meta = soup.find("meta", property="article:modified_time")
    endret = meta["content"][:10] if meta and meta.get("content") else ""
    main = soup.find("main") or soup.find(id="content-section") or soup.find("article") or soup.body
    return tittel, str(main), endret


def rens(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for sel in STØY:
        for el in soup.select(sel):
            el.decompose()
    # Fjern "Relaterte sider", "Fra svarbasen", "Fant du det du lette etter?" og alt etter
    for h in soup.find_all(["h2", "h3"]):
        if STØY_OVERSKRIFTER.match(h.get_text(strip=True)):
            for sib in list(h.find_next_siblings()):
                sib.decompose()
            h.decompose()
    tekst = md(str(soup), heading_style="ATX", bullets="-")
    # Rydd: fjern gjentatte tomme linjer, GA-lenkeparametre osv.
    tekst = re.sub(r"\?_gl=[^)\s]+", "", tekst)
    tekst = re.sub(r"\n{3,}", "\n\n", tekst)
    # Fjern H1 (den legges i metadata) og bindestrek-linjer
    tekst = re.sub(r"^# .*\n", "", tekst, count=1)
    tekst = re.sub(r"^\s*-{3,}\s*$", "", tekst, flags=re.M)
    return tekst.strip() + "\n"


def lagre(kategori: str, url: str, tittel: str, brødtekst: str, endret: str):
    UT.mkdir(parents=True, exist_ok=True)
    fil = UT / f"{slug_fra_url(url)}.md"
    front = (
        "---\n"
        f"tittel: {tittel}\n"
        "kilde: Språkrådet\n"
        f"url: {url}\n"
        f"sist_endret: {endret}\n"
        f"hentet: {dt.date.today().isoformat()}\n"
        f"kategori: {kategori}\n"
        "bruk: Gjengitt med tillatelse fra Språkrådet. Oppgi alltid kilde og lenke.\n"
        "---\n\n"
        f"# {tittel}\n\n"
    )
    fil.write_text(front + brødtekst, encoding="utf-8")
    return fil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bare-test", action="store_true")
    args = ap.parse_args()

    sider = SIDER[:3] if args.bare_test else SIDER
    logg = []
    for kategori, sti in sider:
        url = BASE + sti
        slug = slug_fra_url(url)
        print(f"Henter {slug} ...", end=" ", flush=True)
        try:
            res = hent_via_wpjson(slug)
            metode = "wp-json"
            if res is None:
                res = hent_via_html(url)
                metode = "html"
            tittel, html, endret = res
            fil = lagre(kategori, url, tittel, rens(html), endret)
            print(f"OK ({metode}) -> {fil}")
            logg.append({"url": url, "fil": str(fil), "metode": metode, "endret": endret})
        except Exception as e:
            print(f"FEIL: {e}")
            logg.append({"url": url, "feil": str(e)})
        time.sleep(1)

    (UT / "_hentelogg.json").write_text(json.dumps(logg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFerdig. {len([l for l in logg if 'fil' in l])} av {len(sider)} sider lagret i {UT}/")
    print("Sjekk et par filer manuelt – særlig tabeller i ordlistene.")


if __name__ == "__main__":
    sys.exit(main())
