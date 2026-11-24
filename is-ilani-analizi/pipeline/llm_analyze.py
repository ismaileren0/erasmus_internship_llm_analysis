"""
ADIM 3: Büyük Dil Modeli (LLM) ile analiz — Ollama (yerel, ücretsiz)
==================================================================
Her ilan metni yerel bir LLM'e (varsayılan: qwen2.5:7b) gönderilir ve modelden
**JSON şemasına uyan yapılandırılmış** bir cevap istenir:
  kategori, seviye, ülke, ücret durumu, süre, öğrenci şartı, Erasmus+ uygunluğu (+ gerekçe),
  dil şartı, teknik ve sosyal beceriler, eğitim, son başvuru, yapay zeka ile ilgili mi, özet

Kullanılan teknikler:
  - Structured Output: Ollama'nın `format=<JSON şema>` özelliği modeli şemaya uymaya zorlar
  - Pydantic ile doğrulama: geçersiz cevap gelirse tekrar denenir
  - temperature=0: aynı ilana her seferinde aynı cevap (tekrarlanabilirlik)
  - Önbellek (cache): sonuçlar data/llm_cache.jsonl'e yazılır; yarıda kesilirse kaldığı yerden devam eder

Hazırlık:  1) https://ollama.com adresinden Ollama'yı kurun
           2) ollama pull qwen2.5:7b      (zayıf bilgisayar için: ollama pull llama3.2:3b)
Çalıştırma: python -m pipeline.llm_analyze                # tüm ilanlar
            python -m pipeline.llm_analyze --limit 20     # hızlı deneme
            OLLAMA_MODEL=llama3.2:3b python -m pipeline.llm_analyze
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

import config
from pipeline.clean import load_clean
from pipeline.skills import canonical, grounded, keyword_skills
from scrapers.common import country_iso, erasmus_status

KATEGORILER = ("Yazılım Geliştirme", "Veri Bilimi / Yapay Zeka", "DevOps / Bulut / Altyapı",
               "Siber Güvenlik", "Test / Kalite", "Tasarım / UI-UX", "Mühendislik (Yazılım dışı)",
               "Araştırma / Akademik", "Pazarlama / İletişim", "Satış / İş Geliştirme", "Finans / Muhasebe",
               "Hukuk", "İnsan Kaynakları", "Operasyon / Lojistik / Tedarik", "Kamu / AB Kurumu", "Diğer")
SEVIYELER = ("Stajyer", "Öğrenci işi (Werkstudent vb.)", "Yeni Mezun / Junior", "Deneyimli", "Belirtilmemiş")
MODELLER = ("Ofis", "Hibrit", "Uzaktan", "Belirtilmemiş")
UCRET = ("Ücretli", "Ücretsiz", "Belirtilmemiş")
ERASMUS = ("Uygun", "Muhtemelen uygun", "Uygun değil")
DONEM = ("Uyumlu", "Belirsiz", "Uyumsuz")


class IlanAnalizi(BaseModel):
    """LLM'den beklediğimiz cevabın şeması."""
    kategori: Literal[KATEGORILER]
    seviye: Literal[SEVIYELER]
    calisma_modeli: Literal[MODELLER]
    ulke: str = Field(description="Stajın yapılacağı ülkenin Türkçe adı (ör. Almanya); birden çoksa ilki; yoksa 'Belirtilmemiş'")
    sehir: str = Field(description="Şehir; yoksa 'Belirtilmemiş'")
    ucret_durumu: Literal[UCRET]
    aylik_ucret_eur: Optional[int] = Field(description="Aylık brüt ücret/hibe, euro; yazmıyorsa null")
    sure_ay: Optional[int] = Field(description="Staj süresi, ay; yazmıyorsa null")
    baslangic: str = Field(description="Stajın başlangıç zamanı (ör. 'Hemen', 'Mart 2027', 'Yaz 2027'); yoksa 'Belirtilmemiş'")
    donem_uyumu: Literal[DONEM] = Field(description=f"Adayın müsaitliği ({config.AVAILABILITY}) ile başlangıç/süre uyumu")
    ogrenci_sarti: bool = Field(description="Adayın kayıtlı öğrenci olması isteniyor mu (öğrenci stajı, zorunlu staj, Werkstudent)")
    erasmus_uygunlugu: Literal[ERASMUS] = Field(description="Türkiye'deki bir üniversite öğrencisinin Erasmus+ stajı için uygunluğu")
    erasmus_gerekce: str = Field(description="Uygunluk kararının tek cümlelik Türkçe gerekçesi")
    ingilizce_yeterli: bool = Field(description="İş İngilizce yürütülebiliyor mu (yerel dil zorunlu değil)")
    yerel_dil_sarti: list[str] = Field(description="Zorunlu istenen İngilizce dışı diller, ör. ['Almanca']; yoksa []")
    teknik_beceriler: list[str] = Field(description="İlanda istenen teknik beceri/araç/teknoloji adları, kısa")
    sosyal_beceriler: list[str] = Field(description="İletişim, takım çalışması gibi kişisel beceriler, kısa")
    egitim: str = Field(description="İstenen bölüm/eğitim, kısa; yoksa 'Belirtilmemiş'")
    son_basvuru: str = Field(description="Son başvuru tarihi YYYY-AA-GG; yoksa 'Belirtilmemiş'")
    yapay_zeka_ilgili: bool = Field(description="İlan yapay zeka, makine öğrenmesi, veri bilimi veya LLM ile ilgili mi")
    ozet: str = Field(description="İlanın tek cümlelik Türkçe özeti")


