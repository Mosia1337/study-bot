"""
Study Assistant Bot

Перед запуском:
1. Создайте файл .env с токеном бота
2. Установите Tesseract OCR (инструкция в README)
"""

import os
import asyncio
import logging
import sqlite3
import pytesseract
import wikipediaapi
import aiohttp
import sys
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv(dotenv_path='.env')

# Проверка токена
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("Токен бота не найден в файле .env")
    print("ОШИБКА: Токен бота не найден в файле .env")
    print("Создайте файл .env в папке с ботом и добавьте строку:")
    print("BOT_TOKEN=ваш_токен_бота")
    sys.exit(1)

# Настройка бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Инициализация состояний пользователя
user_states = {}


# База данных SQLite
def init_db():
    try:
        with sqlite3.connect('study_bot.db') as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users
                         (
                             user_id
                             INTEGER
                             PRIMARY
                             KEY,
                             last_active
                             TEXT
                         )''')
            c.execute('''CREATE TABLE IF NOT EXISTS summaries
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             user_id
                             INTEGER,
                             topic
                             TEXT,
                             content
                             TEXT,
                             created_at
                             TEXT
                             DEFAULT
                             CURRENT_TIMESTAMP
                         )''')
            conn.commit()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")


# Инициализация базы данных
init_db()


# Клавиатура
def study_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📝 Сделать конспект"))
    builder.add(KeyboardButton(text="🔍 Найти информацию"))
    builder.add(KeyboardButton(text="🖼️ Решить по фото"))
    builder.add(KeyboardButton(text="📚 Мои конспекты"))
    builder.add(KeyboardButton(text="🧮 Калькулятор формул"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


# Обработчики команд
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    try:
        with sqlite3.connect('study_bot.db') as conn:
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO users (user_id, last_active) VALUES (?, ?)",
                      (user_id, datetime.now().isoformat()))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при добавлении пользователя: {e}")

    await message.answer(
        "📚 Привет! Я твой бесплатный учебный помощник.\n"
        "Выбери действие:",
        reply_markup=study_keyboard()
    )


# Генерация конспекта с помощью Wikipedia
async def generate_summary(topic: str) -> str:
    try:
        # Используем Wikipedia API
        wiki = wikipediaapi.Wikipedia('ru', timeout=10)
        page = wiki.page(topic)

        if not page.exists():
            return "😢 Не удалось найти информацию по этой теме. Попробуйте уточнить запрос."

        # Формируем структурированный конспект
        sections = []
        for section in page.sections:
            sections.append(f"## {section.title}\n{section.text[:500]}...")

        return f"📘 Конспект по теме '{topic}':\n\n" + "\n\n".join(sections[:5])  # Ограничиваем 5 разделами
    except Exception as e:
        logger.error(f"Ошибка Wikipedia: {e}")
        return "⚠️ Ошибка получения данных. Попробуйте другую тему."


# Поиск информации
async def search_info(query: str) -> str:
    try:
        # Используем бесплатный API DuckDuckGo
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_redirect": 1,
                        "no_html": 1,
                        "skip_disambig": 1
                    },
                    timeout=10
            ) as response:
                data = await response.json()

        abstract_text = data.get('AbstractText', '')
        if not abstract_text:
            return "🔍 Информация не найдена. Попробуйте сформулировать запрос иначе."

        source = data.get('AbstractURL', 'DuckDuckGo')
        return f"🔍 Результаты по запросу '{query}':\n\n{abstract_text}\n\nИсточник: {source}"
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Ошибка поиска: {e}")
        return "⚠️ Ошибка поиска. Попробуйте позже."


# Распознавание текста с фото
async def ocr_from_photo(image_path: str) -> str:
    try:
        # Кросс-платформенная настройка Tesseract
        tesseract_cmd = os.getenv("TESSERACT_CMD")
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        else:
            # Автоопределение для Linux/Mac
            if sys.platform != 'win32':
                pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

        text = pytesseract.image_to_string(Image.open(image_path), lang='rus+eng')
        return text.strip() or "Не удалось распознать текст на фото"
    except (FileNotFoundError, UnidentifiedImageError, pytesseract.TesseractError) as e:
        logger.error(f"Ошибка OCR: {e}")
        error_msg = "Ошибка обработки изображения. "
        if isinstance(e, FileNotFoundError):
            error_msg += "Убедитесь, что Tesseract установлен и путь указан в TESSERACT_CMD"
        return error_msg


# Решение математических задач
async def solve_math_problem(text: str) -> str:
    try:
        # Используем бесплатный API Wolfram Alpha (демо-режим)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    "https://api.wolframalpha.com/v1/result",
                    params={"i": text, "appid": "DEMO"},
                    timeout=15
            ) as response:
                if response.status == 501:
                    return "🤔 Не могу решить эту задачу. Попробуйте сформулировать проще."

                solution = await response.text()
                return f"🧮 Решение:\n{solution}"
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Ошибка решения задачи: {e}")
        return "⚠️ Ошибка решения задачи. Попробуйте другую."


# Обработчики сообщений
@dp.message(F.text == "📝 Сделать конспект")
async def handle_summary(message: types.Message):
    user_id = message.from_user.id
    user_states[user_id] = "summary"
    await message.answer("📖 Введите тему для конспекта:")


@dp.message(F.text == "🔍 Найти информацию")
async def handle_search(message: types.Message):
    user_id = message.from_user.id
    user_states[user_id] = "search"
    await message.answer("🔎 Что вас интересует? Введите запрос:")


@dp.message(F.text == "🖼️ Решить по фото")
async def handle_photo(message: types.Message):
    user_id = message.from_user.id
    user_states[user_id] = "photo"
    await message.answer("📸 Отправьте фото с задачей:")


@dp.message(F.text == "📚 Мои конспекты")
async def handle_notes(message: types.Message):
    user_id = message.from_user.id
    try:
        with sqlite3.connect('study_bot.db') as conn:
            c = conn.cursor()
            c.execute("SELECT id, topic FROM summaries WHERE user_id = ?", (user_id,))
            notes = c.fetchall()

        if not notes:
            await message.answer("📭 У вас пока нет сохраненных конспектов.")
            return

        response = "📚 Ваши конспекты:\n\n"
        for i, (note_id, topic) in enumerate(notes, 1):
            response += f"{i}. {topic}\n"

        user_states[user_id] = "show_notes_list"
        await message.answer(response + "\nОтправьте номер конспекта для просмотра:")
    except Exception as e:
        logger.error(f"Ошибка при получении конспектов: {e}")
        await message.answer("⚠️ Произошла ошибка при загрузке конспектов.")


@dp.message(F.text == "🧮 Калькулятор формул")
async def handle_calculator(message: types.Message):
    user_id = message.from_user.id
    user_states[user_id] = "calculator"
    await message.answer("🧮 Введите математическое выражение или задачу:")


@dp.message(F.photo)
async def handle_photo_message(message: types.Message):
    user_id = message.from_user.id
    if user_states.get(user_id) != "photo":
        await message.answer("ℹ️ Пожалуйста, сначала выберите действие '🖼️ Решить по фото' в меню.")
        return

    try:
        await message.answer("⏳ Обрабатываю фото...")

        # Скачиваем фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        os.makedirs("temp", exist_ok=True)
        file_path = f"temp/{file.file_id}.jpg"
        await bot.download_file(file.file_path, file_path)

        # Распознаем текст
        text = await ocr_from_photo(file_path)
        if "Ошибка" in text:
            await message.answer(text)
        else:
            await message.answer(f"📖 Распознанный текст:\n{text}\n\n⏳ Ищу решение...")

            # Сохраняем конспект
            with sqlite3.connect('study_bot.db') as conn:
                c = conn.cursor()
                c.execute("INSERT INTO summaries (user_id, topic, content) VALUES (?, ?, ?)",
                          (user_id, "Задача с фото", text))
                conn.commit()

            # Пытаемся решить как математическую задачу
            solution = await solve_math_problem(text)
            await message.answer(solution)

        # Удаляем временный файл
        os.remove(file_path)
    except Exception as e:
        logger.exception(f"Ошибка обработки фото: {e}")
        await message.answer("⚠️ Произошла ошибка при обработке фото. Попробуйте еще раз.")
    finally:
        user_states.pop(user_id, None)


@dp.message(F.text)
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if not state:
        await message.answer("ℹ️ Пожалуйста, выберите действие из меню.")
        return

    try:
        if state == "summary":
            await message.answer("⏳ Создаю конспект...")
            summary = await generate_summary(message.text)

            # Сохраняем в базу данных
            with sqlite3.connect('study_bot.db') as conn:
                c = conn.cursor()
                c.execute("INSERT INTO summaries (user_id, topic, content) VALUES (?, ?, ?)",
                          (user_id, message.text, summary))
                conn.commit()

            # Разбиваем длинное сообщение
            if len(summary) > 4000:
                for i in range(0, len(summary), 4000):
                    await message.answer(summary[i:i + 4000])
            else:
                await message.answer(summary)

            user_states.pop(user_id, None)

        elif state == "search":
            await message.answer("⏳ Ищу информацию...")
            result = await search_info(message.text)
            await message.answer(result)
            user_states.pop(user_id, None)

        elif state == "show_notes_list":
            try:
                note_index = int(message.text) - 1
                with sqlite3.connect('study_bot.db') as conn:
                    c = conn.cursor()
                    c.execute("SELECT topic, content FROM summaries WHERE user_id = ?", (user_id,))
                    notes = c.fetchall()

                if 0 <= note_index < len(notes):
                    topic, content = notes[note_index]
                    # Разбиваем длинное сообщение
                    if len(content) > 4000:
                        for i in range(0, len(content), 4000):
                            await message.answer(content[i:i + 4000])
                    else:
                        await message.answer(f"📘 Конспект: {topic}\n\n{content}")
                else:
                    await message.answer("❌ Неверный номер конспекта.")
            except ValueError:
                await message.answer("❌ Пожалуйста, введите номер конспекта.")
            finally:
                user_states.pop(user_id, None)

        elif state == "calculator":
            await message.answer("⏳ Решаю задачу...")
            solution = await solve_math_problem(message.text)
            await message.answer(solution)
            user_states.pop(user_id, None)

    except Exception as e:
        logger.exception(f"Ошибка обработки запроса: {e}")
        await message.answer("⚠️ Произошла непредвиденная ошибка. Попробуйте позже.")
        user_states.pop(user_id, None)


# Уведомление о неактивности
async def inactivity_check():
    try:
        with sqlite3.connect('study_bot.db') as conn:
            c = conn.cursor()
            c.execute("SELECT user_id, last_active FROM users")
            users = c.fetchall()

        for user_id, last_active in users:
            if not last_active:
                continue
            last_active = datetime.fromisoformat(last_active)
            if datetime.now() - last_active > timedelta(days=3):
                try:
                    await bot.send_message(
                        user_id,
                        "📚 Не забывай учиться! Я всегда готов помочь с конспектами и задачами."
                    )
                    # Обновляем время активности
                    c.execute("UPDATE users SET last_active = ? WHERE user_id = ?",
                              (datetime.now().isoformat(), user_id))
                    conn.commit()
                except Exception:
                    pass  # Пользователь заблокировал бота
    except Exception as e:
        logger.error(f"Ошибка проверки неактивности: {e}")


# Планировщик задач
async def scheduler():
    while True:
        await asyncio.sleep(3600)  # Каждый час
        await inactivity_check()


# Запуск бота
async def main():
    # Создаем временную папку
    os.makedirs("temp", exist_ok=True)

    # Запускаем фоновую задачу
    asyncio.create_task(scheduler())

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")