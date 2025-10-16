import logging
import asyncio
import aiosqlite
import requests
import csv
import os
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import InputFile
from aiogram.types import WebAppInfo  # ← ОБЯЗАТЕЛЬНЫЙ ИМПОРТ ДЛЯ MINI APP


API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
WEBAPP_URL = os.getenv('WEBAPP_URL')  # ← ВАШ FRAMER САЙТ (HTTPS)


bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
waiting_for_location = {}


# === БАЗА ДАННЫХ ===
async def init_db():
    """Создает базу данных для пользователей"""
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
    """Сохраняет данные пользователя в базу"""
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
    """Проверяет, зарегистрирован ли пользователь"""
    async with aiosqlite.connect("users.db") as db:
        cursor = await db.execute("SELECT registered FROM users WHERE user_id = ? AND registered = 1", (user_id,))
        return bool(await cursor.fetchone())


async def get_all_users():
    """Получает список всех зарегистрированных пользователей"""
    async with aiosqlite.connect("users.db") as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE registered = 1")
        return [row[0] for row in await cursor.fetchall()]


# === СОЗДАНИЕ КНОПКИ MINI APP ===
def create_shop_keyboard():
    """Создает inline кнопку для открытия Mini App магазина"""
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton(
            text="🛒 Открыть магазин", 
            web_app=WebAppInfo(url=WEBAPP_URL)  # ← ОТКРЫВАЕТ MINI APP ВНУТРИ TELEGRAM
        )
    )
    return keyboard


# === ОБРАБОТКА ДАННЫХ ИЗ MINI APP ===
@dp.message_handler(content_types=['web_app_data'])
async def handle_webapp_data(message: types.Message):
    """Обрабатывает данные, отправленные из Mini App"""
    try:
        data = message.web_app_data.data
        user_id = message.from_user.id
        
        # Обработка данных заказа из вашего Framer магазина
        await message.answer(f"✅ Ваш заказ получен!\n\n📋 Данные заказа:\n{data}")
        
        # Уведомление админа о новом заказе
        try:
            await bot.send_message(
                ADMIN_ID, 
                f"🆕 Новый заказ!\n\n👤 От пользователя: {user_id}\n📋 Данные:\n{data}"
            )
        except Exception as e:
            print(f"Ошибка отправки админу: {e}")
            
    except Exception as e:
        print(f"Ошибка обработки WebApp данных: {e}")
        await message.answer("❌ Произошла ошибка при обработке заказа")


# === ФОТО/ВИДЕО РАССЫЛКА АДМИНУ ===
@dp.message_handler(content_types=['photo'])
async def admin_photo_broadcast(message: types.Message):
    """Рассылка фото с подписью /broadcast_photo"""
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
            print(f"Ошибка отправки фото пользователю {user_id}: {e}")
            
    await message.answer(f"📸 Фото разослано {success} пользователям")


@dp.message_handler(content_types=['video'])
async def admin_video_broadcast(message: types.Message):
    """Рассылка видео с подписью /broadcast_video"""
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
            print(f"Ошибка отправки видео пользователю {user_id}: {e}")
            
    await message.answer(f"🎬 Видео разослано {success} пользователям")


# === СТАРТ И РЕГИСТРАЦИЯ ===
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    
    if await is_registered(user_id):
        # Пользователь уже зарегистрирован - показываем кнопку Mini App
        keyboard = create_shop_keyboard()
        await message.answer("С возвращением! 👋", reply_markup=keyboard)
    else:
        # Запрос номера телефона для регистрации
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
            resize_keyboard=True
        )
        await message.answer(
            "Привет! 🎉\n\nДля начала работы с магазином отправьте свой номер телефона:", 
            reply_markup=keyboard
        )


@dp.message_handler(content_types=["contact"])
async def get_phone(message: types.Message):
    """Обработка номера телефона"""
    user_id = message.from_user.id
    phone = message.contact.phone_number
    
    # Сохраняем номер в базу
    await save_user(user_id, phone=phone)
    
    # Запрос геолокации
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
        resize_keyboard=True
    )
    await message.answer(
        "✅ Номер принят!\n\nТеперь отправьте вашу геолокацию для завершения регистрации:", 
        reply_markup=keyboard
    )
    
    # Устанавливаем таймаут на получение геолокации
    waiting_for_location[user_id] = True
    asyncio.create_task(location_timeout(message, user_id))


@dp.message_handler(content_types=["location"])
async def get_location(message: types.Message):
    """Обработка геолокации и завершение регистрации"""
    user_id = message.from_user.id
    lat = message.location.latitude
    lon = message.location.longitude
    
    # Сохраняем геолокацию и завершаем регистрацию
    await save_user(user_id, latitude=lat, longitude=lon, registered=1)
    waiting_for_location.pop(user_id, None)
    
    # Показываем кнопку Mini App
    keyboard = create_shop_keyboard()
    
    await message.answer("✅ Регистрация завершена!", reply_markup=ReplyKeyboardRemove())
    await message.answer("🎉 Добро пожаловать в наш магазин!\nИспользуйте кнопку ниже для заказа:", reply_markup=keyboard)