SYSTEM_PROMPT = f"""Sen Erasmus+ staj danışmanı bir insan kaynakları analistisin. Sana Avrupa'dan bir staj
veya iş ilanı verilecek; ilan Almanca, Fransızca, İspanyolca gibi farklı dillerde olabilir.
İlanı okuyup SADECE istenen JSON formatında, Türkçe değerlerle cevap ver. Kurallar:
- kategori: {", ".join(KATEGORILER)}
- seviye: {", ".join(SEVIYELER)}
- calisma_modeli: {", ".join(MODELLER)};  ucret_durumu: {", ".join(UCRET)}
- erasmus_uygunlugu — Türkiye'de üniversiteye kayıtlı bir öğrencinin Erasmus+ hibesiyle 2-12 ay staj yapması:
    "Uygun": öğrencilere açık bir staj; ülke AB üyesi veya Norveç, İzlanda, Lihtenştayn, Kuzey Makedonya, Sırbistan.
    "Muhtemelen uygun": staj ama öğrenci şartı/ülke/süre belirsiz.
    "Uygun değil": deneyimli eleman ilanı, tam zamanlı kadrolu iş, AB dışı ülke veya Türkiye'de.
- donem_uyumu — aday {config.AVAILABILITY} müsait:
    "Uyumlu": başlangıç Haziran-Eylül 2027 arası, "yaz stajı 2027" ya da tarih esnek/sürekli alım.
    "Belirsiz": tarih yazmıyor.   "Uyumsuz": hemen/2027 baharında başlıyor ya da 6 aydan uzun ve esnek değil.
- yerel_dil_sarti: yalnızca ZORUNLU istenen yerel dili yaz ("iyi Almanca bilgisi şart" gibi). "Avantaj" ise yazma.
- teknik_beceriler: YALNIZCA ilan metninde kelimesi kelimesine geçen teknoloji, yazılım ve yöntemleri yaz
  (ör. "Python", "SQL", "Excel", "SAP"). Alanı tahmin ederek ekleme yapma: metinde "Python" kelimesi
  yoksa "Python" yazma. Hiç teknik beceri yazmıyorsa boş liste ver.
- sosyal_beceriler: en fazla 5 tane, kısa.
- Bilgi yoksa liste boş, metin "Belirtilmemiş", sayı null olsun. ozet Türkçe ve tek cümle."""


def build_user_prompt(row: pd.Series) -> str:
    desc = str(row["description"])[: config.MAX_DESC_CHARS]
    return (f"Başlık: {row['title']}\nŞirket: {row['company']}\nKonum: {row['location']} ({row.get('country', '')})\n"
            f"Tür: {row['job_type']}\nSon başvuru: {row.get('deadline', '')}\n\nİlan metni:\n{desc}")


