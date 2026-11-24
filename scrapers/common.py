"""
Scraper'ların ortak parçaları: ilan veri modeli, bekleme, kaydetme.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

import config

# HTML ayrıştırıcı: lxml (hızlı) kuruluysa onu, değilse Python'un yerleşik html.parser'ını kullan
try:
    import lxml  # noqa: F401
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"
    print("Not: 'lxml' bulunamadı, yerleşik 'html.parser' kullanılıyor (pip install lxml ile hızlanır).")


@dataclass
class Job:
    """Tek bir staj ilanı. Tüm kaynaklar aynı alanları doldurur."""
    source: str                 # "eurodesk" | "eures" | "linkedin" | "youthall"
    method: str                 # "requests+bs4" | "selenium" | "json-api"
    job_id: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    country: str = ""           # Türkçe ülke adı (biliniyorsa)
    job_type: str = ""          # Stajyer / Tam Zamanlı / ...
    work_model: str = ""        # Ofis / Hibrit / Uzaktan (sitede yazıyorsa)
    posted_date: str = ""
    deadline: str = ""
    department: str = ""
    description: str = ""       # temiz metin
    extra: dict = field(default_factory=dict)
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def polite_sleep(min_s: float = None, max_s: float = None) -> None:
    """İstekler arasında rastgele bekle (sunucuya yük bindirmemek ve engellenmemek için)."""
    time.sleep(random.uniform(min_s or config.MIN_DELAY, max_s or config.MAX_DELAY))


def html_to_text(html: str) -> str:
    """HTML açıklamayı okunabilir düz metne çevirir (madde işaretlerini korur)."""
    if not html:
        return ""
    soup = BeautifulSoup(html, PARSER)
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    for br in soup.find_all(["br", "p", "div", "h1", "h2", "h3", "h4", "ul", "ol"]):
        br.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# ---------------------------------------------------------------------------
# Ülkeler ve Erasmus+ uygunluğu
# Kaynak: Erasmus+ Programme Guide 2026, "Eligible countries": AB'nin 27 üyesi + programa
# bağlı üçüncü ülkeler (İzlanda, Lihtenştayn, Norveç, Kuzey Makedonya, Sırbistan, Türkiye).
# Türkiye'den başvuran öğrenci için staj ülkesi Türkiye dışında olmalı.
# Birleşik Krallık 2027'den itibaren programa bağlanacak (kontrol edilmeli).
# ---------------------------------------------------------------------------
# ISO kodu: (Türkçe ad, İngilizce ad, Erasmus durumu)  — durum: "Evet" | "2027'den itibaren" | "Hayır"
COUNTRIES: dict[str, tuple[str, str, str]] = {
    "AT": ("Avusturya", "Austria", "Evet"), "BE": ("Belçika", "Belgium", "Evet"),
    "BG": ("Bulgaristan", "Bulgaria", "Evet"), "HR": ("Hırvatistan", "Croatia", "Evet"),
    "CY": ("Kıbrıs (GKRY)", "Cyprus", "Evet"), "CZ": ("Çekya", "Czechia", "Evet"),
    "DK": ("Danimarka", "Denmark", "Evet"), "EE": ("Estonya", "Estonia", "Evet"),
    "FI": ("Finlandiya", "Finland", "Evet"), "FR": ("Fransa", "France", "Evet"),
    "DE": ("Almanya", "Germany", "Evet"), "GR": ("Yunanistan", "Greece", "Evet"),
    "HU": ("Macaristan", "Hungary", "Evet"), "IE": ("İrlanda", "Ireland", "Evet"),
    "IT": ("İtalya", "Italy", "Evet"), "LV": ("Letonya", "Latvia", "Evet"),
    "LT": ("Litvanya", "Lithuania", "Evet"), "LU": ("Lüksemburg", "Luxembourg", "Evet"),
    "MT": ("Malta", "Malta", "Evet"), "NL": ("Hollanda", "Netherlands", "Evet"),
    "PL": ("Polonya", "Poland", "Evet"), "PT": ("Portekiz", "Portugal", "Evet"),
    "RO": ("Romanya", "Romania", "Evet"), "SK": ("Slovakya", "Slovakia", "Evet"),
    "SI": ("Slovenya", "Slovenia", "Evet"), "ES": ("İspanya", "Spain", "Evet"),
    "SE": ("İsveç", "Sweden", "Evet"),
    "IS": ("İzlanda", "Iceland", "Evet"), "LI": ("Lihtenştayn", "Liechtenstein", "Evet"),
    "NO": ("Norveç", "Norway", "Evet"), "MK": ("Kuzey Makedonya", "North Macedonia", "Evet"),
    "RS": ("Sırbistan", "Serbia", "Evet"),
    "TR": ("Türkiye", "Türkiye", "Hayır"),          # kendi ülken: yurt dışı stajı sayılmaz
    "GB": ("Birleşik Krallık", "United Kingdom", "2027'den itibaren"),
    "CH": ("İsviçre", "Switzerland", "Hayır"),
}
_ALIASES = {
    "the netherlands": "NL", "holland": "NL", "czech republic": "CZ", "turkey": "TR", "türkiye": "TR",
    "uk": "GB", "england": "GB", "deutschland": "DE", "österreich": "AT", "españa": "ES",
    "italia": "IT", "nederland": "NL", "belgique": "BE", "polska": "PL", "sverige": "SE",
    "münih": "DE", "munich": "DE", "berlin": "DE", "amsterdam": "NL", "valencia": "ES",
    "madrid": "ES", "barcelona": "ES", "paris": "FR", "lisbon": "PT", "lizbon": "PT",
    "vienna": "AT", "viyana": "AT", "brussels": "BE", "brüksel": "BE", "prague": "CZ",
    "dublin": "IE", "milano": "IT", "milan": "IT", "rome": "IT", "roma": "IT", "warsaw": "PL",
    "london": "GB", "londra": "GB", "zurich": "CH", "zürich": "CH", "geneva": "CH", "cenevre": "CH",
}
_NAME_TO_ISO = {}
for _iso, (_tr, _en, _) in COUNTRIES.items():
    _NAME_TO_ISO[_tr.lower()] = _iso
    _NAME_TO_ISO[_en.lower()] = _iso
_NAME_TO_ISO.update(_ALIASES)


def country_iso(text: str) -> str:
    """'Rotterdam, South Holland, Netherlands' -> 'NL'. Bulamazsa ''."""
    if not text:
        return ""
    t = text.strip()
    if t.upper() in COUNTRIES:
        return t.upper()
    low = t.lower()
    # önce virgülle ayrılmış parçaların sonundan başla (ülke genelde en sonda)
    for part in reversed([p.strip() for p in low.split(",")]):
        if part in _NAME_TO_ISO:
            return _NAME_TO_ISO[part]
    for name, iso in sorted(_NAME_TO_ISO.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(name)}\b", low):
            return iso
    return ""


def country_tr(iso: str) -> str:
    return COUNTRIES.get(iso, ("", "", ""))[0] if iso else ""


def erasmus_status(iso: str) -> str:
    """Ülke Erasmus+ stajı için uygun mu? (Türkiye'den giden öğrenci açısından)"""
    if not iso:
        return "Bilinmiyor"
    return COUNTRIES.get(iso, ("", "", "Hayır"))[2]


def save_jobs(jobs: list[Job], name: str, merge: bool = True) -> Path:
    """Ham sonuçları data/raw/<name>.json olarak kaydeder.
    merge=True: önceki çalıştırmaların ilanları silinmez; yeni ilanlar eklenir ve her ilanın
    ilk görüldüğü tarih (first_seen) saklanır. Böylece günlük çalıştırmalarla veri birikir."""
    path = config.RAW_DIR / f"{name}.json"
    old: dict[str, dict] = {}
    if merge and path.exists():
        try:
            old = {str(r["job_id"]): r for r in json.loads(path.read_text(encoding="utf-8"))}
        except (ValueError, KeyError):
            old = {}
    today = datetime.now().date().isoformat()
    rows = dict(old)
    new = 0
    for j in jobs:
        r = asdict(j)
        prev = old.get(str(j.job_id))
        r["first_seen"] = prev.get("first_seen", today) if prev else today
        new += prev is None
        rows[str(j.job_id)] = r
    path.write_text(json.dumps(list(rows.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[kayıt] {name}: bu çalıştırmada {len(jobs)} ilan, {new} yeni, toplam {len(rows)} -> {path}")
    return path
