"""Клиент для AI API ai.rt.ru: LLM, Yandex ART, Stable Diffusion + download."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import uuid
from urllib.parse import quote_plus
from typing import Literal

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
        if not self.token:
            raise AIClientError(
                "AI_TOKEN не задан. Заполните .env (см. .env.example)."
            )
        self.base_url = (base_url or config.AI_BASE_URL).rstrip("/")
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
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
        if backend == "yandex-art":
            image_id = await self.yandex_art(prompt, aspect=aspect)
            service_type = "yaArt"
        else:
            image_id = await self.stable_diffusion(prompt)
            service_type = "sd"
        return await self.download_image(image_id, service_type)

    async def download_internet_image(self, query: str, aspect: str = "16:9") -> bytes:
        """Скачать фото из открытых источников (без API-ключа)."""
        q = quote_plus((query or "technology presentation").strip())
        w, h = (1600, 900) if aspect == "16:9" else (1200, 1200)
        seed = hashlib.sha1(q.encode("utf-8")).hexdigest()[:12]
        urls = [
            f"https://picsum.photos/seed/{seed}/{w}/{h}",
            f"https://loremflickr.com/{w}/{h}/{q}",
        ]
        last_err = ""
        for url in urls:
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as cli:
                    r = await cli.get(url, headers={"User-Agent": "SlideForge/1.0"})
                ctype = r.headers.get("content-type", "")
                if r.status_code == 200 and ctype.startswith("image/") and len(r.content) > 1024:
                    return r.content
                last_err = f"{url} status={r.status_code} ctype={ctype}"
            except Exception as e:
                last_err = f"{url} error={e}"
        raise AIClientError(f"Не удалось получить интернет-изображение: {last_err}")

    async def internet_image_candidates(self, query: str, count: int = 6, aspect: str = "16:9") -> list[bytes]:
        q = (query or "technology presentation").strip()
        count = max(1, min(int(count), 12))
        w, h = (1600, 900) if aspect == "16:9" else (1200, 1200)
        out: list[bytes] = []
        seen: set[str] = set()
        base_seeds = [hashlib.sha1(f"{q}-{i}".encode("utf-8")).hexdigest()[:12] for i in range(count * 2)]
        urls: list[str] = []
        for seed in base_seeds:
            urls.append(f"https://picsum.photos/seed/{seed}/{w}/{h}")
            urls.append(f"https://loremflickr.com/{w}/{h}/{quote_plus(q)}?lock={seed}")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as cli:
            for url in urls:
                if len(out) >= count:
                    break
                try:
                    r = await cli.get(url, headers={"User-Agent": "SlideForge/1.0"})
                    ctype = r.headers.get("content-type", "")
                    if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) < 1024:
                        continue
                    dig = hashlib.sha1(r.content).hexdigest()
                    if dig in seen:
                        continue
                    seen.add(dig)
                    out.append(r.content)
                except Exception:
                    continue
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
