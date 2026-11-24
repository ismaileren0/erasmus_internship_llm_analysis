"""
ADIM 5: Streamlit demo paneli — Avrupa'da Erasmus+ stajı arama
Çalıştırma:  streamlit run app.py
"""
import json
from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st

import config

BLUE, ORANGE = "#2a78d6", "#eb6834"
LIST_COLS = ("teknik_beceriler", "sosyal_beceriler", "yerel_dil_sarti", "keyword_beceriler",
             "eslesen_beceriler", "eksik_beceriler")
STATUS_FILE = config.DATA_DIR / "basvurular.csv"      # başvuru takibi (senin bilgisayarında kalır)
DURUMLAR = ["Yeni", "Başvuracağım", "Başvurdum", "İlgilenmiyorum"]
st.set_page_config(page_title="Avrupa Staj İlanı Analizi", page_icon="🇪🇺", layout="wide")


@st.cache_data
def load():
    p = config.DATA_DIR / "analiz.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    for c in LIST_COLS:
        if c not in df:
            df[c] = "[]"
        df[c] = df[c].apply(lambda s: json.loads(s) if isinstance(s, str) else [])
    for c, v in (("uyum_puani", 0), ("donem_uyumu", "Belirsiz"), ("baslangic", "Belirtilmemiş"), ("first_seen", "")):
        if c not in df:
            df[c] = v
    for c in ("ingilizce_yeterli", "yapay_zeka_ilgili", "ogrenci_sarti"):
        df[c] = df[c].astype(str).str.lower().eq("true")
    return df


def load_status() -> pd.DataFrame:
    if STATUS_FILE.exists():
        return pd.read_csv(STATUS_FILE, dtype=str).fillna("")
    return pd.DataFrame(columns=["uid", "durum", "tarih", "title", "company", "url"])


def save_status(st_df: pd.DataFrame) -> None:
    st_df.to_csv(STATUS_FILE, index=False, encoding="utf-8-sig")


def hbar(items, title, color=BLUE):
    if not items:
        st.info("Veri yok")
        return
    d = pd.DataFrame(items, columns=["ad", "sayı"]).iloc[::-1]
    fig = px.bar(d, x="sayı", y="ad", orientation="h", title=title, text="sayı", color_discrete_sequence=[color])
    fig.update_layout(height=max(280, 28 * len(d) + 80), yaxis_title=None, xaxis_title="İlan sayısı",
                      margin=dict(l=10, r=10, t=50, b=10))
    fig.update_traces(textposition="outside", cliponaxis=False)
    st.plotly_chart(fig, width="stretch")


df = load()
st.title("🇪🇺 Web Scraping + LLM ile Avrupa Staj İlanı Analizi")
st.caption("Kaynaklar: Eurodesk (requests + BeautifulSoup) · EURES (JSON API) · LinkedIn (Selenium) · Youthall "
           "(BeautifulSoup) • Analiz: Ollama (yerel LLM)")
if df is None:
    st.error("data/analiz.csv bulunamadı. Önce `python run_all.py` çalıştırın.")
    st.stop()
if str(df["model"].iloc[0]).startswith("mock"):
    st.warning("Bu veriler TEST (mock) modunda üretildi; gerçek LLM sonucu değildir.")

# --- Filtreler --------------------------------------------------------------
with st.sidebar:
    st.header("Filtreler")
    src = st.multiselect("Kaynak", sorted(df["source"].unique()), default=sorted(df["source"].unique()))
    er = st.multiselect("Erasmus+ uygunluğu", ["Uygun", "Muhtemelen uygun", "Uygun değil"],
                        default=["Uygun", "Muhtemelen uygun"])
    ulkeler = st.multiselect("Ülke", sorted(df["ulke_son"].dropna().unique()))
    kats = st.multiselect("Kategori", sorted(df["kategori"].unique()))
    only_en = st.checkbox("Yalnızca İngilizce yeterli olanlar")
    only_paid = st.checkbox("Yalnızca ücretli olanlar")
    donem = st.multiselect("Dönem uyumu (Haziran 2027)", ["Uyumlu", "Belirsiz", "Uyumsuz"],
                           default=["Uyumlu", "Belirsiz"])
