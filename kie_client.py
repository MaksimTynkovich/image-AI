from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import asyncio
import json

import httpx

from config import get_settings


settings = get_settings()


@dataclass
class GeneratedImage:
    """Represents a generated image (single URL)."""

    url: str


class KieClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.kie.base_url,
            headers={
                "Authorization": f"Bearer {settings.kie.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "auto",
        resolution: str = "1K",
        output_format: str = "png",
        image_urls: Optional[List[str]] = None,
    ) -> GeneratedImage:
        """Create image generation task and wait for result.

        1. POST /api/v1/jobs/createTask  -> get taskId
        2. Poll  /api/v1/jobs/recordInfo -> get resultUrls[0]

        Based on official docs:
        - Nano Banana Pro: https://docs.kie.ai/market/google/pro-image-to-image
        - Get Task Details: https://docs.kie.ai/market/common/get-task-detail
        """

        payload: Dict[str, Any] = {
            "model": settings.kie.model,
            "callBackUrl": settings.kie.callback_url,
            "input": {
                "prompt": prompt,
                "image_input": image_urls or [],
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "output_format": output_format,
            },
        }

        create_resp = await self._client.post("/jobs/createTask", json=payload)
        create_resp.raise_for_status()
        create_data = create_resp.json()

        try:
            task_id = create_data["data"]["taskId"]
        except Exception:
            raise RuntimeError(
                "Не удалось получить taskId из ответа Kie.ai при создании задачи.\n"
                f"Ответ: {create_data}"
            )

        image_url = await self._wait_for_task_result(task_id)
        return GeneratedImage(url=image_url)

    async def _wait_for_task_result(self, task_id: str) -> str:
        """Poll Get Task Details endpoint until task completes, then return first result URL."""

        # Небольшой backoff по рекомендациям Kie.ai
        # https://docs.kie.ai/market/common/get-task-detail
        poll_interval = 2.0
        max_attempts = 30

        for _ in range(max_attempts):
            resp = await self._client.get(
                "/jobs/recordInfo",
                params={"taskId": task_id},
            )
            resp.raise_for_status()
            data = resp.json()

            if not isinstance(data, dict) or "data" not in data:
                raise RuntimeError(
                    "Неожиданная структура ответа при получении статуса задачи Kie.ai.\n"
                    f"Ответ: {data}"
                )

            task = data["data"]
            state = task.get("state")

            if state in ("waiting", "queuing", "generating", None):
                await asyncio.sleep(poll_interval)
                continue

            if state == "fail":
                fail_code = task.get("failCode", "")
                fail_msg = task.get("failMsg", "")
                raise RuntimeError(
                    f"Генерация на Kie.ai завершилась с ошибкой "
                    f"(state=fail, code={fail_code}, msg={fail_msg})."
                )

            if state == "success":
                result_json_str = task.get("resultJson")
                if not result_json_str:
                    raise RuntimeError(
                        "Задача завершилась успешно, но поле resultJson отсутствует или пусто.\n"
                        f"Ответ: {data}"
                    )

                try:
                    result_obj = json.loads(result_json_str)
                except json.JSONDecodeError:
                    raise RuntimeError(
                        "Не удалось распарсить resultJson из ответа Kie.ai.\n"
                        f"resultJson: {result_json_str}"
                    )

                urls: List[str] = result_obj.get("resultUrls") or []
                if not urls:
                    raise RuntimeError(
                        "В resultJson нет ссылок на изображения (resultUrls пустой).\n"
                        f"resultJson: {result_obj}"
                    )

                return urls[0]

            # Неожиданное состояние
            raise RuntimeError(
                f"Неизвестное состояние задачи Kie.ai: {state}. Ответ: {data}"
            )

        raise RuntimeError(
            f"Не удалось дождаться завершения задачи Kie.ai (taskId={task_id}). "
            "Попробуй ещё раз позже."
        )

    async def aclose(self) -> None:
        await self._client.aclose()

