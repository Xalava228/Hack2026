"""Клиент для AI API ai.rt.ru: LLM, Yandex ART, Stable Diffusion + download."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
import uuid
from urllib.parse import quote_plus
from typing import Any, Literal

import httpx

from . import config

logger = logging.getLogger(__name__)

ImageBackend = Literal["yandex-art", "sd", "internet"]


class AIClientError(RuntimeError):
    pass


class AIClient:
    """Асинхронный клиент к ai.rt.ru."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.token = (token or config.AI_TOKEN).strip()
        self.base_url = (base_url or config.AI_BASE_URL).rstrip("/")
        self.timeout = timeout

    def _require_token(self) -> None:
        if not self.token:
            raise AIClientError(
                "AI_TOKEN не задан. Заполните .env (см. .env.example)."
            )

    @property
    def _headers(self) -> dict[str, str]:
        self._require_token()
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    # ----------------------- LLM -----------------------
    async def chat(
        self,
        user_message: str,
        system_prompt: str = (
            "Ты — профессиональный ассистент по созданию презентаций. "
            "Отвечай чётко, структурированно, на языке запроса."
        ),
        max_new_tokens: int = 2048,
        temperature: float = 0.4,
        model: str | None = None,
    ) -> str:
        """Запрос к Qwen / Llama. Возвращает текстовый ответ."""
        payload = {
            "uuid": str(uuid.uuid4()),
            "chat": {
                "model": model or config.LLM_MODEL,
                "user_message": user_message,
                "contents": [{"type": "text", "text": user_message}],
                "message_template": "<s>{role}\n{content}</s>",
                "response_template": "<s>bot\n",
                "system_prompt": system_prompt,
                "max_new_tokens": max_new_tokens,
                "no_repeat_ngram_size": 15,
                "repetition_penalty": 1.1,
                "temperature": temperature,
                "top_k": 40,
                "top_p": 0.9,
                "chat_history": [],
            },
        }
        url = f"{self.base_url}/llama/chat"
        try:
            r = await self._post_with_retries(url, payload, retries=3, backoff=1.2)
        except Exception as e:
            raise AIClientError(f"Не удалось подключиться к LLM: {e}") from e
        if r.status_code >= 400:
            raise AIClientError(
                f"LLM HTTP {r.status_code}: {r.text[:1000]}"
            )
        data = r.json()
        return _extract_message_content(data)

    async def _post_with_retries(
        self, url: str, payload: dict, retries: int = 3, backoff: float = 1.5
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as cli:
                    r = await cli.post(url, headers=self._headers, json=payload)
                if r.status_code >= 500 or r.status_code == 429:
                    last_exc = AIClientError(f"{url} HTTP {r.status_code}: {r.text[:300]}")
                else:
                    return r
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
                last_exc = e
                logger.warning(
                    "Сетевая ошибка %s (попытка %d/%d): %s",
                    url,
                    attempt + 1,
                    retries,
                    e,
                )
            await asyncio.sleep(backoff * (attempt + 1))
        raise AIClientError(f"Не удалось вызвать {url}: {last_exc}")

    # ----------------- IMAGES (Yandex ART) -----------------
    async def yandex_art(
        self,
        prompt: str,
        aspect: str = "16:9",
        seed: int | None = None,
        translate: bool = True,
    ) -> int:
        """Генерация изображения. Возвращает id, который потом скачивается."""
        payload = {
            "uuid": str(uuid.uuid4()),
            "image": {
                "request": prompt,
                "seed": seed if seed is not None else random.randint(1, 2**31 - 1),
                "translate": translate,
                "model": "yandex-art",
                "aspect": aspect,
            },
        }
        url = f"{self.base_url}/ya/image"
        r = await self._post_with_retries(url, payload)
        if r.status_code >= 400:
            raise AIClientError(f"Yandex ART HTTP {r.status_code}: {r.text[:500]}")
        return _extract_image_id(r.json())

    # --------------- IMAGES (Stable Diffusion) ---------------
    async def stable_diffusion(
        self,
        prompt: str,
        seed: int | None = None,
        translate: bool = True,
    ) -> int:
        """Генерация изображения через SD. Возвращает id."""
        payload = {
            "uuid": str(uuid.uuid4()),
            "sdImage": {
                "request": prompt,
                "seed": seed if seed is not None else random.randint(1, 2**31 - 1),
                "translate": translate,
            },
        }
        url = f"{self.base_url}/sd/img"
        r = await self._post_with_retries(url, payload)
        if r.status_code >= 400:
            raise AIClientError(f"SD HTTP {r.status_code}: {r.text[:500]}")
        return _extract_image_id(r.json())

    # ----------------------- DOWNLOAD -----------------------
    async def download_image(
        self,
        image_id: int,
        service_type: str,
        image_type: str = "png",
        retries: int = 30,
        retry_delay: float = 2.0,
    ) -> bytes:
        """Скачать изображение. Если ещё не готово — повторять с паузой."""
        url = f"{self.base_url}/download"
        params = {
            "id": image_id,
            "serviceType": service_type,
            "imageType": image_type,
        }
        last_status: int | str | None = None
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as cli:
                    r = await cli.get(url, headers=self._headers, params=params)
                last_status = r.status_code
                ctype = r.headers.get("content-type", "")
                if r.status_code == 200 and (
                    ctype.startswith("image/")
                    or r.content[:4]
                    in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"GIF8")
                ):
                    return r.content
                # Для некоторых id сервис сразу отвечает 400/404: такой id уже не станет валидным.
                if r.status_code in (400, 404):
                    raise AIClientError(
                        f"download invalid id={image_id}: HTTP {r.status_code} ({service_type})"
                    )
                logger.info(
                    "Изображение id=%s ещё не готово (status=%s, ctype=%s), попытка %d/%d",
                    image_id,
                    r.status_code,
                    ctype,
                    attempt + 1,
                    retries,
                )
            except (
                httpx.ConnectError,
                httpx.ReadError,
                httpx.RemoteProtocolError,
                httpx.ReadTimeout,
            ) as e:
                last_status = type(e).__name__
                logger.warning(
                    "Сетевая ошибка при скачивании id=%s: %s (попытка %d/%d)",
                    image_id,
                    e,
                    attempt + 1,
                    retries,
                )
            await asyncio.sleep(retry_delay)
        raise AIClientError(
            f"Не удалось скачать изображение id={image_id} (последний статус: {last_status})"
        )

    async def generate_image(
        self,
        prompt: str,
        backend: ImageBackend = "yandex-art",
        aspect: str = "16:9",
    ) -> bytes:
        """Генерация + скачивание одним вызовом. Возвращает bytes картинки."""
        if backend == "internet":
            return await self.download_internet_image(prompt, aspect=aspect)
        # ai.rt иногда возвращает id, который падает на /download c 400.
        # Пробуем пересоздать картинку ещё раз, чтобы не терять слайд.
        last_err: Exception | None = None
        for _attempt in range(2):
            try:
                if backend == "yandex-art":
                    image_id = await self.yandex_art(prompt, aspect=aspect)
                    service_type = "yaArt"
                else:
                    image_id = await self.stable_diffusion(prompt)
                    service_type = "sd"
                return await self.download_image(image_id, service_type)
            except AIClientError as e:
                last_err = e
                logger.warning("Retry image generation due to download/generation error: %s", e)
        raise AIClientError(f"Не удалось сгенерировать изображение после повтора: {last_err}")

    async def download_internet_image(self, query: str, aspect: str = "16:9") -> bytes:
        """Скачать релевантное фото из открытых источников (без API-ключа)."""
        items = await self.internet_image_candidates(query=query, count=1, aspect=aspect)
        if items:
            return items[0]
        raise AIClientError("Не удалось получить интернет-изображение: нет релевантных результатов.")

    def _aspect_size(self, aspect: str) -> tuple[int, int]:
        return (1600, 900) if aspect == "16:9" else (1200, 1200)

    def _tokenize(self, text: str) -> list[str]:
        return [t for t in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", (text or "").lower()) if len(t) >= 3]

    def _query_token_set(self, query: str) -> set[str]:
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "first", "plant",
            "это", "как", "для", "или", "что", "где", "когда", "первый", "завод", "станция",
            "фото", "изображение",
        }
        toks = [t for t in self._tokenize(query) if t not in stop]
        return set(toks)

    def _has_cyrillic(self, text: str) -> bool:
        return any("а" <= ch.lower() <= "я" or ch in "ёЁ" for ch in (text or ""))

    def _transliterate_ru_to_lat(self, text: str) -> str:
        # Простая практичная транслитерация для web-поиска.
        m = {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
            "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
            "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
            "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
            "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        }
        out: list[str] = []
        for ch in text or "":
            low = ch.lower()
            if low in m:
                tr = m[low]
                if ch.isupper() and tr:
                    tr = tr[0].upper() + tr[1:]
                out.append(tr)
            else:
                out.append(ch)
        return "".join(out)

    def _match_score(self, query_tokens: set[str], text: str) -> float:
        if not query_tokens:
            return 0.0
        tt = set(self._tokenize(text))
        if not tt:
            return 0.0
        inter = len(query_tokens & tt)
        return inter / max(1, len(query_tokens))

    async def _wikimedia_image_urls(self, query: str, limit: int, aspect: str) -> list[tuple[str, float]]:
        q = (query or "").strip()
        if not q:
            return []
        w, h = self._aspect_size(aspect)
        q_tokens = self._query_token_set(q)
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": "6",  # File namespace
            "gsrsearch": f"filetype:bitmap {q}",
            "gsrlimit": str(max(6, min(limit * 4, 30))),
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": str(w),
            "iiurlheight": str(h),
            "origin": "*",
        }
        url = "https://commons.wikimedia.org/w/api.php"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as cli:
                r = await cli.get(url, params=params, headers={"User-Agent": "SlideForge/1.0"})
            if r.status_code != 200:
                return []
            data = r.json()
            pages = (((data or {}).get("query") or {}).get("pages") or {})
            ranked: list[tuple[str, float]] = []
            for page in pages.values():
                info = (page.get("imageinfo") or [{}])[0]
                thumb = str(info.get("thumburl") or "").strip()
                original = str(info.get("url") or "").strip()
                cand = thumb or original
                if cand.startswith("http"):
                    title = str(page.get("title") or "")
                    score = self._match_score(q_tokens, title)
                    if q.lower() in title.lower():
                        score += 0.75
                    if score <= 0.0:
                        continue
                    ranked.append((cand, score))
            ranked.sort(key=lambda x: x[1], reverse=True)
            return ranked[: max(limit * 4, 16)]
        except Exception:
            return []

    def _query_variants(self, query: str) -> list[str]:
        q = (query or "").strip()
        if not q:
            return []
        variants = [q]
        # Упрощенный вариант для более широкого поиска.
        compact = " ".join(part for part in q.replace(",", " ").split() if len(part) > 2)
        if compact and compact.lower() != q.lower():
            variants.append(compact)
        # Для исторических/сложных запросов часто полезны "photo"/"site"/"building".
        if self._has_cyrillic(q):
            variants.append(f"{q} фото")
            variants.append(f"{q} объект")
            tr = self._transliterate_ru_to_lat(q).strip()
            if tr and tr.lower() != q.lower():
                variants.append(tr)
                variants.append(f"{tr} photo")
        else:
            variants.append(f"{q} photo")
            variants.append(f"{q} building")
        # Удаляем дубли, сохраняя порядок.
        seen: set[str] = set()
        out: list[str] = []
        for v in variants:
            key = v.lower().strip()
            if key and key not in seen:
                seen.add(key)
                out.append(v.strip())
        return out[:4]

    async def _openverse_image_urls(self, query: str, limit: int, aspect: str) -> list[str]:
        q = (query or "").strip()
        if not q:
            return []
        w, h = self._aspect_size(aspect)
        openverse_q = q
        if self._has_cyrillic(q):
            # Openverse часто хуже ранжирует кириллицу, даём транслитерацию.
            openverse_q = self._transliterate_ru_to_lat(q) or q
        params = {
            "q": openverse_q,
            "page_size": str(max(10, min(limit * 6, 40))),
            "license_type": "commercial",
            "mature": "false",
            "extension": "jpg,png,webp",
            "source": "flickr,wikimedia",
            "aspect_ratio": "wide" if aspect == "16:9" else "square",
        }
        url = "https://api.openverse.org/v1/images/"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as cli:
                r = await cli.get(url, params=params, headers={"User-Agent": "SlideForge/1.0"})
            if r.status_code == 401:
                logger.warning("Openverse returned 401, skipping this source.")
                return []
            if r.status_code != 200:
                return []
            data = r.json()
            results = data.get("results") or []
            out: list[str] = []
            for row in results:
                if not isinstance(row, dict):
                    continue
                iw = int(row.get("width") or 0)
                ih = int(row.get("height") or 0)
                if iw > 0 and ih > 0 and (iw < max(700, w // 2) or ih < max(500, h // 2)):
                    continue
                cand = str(row.get("url") or row.get("thumbnail") or "").strip()
                if cand.startswith("http"):
                    out.append(cand)
            return out[: max(limit * 3, 15)]
        except Exception:
            return []

    def _fallback_image_urls(self, query: str, limit: int, aspect: str) -> list[str]:
        q = (query or "technology presentation").strip()
        w, h = self._aspect_size(aspect)
        urls: list[str] = []
        for i in range(max(6, limit * 3)):
            sig = hashlib.sha1(f"{q}-{i}".encode("utf-8")).hexdigest()[:12]
            # picsum остаётся только как последний резервный источник.
            urls.append(f"https://picsum.photos/seed/{sig}/{w}/{h}")
        return urls

    async def internet_image_candidates(self, query: str, count: int = 6, aspect: str = "16:9") -> list[bytes]:
        q = (query or "technology presentation").strip()
        count = max(1, min(int(count), 12))
        out: list[bytes] = []
        seen_hashes: set[str] = set()
        seen_urls: set[str] = set()

        ranked_urls: list[tuple[str, float]] = []
        ranked_urls.extend((u, 2.0) for u in await self._openverse_image_urls(q, count, aspect))
        for qv in self._query_variants(q):
            ranked_urls.extend(await self._wikimedia_image_urls(qv, count, aspect))
        ranked_urls.extend((u, -0.2) for u in self._fallback_image_urls(q, count, aspect))

        sem = asyncio.Semaphore(6)

        async def _fetch_one(cli: httpx.AsyncClient, url: str) -> bytes | None:
            async with sem:
                try:
                    r = await cli.get(url, headers={"User-Agent": "SlideForge/1.0"})
                    ctype = r.headers.get("content-type", "")
                    final_url = str(r.url)
                    if "defaultImage.small" in final_url:
                        return None
                    if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) < 2048:
                        return None
                    return r.content
                except Exception:
                    return None

        ranked_urls.sort(key=lambda x: x[1], reverse=True)
        unique_urls = [u for u, _s in ranked_urls if not (u in seen_urls or seen_urls.add(u))]
        # Не тратим время на слишком длинный хвост ссылок.
        unique_urls = unique_urls[:120]

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as cli:
            tasks = [asyncio.create_task(_fetch_one(cli, url)) for url in unique_urls]
            for fut in asyncio.as_completed(tasks):
                data = await fut
                if not data:
                    continue
                dig = hashlib.sha1(data).hexdigest()
                if dig in seen_hashes:
                    continue
                seen_hashes.add(dig)
                out.append(data)
                if len(out) >= count:
                    break
        return out


# ----------------- helpers -----------------
def _extract_message_content(data) -> str:
    """API возвращает массив объектов с message.content."""
    if isinstance(data, list) and data:
        first = data[0]
        msg = first.get("message") if isinstance(first, dict) else None
        if isinstance(msg, dict):
            return str(msg.get("content", "")).strip()
    if isinstance(data, dict):
        msg = data.get("message")
        if isinstance(msg, dict):
            return str(msg.get("content", "")).strip()
        if "content" in data:
            return str(data["content"]).strip()
    raise AIClientError(f"Неожиданный ответ LLM: {data!r}")


def _extract_image_id(data) -> int:
    if isinstance(data, list) and data:
        first = data[0]
        msg = first.get("message") if isinstance(first, dict) else None
        if isinstance(msg, dict) and "id" in msg:
            return int(msg["id"])
    if isinstance(data, dict):
        msg = data.get("message")
        if isinstance(msg, dict) and "id" in msg:
            return int(msg["id"])
        if "id" in data:
            return int(data["id"])
    raise AIClientError(f"Не найден id изображения: {data!r}")