# ---------------------------------------------------------------------------
# LLM arka uçları
# ---------------------------------------------------------------------------
class OllamaBackend:
    def __init__(self, model: str = config.OLLAMA_MODEL, host: str = config.OLLAMA_HOST):
        from ollama import Client
        self.model = model
        # timeout: model bir ilanda takılırsa (ör. JSON modunda durmadan boşluk üretmesi)
        # 3 dakika sonra o ilanı atlayıp devam et
        self.client = Client(host=host, timeout=180)
        self.schema = IlanAnalizi.model_json_schema()

    def check(self) -> None:
        try:
            names = [m.model for m in self.client.list().models]
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"Ollama'ya bağlanılamadı ({e}). Ollama uygulaması açık mı? "
                             f"Terminalde 'ollama serve' çalıştırmayı deneyin.")
        if not any(n == self.model or n.startswith(self.model + ":") or n.split(":")[0] == self.model for n in names):
            raise SystemExit(f"Model bulunamadı: {self.model}. Önce: ollama pull {self.model}\n"
                             f"Yüklü modeller: {names}")

    def analyze(self, prompt: str) -> tuple[IlanAnalizi, float]:
        t0 = time.time()
        last_err = None
        for _ in range(3):
            resp = self.client.chat(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": prompt}],
                format=self.schema,                   # Structured Output
                # num_predict: cevap en fazla ~800 token; sonsuz üretimi engeller
                options={"temperature": 0, "num_ctx": 4096, "num_predict": 800},
            )
            try:
                return IlanAnalizi.model_validate_json(resp.message.content), time.time() - t0
            except ValidationError as e:
                last_err = e
        raise RuntimeError(f"LLM geçerli JSON üretemedi: {last_err}")

    def generate(self, prompt: str, system: str = "") -> str:
        """Serbest metin üretimi (pazar özeti ve canlı demo için)."""
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        resp = self.client.chat(model=self.model, messages=msgs, options={"temperature": 0.3, "num_predict": 1200})
        return resp.message.content


class MockBackend:
    """SADECE TEST İÇİN: Ollama kurulu değilken boru hattının çalıştığını denemek için.
    Gerçek LLM değildir; sonuçlar sunumda/raporda KULLANILMAMALIDIR."""
    model = "mock (test)"

    def check(self) -> None:
        print("UYARI: LLM_BACKEND=mock — gerçek LLM kullanılmıyor, sonuçlar yalnızca test amaçlıdır.")

    def analyze(self, prompt: str) -> tuple[IlanAnalizi, float]:
        low = prompt.lower()
        sk = keyword_skills(prompt)
        kat = ("Veri Bilimi / Yapay Zeka" if any(w in low for w in ("veri", "data", "yapay", "machine"))
               else "Yazılım Geliştirme" if any(w in low for w in ("yazılım", "developer", "software"))
               else "Diğer")
        intern = any(w in low for w in ("staj", "intern", "trainee", "praktikum"))
        de = "almanca" in low or "german" in low or "deutsch" in low
        return IlanAnalizi(
            kategori=kat, seviye="Stajyer" if intern else "Belirtilmemiş",
            calisma_modeli="Uzaktan" if "remote" in low or "uzaktan" in low else "Belirtilmemiş",
            ulke="Belirtilmemiş", sehir="Belirtilmemiş",
            ucret_durumu="Ücretli" if "€" in prompt or "eur" in low else "Belirtilmemiş",
            aylik_ucret_eur=None, sure_ay=6 if "6 month" in low or "6-month" in low else None,
            baslangic="Belirtilmemiş", donem_uyumu="Uyumlu" if "2027" in low else "Belirsiz",
            ogrenci_sarti=intern, erasmus_uygunlugu="Muhtemelen uygun" if intern else "Uygun değil",
            erasmus_gerekce="(test)", ingilizce_yeterli=not de, yerel_dil_sarti=["Almanca"] if de else [],
            teknik_beceriler=sk, sosyal_beceriler=["Takım çalışması"] if "team" in low or "takım" in low else [],
            egitim="Belirtilmemiş", son_basvuru="Belirtilmemiş",
            yapay_zeka_ilgili=kat == "Veri Bilimi / Yapay Zeka", ozet="(test özeti)",
        ), 0.0

    def generate(self, prompt: str, system: str = "") -> str:
        return "(mock) Gerçek LLM bağlı değil."