f = df[df["source"].isin(src) & df["erasmus_son"].isin(er or df["erasmus_son"].unique())]
if ulkeler:
    f = f[f["ulke_son"].isin(ulkeler)]
if kats:
    f = f[f["kategori"].isin(kats)]
if only_en:
    f = f[f["ingilizce_yeterli"]]
if only_paid:
    f = f[f["ucret_durumu"] == "Ücretli"]
if donem:
    f = f[f["donem_uyumu"].isin(donem)]

tabs = st.tabs(["Genel Bakış", "🗓️ Bugünün Listesi", "🏛️ Üniversiteler", "🎯 Başvuru Listesi", "Beceriler", "LLM vs Klasik Yöntem",
                "✉️ Motivasyon Mektubu", "🤖 Canlı LLM Demo", "📝 Piyasa Özeti"])

# --- 1) Genel bakış ---------------------------------------------------------
with tabs[0]:
    c = st.columns(5)
    c[0].metric("İlan", len(f))
    c[1].metric("Ülke", f["ulke_son"].nunique())
    c[2].metric("Erasmus+ uygun", int((f["erasmus_son"] == "Uygun").sum()))
    c[3].metric("İngilizce yeterli", f"%{f['ingilizce_yeterli'].mean() * 100:.0f}" if len(f) else "-")
    med = pd.to_numeric(f["aylik_ucret_eur"], errors="coerce").median()
    c[4].metric("Ortanca aylık ücret", f"€{med:,.0f}" if pd.notna(med) else "-")
    a, b = st.columns(2)
    with a:
        hbar(list(f["ulke_son"].value_counts().head(15).items()), "Ülke")
        hbar(list(f["ucret_durumu"].value_counts().items()), "Ücret durumu")
    with b:
        hbar(list(df[df["source"].isin(src)]["erasmus_son"].value_counts().items()),
             "Erasmus+ uygunluğu (filtre öncesi)", ORANGE)
        hbar(list(f["kategori"].value_counts().items()), "Kategori")
    hbar(Counter(x for xs in f["yerel_dil_sarti"] for x in xs).most_common(8), "Zorunlu yerel dil şartı")
    st.caption(f"Kaynak dağılımı: {f['source'].value_counts().to_dict()} • Model: {df['model'].iloc[0]}")


# --- 2) Bugünün listesi: uyum puanına göre sıralı, başvurulanlar hariç ------------
with tabs[1]:
    status = load_status()
    durum_map = dict(zip(status["uid"], status["durum"]))
    applied = int((status["durum"] == "Başvurdum").sum())
    c = st.columns(4)
    hedef = c[0].number_input("Toplam hedef", 10, 1000, 340, step=10)
    gunluk = c[1].number_input("Günlük hedef", 1, 100, 20)
    c[2].metric("Başvurulan", f"{applied} / {hedef}")
    c[3].metric("Uygun, henüz bakılmamış", int(sum(durum_map.get(u, "Yeni") == "Yeni" for u in f["uid"])))
    st.progress(min(applied / hedef, 1.0))
    st.caption("Sıralama: uyum puanı (Erasmus+ 30 · dönem 20 · İngilizce 15 · CV beceri eşleşmesi 25 · seviye 10). "
               "Durumu değiştirip **Kaydet**'e bas; 'Başvurdum' ve 'İlgilenmiyorum' olanlar listeden çıkar.")
    t = f.copy()
    t["Durum"] = t["uid"].map(durum_map).fillna("Yeni")
    t = t[t["Durum"].isin(["Yeni", "Başvuracağım"])].sort_values(["uyum_puani", "first_seen"], ascending=[False, False])
    t = t.head(int(gunluk))
    t["eşleşen"] = t["eslesen_beceriler"].apply(", ".join)
    t["eksik"] = t["eksik_beceriler"].apply(", ".join)
    t["dil"] = t["yerel_dil_sarti"].apply(lambda xs: ", ".join(xs) or "İngilizce yeterli")
    cols = ["Durum", "uyum_puani", "title", "company", "ulke_son", "baslangic", "sure_ay", "ucret_durumu",
            "eşleşen", "eksik", "dil", "son_basvuru", "url", "uid"]
    edited = st.data_editor(
        t[cols], hide_index=True, width="stretch", disabled=[c for c in cols if c != "Durum"],
        column_config={"Durum": st.column_config.SelectboxColumn("Durum", options=DURUMLAR, required=True),
                       "uyum_puani": st.column_config.ProgressColumn("Uyum", min_value=0, max_value=100, format="%d"),
                       "url": st.column_config.LinkColumn("link"), "ulke_son": "Ülke", "uid": None,
                       "title": "İlan", "company": "Şirket", "baslangic": "Başlangıç", "sure_ay": "Ay"},
        key="bugun")
    if st.button("Kaydet", type="primary"):
        today = pd.Timestamp.today().date().isoformat()
        keep = status[~status["uid"].isin(edited["uid"])]
        changed = edited[edited["Durum"] != "Yeni"].merge(f[["uid", "title", "company", "url"]], on="uid",
                                                           suffixes=("_x", ""))
        rows = pd.DataFrame({"uid": changed["uid"], "durum": changed["Durum"], "tarih": today,
                             "title": changed["title"], "company": changed["company"], "url": changed["url"]})
        save_status(pd.concat([keep, rows], ignore_index=True))
        st.session_state.pop("bugun", None)
        st.toast(f"{len(rows)} ilanın durumu kaydedildi.")
        st.rerun()
    with st.expander(f"Başvuru geçmişi ({len(status)})"):
        st.dataframe(status.sort_values("tarih", ascending=False), hide_index=True, width="stretch",
                     column_config={"url": st.column_config.LinkColumn("link"), "uid": None})

