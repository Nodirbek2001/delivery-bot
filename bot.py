import logging
import asyncio
import aiosqlite
import requests
from aiogram.types import FSInputFile
import csv
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

API_TOKEN = '8431247395:AAFSgmZtptwXRPI6l7hFee9Kzt2OX5_EnSE'
ADMIN_ID = 5049741772
WEBAPP_URL = 'https://fresh-interfaces-427134.framer.app/'

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
waiting_for_location = {}

# === БАЗА ДАННЫХ ===
async def init_db():
    async with aiosqlite.connect("users.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                phone TEXT,
                latitude REAL,
                longitude REAL,
                registered INTEGER DEFAULT 0
            )
        """)
        await db.commit()
    print("✅ База данных готова")

async def save_user(user_id, phone=None, latitude=None, longitude=None, registered=None):
    async with aiosqlite.connect("users.db") as db:
        await db.execute("""
            INSERT OR REPLACE INTO users (user_id, phone, latitude, longitude, registered)
            VALUES (?, 
                    COALESCE(?, (SELECT phone FROM users WHERE user_id = ?)), 
                    COALESCE(?, (SELECT latitude FROM users WHERE user_id = ?)), 
                    COALESCE(?, (SELECT longitude FROM users WHERE user_id = ?)), 
                    COALESCE(?, (SELECT registered FROM users WHERE user_id = ?)))
        """, (user_id, phone, user_id, latitude, user_id, longitude, user_id, registered, user_id))
        await db.commit()

async def is_registered(user_id):
    async with aiosqlite.connect("users.db") as db:
        cursor = await db.execute("SELECT registered FROM users WHERE user_id = ? AND registered = 1", (user_id,))
        return bool(await cursor.fetchone())

async def get_all_users():
    async with aiosqlite.connect("users.db") as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE registered = 1")
        return [row[0] for row in await cursor.fetchall()]

# === СПЕЦИАЛЬНЫЕ ХЕНДЛЕРЫ - ВВЕРХУ! ===

@dp.message(F.photo)
async def admin_photo_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.caption or not message.caption.lower().startswith('/broadcast_photo'):
        return
    caption = message.caption[len('/broadcast_photo'):].strip()
    file_id = message.photo[-1].file_id
    users = await get_all_users()
    success = 0
    for user_id in users:
        try:
            await bot.send_photo(user_id, file_id, caption=caption)
            success += 1
        except Exception as e:
            print(e)
    await message.answer(f"📸 Фото разослано {success} пользователям")

@dp.message(F.video)
async def admin_video_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.caption or not message.caption.lower().startswith('/broadcast_video'):
        return
    caption = message.caption[len('/broadcast_video'):].strip()
    file_id = message.video.file_id
    users = await get_all_users()
    success = 0
    for user_id in users:
        try:
            await bot.send_video(user_id, file_id, caption=caption)
            success += 1
        except Exception as e:
            print(e)
    await message.answer(f"🎬 Видео разослано {success} пользователям")

# === БАЗОВЫЕ КОМАНДЫ И РЕГИСТРАЦИЯ ===

@dp.message(Command("start"))
async def start_command(message: types.Message):
    user_id = message.from_user.id
    if await is_registered(user_id):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
        await message.answer("С возвращением! 👋", reply_markup=keyboard)
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
            resize_keyboard=True
        )
        await message.answer("Привет! Отправьте номер для регистрации:", reply_markup=keyboard)

@dp.message(F.contact)
async def get_phone(message: types.Message):
    user_id = message.from_user.id
    phone = message.contact.phone_number
    await save_user(user_id, phone=phone)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
        resize_keyboard=True
    )
    await message.answer("Номер принят! Теперь отправьте геолокацию:", reply_markup=keyboard)
    waiting_for_location[user_id] = True
    asyncio.create_task(location_timeout(message, user_id))

@dp.message(F.location)
async def get_location(message: types.Message):
    user_id = message.from_user.id
    lat = message.location.latitude
    lon = message.location.longitude
    await save_user(user_id, latitude=lat, longitude=lon, registered=1)
    waiting_for_location.pop(user_id, None)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])

    await message.answer("✅ Регистрация завершена!", reply_markup=ReplyKeyboardRemove())
    await message.answer("Добро пожаловать в магазин:", reply_markup=keyboard)

async def location_timeout(message: types.Message, user_id: int):
    await asyncio.sleep(15)
    if waiting_for_location.get(user_id):
        await message.answer("⚠️ Геолокация не получена. Включите GPS и попробуйте снова или откройте бота на телефоне.")
        waiting_for_location.pop(user_id, None)

# === РАССЫЛКА ТЕКСТА (ТОЛЬКО ДЛЯ АДМИНА) ===

@dp.message(Command("broadcast"))
async def text_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("Использование: /broadcast Ваш текст")
        return
    users = await get_all_users()
    success = 0
    for user_id in users:
        try:
            await bot.send_message(user_id, text)
            success += 1
        except:
            pass
    await message.answer(f"📝 Текст отправлен {success} пользователям")

@dp.message(Command("users"))
async def users_count(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    count = len(await get_all_users())
    await message.answer(f"👥 Зарегистрировано: {count} пользователей")


from aiogram.types import FSInputFile

import concurrent.futures

def geocode_coords(lat, lon):
    if not lat or not lon:
        return "нет данных"
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}&accept-language=ru"
        resp = requests.get(url, timeout=5, headers={"User-Agent": "telegram-bot-exporter/1.0"})
        data = resp.json()
        if "display_name" in data:
            return data["display_name"]
        elif "address" in data:
            # Самый точный адрес: улица, город, страна
            addr = data["address"]
            parts = [addr.get(k) for k in ("road", "house_number", "city", "town", "village", "state", "country")]
            return ", ".join([str(p) for p in parts if p])
        return f"{lat}, {lon}"
    except Exception:
        return f"{lat}, {lon}"


async def export_csv_ext(message, only_registered: bool):
    async with aiosqlite.connect("users.db") as db:
        where = "WHERE registered = 1" if only_registered else ""
        cursor = await db.execute(f"SELECT user_id, phone, latitude, longitude, registered FROM users {where}")
        users = await cursor.fetchall()
        if not users:
            await message.answer("В базе нет подходящих пользователей.")
            return
        filename = "users_export.csv"
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            geo_texts = list(pool.map(lambda u: geocode_coords(u[2], u[3]), users))
        with open(filename, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["№", "Telegram ID", "Телефон", "Статус", "Гео-адрес", "Координаты"])
            for idx, (user, geo_text) in enumerate(zip(users, geo_texts), 1):
                user_id, phone, lat, lon, reg = user
                status = "✅" if reg else "❌"
                coords = f"{lat or '-'}; {lon or '-'}"
                writer.writerow([idx, user_id, phone or "Нет данных", status, geo_text, coords])
        doc = FSInputFile(filename)
        await bot.send_document(message.chat.id, doc, caption="Выгрузка пользователей (CSV/Excel)")
        try:
            os.remove(filename)
        except Exception:
            pass

@dp.message(Command("export_users_ok"))
async def export_ok(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await export_csv_ext(message, only_registered=True)

@dp.message(Command("export_users_all"))
async def export_all(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await export_csv_ext(message, only_registered=False)



# === ДЛЯ ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ (В САМОМ НИЗУ!) ===

@dp.message()
async def any_message(message: types.Message):
    user_id = message.from_user.id
    if await is_registered(user_id):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🛒 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
        )
        await message.answer("Используйте кнопку для заказа:", reply_markup=keyboard)
    else:
        await message.answer("Для начала отправьте команду /start")

# === СТАРТ БОТА ===
async def main():
    await init_db()
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