def get_backend(model: str | None = None):
    if config.LLM_BACKEND == "mock":
        return MockBackend()
    return OllamaBackend(model or config.OLLAMA_MODEL)


# ---------------------------------------------------------------------------
# Toplu analiz
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "erasmus2"   # şema değişince eski önbellek kullanılmasın


def cache_path(model_name: str):
    safe = model_name.replace(":", "_").replace("/", "_").replace(" ", "_")
    return config.DATA_DIR / f"llm_cache_{safe}_{SCHEMA_VERSION}.jsonl"


def load_cache(model_name: str) -> dict:
    p = cache_path(model_name)
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["uid"]] = r
    return out


def _final_erasmus(r) -> str:
    if r["erasmus_ulke"] == "Hayır":
        return "Uygun değil"
    if r["erasmus_ulke"] == "2027'den itibaren" and r["erasmus_uygunlugu"] == "Uygun":
        return "Muhtemelen uygun"
    return r["erasmus_uygunlugu"]


# ---------------------------------------------------------------------------
# Üçüncü LLM görevi: motivasyon mektubu taslağı
# ---------------------------------------------------------------------------
LETTER_SYSTEM = ("You are a career advisor who writes concise, sincere internship application letters for "
                 "Erasmus+ students. Never invent facts about the applicant: use [brackets] for unknown details.")


def cover_letter(row: dict, profile: str = config.APPLICANT_PROFILE, backend=None) -> str:
    """Seçilen ilana göre İngilizce motivasyon mektubu taslağı yazar. İpucu (staj rehberinden):
    Erasmus+ kapsamında gelindiği, ücret beklentisi olmadığı ve hibenin AB tarafından
    karşılanacağı İLK paragrafta söylenmeli — şirketin mali yükünü kaldırır."""
    backend = backend or get_backend()
    prompt = (
        "Write a cover letter (max 250 words, English) for this internship.\n"
        "MUST in the FIRST paragraph: the applicant will come within the Erasmus+ traineeship programme, "
        "has no salary expectation, and the monthly grant is covered by the EU (Erasmus+).\n"
        "Then: 2-3 sentences that connect the applicant's REAL projects and skills to this posting's "
        "requirements (pick the most relevant project); availability (from June 2027, 2-6 months); "
        "polite closing signed as [Name].\n\n"
        f"Applicant: {profile}\n\nInternship: {row.get('title')} at {row.get('company')} "
        f"({row.get('ulke_son') or row.get('country')})\nKey requirements: {row.get('teknik_beceriler')}\n"
        f"Posting (excerpt): {str(row.get('description', ''))[:1500]}"
    )
    return backend.generate(prompt, LETTER_SYSTEM)


def university_email(uni: dict, profile: str = config.APPLICANT_PROFILE, backend=None) -> str:
    """Bir üniversiteye (uluslararası ofis / bilgisayar bilimleri bölümü) gönderilecek
    spekülatif Erasmus+ staj başvurusu e-posta taslağı."""
    backend = backend or get_backend()
    prompt = (
        "Write a short, polite email (max 200 words, English) to the international relations office of the "
        "university below, asking whether its computer science / AI research groups could host an Erasmus+ "
        "traineeship. FIRST paragraph: the applicant comes within Erasmus+ (traineeship mobility), has no salary "
        "expectation and the monthly grant is paid by the EU via the home university. Then 2 sentences on the "
        "applicant's most relevant projects; availability from June 2027 for 2-6 months; ask them to forward the "
        "email to a suitable lab or tell whom to contact; mention CV attached. Subject line first. Sign as [Name].\n\n"
        f"University: {uni.get('name')} ({uni.get('city')}, {uni.get('country')})\nApplicant: {profile}"
    )
    return backend.generate(prompt, LETTER_SYSTEM)


