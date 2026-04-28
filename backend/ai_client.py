"""Клиент для AI API ai.rt.ru: LLM, Yandex ART, Stable Diffusion + download."""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from typing import Literal

import httpx

from . import config

logger = logging.getLogger(__name__)

ImageBackend = Literal["yandex-art", "sd"]


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
        async with httpx.AsyncClient(timeout=self.timeout) as cli:
            r = await cli.post(url, headers=self._headers, json=payload)
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
        if backend == "yandex-art":
            image_id = await self.yandex_art(prompt, aspect=aspect)
            service_type = "yaArt"
        else:
            image_id = await self.stable_diffusion(prompt)
            service_type = "sd"
        return await self.download_image(image_id, service_type)


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
