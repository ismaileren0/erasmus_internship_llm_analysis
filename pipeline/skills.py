"""
Beceri sözlüğü: (1) LLM çıktısındaki farklı yazımları tek isme indirger  ("python3" -> "Python")
                (2) Klasik (LLM'siz) anahtar kelime yönteminin sözlüğü olarak kullanılır.
"""
from __future__ import annotations

import re

# kanonik ad -> metinde aranacak düzenli ifadeler
SKILL_PATTERNS: dict[str, list[str]] = {
    "Python": [r"python\d?"],
    "Java": [r"java(?!\s*script)"],
    "JavaScript": [r"javascript", r"\bjs\b"],
    "TypeScript": [r"typescript"],
    "C#": [r"c#", r"c sharp"],
    "C/C++": [r"c\+\+", r"\bc/c\+\+"],
    ".NET": [r"\.net\b", r"asp\.net", r"dotnet"],
    "Go": [r"\bgolang\b", r"\bgo\b(?= (?:dili|language|programming))"],
    "Kotlin": [r"kotlin"],
    "Swift": [r"\bswift\b"],
    "PHP": [r"\bphp\b"],
    "SQL": [r"\bsql\b", r"t-sql", r"pl/sql", r"mysql", r"postgres\w*", r"ms ?sql"],
    "NoSQL": [r"nosql", r"mongodb", r"redis", r"cassandra"],
    "React": [r"react(?:\.js|js)?\b"],
    "Angular": [r"angular"],
    "Vue": [r"vue(?:\.js)?"],
    "Node.js": [r"node(?:\.js|js)\b"],
    "Spring": [r"spring(?: boot)?"],
    "Django/Flask": [r"django", r"flask", r"fastapi"],
    "HTML/CSS": [r"\bhtml5?\b", r"\bcss3?\b"],
    "Git": [r"\bgit\b", r"github", r"gitlab"],
    "Docker": [r"docker"],
    "Kubernetes": [r"kubernetes", r"\bk8s\b"],
    "Linux": [r"linux", r"unix"],
    "Bulut (AWS/Azure/GCP)": [r"\baws\b", r"amazon web services", r"azure", r"\bgcp\b", r"google cloud"],
    "Makine Öğrenmesi": [r"machine learning", r"makine öğren\w*", r"\bml\b"],
    "Derin Öğrenme": [r"deep learning", r"derin öğren\w*", r"tensorflow", r"pytorch", r"keras"],
    "Yapay Zeka / LLM": [r"yapay zek\w*", r"artificial intelligence", r"\bai\b", r"\bllm\w*", r"generative ai", r"üretken yapay"],
    "Veri Analizi": [r"data analy\w*", r"veri analiz\w*", r"pandas", r"numpy"],
    "Power BI / Tableau": [r"power ?bi", r"tableau", r"qlik"],
    "Excel": [r"excel"],
    "MS Office": [r"ms office", r"microsoft office", r"office programlar\w*"],
    "SAP": [r"\bsap\b"],
    "REST API": [r"rest(?:ful)? api", r"\bapi\b"],
    "Mikroservis": [r"microservice\w*", r"mikroservis\w*"],
    "CI/CD": [r"ci/cd", r"jenkins", r"devops"],
    "Agile/Scrum": [r"agile", r"scrum", r"çevik"],
    "Test/QA": [r"unit test\w*", r"selenium", r"\bqa\b", r"test otomasyon\w*"],
    "Computer Vision": [r"computer vision", r"opencv", r"image processing", r"görüntü işleme", r"mediapipe"],
    "Web Scraping": [r"web scraping", r"scraping", r"crawler"],
    "Siber Güvenlik": [r"cyber ?security", r"siber güvenlik", r"güvenlik test\w*"],
    "Figma/UI-UX": [r"figma", r"ui/ux", r"\bux\b", r"kullanıcı deneyimi"],
    "AutoCAD": [r"autocad", r"solidworks", r"catia"],
    "Dijital Pazarlama": [r"digital marketing", r"dijital pazarlama", r"\bseo\b", r"google ads", r"sosyal medya"],
}

_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in SKILL_PATTERNS.items()}


def keyword_skills(text: str) -> list[str]:
    """Klasik yöntem: metinde sözlükteki kalıpları arar."""
    text = text or ""
    return sorted(k for k, pats in _COMPILED.items() if any(p.search(text) for p in pats))


def canonical(skill: str) -> str:
    """LLM'in yazdığı beceri adını sözlükteki kanonik ada çevirir; sözlükte yoksa düzgün yazar."""
    s = (skill or "").strip().strip(".,;")
    if not s:
        return ""
    for k, pats in _COMPILED.items():
        if s.lower() == k.lower() or any(p.fullmatch(s) for p in pats):
            return k
    for k, pats in _COMPILED.items():                 # "Python programlama" -> Python
        if any(p.search(s) for p in pats) and len(s) <= 30:
            return k
    return s[:1].upper() + s[1:]


def grounded(skill: str, text: str) -> bool:
    """Dayanak (grounding) kontrolü: LLM'in yazdığı beceri ilan metninde gerçekten geçiyor mu?
    Sözlükteki kalıplardan biri ya da becerinin kendi adı metinde aranır. Geçmiyorsa LLM
    büyük olasılıkla 'halüsinasyon' üretmiştir (ör. perakende stajına 'SQL' yazmak)."""
    if not skill:
        return False
    c = canonical(skill)
    if c in _COMPILED and any(p.search(text or "") for p in _COMPILED[c]):
        return True
    low = (text or "").lower()
    return skill.lower() in low or c.lower() in low
