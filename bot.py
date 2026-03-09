import asyncio
import logging
from typing import List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

from config import get_settings
from kie_client import KieClient
from db import (
    AsyncSessionLocal,
    init_db,
    get_or_create_user,
    create_image_request,
    update_image_request_status,
)
import httpx


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


settings = get_settings()
bot = Bot(token=settings.bot.token)
dp = Dispatcher()
kie_client = KieClient()
user_states: dict[int, str] = {}


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Сгенерировать картинку", callback_data="generate_image")],
            [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
        ]
    )

    text = (
        "Привет! 👋\n\n"
        "Я твой помощник по творчеству с ИИ.\n"
        "Сейчас я умею создавать красивые картинки по описанию.\n\n"
        "Нажми кнопку *«Сгенерировать картинку»*, чтобы начать."
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Сгенерировать картинку", callback_data="generate_image")],
        ]
    )

    text = (
        "✨ *Как пользоваться ботом*\n\n"
        "1. Нажми кнопку *«Сгенерировать картинку»*.\n"
        "2. Отправь *текст* или *фото с подписью* — это будет описание для ИИ.\n"
        "3. Подожди несколько секунд — и я пришлю готовое изображение.\n\n"
        "В будущем здесь появятся и другие разделы: текст, видео и многое другое."
    )
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@dp.message(Command("imagine"))
async def cmd_imagine(message: Message) -> None:
    prompt = message.text.removeprefix("/imagine").strip()

    if not prompt:
        await message.answer(
            "После команды напиши, какую картинку хочешь получить.\n\n"
            "Например:\n"
            "/imagine банан‑супергерой на обложке комикса",
        )
        return

    await _handle_image_generation(message, prompt)