async def location_timeout(message: types.Message, user_id: int):
    """Таймаут ожидания геолокации (15 секунд)"""
    await asyncio.sleep(15)
    if waiting_for_location.get(user_id):
        await message.answer(
            "⚠️ Геолокация не получена.\n\n"
            "💡 Попробуйте:\n"
            "• Включить GPS на устройстве\n"
            "• Открыть бота в мобильном приложении Telegram\n"
            "• Нажать /start для повторной попытки"
        )
        waiting_for_location.pop(user_id, None)


# === РАССЫЛКА ТЕКСТА (ТОЛЬКО ДЛЯ АДМИНА) ===
@dp.message_handler(commands=['broadcast'])
async def text_broadcast(message: types.Message):
    """Рассылка текстового сообщения всем пользователям"""
    if message.from_user.id != ADMIN_ID:
        return
        
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("❌ Использование: /broadcast Ваш текст для рассылки")
        return
        
    users = await get_all_users()
    success = 0
    failed = 0
    
    for user_id in users:
        try:
            await bot.send_message(user_id, text)
            success += 1
        except Exception as e:
            print(f"Ошибка отправки пользователю {user_id}: {e}")
            failed += 1
            
    await message.answer(f"📝 Рассылка завершена:\n✅ Отправлено: {success}\n❌ Ошибок: {failed}")


@dp.message_handler(commands=['users'])
async def users_count(message: types.Message):
    """Статистика пользователей"""
    if message.from_user.id != ADMIN_ID:
        return
        
    count = len(await get_all_users())
    await message.answer(f"👥 Зарегистрировано пользователей: {count}")


# === ЭКСПОРТ ПОЛЬЗОВАТЕЛЕЙ В CSV ===
def geocode_coords(lat, lon):
    """Получение адреса по координатам"""
    if not lat or not lon:
        return "нет данных"
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}&accept-language=ru"
        resp = requests.get(url, timeout=5, headers={"User-Agent": "telegram-bot-exporter/1.0"})
        data = resp.json()
        
        if "display_name" in data:
            return data["display_name"]
        elif "address" in data:
            addr = data["address"]
            parts = [addr.get(k) for k in ("road", "house_number", "city", "town", "village", "state", "country")]
            return ", ".join([str(p) for p in parts if p])
        return f"{lat}, {lon}"
    except Exception:
        return f"{lat}, {lon}"


async def export_csv_ext(message, only_registered: bool):
    """Экспорт пользователей в CSV"""
    async with aiosqlite.connect("users.db") as db:
        where = "WHERE registered = 1" if only_registered else ""
        cursor = await db.execute(f"SELECT user_id, phone, latitude, longitude, registered FROM users {where}")
        users = await cursor.fetchall()
        
        if not users:
            await message.answer("📋 В базе нет подходящих пользователей.")
            return
            
        filename = "users_export.csv"
        
        # Получение адресов по координатам (многопоточно)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            geo_texts = list(pool.map(lambda u: geocode_coords(u[2], u[3]), users))
        
        # Создание CSV файла
        with open(filename, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["№", "Telegram ID", "Телефон", "Статус", "Адрес", "Координаты"])
            
            for idx, (user, geo_text) in enumerate(zip(users, geo_texts), 1):
                user_id, phone, lat, lon, reg = user
                status = "✅ Зарегистрирован" if reg else "❌ Не завершил"
                coords = f"{lat or '-'}; {lon or '-'}"
                writer.writerow([idx, user_id, phone or "Нет данных", status, geo_text, coords])
        
        # Отправка файла
        doc = InputFile(filename)
        caption = "📊 Выгрузка пользователей (CSV/Excel)" + (" - только зарегистрированные" if only_registered else " - все пользователи")
        await bot.send_document(message.chat.id, doc, caption=caption)
        
        # Удаление временного файла
        try:
            os.remove(filename)
        except Exception:
            pass


@dp.message_handler(commands=['export_users_ok'])
async def export_registered_users(message: types.Message):
    """Экспорт зарегистрированных пользователей"""
    if message.from_user.id != ADMIN_ID:
        return
    await export_csv_ext(message, only_registered=True)


@dp.message_handler(commands=['export_users_all'])
async def export_all_users(message: types.Message):
    """Экспорт всех пользователей"""
    if message.from_user.id != ADMIN_ID:
        return
    await export_csv_ext(message, only_registered=False)


# === ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ ===
@dp.message_handler()
async def any_message(message: types.Message):
    """Обработка любых других сообщений"""
    user_id = message.from_user.id
    
    if await is_registered(user_id):
        # Показываем кнопку Mini App зарегистрированным пользователям
        keyboard = create_shop_keyboard()
        await message.answer("🛒 Используйте кнопку ниже для перехода в магазин:", reply_markup=keyboard)
    else:
        # Предлагаем незарегистрированным пользователям начать регистрацию
        await message.answer("👋 Для начала работы отправьте команду /start")


# === ЗАПУСК БОТА ===
async def on_startup(dp):
    """Функция запуска бота"""
    await init_db()
    print("🚀 Бот успешно запущен!")
    print("📱 Mini App поддержка активирована")
    print(f"🔗 URL магазина: {WEBAPP_URL}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    executor.start_polling(dp, on_startup=on_startup)
