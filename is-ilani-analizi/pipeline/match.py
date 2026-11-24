"""
Aday-ilan uyum puanı (0-100)
===========================
LLM'in her ilandan çıkardığı yapılandırılmış bilgiler + adayın CV'den alınan becerileri (config.MY_SKILLS)
birleştirilerek her ilana şeffaf, kurala dayalı bir puan verilir. Panelde "Bugünün Listesi" bu puana göre sıralanır.

| Ölçüt                    | Puan |
|--------------------------|------|
| Erasmus+ uygunluğu       | Uygun 30 · Muhtemelen 15 · Değil 0 |
| Dönem (Haziran 2027)     | Uyumlu 20 · Belirsiz 10 · Uyumsuz 0 |
| Dil (İngilizce yeterli)  | 15 (zorunlu yerel dil yoksa) |
| Beceri eşleşmesi         | 0-25 (ilanın istediği becerilerin ne kadarı adayda var) |
| Seviye                   | Stajyer / öğrenci işi 10 |
"""
from __future__ import annotations

import pandas as pd

import config
from pipeline.skills import canonical

MY = {canonical(s).lower() for s in config.MY_SKILLS}


def _norm(xs) -> list[str]:
    return [canonical(x) for x in (xs or []) if canonical(x)]


def score_row(r) -> tuple[int, list[str], list[str]]:
    skills = _norm(r["teknik_beceriler"])
    matched = [s for s in skills if s.lower() in MY]
    missing = [s for s in skills if s.lower() not in MY]
    p = {"Uygun": 30, "Muhtemelen uygun": 15}.get(r.get("erasmus_son", ""), 0)
    p += {"Uyumlu": 20, "Belirsiz": 10}.get(r.get("donem_uyumu", ""), 0)
    eng = str(r.get("ingilizce_yeterli")).lower() == "true"
    if eng and not (r.get("yerel_dil_sarti") or []):
        p += 15
    if skills:
        p += round(25 * len(matched) / min(len(skills), 5)) if len(matched) < 5 else 25
    else:
        p += 8                                   # beceri yazmıyorsa nötr puan
    if r.get("seviye") in ("Stajyer", "Öğrenci işi (Werkstudent vb.)"):
        p += 10
    return min(p, 100), matched, missing


def add_scores(df: pd.DataFrame) -> pd.DataFrame:
    res = df.apply(score_row, axis=1, result_type="expand")
    df["uyum_puani"], df["eslesen_beceriler"], df["eksik_beceriler"] = res[0], res[1], res[2]
    return df