# --- Üniversiteler: spekülatif Erasmus+ staj başvurusu hedefleri ----------------
with tabs[2]:
    up = config.DATA_DIR / "universiteler.csv"
    if not up.exists():
        st.info("Liste yok. Önce: `python -m scrapers.universities_wikidata`")
    else:
        uni = pd.read_csv(up).fillna("")
        st.markdown("Üniversiteler staj ilanını iş sitelerinde nadiren yayınlar: **uluslararası ofise veya bir "
                    "laboratuvara doğrudan e-posta** yazılır. Liste Wikidata açık verisinden (SPARQL) çekildi.")
        c = st.columns([2, 2, 1])
        u_ulke = c[0].multiselect("Ülke", sorted(uni["country"].unique()), default=sorted(uni["country"].unique()))
        u_ara = c[1].text_input("Ara (ad / şehir)")
        u_tek = c[2].checkbox("Yalnızca teknik/bilim odaklı", value=False)
        u = uni[uni["country"].isin(u_ulke)]
        if u_ara:
            u = u[u["name"].str.contains(u_ara, case=False) | u["city"].str.contains(u_ara, case=False)]
        if u_tek:
            u = u[u["teknik_odakli"].astype(str).str.lower() == "true"]
        status = load_status()
        u = u.assign(Durum=("uni:" + u["wikidata_id"]).map(dict(zip(status["uid"], status["durum"]))).fillna("Yeni"))
        u["domain"] = u["website"].str.replace(r"^https?://(www\.)?", "", regex=True).str.split("/").str[0]
        u["erasmus_ara"] = "https://www.google.com/search?q=site%3A" + u["domain"] + "+erasmus+incoming+traineeship"
        u["bolum_ara"] = "https://www.google.com/search?q=site%3A" + u["domain"] + "+computer+science+faculty"
        st.dataframe(u[["Durum", "name", "city", "country", "type", "website", "erasmus_ara", "bolum_ara"]],
                     hide_index=True, width="stretch",
                     column_config={"website": st.column_config.LinkColumn("site"),
                                    "erasmus_ara": st.column_config.LinkColumn("Erasmus ofisi", display_text="ara"),
                                    "bolum_ara": st.column_config.LinkColumn("Bölüm", display_text="ara"),
                                    "name": "Üniversite", "city": "Şehir", "country": "Ülke", "type": "Tür"})
        if len(u):
            sel = st.selectbox("Üniversite seç", u.index, format_func=lambda i: f"{u.at[i, 'name']} ({u.at[i, 'city']})")
            b1, b2 = st.columns(2)
            if b1.button("E-posta taslağı oluştur", type="primary"):
                from pipeline.llm_analyze import university_email
                with st.spinner(f"{config.OLLAMA_MODEL} yazıyor..."):
                    try:
                        st.text_area("Taslak", university_email(u.loc[sel].to_dict()), height=360)
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Ollama hatası: {e}")
            if b2.button("Başvurdum olarak işaretle"):
                r = u.loc[sel]
                row = pd.DataFrame([{"uid": "uni:" + r["wikidata_id"], "durum": "Başvurdum",
                                     "tarih": pd.Timestamp.today().date().isoformat(), "title": "Spekülatif başvuru",
                                     "company": r["name"], "url": r["website"]}])
                save_status(pd.concat([status[status["uid"] != row.at[0, "uid"]], row], ignore_index=True))
                st.toast(f"{r['name']} işaretlendi.")
                st.rerun()