@dp.callback_query(F.data == "generate_image")
async def handle_generate_button(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        await callback.answer()
        return

    user_states[callback.from_user.id] = "awaiting_prompt_or_photo"
    await callback.message.answer(
        "Опиши, какую картинку ты хочешь.\n\n"
        "Можно просто текст, а можно *фото с подписью* как референс.\n\n"
        "Например: *«банан‑супергерой в стиле неонового комикса»*.",
        parse_mode="Markdown",
    )
    await callback.answer()


@dp.callback_query(F.data == "help")
async def handle_help_button(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await cmd_help(callback.message)


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(message: Message) -> None:
    user_id = message.from_user.id
    state = user_states.get(user_id)

    # Пользователь сначала должен нажать кнопку "Сгенерировать картинку"
    if state != "awaiting_prompt_or_photo":
        await message.answer(
            "Чтобы создать изображение, нажми кнопку *«Сгенерировать картинку»* под моим сообщением.",
            parse_mode="Markdown",
        )
        await cmd_start(message)
        return

    prompt = message.text.strip()
    if not prompt:
        await message.answer(
            "Пожалуйста, напиши короткое описание будущей картинки.",
        )
        return

    # Сбрасываем состояние и генерируем
    user_states.pop(user_id, None)
    await _handle_image_generation(message, prompt)


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if state != "awaiting_prompt_or_photo":
        await message.answer(
            "Сначала нажми кнопку *«Сгенерировать картинку»*, а затем пришли фото с подписью.",
            parse_mode="Markdown",
        )
        await cmd_start(message)
        return

    caption = (message.caption or "").strip()
    if not caption:
        await message.answer(
            "Добавь, пожалуйста, короткое текстовое описание в подпись к фото и пришли ещё раз.",
        )
        return

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{settings.bot.token}/{file.file_path}"

    user_states.pop(user_id, None)
    await _handle_image_generation(message, caption, image_urls=[file_url])


async def _handle_image_generation(
    message: Message,
    prompt: str,
    image_urls: Optional[List[str]] = None,
) -> None:
    waiting_msg = await message.answer(
        "Создаю картинку… ⏳\n\n"
        "Прогресс: 0%\n"
        "🟥🟥🟥🟥🟥",
    )

    stop_event = asyncio.Event()
    upload_event = asyncio.Event()

    async def send_chat_actions() -> None:
        try:
            while not stop_event.is_set():
                # Ждём, пока индикатор прогресса не заполнится на 100%
                await upload_event.wait()
                if stop_event.is_set():
                    break

                # После 100% показываем, что бот "отправляет фото"
                await bot.send_chat_action(message.chat.id, "upload_photo")
                await asyncio.sleep(4)
        except Exception:
            # Любые ошибки здесь не должны ломать основную логику
            pass

    async def update_progress_bar() -> None:
        total_seconds = 30.0
        segments = 5
        last_green = -1

        try:
            loop = asyncio.get_running_loop()
            start = loop.time()

            while not stop_event.is_set():
                now = loop.time()
                elapsed = now - start
                progress = max(0.0, min(1.0, elapsed / total_seconds))
                green = int(progress * segments)
                if green > segments:
                    green = segments
                red = segments - green

                if green != last_green:
                    last_green = green
                    bar = "🟩" * green + "🟥" * red
                    percent = green * (100 // segments)
                    text = (
                        "Создаю картинку… ⏳\n\n"
                        f"Прогресс: {percent}%\n"
                        f"{bar}"
                    )

                    # Как только все сегменты стали зелёными — запускаем "отправку фото"
                    if green == segments:
                        upload_event.set()

                    try:
                        await waiting_msg.edit_text(text)
                    except Exception:
                        # Сообщение могли удалить/изменить — не критично
                        pass

                await asyncio.sleep(2)
        except Exception:
            # Любые ошибки в индикаторе прогресса игнорируем
            pass

    chat_action_task = asyncio.create_task(send_chat_actions())
    progress_task = asyncio.create_task(update_progress_bar())

    request_id: Optional[int] = None

    try:
        # Логируем пользователя и запрос в БД
        async with AsyncSessionLocal() as session:
            tg_user = message.from_user
            db_user = await get_or_create_user(
                session=session,
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
            )
            req = await create_image_request(
                session=session,
                user=db_user,
                prompt=prompt,
                image_urls=image_urls,
                status="pending",
            )
            request_id = req.id
            await session.commit()

        generated = await kie_client.generate_image(
            prompt=prompt,
            aspect_ratio="auto",
            resolution="1K",
            output_format="png",
            image_urls=image_urls,
        )

        # Скачиваем изображение по ссылке и отправляем в Telegram
        async with httpx.AsyncClient() as client:
            resp = await client.get(generated.url)
            resp.raise_for_status()
            image_bytes = resp.content

        photo = BufferedInputFile(image_bytes, filename="generated.png")

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎨 Сгенерировать ещё",
                        callback_data="generate_image",
                    )
                ]
            ]
        )

        await message.answer_photo(
            photo=photo,
            caption=(
                "Готово! ✨\n\n"
                "Если хочешь ещё одну картинку — нажми кнопку ниже."
            ),
            reply_markup=keyboard,
        )

    except Exception as exc:
        logger.exception("Ошибка при генерации изображения: %s", exc)
        # Обновляем статус запроса в БД
        if request_id is not None:
            try:
                async with AsyncSessionLocal() as session:
                    await update_image_request_status(
                        session=session,
                        request_id=request_id,
                        status="fail",
                        error_message=str(exc)[:1000],
                    )
                    await session.commit()
            except Exception:
                logger.exception("Не удалось обновить статус запроса в БД")

        await message.answer(
            "Не получилось создать картинку 😔\n"
            "Попробуй ещё раз чуть позже или измени описание.",
        )
    finally:
        stop_event.set()
        try:
            await chat_action_task
        except Exception:
            pass
        try:
            await progress_task
        except Exception:
            pass
        try:
            await waiting_msg.delete()
        except Exception:
            pass


async def main() -> None:
    logger.info("Инициализация БД…")
    await init_db()
    logger.info("Запуск бота…")
    try:
        await dp.start_polling(bot)
    finally:
        await kie_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())