def run(limit: int | None = None, model: str | None = None) -> pd.DataFrame:
    df = load_clean()
    if config.PREFILTER:
        mask = df["alan_uygun"].astype(bool)
        if config.ONLY_ENGLISH:
            mask &= df["ilan_dili"].isin(["en", "?"]) | df["source"].eq("eurodesk")   # "?": dil anlaşılamadı -> LLM karar versin
        print(f"[llm] ön filtre: {len(df)} ilandan {int(mask.sum())} tanesi LLM'e gönderilecek "
              f"(alan: yazılım/veri{', dil: İngilizce' if config.ONLY_ENGLISH else ''})")
        df = df[mask]
    if limit:
        df = df.head(limit)
    backend = get_backend(model)
    backend.check()
    cache = load_cache(backend.model)
    todo = df[~df["uid"].isin(cache)]
    print(f"[llm] model={backend.model} | toplam {len(df)} ilan, önbellekte {len(df) - len(todo)}, "
          f"analiz edilecek {len(todo)}")

    with cache_path(backend.model).open("a", encoding="utf-8") as fh:
        for i, (_, row) in enumerate(todo.iterrows(), 1):
            try:
                res, sec = backend.analyze(build_user_prompt(row))
            except Exception as e:  # noqa: BLE001
                print(f"  ! {row['uid']} analiz edilemedi: {e}")
                continue
            rec = {"uid": row["uid"], "model": backend.model, "sure_sn": round(sec, 2), **res.model_dump()}
            cache[row["uid"]] = rec
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"  [{i}/{len(todo)}] {sec:5.1f} sn | {res.kategori:<28} | {row['title'][:50]}")

    res_df = pd.DataFrame([cache[u] for u in df["uid"] if u in cache])
    if res_df.empty:
        raise SystemExit("Hiç sonuç yok.")
    # Beceri adlarını tek tipe indir (Python3 -> Python, ms excel -> Excel ...)
    res_df["teknik_beceriler"] = res_df["teknik_beceriler"].apply(
        lambda xs: sorted({canonical(x) for x in xs if canonical(x)}))
    out = df.merge(res_df, on="uid", how="inner")
    # Dayanak (grounding) kontrolü: metinde geçmeyen becerileri ayır -> halüsinasyonu ölç ve temizle
    texts = out["title"] + "\n" + out["description"]
    out["teknik_beceriler_ham"] = out["teknik_beceriler"]
    out["dayanaksiz_beceriler"] = [[x for x in xs if not grounded(x, t)] for xs, t in zip(out["teknik_beceriler"], texts)]
    out["teknik_beceriler"] = [[x for x in xs if grounded(x, t)] for xs, t in zip(out["teknik_beceriler"], texts)]
    n_all = sum(len(x) for x in out["teknik_beceriler_ham"])
    n_bad = sum(len(x) for x in out["dayanaksiz_beceriler"])
    print(f"[llm] dayanak kontrolü: {n_all} becerinin {n_bad} tanesi (%{100 * n_bad / max(n_all, 1):.1f}) "
          f"ilan metninde geçmiyor -> ayıklandı")
    # Ülke: scraper'dan gelen bilgi varsa onu, yoksa LLM'in bulduğunu kullan
    out["ulke_son"] = out["country"].where(out["country"] != "Belirtilmemiş", out["ulke"])
    # Nihai Erasmus kararı: LLM'in kararı + ülke kuralı (AB/bağlı ülke değilse uygun değil)
    out["erasmus_ulke"] = out["ulke_son"].apply(lambda c: erasmus_status(country_iso(c)))
    out["erasmus_son"] = out.apply(_final_erasmus, axis=1)
    # Klasik yöntem (karşılaştırma için): anahtar kelime sözlüğü
    out["keyword_beceriler"] = (out["title"] + "\n" + out["description"]).apply(keyword_skills)
    # CV'ye göre uyum puanı (pipeline/match.py)
    from pipeline.match import add_scores
    out = add_scores(out)
    for col in ("teknik_beceriler", "sosyal_beceriler", "yerel_dil_sarti", "keyword_beceriler",
                "eslesen_beceriler", "eksik_beceriler", "teknik_beceriler_ham", "dayanaksiz_beceriler"):
        out[col] = out[col].apply(lambda xs: json.dumps(list(xs), ensure_ascii=False))
    out.to_csv(config.DATA_DIR / "analiz.csv", index=False, encoding="utf-8-sig")
    print(f"[llm] {len(out)} ilan analiz edildi -> data/analiz.csv")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default=None, help="ör. qwen2.5:7b, llama3.2:3b, gemma3:4b")
    a = ap.parse_args()
    run(a.limit, a.model)