# --- 4) Başvuru listesi -----------------------------------------------------
with tabs[3]:
    st.markdown("Filtrelere uyan ilanlar. Başvurmak istediklerini seçip CSV olarak indirebilirsin.")
    t = f.copy()
    t["beceriler"] = t["teknik_beceriler"].apply(", ".join)
    t["dil şartı"] = t["yerel_dil_sarti"].apply(lambda xs: ", ".join(xs) or "Yok")
    cols = ["uyum_puani", "erasmus_son", "donem_uyumu", "title", "company", "ulke_son", "sehir", "ucret_durumu", "aylik_ucret_eur", "sure_ay",
            "dil şartı", "son_basvuru", "beceriler", "ozet", "erasmus_gerekce", "url"]
    t = t[cols].sort_values("uyum_puani", ascending=False)
    t.insert(0, "Seç", False)
    edited = st.data_editor(t, hide_index=True, width="stretch", disabled=cols,
                            column_config={"url": st.column_config.LinkColumn("link"),
                                           "aylik_ucret_eur": st.column_config.NumberColumn("€/ay"),
                                           "erasmus_son": "Erasmus+", "ulke_son": "Ülke"})
    secilen = edited[edited["Seç"]].drop(columns="Seç")
    st.download_button(f"Seçilen {len(secilen)} ilanı CSV indir", secilen.to_csv(index=False).encode("utf-8-sig"),
                       "basvuru_listem.csv", "text/csv", disabled=secilen.empty)

# --- 3) Beceriler -----------------------------------------------------------
with tabs[4]:
    n = st.slider("Gösterilecek beceri sayısı", 5, 30, 15)
    a, b = st.columns([3, 2])
    with a:
        hbar(Counter(x for xs in f["teknik_beceriler"] for x in xs).most_common(n), "En çok istenen teknik beceriler")
    with b:
        hbar(Counter(x for xs in f["sosyal_beceriler"] for x in xs).most_common(10), "Sosyal beceriler")
    rows = []
    for k, g in f.groupby("kategori"):
        if len(g) >= 2:
            top = Counter(x for xs in g["teknik_beceriler"] for x in xs).most_common(5)
            rows.append({"Kategori": k, "İlan": len(g), "Beceriler": ", ".join(f"{s} ({c})" for s, c in top)})
    if rows:
        st.subheader("Kategoriye göre en çok istenen 5 beceri")
        st.dataframe(pd.DataFrame(rows).sort_values("İlan", ascending=False), hide_index=True, width="stretch")

