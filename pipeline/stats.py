"""
ADIM 4: İstatistikler, grafikler ve LLM ile pazar özeti
======================================================
- data/analiz.csv'den özet istatistikleri hesaplar -> outputs/ozet_istatistikler.json
- Rapor/sunum için grafikleri çizer                 -> outputs/figures/*.png
- LLM (klasik anahtar kelime yöntemine karşı) karşılaştırması
- İstatistikleri LLM'e verip Türkçe "iş piyasası özeti" yazdırır -> outputs/pazar_ozeti.md

Çalıştırma:  python -m pipeline.stats            (özet yazımı dahil)
             python -m pipeline.stats --no-summary
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config

BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK2, MUTED, SURFACE = "#0b0b0b", "#52514e", "#898781", "#fcfcfb"
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 11,
    "axes.titleweight": "bold", "axes.titlesize": 13, "axes.titlelocation": "left",
})


def load_analysis() -> pd.DataFrame:
    df = pd.read_csv(config.DATA_DIR / "analiz.csv")
    for col in ("teknik_beceriler", "sosyal_beceriler", "yerel_dil_sarti", "keyword_beceriler",
                "eslesen_beceriler", "eksik_beceriler", "teknik_beceriler_ham", "dayanaksiz_beceriler"):
        if col not in df:
            df[col] = "[]"
        df[col] = df[col].apply(lambda s: json.loads(s) if isinstance(s, str) else [])
    return df


def count_list(series: pd.Series, top: int | None = None) -> list[tuple[str, int]]:
    c = Counter(x for xs in series for x in xs)
    return c.most_common(top)


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 1.0


def compute(df: pd.DataFrame) -> dict:
    n = len(df)
    llm_sets = df["teknik_beceriler"].apply(set)
    kw_sets = df["keyword_beceriler"].apply(set)
    only_llm = Counter(x for a, b in zip(llm_sets, kw_sets) for x in a - b)
    staj = df[df["seviye"].isin(["Stajyer", "Öğrenci işi (Werkstudent vb.)"])]
    ucret = pd.to_numeric(df["aylik_ucret_eur"], errors="coerce")
    stats = {
        "ilan_sayisi": n,
        "model": df["model"].iloc[0] if n else "",
        "kaynak": df["source"].value_counts().to_dict(),
        "yontem": df["method"].value_counts().to_dict(),
        "ulke": df["ulke_son"].value_counts().head(15).to_dict(),
        "erasmus": df["erasmus_son"].value_counts().to_dict(),
        "donem_uyumu": df["donem_uyumu"].value_counts().to_dict() if "donem_uyumu" in df else {},
        "ortalama_uyum_puani": round(float(df["uyum_puani"].mean()), 1) if "uyum_puani" in df else None,
        "en_cok_eksik_beceri": count_list(df["eksik_beceriler"], 10),
        "dayanak_kontrolu": {
            "llm_beceri_sayisi": int(df["teknik_beceriler_ham"].apply(len).sum()),
            "dayanaksiz_beceri_sayisi": int(df["dayanaksiz_beceriler"].apply(len).sum()),
            "en_cok_dayanaksiz": count_list(df["dayanaksiz_beceriler"], 10),
        },
        "kategori": df["kategori"].value_counts().to_dict(),
        "seviye": df["seviye"].value_counts().to_dict(),
        "calisma_modeli": df["calisma_modeli"].value_counts().to_dict(),
        "ucret_durumu": df["ucret_durumu"].value_counts().to_dict(),
        "ortanca_aylik_ucret_eur": None if ucret.dropna().empty else int(ucret.median()),
        "ucret_bilinen_ilan": int(ucret.notna().sum()),
        "ortanca_sure_ay": None if pd.to_numeric(df["sure_ay"], errors="coerce").dropna().empty
                           else float(pd.to_numeric(df["sure_ay"], errors="coerce").median()),
        "ingilizce_yeterli_oran": round(df["ingilizce_yeterli"].astype(str).str.lower().eq("true").mean() * 100, 1),
        "yerel_dil_sarti": count_list(df["yerel_dil_sarti"], 6),
        "staj_ilan_sayisi": int(len(staj)),
        "yapay_zeka_ilgili_oran": round(df["yapay_zeka_ilgili"].astype(str).str.lower().eq("true").mean() * 100, 1),
        "en_cok_teknik_beceri": count_list(df["teknik_beceriler"], 20),
        "en_cok_sosyal_beceri": count_list(df["sosyal_beceriler"], 10),
        "ortalama_llm_suresi_sn": round(df["sure_sn"].mean(), 2),
        "karsilastirma": {
            "llm_ort_beceri_sayisi": round(llm_sets.apply(len).mean(), 2),
            "keyword_ort_beceri_sayisi": round(kw_sets.apply(len).mean(), 2),
            "ortalama_jaccard_benzerligi": round(pd.Series([jaccard(a, b) for a, b in zip(llm_sets, kw_sets)]).mean(), 3),
            "llm_benzersiz_beceri_sayisi": len(set().union(*llm_sets)) if n else 0,
            "keyword_benzersiz_beceri_sayisi": len(set().union(*kw_sets)) if n else 0,
            "sadece_llm_buldu_ornek": only_llm.most_common(15),
        },
        "kategoriye_gore_top_beceri": {
            k: count_list(g["teknik_beceriler"], 5) for k, g in df.groupby("kategori") if len(g) >= 3
        },
    }
    return stats


# ---------------------------------------------------------------------------
# Grafikler
# ---------------------------------------------------------------------------
def _hbar(items: list[tuple[str, int]], title: str, fname: str, color=BLUE, xlabel="İlan sayısı"):
    if not items:
        return
    labels, vals = zip(*items[::-1])
    fig, ax = plt.subplots(figsize=(8, max(3, 0.38 * len(items) + 1)))
    bars = ax.barh(labels, vals, color=color, height=0.65)
    ax.bar_label(bars, padding=3, color=INK2, fontsize=9)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", color="#e6e5e1", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / fname, dpi=160)
    plt.close(fig)


def make_figures(df: pd.DataFrame, s: dict) -> None:
    _hbar(s["en_cok_teknik_beceri"][:15], "En çok istenen 15 teknik beceri (LLM çıkarımı)", "01_teknik_beceriler.png")
    _hbar(list(s["ulke"].items()), "Ülkelere göre ilan sayısı", "02_ulkeler.png")
    _hbar(list(s["erasmus"].items()), "Erasmus+ stajına uygunluk (LLM + ülke kuralı)", "03_erasmus.png")
    _hbar(list(s["kategori"].items()), "İlanların kategorilere dağılımı", "04_kategoriler.png")
    _hbar(list(s["ucret_durumu"].items()), "Ücret durumu", "05_ucret.png")
    _hbar(s["yerel_dil_sarti"], "Zorunlu yerel dil şartı (İngilizce dışı)", "06_dil_sarti.png")

    # LLM ve anahtar kelime yöntemini aynı beceriler üzerinde yan yana karşılaştır
    top = [k for k, _ in s["en_cok_teknik_beceri"][:12]]
    llm_c = Counter(x for xs in df["teknik_beceriler"] for x in xs)
    kw_c = Counter(x for xs in df["keyword_beceriler"] for x in xs)
    if top:
        fig, ax = plt.subplots(figsize=(9, 5.5))
        y = range(len(top))[::-1]
        ax.barh([i + 0.2 for i in y], [llm_c[k] for k in top], height=0.38, color=BLUE, label="LLM (Ollama)")
        ax.barh([i - 0.2 for i in y], [kw_c[k] for k in top], height=0.38, color=ORANGE, label="Anahtar kelime sözlüğü")
        ax.set_yticks(list(y), top)
        ax.set_title("Beceri çıkarımı: LLM ve klasik yöntem")
        ax.set_xlabel("Becerinin bulunduğu ilan sayısı")
        ax.legend(frameon=False, loc="lower right")
        ax.grid(axis="x", color="#e6e5e1", linewidth=0.8)
        ax.set_axisbelow(True)
        fig.tight_layout()
        fig.savefig(config.FIG_DIR / "07_llm_vs_keyword.png", dpi=160)
        plt.close(fig)
    print(f"[stats] grafikler -> {config.FIG_DIR}")


# ---------------------------------------------------------------------------
# LLM ile pazar özeti (ikinci LLM görevi: özetleme / yorumlama)
# ---------------------------------------------------------------------------
SUMMARY_SYSTEM = ("Sen bir kariyer danışmanı ve veri analistisin. Sana iş/staj ilanlarından "
                  "çıkarılmış istatistikler verilecek. SADECE verilen sayılara dayanarak yorum yap, "
                  "sayı uydurma. Türkçe yaz.")


def write_market_summary(s: dict) -> str:
    from pipeline.llm_analyze import get_backend
    backend = get_backend()
    compact = {k: s[k] for k in ("ilan_sayisi", "kaynak", "ulke", "erasmus", "kategori", "seviye", "ucret_durumu",
                                 "ortanca_aylik_ucret_eur", "ortanca_sure_ay", "ingilizce_yeterli_oran",
                                 "yerel_dil_sarti", "yapay_zeka_ilgili_oran", "en_cok_teknik_beceri",
                                 "en_cok_sosyal_beceri", "kategoriye_gore_top_beceri")}
    prompt = ("Aşağıdaki istatistiklere göre Türkiye'den Erasmus+ stajına başvurmak isteyen bir üniversite "
              "öğrencisi için kısa bir 'Avrupa Staj Piyasası Özeti' yaz. Başlıklar: 1) Genel Tablo, "
              "2) Hangi Ülkeler Öne Çıkıyor, 3) Dil ve Ücret Durumu, 4) Öne Çıkan Beceriler, "
              "5) Başvuru İçin 5 Somut Öneri. En fazla 350 kelime.\n\n"
              + json.dumps(compact, ensure_ascii=False, indent=1))
    text = backend.generate(prompt, SUMMARY_SYSTEM)
    out = f"# Avrupa Staj Piyasası Özeti\n\n_Model: {backend.model} — {s['ilan_sayisi']} ilan_\n\n{text}\n"
    (config.OUT_DIR / "pazar_ozeti.md").write_text(out, encoding="utf-8")
    print("[stats] LLM pazar özeti -> outputs/pazar_ozeti.md")
    return text


def run(summary: bool = True) -> dict:
    df = load_analysis()
    s = compute(df)
    (config.OUT_DIR / "ozet_istatistikler.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[stats] {s['ilan_sayisi']} ilan | AI ile ilgili: %{s['yapay_zeka_ilgili_oran']} | "
          f"Jaccard(LLM, keyword) = {s['karsilastirma']['ortalama_jaccard_benzerligi']}")
    make_figures(df, s)
    if summary:
        write_market_summary(s)
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-summary", action="store_true")
    run(not ap.parse_args().no_summary)
