"""Простая web-справка для улучшения качества плана слайдов."""
from __future__ import annotations

from urllib.parse import quote_plus

import httpx


async def _duckduckgo_summary(query: str, timeout: float = 20.0) -> list[str]:
    url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&no_redirect=1"
    async with httpx.AsyncClient(timeout=timeout) as cli:
        r = await cli.get(url)
    if r.status_code != 200:
        return []
    data = r.json()
    out: list[str] = []
    abs_text = str(data.get("AbstractText") or "").strip()
    if abs_text:
        out.append(abs_text)
    rel = data.get("RelatedTopics") or []
    if isinstance(rel, list):
        for item in rel:
            if isinstance(item, dict):
                txt = str(item.get("Text") or "").strip()
                if txt:
                    out.append(txt)
            if len(out) >= 4:
                break
    return out[:4]


async def _wiki_summary(query: str, timeout: float = 20.0) -> list[str]:
    # 1) Поиск страницы
    search_url = (
        "https://ru.wikipedia.org/w/api.php?action=query&list=search&utf8=1&format=json"
        f"&srlimit=2&srsearch={quote_plus(query)}"
    )
    async with httpx.AsyncClient(timeout=timeout) as cli:
        r = await cli.get(search_url)
    if r.status_code != 200:
        return []
    data = r.json()
    found = data.get("query", {}).get("search", [])
    if not isinstance(found, list) or not found:
        return []
    out: list[str] = []
    async with httpx.AsyncClient(timeout=timeout) as cli:
        for item in found[:2]:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            s_url = f"https://ru.wikipedia.org/api/rest_v1/page/summary/{quote_plus(title)}"
            rr = await cli.get(s_url)
            if rr.status_code != 200:
                continue
            jd = rr.json()
            extract = str(jd.get("extract") or "").strip()
            if extract:
                out.append(f"{title}: {extract}")
    return out[:2]


async def collect_web_context(query: str) -> str:
    """Собрать короткий блок фактов из web-источников для LLM."""
    query = (query or "").strip()
    if len(query) < 3:
        return ""
    facts: list[str] = []
    for chunk in (await _duckduckgo_summary(query)) + (await _wiki_summary(query)):
        txt = " ".join(chunk.split())
        if txt and txt not in facts:
            facts.append(txt)
        if len(facts) >= 5:
            break
    if not facts:
        return ""
    bullets = "\n".join(f"- {x}" for x in facts)
    return (
        "СВЕЖАЯ СПРАВКА ИЗ ИНТЕРНЕТА (используй аккуратно, без копипасты, без выдумок):\n"
        f"{bullets}\n"
    )