# --- 4) LLM vs anahtar kelime ----------------------------------------------
with tabs[5]:
    st.markdown("**Soru:** LLM, klasik *anahtar kelime sözlüğü* yöntemine göre ne kazandırıyor? "
                "(İlanların çoğu Almanca, Fransızca vb. dillerde — sözlük bunları kaçırabilir.)")
    llm_sets, kw_sets = f["teknik_beceriler"].apply(set), f["keyword_beceriler"].apply(set)
    jac = [len(x & y) / len(x | y) if (x | y) else 1 for x, y in zip(llm_sets, kw_sets)]
    c = st.columns(4)
    c[0].metric("LLM: ilan başı beceri", f"{llm_sets.apply(len).mean():.1f}" if len(f) else "-")
    c[1].metric("Sözlük: ilan başı beceri", f"{kw_sets.apply(len).mean():.1f}" if len(f) else "-")
    c[2].metric("Farklı beceri (LLM / sözlük)", f"{len(set().union(*llm_sets))} / {len(set().union(*kw_sets))}")
    c[3].metric("Ortalama Jaccard benzerliği", f"{pd.Series(jac).mean():.2f}" if jac else "-")
    top = [k for k, _ in Counter(x for xs in llm_sets for x in xs).most_common(12)]
    lc, kc = Counter(x for xs in llm_sets for x in xs), Counter(x for xs in kw_sets for x in xs)
    if top:
        d = pd.DataFrame({"Beceri": top * 2, "İlan sayısı": [lc[k] for k in top] + [kc[k] for k in top],
                          "Yöntem": ["LLM (Ollama)"] * len(top) + ["Anahtar kelime"] * len(top)})
        fig = px.bar(d, y="Beceri", x="İlan sayısı", color="Yöntem", barmode="group", orientation="h",
                     color_discrete_sequence=[BLUE, ORANGE], height=520)
        fig.update_layout(yaxis={"categoryorder": "array", "categoryarray": top[::-1]}, yaxis_title=None)
        st.plotly_chart(fig, width="stretch")
    only = Counter(x for a_, b_ in zip(llm_sets, kw_sets) for x in a_ - b_).most_common(20)
    st.markdown("**Sadece LLM'in bulduğu beceriler:** " + (", ".join(f"{s} ({c})" for s, c in only) or "-"))

# --- 5) Motivasyon mektubu --------------------------------------------------
with tabs[6]:
    st.markdown("Bir ilan seç; LLM, Erasmus+ ipucunu ilk paragrafa koyarak İngilizce bir mektup taslağı yazsın: "
                "*Erasmus+ kapsamında geliyorum, ücret beklentim yok, hibem AB tarafından karşılanıyor.*")
    if len(f):
        sel = st.selectbox("İlan", f.index, format_func=lambda i: f"{f.at[i, 'title']} — {f.at[i, 'company']} ({f.at[i, 'ulke_son']})")
        profile = st.text_area("Kendini kısaca tanıt (mektuba girer)", config.APPLICANT_PROFILE, height=90)
        if st.button("Mektup taslağı oluştur", type="primary"):
            from pipeline.llm_analyze import cover_letter
            with st.spinner(f"{config.OLLAMA_MODEL} yazıyor..."):
                try:
                    st.text_area("Taslak (köşeli parantezleri kendin doldur)", cover_letter(f.loc[sel].to_dict(), profile), height=420)
                except Exception as e:  # noqa: BLE001
                    st.error(f"Ollama hatası: {e}")

# --- 6) Canlı demo ----------------------------------------------------------
with tabs[7]:
    st.markdown("Herhangi bir ilan metnini (her dilde) yapıştır; yerel LLM canlı olarak analiz etsin.")
    txt = st.text_area("İlan metni", height=220, placeholder="Ör: 6-month Data Science Internship in Amsterdam...")
    if st.button("Analiz et") and txt.strip():
        from pipeline.llm_analyze import get_backend
        with st.spinner(f"{config.OLLAMA_MODEL} düşünüyor..."):
            try:
                res, sec = get_backend().analyze(f"Başlık: -\nŞirket: -\n\nİlan metni:\n{txt}")
                st.success(f"{sec:.1f} saniyede analiz edildi")
                st.json(res.model_dump())
            except SystemExit as e:
                st.error(str(e))
            except Exception as e:  # noqa: BLE001
                st.error(f"Ollama hatası: {e}")

# --- 7) Piyasa özeti --------------------------------------------------------
with tabs[8]:
    p = config.OUT_DIR / "pazar_ozeti.md"
    st.markdown(p.read_text(encoding="utf-8") if p.exists() else "Henüz üretilmedi: `python -m pipeline.stats`")
