# Henting av Språkrådet-stoff til kunnskapsbasen

## Innhold

| Fil | Hva |
|---|---|
| `hent_sprakradet.py` | Henter ~25 regelsider og ordlister fra sprakradet.no → `kunnskapsbase/sprakradet/*.md` |
| `hent_ordbok.py` | Laster ned Bokmålsordboka/Nynorskordboka (åpne data) og lager lesbar tekst → `kunnskapsbase/ordbok/bm/*.md` |
| `kunnskapsbase/sprakradet/kommaregler.md` | Ferdig eksempel på målformatet (hentet og renset manuelt) |

## Kjøring

```bash
pip install requests beautifulsoup4 markdownify

# 1. Regelsider – start med test
python hent_sprakradet.py --bare-test
python hent_sprakradet.py

# 2. Ordbok – lag først en ordliste (ett ord per linje), f.eks. fra
#    bildetema-ordene eller en frekvensliste, så:
python hent_ordbok.py --dict bm --ordliste mine_ord.txt
# eller bare de 3000 første alfabetisk for å teste formatet:
python hent_ordbok.py --dict bm --maks 3000
```

## Hva du bør sjekke etterpå

1. **Tabeller** i ordlistene («Ord og uttrykk som ofte forveksles», administrativ ordliste) –
   markdownify kan miste kolonner. Åpne filene og se at ord · betydning · eksempel henger sammen.
2. **wp-json**: Loggen `_hentelogg.json` viser om sidene kom via `wp-json` eller `html`.
   Kom alt via `html`, er REST-API-et stengt – det er greit, HTML-fallback fungerer.
3. **Ordbokformat**: Slå opp 5–10 ord på ordbokene.no og sammenlign med det skriptet
   skrev. JSON-strukturen er udokumentert; rendereren er skrevet defensivt.
4. **Størrelse**: Ikke last opp hele ordboka. 3 000–5 000 ord er nok for A1–B2.

## Lisens og kreditering

- **sprakradet.no**: gjengitt med tillatelse fra Språkrådet. Hver fil har kilde og URL i toppen.
- **Ordbøkene**: CC BY 4.0 (UiB og Språkrådet). Skriv i botens infotekst:
  «Ordboksdata fra Bokmålsordboka (Universitetet i Bergen og Språkrådet), CC BY 4.0.»
