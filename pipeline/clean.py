"""
ADIM 2: Temizleme ve saklama (pandas + SQLite)
=============================================
- data/raw/*.json dosyalarını (tüm scraper'ların çıktısı) tek tabloda birleştirir
- Boş açıklamaları ve tekrar eden ilanları ayıklar
- Ülkeyi standart hale getirir ve ülkenin Erasmus+ stajına uygun olup olmadığını işaretler
- Sonucu hem SQLite veritabanına (data/ilanlar.db, tablo: ilanlar) hem CSV'ye yazar

Çalıştırma:  python -m pipeline.clean
"""
from __future__ import annotations

import json
import re
import sqlite3

import pandas as pd

import config
from scrapers.common import country_iso, country_tr, erasmus_status


# Basit dil tespiti: her dilin en sık kullanılan "küçük kelimelerini" sayar (ek kütüphane gerekmez)
STOPWORDS = {
    "en": "the and of to you with for will we our are in is be your this as on an".split(),
    "de": "und der die das mit für wir sie ist bei du ein eine zu den von auf im".split(),
    "fr": "et le la les des vous pour avec nous est une un du en sur au dans".split(),
    "es": "y el la los las para con que nuestro del una un en por se tu".split(),
    "it": "e il la di per con che del una un nel sono della alla delle".split(),
    "nl": "en de het van voor met je wij zijn een op als bij ons".split(),
    "pl": "i w na z do się jest dla oraz nie że jak".split(),
    "pt": "e o a os as para com que nosso uma um em do da".split(),
}


def detect_language(text: str) -> str:
    words = re.findall(r"[a-zà-ÿąćęłńóśźżß]+", (text or "").lower()[:3000])
    if not words:
        return "?"
    counts = {lang: sum(1 for w in words if w in set(sw)) for lang, sw in STOPWORDS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] >= 3 else "?"


def load_raw() -> pd.DataFrame:
    frames = []
    for f in sorted(config.RAW_DIR.glob("*.json")):
        rows = json.loads(f.read_text(encoding="utf-8"))
        if rows:
            frames.append(pd.DataFrame(rows))
            print(f"[clean] {f.name}: {len(rows)} satır")
    if not frames:
        raise SystemExit("data/raw klasöründe veri yok. Önce scraper'ları çalıştırın.")
    return pd.concat(frames, ignore_index=True)


def normalize_type(t: str) -> str:
    low = (t or "").lower()
    if any(w in low for w in ("staj", "intern", "trainee", "praktik", "stagi", "prácticas", "tirocin")):
        return "Staj"
    if any(w in low for w in ("werkstudent", "part", "yarı")):
        return "Yarı Zamanlı / Öğrenci işi"
    if "tam" in low or "full" in low:
        return "Tam Zamanlı"
    return t or "Belirtilmemiş"


def build() -> pd.DataFrame:
    df = load_raw()
    n0 = len(df)
    if "country" not in df:
        df["country"] = ""
    df["description"] = df["description"].fillna("").str.strip()
    df = df[df["description"].str.len() >= 80]                       # açıklaması olmayanları at
    df["uid"] = df["source"] + ":" + df["job_id"].astype(str)
    df = df.drop_duplicates("uid")
    # Aynı şirket + aynı başlık farklı kaynaklarda varsa tek kayıt tut
    df["_key"] = (df["company"].fillna("").str.lower().str.strip() + "|" + df["title"].str.lower().str.strip())
    df = df.drop_duplicates("_key").drop(columns="_key")

    # Ülke: scraper bulduysa onu, yoksa konum metninden çıkar
    df["country_iso"] = df.apply(lambda r: country_iso(r["country"]) or country_iso(r["location"]), axis=1)
    df["country"] = df["country_iso"].apply(country_tr).where(df["country_iso"] != "", "Belirtilmemiş")
    df["erasmus_ulke"] = df["country_iso"].apply(erasmus_status)
    df["type_norm"] = df.apply(lambda r: normalize_type(r["job_type"] or r["title"]), axis=1)
    df.loc[df["title"].str.contains(r"staj|intern|trainee|praktikum|stagiaire|tirocinio", case=False, regex=True),
           "type_norm"] = "Staj"
    df["desc_len"] = df["description"].str.len()
    # Ön filtre sütunları (LLM'e hangi ilanların gideceğini belirler)
    df["ilan_dili"] = df["description"].apply(detect_language)
    df["alan_uygun"] = (df["source"].eq("eurodesk")
                        | df["title"].str.contains(config.FIELD_TITLE_PATTERN, case=False, regex=True))
    if "first_seen" not in df:
        df["first_seen"] = ""
    df["first_seen"] = df["first_seen"].fillna("")
    df["extra"] = df["extra"].apply(lambda x: json.dumps(x, ensure_ascii=False))
    df = df.reset_index(drop=True)
    print(f"[clean] {n0} ham satır -> {len(df)} temiz ilan "
          f"({df['source'].value_counts().to_dict()})")
    print(f"[clean] ilan dili: {df['ilan_dili'].value_counts().to_dict()} | "
          f"alan (yazılım/veri) uygun: {int(df['alan_uygun'].sum())}")
    return df


def save(df: pd.DataFrame) -> None:
    with sqlite3.connect(config.DB_PATH) as con:
        df.to_sql("ilanlar", con, if_exists="replace", index=False)
    df.to_csv(config.DATA_DIR / "ilanlar_temiz.csv", index=False, encoding="utf-8-sig")
    print(f"[clean] kaydedildi: {config.DB_PATH} ve data/ilanlar_temiz.csv")


def load_clean() -> pd.DataFrame:
    with sqlite3.connect(config.DB_PATH) as con:
        return pd.read_sql("SELECT * FROM ilanlar", con)


if __name__ == "__main__":
    save(build())
