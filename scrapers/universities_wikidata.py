"""
YÖNTEM 4: Açık veri sorgusu (Wikidata SPARQL API) — Avrupa'daki üniversiteler
==========================================================================
Erasmus+ stajı bir şirkette olabileceği gibi bir ÜNİVERSİTEDE de (araştırma laboratuvarı,
bilgisayar bilimleri bölümü) yapılabilir. Üniversiteler staj ilanını iş sitelerinde nadiren
yayınlar; öğrenci doğrudan laboratuvara / uluslararası ofise e-posta yazar.

Bu modül Wikidata'nın herkese açık SPARQL sorgu servisinden seçilen ülkelerdeki üniversiteleri
(ad, şehir, tür, web sitesi) çeker. Panelde "Üniversiteler" sekmesinde listelenir ve LLM her
üniversite için bir "spekülatif staj başvurusu" e-posta taslağı yazar.

Neden Wikidata? Yapılandırılmış, açık lisanslı (CC0) ve programla sorgulanmak için tasarlanmış
bir veri kaynağı: scraping yerine bir sorgu dili (SPARQL) ile veri çekmeye örnek.
EURAXESS (AB araştırma ilanları) denendi ama robots.txt ilan sayfalarını ve parametreli
aramaları yasaklıyor, bu yüzden kullanılmadı.

Çalıştırma:  python -m scrapers.universities_wikidata
"""
from __future__ import annotations

import argparse

import pandas as pd
import requests

import config
from scrapers.common import country_tr

ENDPOINT = "https://query.wikidata.org/sparql"
# Wikidata ülke kimlikleri (ISO -> QID)
COUNTRY_QID = {
    "PL": "Q36", "CZ": "Q213", "HU": "Q28", "PT": "Q45", "ES": "Q29", "IT": "Q38", "DE": "Q183",
    "NL": "Q55", "LT": "Q37", "LV": "Q211", "EE": "Q191", "RO": "Q218", "SK": "Q214", "SI": "Q215",
    "HR": "Q224", "GR": "Q41", "AT": "Q40", "BE": "Q31", "FR": "Q142", "SE": "Q34", "FI": "Q33",
    "DK": "Q35", "IE": "Q27", "BG": "Q219", "CY": "Q229", "MT": "Q233", "LU": "Q32", "NO": "Q20",
    "IS": "Q189", "RS": "Q403", "MK": "Q221",
}
# Üniversite türleri: üniversite, devlet ün., özel ün., teknik ün., araştırma ün.
TYPES = "wd:Q3918 wd:Q875538 wd:Q902104 wd:Q1371037 wd:Q15936437"
TECH_WORDS = ("technolog", "technical", "polytechn", "politechn", "techni", "informat", "computer",
              "science", "engineering", "ai ", "akademia górniczo")

QUERY = """SELECT DISTINCT ?uni ?uniLabel ?cityLabel ?website ?typeLabel WHERE {{
  VALUES ?t {{ {types} }}
  ?uni wdt:P31 ?t; wdt:P17 wd:{qid}; wdt:P856 ?website.
  OPTIONAL {{ ?uni wdt:P131 ?city. }}
  BIND(?t AS ?type)
  FILTER NOT EXISTS {{ ?uni wdt:P576 ?dissolved. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,{lang}". }}
}}"""


def parse_bindings(data: dict, iso: str) -> list[dict]:
    rows = {}
    for b in data.get("results", {}).get("bindings", []):
        uid = b["uni"]["value"].rsplit("/", 1)[-1]
        name = b.get("uniLabel", {}).get("value", "")
        if not name or name == uid:                  # etiketi olmayan kayıtlar
            continue
        r = rows.setdefault(uid, {
            "wikidata_id": uid, "name": name, "city": b.get("cityLabel", {}).get("value", ""),
            "country_iso": iso, "country": country_tr(iso), "website": b.get("website", {}).get("value", ""),
            "types": set(),
        })
        r["types"].add(b.get("typeLabel", {}).get("value", ""))
    out = []
    for r in rows.values():
        types = ", ".join(sorted(t for t in r.pop("types") if t))
        low = (r["name"] + " " + types).lower()
        r["type"] = types
        r["teknik_odakli"] = any(w in low for w in TECH_WORDS)
        out.append(r)
    return out


def scrape(countries: list[str] | None = None) -> pd.DataFrame:
    countries = countries or config.UNIVERSITY_COUNTRIES
    s = requests.Session()
    # Wikidata kuralı: programlar kendini tanıtan bir User-Agent göndermeli
    s.headers.update({"User-Agent": "IsIlaniAnalizi/1.0 (university student project; python-requests)",
                      "Accept": "application/sparql-results+json"})
    rows = []
    for iso in countries:
        qid = COUNTRY_QID.get(iso.upper())
        if not qid:
            print(f"  ! Bilinmeyen ülke kodu: {iso}")
            continue
        q = QUERY.format(types=TYPES, qid=qid, lang=iso.lower())
        try:
            r = s.get(ENDPOINT, params={"query": q, "format": "json"}, timeout=90)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  ! Wikidata hatası ({iso}): {e}")
            continue
        got = parse_bindings(r.json(), iso.upper())
        rows += got
        print(f"[üniversite] {country_tr(iso.upper())}: {len(got)} üniversite "
              f"({sum(x['teknik_odakli'] for x in got)} teknik/bilim odaklı)")
    df = pd.DataFrame(rows).drop_duplicates("wikidata_id") if rows else pd.DataFrame()
    if not df.empty:
        df = df.sort_values(["teknik_odakli", "country", "name"], ascending=[False, True, True])
        df.to_csv(config.DATA_DIR / "universiteler.csv", index=False, encoding="utf-8-sig")
        print(f"[üniversite] {len(df)} üniversite -> data/universiteler.csv")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Wikidata'dan üniversite listesi çek")
    ap.add_argument("--countries", nargs="*", default=None, help="ISO kodları, ör. PL CZ HU")
    scrape(ap.parse_args().countries)
