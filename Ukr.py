from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask
from threading import Thread
import asyncio
import os
import random
import time
from datetime import datetime, timedelta
from collections import Counter
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId

load_dotenv()

# ================== Flask для Render ==================
app = Flask('')

@app.route('/')
def home():
    return "Бот працює, братан!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ================== Конфіг ==================
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
GROUP_ID = -1002128624256
ADMIN_ID = 1876083446

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["casino_bot_db"]
users_collection = db["users"]
casino_collection = db["casino"]
market_collection = db["market"]
settings_collection = db["settings"]

last_farm_time = {}
FARM_COOLDOWN = 3600
krizis = False
ITEM_COOLDOWN = 3600

# Активні ігри казино (короткоживучі)
active_casino_games = {}
# ================== Дуелі ==================
pending_duels = {}      # duel_id -> дані пропозиції
active_duels = {}       # duel_id -> дані активної дуелі
DUEL_ACCEPT_TIME = 300  # 5 хвилин на прийняття
pending_arest = {}  # user_id: expire_timestamp
AREST_CHOICE_TIME = 600  # 10 хвилин

# ================== Константи ==================
ITEMS = {
    "marijuana": {"name": "Марихуана", "seed_price": 15, "base_avg": 17, "fluct": 5, "zmina": 3},
    "hashish":   {"name": "Гашиш",     "seed_price": 30, "base_avg": 35, "fluct": 10, "zmina": 5},
    "poppy":     {"name": "Мак",       "seed_price": 60, "base_avg": 75, "fluct": 20, "zmina": 10},
    "cocaine":   {"name": "Кокаїн",    "seed_price": 120, "base_avg": 150, "fluct": 40, "zmina": 25},
    "katinon":   {"name": "Катінон",    "seed_price": 250, "base_avg": 300, "fluct": 80, "zmina": 50},
    "ephedrin":   {"name": "Ефедрін",    "seed_price": 500, "base_avg": 600, "fluct": 160, "zmina": 100},
}

# ================= Налаштування ворів =====================
# protect_level:
#   1 — рятує звичайна охорона (has_protection) АБО покращена (has_protection2)
#   2 — рятує ТІЛЬКИ покращена охорона (has_protection2)
#   0 — ніяка охорона не рятує (повний піздець)

THIEVES = {
    "1": {"name": "Вор",         "days": 2, "percent": 0.20, "protect_level": 1, "start_msg": "🕵️ Вор активований на 2 дні",             "stop_msg": "Вор зупинений"},
    "2": {"name": "Вор",         "days": 5, "percent": 0.10, "protect_level": 1, "start_msg": "🕵️ Вор активований на 5 днів",            "stop_msg": "Вор зупинений"},
    "3": {"name": "Вор",         "days": 1, "percent": 0.50, "protect_level": 1, "start_msg": "🕵️ Вор активований на 1 день",            "stop_msg": "Вор зупинений"},
    "4": {"name": "Вор майстер", "days": 3, "percent": 0.25, "protect_level": 2, "start_msg": "🕵️ Вор майстер активований на 3 дні",     "stop_msg": "Вор майстер зупинений"},
    "5": {"name": "Супер вор",   "days": 5, "percent": 0.50, "protect_level": 0, "start_msg": "🕵️ Наступні 5 днів буде піздець",         "stop_msg": "Ад зупинений"},
}

ECONOM_MESSAGES = {
    "1": "📢 Долар упаде завтра\n\nТреба запастися врожаєм.",
    "2": "📢 Долар виросте завтра\n\nПродавайте все.",
    "3": "📢 Курс долара змінеться\n\nГотуйтесь."
}

SUPER_POWERS = [
    "ти вмієш літати",
    "ти керуєш вогнем",
    "ти читаєш думки",
    "ти стріляєш лазерами з глаз",
    "ти можеш ставати невидимим",
    "у тебе супер-сила",
    "ти дихаєш під водою",
    "ти телепортуєшся",
    "час зупиняється, коли ти кліпаєш",
    "ти розумієш мову тварин"
]

SIDE_EFFECTS = [
    "але тільки по понеділках",
    "але після цього сильно хочеться спати",
    "але твій голос стає як у міньйона",
    "але ти на годину забуваєш, як тебе звати",
    "але тільки коли тримаєш у руках ложку",
    "але від тебе пахне рибою",
    "але ти весь час падаєш на ліве коліно",
    "але твої зуби стають яскраво-зеленими",
    "але тільки якщо ти босоніж",
    "але навколо починають літати голуби і заважати тобі"
]

CASINO_BETS = [10, 50, 300]          # потім заміниш
CASINO_PRICE = 300               # потім заміниш
PROTECTION_PRICE = 150
PROTECTION2_PRICE = 500
ADVOCAT_PRICE = 50
FREEZE_PRICE = 5
ROT_TIME = 86400  # Время до гниения в секундах (86400 = 24 часа, 3600 = 1 час)
ECONOM_PRICE = 300



# ================== Допоміжні функції ==================

async def ensure_user(user_id: int):
    user = await users_collection.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "balance": 0,
            "has_protection": False,
            "has_econom": False,
            "has_advocat": False,
            "has_protection2": False,
            "arest": False,       # Статус тюрьмы
            "arest_end": 0,       # Время окончания тюрьмы
            "inventory": {
                "marijuana": {"normal": [], "frozen": 0},
                "hashish": {"normal": [], "frozen": 0},
                "poppy": {"normal": [], "frozen": 0},
                "cocaine": {"normal": [], "frozen": 0},
                "katinon": {"normal": [], "frozen": 0},
                "ephedrin": {"normal": [], "frozen": 0},
            },
            "last_stolen_at": 0
        }
        await users_collection.insert_one(user)
    else:
        # Автоматически добавляем новые поля старым пользователям, если их нет
        updates = {}
        if "arest" not in user:
            updates["arest"] = False
        if "arest_end" not in user:
            updates["arest_end"] = 0
        if "has_econom" not in user:          # ← додай цей рядок
            updates["has_econom"] = False     # ← і цей
        if updates:
            await users_collection.update_one({"user_id": user_id}, {"$set": updates})
            user.update(updates)
    return user


async def get_balance(user_id: int) -> int:
    user = await ensure_user(user_id)
    return user["balance"]

async def update_balance(user_id: int, delta: int):
    await ensure_user(user_id)
    await users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": delta}}
    )

async def get_inventory(user_id: int) -> dict:
    user = await ensure_user(user_id)
    return user.get("inventory", {})

async def add_item(user_id: int, item: str, frozen: bool = False, amount: int = 1):
    await ensure_user(user_id)
    if frozen:
        await users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {f"inventory.{item}.frozen": amount}}
        )
    else:
        now = time.time()
        timestamps = [now] * amount
        await users_collection.update_one(
            {"user_id": user_id},
            {"$push": {f"inventory.{item}.normal": {"$each": timestamps}}}
        )


async def remove_item(user_id: int, item: str, frozen: bool = False, amount: int = 1) -> bool:
    await clean_rotten_items(user_id)  # Сначала чистим гниль, чтобы нельзя было продать тухляк

    if frozen:
        path = f"inventory.{item}.frozen"
        result = await users_collection.update_one(
            {"user_id": user_id, path: {"$gte": amount}},
            {"$inc": {path: -amount}}
        )
        return result.modified_count > 0
    else:
        # Забираємо тільки готові (ts <= now)
        user = await users_collection.find_one({"user_id": user_id})
        if not user:
            return False
        path = f"inventory.{item}.normal"
        normal = user.get("inventory", {}).get(item, {}).get("normal", [])
        if isinstance(normal, int):
            normal = [time.time()] * normal

        now = time.time()
        ready = sorted([ts for ts in normal if ts <= now])
        if len(ready) < amount:
            return False

        # Видаляємо amount найстаріших готових
        to_remove = ready[:amount]
        new_normal = []
        removed = 0
        for ts in normal:
            if removed < amount and ts <= now and ts == to_remove[removed]:
                removed += 1
                continue
            new_normal.append(ts)

        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {path: new_normal}}
        )
        return True

async def get_current_prices() -> dict:
    settings = await settings_collection.find_one({"_id": "main"})
    if not settings or "prices" not in settings:
        prices = {k: v["base_avg"] for k, v in ITEMS.items()}
        await settings_collection.update_one(
            {"_id": "main"},
            {"$set": {"prices": prices}},
            upsert=True
        )
        return prices
    return settings["prices"]

async def get_sell_price(item: str) -> int:
    prices = await get_current_prices()
    avg = prices.get(item, ITEMS[item]["base_avg"])
    fluct = ITEMS[item]["fluct"]
    return random.randint(max(1, avg - fluct), avg + fluct)

async def get_seed_prices() -> dict:
    settings = await settings_collection.find_one({"_id": "main"})
    if not settings or "seed_prices" not in settings:
        prices = {k: v["seed_price"] for k, v in ITEMS.items()}
        await settings_collection.update_one(
            {"_id": "main"},
            {"$set": {"seed_prices": prices}},
            upsert=True
        )
        return prices
    return settings["seed_prices"]

async def get_casino():
    doc = await casino_collection.find_one({"_id": "main"})
    if not doc:
        doc = {"_id": "main", "owner_id": None, "is_active": False}
        await casino_collection.insert_one(doc)
    return doc

async def set_casino_owner(owner_id: int | None):
    await casino_collection.update_one(
        {"_id": "main"},
        {"$set": {"owner_id": owner_id, "is_active": owner_id is not None}},
        upsert=True
    )

@router.callback_query(F.data == "choose_arest")
async def choose_arest_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id not in pending_arest:
        await callback.answer("Вибір вже неактуальний", show_alert=True)
        return

    del pending_arest[user_id]
    await force_arest(user_id)

    await callback.answer("Ти сів у тюрму на 1 день!", show_alert=True)
    await callback.message.edit_text("🔒 Тебе заарештували. Наступні 24 години ферма, шоп і продаж закриті.")


@router.callback_query(F.data == "try_bribe")
async def try_bribe_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id not in pending_arest:
        await callback.answer("Вибір вже неактуальний", show_alert=True)
        return

    if not await try_spend(user_id, 100):
        await callback.answer("Немає 100$ на взятку!", show_alert=True)
        return

    del pending_arest[user_id]

    # === ВАЖЛИВО: ставимо кулдаун одразу ===
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"last_zaderjanie_at": time.time()}}
    )

    roll = random.random()
    if roll < 0.25:
        # Не повезло
        await force_arest(user_id)
        await callback.answer("Невдалося!", show_alert=True)
        await callback.message.edit_text(
            "👮‍♂️ Міліція взяла 100$ і все одно арештувала тебе на 1 день!"
        )
    else:
        # Пощастило
        await callback.answer("Вдалося!", show_alert=True)
        await callback.message.edit_text(
            "🎉 Міліція взяла бабки і відпустила тебе. Тобі пощастило."
        )

@router.message(Command("vubir"))
async def cmd_vubir(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id)

    text = (
        "🛒 <b>Вибір</b>\n\n"
        "Тебе прижала міліція. Вибирай:\n"
        "• Арест на 1 день (без ферми, шопа та продажу)\n"
        "• Дати взятку 100$ (<b>Увага:</b> шанс, що мусора заберуть бабки і все одно посадять — 25%!)"
    )
    buttons = [
        [InlineKeyboardButton(text="🔒 Піти в тюрму на 1 день", callback_data="choose_arest")],
        [InlineKeyboardButton(text="💸 Дати взятку 100$ (ризик 10%)", callback_data="try_bribe")]
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# ================== Старт ==================

@router.message(CommandStart())
async def start_command(message: Message):
    await ensure_user(message.from_user.id)
    await message.reply(
        "Привіт, братан\n\n"
        "Команди:\n"
        "/balance — баланс\n"
        "/shop — магазин\n"
        "/inv — інвентар\n"
        "/market — дошка оголошень\n"
        "/casino — казино\n"
        "ферма — заробити бабло\n"
        "/top — топ бариг\n"
        "/duel — дуель\n"
        "побочка — отримати суперсилу"
        )
    


# ================== Баланс ==================

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id)
    await try_steal(user_id)  # перевірка вора
    await try_arest(user_id)
    balance = await get_balance(user_id)
    user = await users_collection.find_one({"user_id": user_id})
    if user.get("has_protection2"):
        prot = "🛡🛡 Охорона II (максимальна)"
    elif user.get("has_protection"):
        prot = "✅ Звичайна охорона"
    else:
        prot = "❌ Немає охорони"

    await message.answer(
        f"💰 У тебе в кишені: <b>{balance}</b> $\n"
        f"🛡 {prot}",
        parse_mode="HTML"
    )

# ================== Ферма ==================

@router.message(F.text.lower() == "ферма")
async def ferma(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id)
    await try_steal(user_id)
    await try_arest(user_id)

    user = await ensure_user(message.from_user.id) # или callback.from_user.id
    if user.get("arest"):
        if time.time() < user.get("arest_end", 0):
            await message.answer("🔒 Ти в тюрмі, куди сунешся? Чекай звільнення.") # или callback.answer(...)
            return
        else:
            # Срок тюрьмы вышел, снимаем арест
            await users_collection.update_one({"user_id": user_id}, {"$set": {"arest": False}})

    now = time.time()
    if user_id in last_farm_time:
        left = FARM_COOLDOWN - (now - last_farm_time[user_id])
        if left > 0:
            minutes = int(left // 60)
            seconds = int(left % 60)
            await message.answer(f"⏳ Ще рано. Чекай {minutes} хв {seconds} сек")
            return

    if krizis == True:
        bablo = random.randint(0, 5)
        last_farm_time[user_id] = now

        if bablo == 0:
            await message.answer("Ніхуя не випало 😅 Спробуй пізніше")
        else:
            await update_balance(user_id, bablo)
            new_bal = await get_balance(user_id)
            await message.answer(
            f"💰 Заробив <b>{bablo}</b> $\n"
            f"Тепер у тебе: {new_bal}",
            parse_mode="HTML"
            )
        await message.answer("нахуй пішов")
        return

    bablo = random.randint(0, 10)
    last_farm_time[user_id] = now

    if bablo == 0:
        await message.answer("Ніхуя не випало 😅 Спробуй пізніше")
    else:
        await update_balance(user_id, bablo)
        new_bal = await get_balance(user_id)
        await message.answer(
            f"💰 Заробив <b>{bablo}</b> $\n"
            f"Тепер у тебе: {new_bal}",
            parse_mode="HTML"
        )

# ================== Магазин ==================

@router.message(Command("shop"))
async def cmd_shop(message: Message):
    user_id = message.from_user.id
    user = await ensure_user(message.from_user.id) # или callback.from_user.id
    if user.get("arest"):
        if time.time() < user.get("arest_end", 0):
            await message.answer("🔒 Ти в тюрмі, куди сунешся? Чекай звільнення.") # или callback.answer(...)
            return
        else:
            # Срок тюрьмы вышел, снимаем арест
            await users_collection.update_one({"user_id": user_id}, {"$set": {"arest": False}})


    if krizis == True:
        await message.answer("нахуй пішов")
        return

    await ensure_user(message.from_user.id)
    seed_prices = await get_seed_prices()
    settings = await settings_collection.find_one({"_id": "main"}) or {}
    deficit_items = settings.get("deficit_items", [])

    text = "🛒 <b>Магазин</b>\n\n"
    text += "<b>Насіння</b> (треба чекати годину для врожаю):\n"
    buttons = []

    for key, data in ITEMS.items():
        price = seed_prices.get(key, data["seed_price"])
        if key in deficit_items:
            text += f"• {data['name']} — <b>❌ ДЕФІЦИТ</b>\n"
            buttons.append([InlineKeyboardButton(text=f"❌ {data['name']} (немає)", callback_data=f"buy_seed_{key}")])
        else:
            text += f"• {data['name']} — {price}$\n"
            buttons.append([InlineKeyboardButton(text=f"{data['name']} {price}$", callback_data=f"buy_seed_{key}")])

    text += f"\n🛡 Охорона (назавжди) — {PROTECTION_PRICE}$\n"
    text += f"🛡🛡 Охорона II (від майстра) — {PROTECTION2_PRICE}$\n"
    text += f"📈 Економічна розвідка — {ECONOM_PRICE}$\n"
    text += f"Адвокат — {ADVOCAT_PRICE}$\n"    
    text += f"🎰 Казино — {CASINO_PRICE}$\n"

    buttons.append([InlineKeyboardButton(text=f"Охорона {PROTECTION_PRICE}$", callback_data="buy_protection")])
    buttons.append([InlineKeyboardButton(text=f"Охорона II {PROTECTION2_PRICE}$", callback_data="buy_protection2")])
    buttons.append([InlineKeyboardButton(text=f"Купити економічну розвідку {ECONOM_PRICE}$", callback_data="buy_econom")])
    buttons.append([InlineKeyboardButton(text=f"Купити адвоката {ADVOCAT_PRICE}$", callback_data="buy_advocat")])
    buttons.append([InlineKeyboardButton(text=f"Купити казино {CASINO_PRICE}$", callback_data="buy_casino")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "buy_protection2")
async def buy_protection2(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await ensure_user(user_id)

    if user.get("has_protection2"):
        await callback.answer("У тебе вже є Охорона II!", show_alert=True)
        return

    result = await users_collection.update_one(
        {
            "user_id": user_id,
            "has_protection2": {"$ne": True},
            "balance": {"$gte": PROTECTION2_PRICE}
        },
        {
            "$inc": {"balance": -PROTECTION2_PRICE},
            "$set": {"has_protection2": True}
        }
    )

    if result.modified_count == 0:
        await callback.answer("Не вистачає бабла", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer("🛡🛡 Охорону II купив! Тепер навіть Вор-майстер тебе не дістане.")

@router.callback_query(F.data.startswith("buy_seed_"))
async def buy_seed(callback: CallbackQuery):
    user_id = callback.from_user.id
    item = callback.data.replace("buy_seed_", "")
    if item not in ITEMS:
        await callback.answer("Хуйня якась", show_alert=True)
        return

    # 1. Спочатку перевіряємо дефіцит (ДО списання грошей!)
    settings = await settings_collection.find_one({"_id": "main"}) or {}
    deficit_items = settings.get("deficit_items", [])
    if item in deficit_items:
        await callback.answer("Немає товара, бля (Дефіцит)", show_alert=True)
        return

    # 2. Беремо актуальну ціну і списуємо гроші
    seed_prices = await get_seed_prices()
    price = seed_prices.get(item, ITEMS[item]["seed_price"])

    if not await try_spend(user_id, price):
        await callback.answer("Немає бабла, бля", show_alert=True)
        return


    # 3. Видаємо врожай (з'явиться через ITEM_COOLDOWN)
    ready_at = time.time() + ITEM_COOLDOWN
    await users_collection.update_one(
        {"user_id": user_id},
        {"$push": {f"inventory.{item}.normal": ready_at}}
    )

    await callback.answer()
    await callback.message.answer(
        f"✅ Купив {ITEMS[item]['name']} за {price}$\n"
        f"Врожай з'явиться в інвентарі через 1 годину. Дивись /inv"
    )

@router.callback_query(F.data == "buy_econom")
async def buy_econom(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await ensure_user(user_id)

    if user.get("has_econom"):
        await callback.answer("У тебе вже є економічна розвідка, нахуй повторно", show_alert=True)
        return

    result = await users_collection.update_one(
        {
            "user_id": user_id,
            "has_econom": {"$ne": True},
            "balance": {"$gte": ECONOM_PRICE}
        },
        {
            "$inc": {"balance": -ECONOM_PRICE},
            "$set": {"has_econom": True}
        }
    )

    if result.modified_count == 0:
        await callback.answer("Не вистачає бабла", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer("Економічну розвідку купив. Тепер ти готовий до всього. Для отримання повідомлень напиши у лс боту")

@router.callback_query(F.data == "buy_protection")
async def buy_protection(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await ensure_user(user_id)

    if user.get("has_protection"):
        await callback.answer("У тебе вже є охорона, нахуй повторно", show_alert=True)
        return

    result = await users_collection.update_one(
        {
            "user_id": user_id,
            "has_protection": {"$ne": True},
            "balance": {"$gte": PROTECTION_PRICE}
        },
        {
            "$inc": {"balance": -PROTECTION_PRICE},
            "$set": {"has_protection": True}
        }
    )

    if result.modified_count == 0:
        await callback.answer("Не вистачає бабла", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer("🛡 Охорону купив. Тепер вор тебе не дістане.")

@router.callback_query(F.data == "buy_advocat")
async def buy_advocat(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await ensure_user(user_id)

    if user.get("has_advocat"):
        await callback.answer("У тебе вже є адвокат, нахуй повторно", show_alert=True)
        return

    result = await users_collection.update_one(
        {
            "user_id": user_id,
            "has_advocat": {"$ne": True},
            "balance": {"$gte": ADVOCAT_PRICE}
        },
        {
            "$inc": {"balance": -ADVOCAT_PRICE},
            "$set": {"has_advocat": True}
        }
    )

    if result.modified_count == 0:
        await callback.answer("Не вистачає бабла", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer("🛡 Адвоката купив. Тепер поліція тебе не можливо не троне.")

@router.callback_query(F.data == "buy_casino")
async def buy_casino(callback: CallbackQuery):
    user_id = callback.from_user.id
    casino = await get_casino()

    if casino.get("owner_id"):
        await callback.answer("Казино вже хтось купив", show_alert=True)
        return

    if not await try_spend(user_id, CASINO_PRICE):
        await callback.answer("Немає стількох бабок", show_alert=True)
        return

    # Атомарно ставим владельца, только если место еще свободно
    res = await casino_collection.update_one(
        {"_id": "main", "owner_id": None},
        {"$set": {"owner_id": user_id, "is_active": True}}
    )

    if res.modified_count == 0:
        # Кто-то успел купить на долю секунды раньше — возвращаем бабки
        await update_balance(user_id, CASINO_PRICE)
        await callback.answer("Казино вже хтось купив", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer(
        f"🎰 Вітаю, ти купив казино за {CASINO_PRICE}$.\n"
        f"Тепер всі лохи грають на тебе."
    )

# ================== Інвентар ==================
async def clean_rotten_items(user_id: int) -> dict:
    user = await ensure_user(user_id)
    inv = user.get("inventory", {})
    now = time.time()
    updates = {}
    rotten_report = []

    for item_key, data in ITEMS.items():
        normal_data = inv.get(item_key, {}).get("normal", [])

        # Совместимость со старой базой (если там еще лежит число int)
        if isinstance(normal_data, int):
            normal_data = [now] * normal_data
            updates[f"inventory.{item_key}.normal"] = normal_data

        # Готові + не згнили
        ready_fresh = [ts for ts in normal_data if ts <= now and now - ts < ROT_TIME]
        # Ще ростуть (майбутній час)
        growing = [ts for ts in normal_data if ts > now]
        rotten_count = len(normal_data) - len(ready_fresh) - len(growing)

        if rotten_count > 0 or len(ready_fresh) + len(growing) != len(normal_data):
            updates[f"inventory.{item_key}.normal"] = ready_fresh + growing
            if rotten_count > 0:
                rotten_report.append(f"{data['name']}: {rotten_count} шт.")

    if updates:
        await users_collection.update_one({"user_id": user_id}, {"$set": updates})
        user = await users_collection.find_one({"user_id": user_id})

    return user.get("inventory", {}), rotten_report

@router.message(Command("inv"))
async def cmd_inv(message: Message):
    user_id = message.from_user.id
    inv, rotten_report = await clean_rotten_items(user_id)
    now = time.time()

    text = ""
    if rotten_report:
        text += "🤢 <b>Поки ти спав, частина врожаю згнила:</b>\n"
        text += "• " + "\n• ".join(rotten_report) + "\n\n"

    text += "🎒 <b>Твій інвентар:</b>\n\n"
    has_anything = False
    buttons = []

    for key, data in ITEMS.items():
        normal_list = inv.get(key, {}).get("normal", [])
        if isinstance(normal_list, int):
            normal_list = [now] * normal_list

        ready_list = [ts for ts in normal_list if ts <= now]
        normal = len(ready_list)
        frozen = inv.get(key, {}).get("frozen", 0)

        if normal > 0 or frozen > 0:
            has_anything = True
            text += f"<b>{data['name']}</b>\n"
            if normal > 0:
                # Считаем остаток жизни самого старого готового предмета
                oldest_ts = min(ready_list)
                left_sec = max(0, int(ROT_TIME - (now - oldest_ts)))
                hours = left_sec // 3600
                mins = (left_sec % 3600) // 60

                text += f"  • Звичайний: {normal} шт. (згниє через {hours}г {mins}хв)\n"
                buttons.append([
                    InlineKeyboardButton(text=f"Продати боту {data['name']}", callback_data=f"sellbot_{key}"),
                    InlineKeyboardButton(text=f"❄️ Заморозити ({FREEZE_PRICE}$)", callback_data=f"freeze_{key}")
                ])
                buttons.append([
                    InlineKeyboardButton(text=f"На дошку {data['name']}", callback_data=f"market_add_{key}_0")
                ])
            if frozen > 0:
                text += f"  • Заморожений: {frozen} шт.\n"
                buttons.append([
                    InlineKeyboardButton(text=f"Розморозити", callback_data=f"unfreeze_{key}"),
                    InlineKeyboardButton(text=f"На дошку (зам)", callback_data=f"market_add_{key}_1")
                ])

    if not has_anything:
        text += "Порожньо, бля 🤷‍♂️"

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("sellbot_"))
async def sell_to_bot(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await ensure_user(user_id)

    if user.get("arest"):
        if time.time() < user.get("arest_end", 0):
            await callback.answer("🔒 Ти в тюрмі, куди сунешся? Чекай звільнення.")
            return
        else:
            await users_collection.update_one({"user_id": user_id}, {"$set": {"arest": False}})

    if krizis == True:
        await callback.answer("нахуй пішов")
        return

    parts = callback.data.split("_")
    item = parts[1]
    # frozen flag not used here, always normal

    success = await remove_item(user_id, item, frozen=False, amount=1)
    if not success:
        await callback.answer("Немає такого врожаю", show_alert=True)
        return

    price = await get_sell_price(item)
    await update_balance(user_id, price)

    await callback.answer()
    await callback.message.answer(
        f"✅ Продав {ITEMS[item]['name']} боту за <b>{price}$</b>",
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("freeze_"))
async def freeze_item(callback: CallbackQuery):
    item = callback.data.replace("freeze_", "")
    user_id = callback.from_user.id

    if not await try_spend(user_id, FREEZE_PRICE):
        await callback.answer(f"Треба {FREEZE_PRICE}$ на заморозку!", show_alert=True)
        return

    success = await remove_item(user_id, item, frozen=False, amount=1)
    if not success:
        # Товар уже сгнил или его нет — возвращаем 5$
        await update_balance(user_id, FREEZE_PRICE)
        await callback.answer("Немає свіжого врожаю (можливо, вже згнив)", show_alert=True)
        return

    await add_item(user_id, item, frozen=True, amount=1)
    await callback.answer()
    await callback.message.answer(f"❄️ {ITEMS[item]['name']} заморозив за {FREEZE_PRICE}$. Тепер не згниє.")

@router.callback_query(F.data.startswith("unfreeze_"))
async def unfreeze_item(callback: CallbackQuery):
    item = callback.data.replace("unfreeze_", "")
    user_id = callback.from_user.id

    success = await remove_item(user_id, item, frozen=True, amount=1)
    if not success:
        await callback.answer("Немає замороженого", show_alert=True)
        return

    await add_item(user_id, item, frozen=False, amount=1)
    await callback.answer("Розморожено!")
    await callback.message.answer(f"🌡 {ITEMS[item]['name']} розморожено.")

# ================== Дошка оголошень ==================

@router.message(Command("market"))
async def cmd_market(message: Message):
    listings = await market_collection.find().sort("created_at", -1).limit(15).to_list(15)

    if not listings:
        await message.answer("Дошка оголошень порожня.")
        return

    text = "📋 <b>Дошка оголошень</b>\n\n"
    buttons = []

    for listing in listings:
        item_name = ITEMS[listing["item"]]["name"]
        frozen_text = " (зам)" if listing.get("frozen") else ""
        seller_name = listing.get("seller_name", str(listing["seller_id"]))
        text += (
            f"• {item_name}{frozen_text} — <b>{listing['price']}$</b>\n"
            f"  від {seller_name}\n\n"
        )
        buttons.append([
            InlineKeyboardButton(
                text=f"Купити за {listing['price']}$",
                callback_data=f"market_buy_{listing['_id']}"
            )
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("market_add_"))
async def market_add(callback: CallbackQuery):
    # market_add_{item}_{frozen_flag}
    parts = callback.data.split("_")
    item = parts[2]
    frozen = parts[3] == "1"
    user_id = callback.from_user.id

    # Просимо ціну наступним повідомленням — спрощений варіант
    # Для простоти зараз ставимо фіксовану логіку через окрему команду
    await callback.answer()
    await callback.message.answer(
        f"Щоб виставити {ITEMS[item]['name']}{' (зам)' if frozen else ''} на дошку, "
        f"напиши команду:\n"
        f"<code>/sellmarket {item} {'1' if frozen else '0'} ціна</code>\n\n"
        f"Приклад: <code>/sellmarket {item} {'1' if frozen else '0'} 25</code>",
        parse_mode="HTML"
    )

@router.message(Command("sellmarket"))
async def cmd_sellmarket(message: Message, command: CommandObject):
    user_id = message.from_user.id
    if not command.args:
        await message.answer("Формат: /sellmarket предмет 0/1 ціна\nПриклад: /sellmarket marijuana 0 20")
        return

    try:
        parts = command.args.split()
        if len(parts) < 3:
            await message.answer("Невірний формат. Приклад: /sellmarket marijuana 0 20")
            return
        item = parts[0]
        frozen = parts[1] == "1"
        price = int(parts[2])
    except:
        await message.answer("Невірний формат")
        return

    if item not in ITEMS:
        await message.answer("Невідомий предмет")
        return
    if price < 1:
        await message.answer("Ціна має бути більше 0")
        return

    success = await remove_item(user_id, item, frozen=frozen, amount=1)
    if not success:
        await message.answer("У тебе немає цього врожаю")
        return

    await market_collection.insert_one({
        "seller_id": user_id,
        "seller_name": message.from_user.first_name,
        "item": item,
        "frozen": frozen,
        "price": price,
        "created_at": time.time()
    })

    await message.answer(f"✅ Виставив {ITEMS[item]['name']} за {price}$ на дошку.")

async def try_spend(user_id: int, amount: int) -> bool:
    await ensure_user(user_id)
    result = await users_collection.update_one(
        {"user_id": user_id, "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount}}
    )
    return result.modified_count > 0

@router.callback_query(F.data.startswith("market_buy_"))
async def market_buy(callback: CallbackQuery):
    listing_id = callback.data.replace("market_buy_", "")
    buyer_id = callback.from_user.id

    try:
        obj_id = ObjectId(listing_id)
    except Exception:
        await callback.answer("Оголошення не знайдено", show_alert=True)
        return

    # 1. Атомарно забираємо лот з ринку, щоб ніхто інший його не перехопив
    listing = await market_collection.find_one_and_delete({"_id": obj_id})
    if not listing:
        await callback.answer("Вже хтось купив або видалено", show_alert=True)
        return

    # 2. Якщо покупець = продавець — повертаємо лот назад на дошку
    if listing["seller_id"] == buyer_id:
        await market_collection.insert_one(listing)
        await callback.answer("Не можна купити своє", show_alert=True)
        return

    price = listing["price"]

    # 3. Пробуємо атомарно списати гроші. Якщо не вистачає — повертаємо лот назад
    paid = await try_spend(buyer_id, price)
    if not paid:
        await market_collection.insert_one(listing)
        await callback.answer("Недостатньо грошей", show_alert=True)
        return

    # 4. Усе пройшло успішно — нараховуємо гроші продавцю і видаємо товар покупцю
    await update_balance(listing["seller_id"], price)
    await add_item(buyer_id, listing["item"], frozen=listing.get("frozen", False), amount=1)

    await callback.answer("Куплено!")
    await callback.message.answer(
        f"✅ Ти купив {ITEMS[listing['item']]['name']} за {price}$"
    )

    try:
        await bot.send_message(
            listing["seller_id"],
            f"💰 Твій {ITEMS[listing['item']]['name']} купили за {price}$"
        )
    except Exception:
        pass

# ================== Казино ==================

@router.message(Command("casino"))
async def cmd_casino(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id)

    casino = await get_casino()
    if not casino.get("owner_id"):
        await message.answer("Казино зараз нікому не належить. Купи його в /shop")
        return

    # Показуємо варіанти ставок
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Ставка {bet}$", callback_data=f"casinobet_{bet}")]
        for bet in CASINO_BETS
    ])

    owner = casino["owner_id"]
    await message.answer(
        f"🎰 <b>Казино</b>\n"
        f"Власник: <code>{owner}</code>\n\n"
        f"Вибери ставку:",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("casinobet_"))
async def casino_choose_bet(callback: CallbackQuery):
    user_id = callback.from_user.id
    bet = int(callback.data.replace("casinobet_", ""))

    if bet not in CASINO_BETS:
        await callback.answer("Невірний варіант", show_alert=True)
        return
    
    casino = await get_casino()
    owner_id = casino.get("owner_id")
    if not owner_id:
        await callback.answer("Казино вже не працює", show_alert=True)
        return

    if not await try_spend(user_id, bet):
        await callback.answer("Немає стількох бабок", show_alert=True)
        return

    # Генеруємо поле
    pool = ["😂"] * 3 + ["😒"] * 2 + ["👍"] * 2 + ["🙊"] * 2
    random.shuffle(pool)

    keyboard_rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            row.append(InlineKeyboardButton(text="⬛", callback_data=f"casopen_{user_id}_{idx}"))
        keyboard_rows.append(row)

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    sent = await callback.message.answer(
        f"Ставка: <b>{bet}$</b>\nВідкрий 3 клітинки",
        reply_markup=markup,
        parse_mode="HTML"
    )

    active_casino_games[sent.message_id] = {
        "user_id": user_id,
        "bet": bet,
        "owner_id": owner_id,
        "emojis": pool,
        "opened": set(),
        "finished": False
    }
    await callback.answer()

@router.callback_query(F.data.startswith("casopen_"))
async def casino_open_cell(callback: CallbackQuery):
    parts = callback.data.split("_")
    owner_of_game = int(parts[1])
    cell_idx = int(parts[2])
    user_id = callback.from_user.id

    if user_id != owner_of_game:
        await callback.answer("Це не твоя гра!", show_alert=True)
        return

    msg_id = callback.message.message_id
    game = active_casino_games.get(msg_id)

    if not game or game.get("finished"):
        await callback.answer("Гра вже закінчена", show_alert=True)
        return

    if cell_idx in game["opened"]:
        await callback.answer("Вже відкрито")
        return

    # Захист від лагів — одразу додаємо
    game["opened"].add(cell_idx)

    if len(game["opened"]) > 3:
        await callback.answer("Вже відкрито 3 клітинки")
        return

    opened_count = len(game["opened"])

    # Оновлюємо клавіатуру
    keyboard_rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            if idx in game["opened"]:
                row.append(InlineKeyboardButton(text=game["emojis"][idx], callback_data="noop"))
            else:
                row.append(InlineKeyboardButton(text="⬛", callback_data=f"casopen_{user_id}_{idx}"))
        keyboard_rows.append(row)

    if opened_count < 3:
        await callback.message.edit_text(
            f"Ставка: <b>{game['bet']}$</b>\nВідкрий ще {3 - opened_count}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # === Гра закінчена ===
    game["finished"] = True

    chosen = [game["emojis"][i] for i in game["opened"]]
    counts = Counter(chosen)
    max_count = max(counts.values())

    bet = game["bet"]
    owner_id = game["owner_id"]
    win_amount = 0
    result_text = ""

    if max_count == 3:
        win_amount = bet * 3
        result_text = f"🎉 Джекпот ×3! +{win_amount}$"
    elif max_count == 2:
        win_amount = bet * 2
        result_text = f"🔥 Виграш ×2! +{win_amount}$"
    else:
        result_text = f"💸 Програш -{bet}$"

    # Розрахунки з власником
    if win_amount > 0:
        owner_balance = await get_balance(owner_id)
        if owner_balance >= win_amount:
            await update_balance(owner_id, -win_amount)
            await update_balance(user_id, win_amount)
        else:
            # Власник не може виплатити → казино повертається в магазин
            await update_balance(user_id, win_amount)  # все одно даємо виграш гравцю (з повітря)
            await set_casino_owner(None)
            result_text += "\n\n⚠️ У власника закінчились гроші. Казино повернулось в магазин!"
    else:
        # Програш — гроші вже зняті з гравця, додаємо власнику
        await update_balance(owner_id, bet)

    # Фінальна клавіатура (все відкрито або ні)
    final_rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            if idx in game["opened"]:
                row.append(InlineKeyboardButton(text=game["emojis"][idx], callback_data="noop"))
            else:
                row.append(InlineKeyboardButton(text="⬛", callback_data="noop"))
        final_rows.append(row)

    current_balance = await get_balance(user_id)

    await callback.message.edit_text(
        f"Ставка: <b>{bet}$</b>\n"
        f"{result_text}\n\n"
        f"Твій баланс: <b>{current_balance}$</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=final_rows),
        parse_mode="HTML"
    )

    del active_casino_games[msg_id]
    await callback.answer()

@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()

# ================== Топ ==================

@router.message(Command("top"))
async def cmd_top(message: Message):
    cursor = users_collection.find().sort("balance", -1).limit(10)
    top_users = await cursor.to_list(10)

    if not top_users:
        await message.answer("Поки ніхто нічого не має")
        return

    text = "🏆 <b>Топ бариг:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7

    for i, user_data in enumerate(top_users):
        uid = user_data["user_id"]
        bal = user_data["balance"]
        try:
            user = await bot.get_chat(uid)
            name = user.first_name or str(uid)
        except:
            name = str(uid)
        text += f"{medals[i]} {name} — <b>{bal}$</b>\n"

    await message.answer(text, parse_mode="HTML")

#==================== развлекаловка

@router.message(Command("duel"))
async def cmd_duel(message: Message, command: CommandObject):
    if not message.reply_to_message:
        await message.answer("Відповідай на повідомлення людини, з якою хочеш дуель:\n<code>/duel 50</code>", parse_mode="HTML")
        return

    if not command.args:
        await message.answer("Вкажи ставку: /duel 50")
        return

    try:
        stake = int(command.args.strip())
        if stake < 0:
            await message.answer("Мінімальна ставка — 0$")
            return
    except:
        await message.answer("Ставка має бути числом")
        return

    challenger_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id

    if challenger_id == target_id:
        await message.answer("Не можна викликати себе")
        return

    # Перевірка балансів
    if not await try_spend(challenger_id, 0):  # просто ensure
        pass
    bal1 = await get_balance(challenger_id)
    bal2 = await get_balance(target_id)

    if bal1 < stake:
        await message.answer("У тебе недостатньо грошей")
        return
    if bal2 < stake:
        await message.answer("У суперника недостатньо грошей")
        return

    # Перевірка, чи вже в дуелі
    for d in list(pending_duels.values()) + list(active_duels.values()):
        if challenger_id in (d.get("p1"), d.get("p2")) or target_id in (d.get("p1"), d.get("p2")):
            await message.answer("Хтось із вас вже в дуелі / очікує відповіді")
            return

    duel_id = f"{challenger_id}_{target_id}_{int(time.time())}"
    pending_duels[duel_id] = {
        "p1": challenger_id,
        "p2": target_id,
        "stake": stake,
        "chat_id": message.chat.id,
        "expire": time.time() + DUEL_ACCEPT_TIME,
        "p1_name": message.from_user.first_name,
        "p2_name": message.reply_to_message.from_user.first_name
    }

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Прийняти", callback_data=f"duel_accept_{duel_id}"),
            InlineKeyboardButton(text="❌ Відхилити", callback_data=f"duel_reject_{duel_id}")
        ]
    ])

    await message.answer(
        f"⚔️ <b>Дуель!</b>\n\n"
        f"{message.from_user.first_name} викликає {message.reply_to_message.from_user.first_name}\n"
        f"Ставка: <b>{stake}$</b> (банк буде {stake*2}$)\n\n"
        f"У тебе є 5 хвилин, щоб прийняти.",
        reply_markup=kb,
        parse_mode="HTML"
    )

    # Авто-скасування через 5 хвилин
    async def auto_reject():
        await asyncio.sleep(DUEL_ACCEPT_TIME)
        if duel_id in pending_duels:
            del pending_duels[duel_id]
            try:
                await bot.send_message(message.chat.id, f"⏰ Час вийшов. Дуель скасовано.")
            except:
                pass

    asyncio.create_task(auto_reject())

@router.callback_query(F.data.startswith("duel_accept_"))
async def duel_accept(callback: CallbackQuery):
    duel_id = callback.data.replace("duel_accept_", "")
    duel = pending_duels.get(duel_id)

    if not duel:
        await callback.answer("Дуель вже неактуальна", show_alert=True)
        return

    if callback.from_user.id != duel["p2"]:
        await callback.answer("Це не твоя дуель", show_alert=True)
        return

    if time.time() > duel["expire"]:
        del pending_duels[duel_id]
        await callback.answer("Час вийшов", show_alert=True)
        return

    # Забираємо ставку в обох
    if not await try_spend(duel["p1"], duel["stake"]):
        await callback.answer("У викликача вже немає грошей", show_alert=True)
        del pending_duels[duel_id]
        return
    if not await try_spend(duel["p2"], duel["stake"]):
        # Повертаємо першому
        await update_balance(duel["p1"], duel["stake"])
        await callback.answer("У тебе недостатньо грошей", show_alert=True)
        del pending_duels[duel_id]
        return

    # Створюємо активну дуель
    del pending_duels[duel_id]
    active_duels[duel_id] = {
        "p1": duel["p1"],
        "p2": duel["p2"],
        "stake": duel["stake"],
        "pot": duel["stake"] * 2,
        "acc1": 40,
        "acc2": 40,
        "turn": duel["p1"],          # хто ходить
        "p1_name": duel["p1_name"],
        "p2_name": duel["p2_name"],
        "chat_id": duel["chat_id"]
    }

    await callback.message.edit_text(
        f"⚔️ <b>Дуель почалася!</b>\n\n"
        f"{duel['p1_name']} vs {duel['p2_name']}\n"
        f"Банк: <b>{duel['stake']*2}$</b>\n\n"
        f"Приціл:\n"
        f"• {duel['p1_name']}: 40%\n"
        f"• {duel['p2_name']}: 40%\n\n"
        f"Хід: <b>{duel['p1_name']}</b>",
        reply_markup=get_duel_keyboard(duel_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("duel_reject_"))
async def duel_reject(callback: CallbackQuery):
    duel_id = callback.data.replace("duel_reject_", "")
    duel = pending_duels.get(duel_id)

    if not duel:
        await callback.answer("Дуель вже неактуальна", show_alert=True)
        return

    if callback.from_user.id != duel["p2"]:
        await callback.answer("Це не твоя дуель", show_alert=True)
        return

    del pending_duels[duel_id]
    await callback.message.edit_text(f"❌ {callback.from_user.first_name} відхилив дуель.")
    await callback.answer()

def get_duel_keyboard(duel_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎯 Прицілитися", callback_data=f"duel_aim_{duel_id}"),
            InlineKeyboardButton(text="🔫 Вистрілити", callback_data=f"duel_shoot_{duel_id}")
        ],
        [
            InlineKeyboardButton(text="💨 Збити приціл", callback_data=f"duel_disrupt_{duel_id}")
        ]
    ])


@router.callback_query(F.data.startswith("duel_aim_"))
async def duel_aim(callback: CallbackQuery):
    duel_id = callback.data.replace("duel_aim_", "")
    duel = active_duels.get(duel_id)
    if not duel:
        await callback.answer("Дуель закінчена", show_alert=True)
        return

    uid = callback.from_user.id
    if uid != duel["turn"]:
        await callback.answer("Зараз не твій хід!", show_alert=True)
        return

    # Підвищуємо приціл
    if uid == duel["p1"]:
        duel["acc1"] = min(95, duel["acc1"] + random.randint(18, 28))
        new_acc = duel["acc1"]
        name = duel["p1_name"]
    else:
        duel["acc2"] = min(95, duel["acc2"] + random.randint(18, 28))
        new_acc = duel["acc2"]
        name = duel["p2_name"]

    # Передаємо хід
    duel["turn"] = duel["p2"] if uid == duel["p1"] else duel["p1"]
    next_name = duel["p2_name"] if duel["turn"] == duel["p2"] else duel["p1_name"]

    await callback.message.edit_text(
        f"⚔️ <b>Дуель</b>\n\n"
        f"{duel['p1_name']} vs {duel['p2_name']}\n"
        f"Банк: <b>{duel['pot']}$</b>\n\n"
        f"Приціл:\n"
        f"• {duel['p1_name']}: {duel['acc1']}%\n"
        f"• {duel['p2_name']}: {duel['acc2']}%\n\n"
        f"🎯 {name} прицілився → {new_acc}%\n"
        f"Хід: <b>{next_name}</b>",
        reply_markup=get_duel_keyboard(duel_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("duel_shoot_"))
async def duel_shoot(callback: CallbackQuery):
    duel_id = callback.data.replace("duel_shoot_", "")
    duel = active_duels.get(duel_id)
    if not duel:
        await callback.answer("Дуель закінчена", show_alert=True)
        return

    uid = callback.from_user.id
    if uid != duel["turn"]:
        await callback.answer("Зараз не твій хід!", show_alert=True)
        return

    if uid == duel["p1"]:
        acc = duel["acc1"]
        shooter_name = duel["p1_name"]
        target_name = duel["p2_name"]
        target_id = duel["p2"]
    else:
        acc = duel["acc2"]
        shooter_name = duel["p2_name"]
        target_name = duel["p1_name"]
        target_id = duel["p1"]

    hit = random.randint(1, 100) <= acc

    if hit:
        # Влучання — кінець дуелі
        winner_id = uid
        await update_balance(winner_id, duel["pot"])
        del active_duels[duel_id]

        await callback.message.edit_text(
            f"💥 <b>ВИСТРІЛ В ГОЛОВУ!</b>\n\n"
            f"{shooter_name} влучив у {target_name}!\n\n"
            f"🏆 Переможець: <b>{shooter_name}</b>\n"
            f"Забирає банк: <b>{duel['pot']}$</b>",
            parse_mode="HTML"
        )
        await callback.answer("Влучив!")
    else:
        # Промах
        if uid == duel["p1"]:
            duel["acc1"] = max(15, duel["acc1"] - random.randint(12, 22))
        else:
            duel["acc2"] = max(15, duel["acc2"] - random.randint(12, 22))

        duel["turn"] = target_id
        next_name = target_name

        await callback.message.edit_text(
            f"⚔️ <b>Дуель</b>\n\n"
            f"{duel['p1_name']} vs {duel['p2_name']}\n"
            f"Банк: <b>{duel['pot']}$</b>\n\n"
            f"Приціл:\n"
            f"• {duel['p1_name']}: {duel['acc1']}%\n"
            f"• {duel['p2_name']}: {duel['acc2']}%\n\n"
            f"🔫 {shooter_name} стріляє... <b>ПРОМАХ!</b>\n"
            f"Хід: <b>{next_name}</b>",
            reply_markup=get_duel_keyboard(duel_id),
            parse_mode="HTML"
        )
        await callback.answer("Промах...")


@router.callback_query(F.data.startswith("duel_disrupt_"))
async def duel_disrupt(callback: CallbackQuery):
    duel_id = callback.data.replace("duel_disrupt_", "")
    duel = active_duels.get(duel_id)
    if not duel:
        await callback.answer("Дуель закінчена", show_alert=True)
        return

    uid = callback.from_user.id
    if uid != duel["turn"]:
        await callback.answer("Зараз не твій хід!", show_alert=True)
        return

    if uid == duel["p1"]:
        duel["acc2"] = max(10, duel["acc2"] - random.randint(15, 30))
        name = duel["p1_name"]
        target_acc = duel["acc2"]
        target_name = duel["p2_name"]
    else:
        duel["acc1"] = max(10, duel["acc1"] - random.randint(15, 30))
        name = duel["p2_name"]
        target_acc = duel["acc1"]
        target_name = duel["p1_name"]

    duel["turn"] = duel["p2"] if uid == duel["p1"] else duel["p1"]
    next_name = duel["p2_name"] if duel["turn"] == duel["p2"] else duel["p1_name"]

    await callback.message.edit_text(
        f"⚔️ <b>Дуель</b>\n\n"
        f"{duel['p1_name']} vs {duel['p2_name']}\n"
        f"Банк: <b>{duel['pot']}$</b>\n\n"
        f"Приціл:\n"
        f"• {duel['p1_name']}: {duel['acc1']}%\n"
        f"• {duel['p2_name']}: {duel['acc2']}%\n\n"
        f"💨 {name} збив приціл {target_name} → {target_acc}%\n"
        f"Хід: <b>{next_name}</b>",
        reply_markup=get_duel_keyboard(duel_id),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(F.text.lower() == "побочка")
async def cmd_pobochka(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id)
    
    power = random.choice(SUPER_POWERS)
    effect = random.choice(SIDE_EFFECTS)
    
    name = message.from_user.first_name
    
    text = (
        f"✨ Твоя суперсила: <b>{power}</b>!\n"
        f"⚠️ Побічний ефект: <b>{effect}</b>."
    )
    
    await message.answer(text, parse_mode="HTML")

# ================== Адмін ==================

@router.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if message.reply_to_message and len(args) == 2:
        try:
            amount = int(args[1])
            target_id = message.reply_to_message.from_user.id
            target_name = message.reply_to_message.from_user.first_name
        except:
            await message.answer("Відповідай на повідомлення: /give 100")
            return
    elif len(args) == 3:
        try:
            target_id = int(args[1])
            amount = int(args[2])
            target_name = str(target_id)
        except:
            await message.answer("/give ID кількість")
            return
    else:
        await message.answer("Формат: /give 100 (реплаєм) або /give ID 100")
        return

    if amount <= 0:
        await message.answer("Тільки додатні числа")
        return

    await update_balance(target_id, amount)
    new_bal = await get_balance(target_id)
    await message.answer(f"✅ Кинув {amount}$ на {target_name}\nТепер: {new_bal}")

@router.message(F.text.regexp(r"^/thief([1-5])?_start$"))
async def any_thief_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    # Визначаємо номер вора з команди (/thief_start -> "1", /thief3_start -> "3")
    cmd = message.text.split()[0]
    num = cmd.replace("/thief", "").replace("_start", "") or "1"
    cfg = THIEVES[num]

    end_time = time.time() + cfg["days"] * 24 * 3600
    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {f"thief_{num}_end": end_time}},
        upsert=True
    )
    await message.answer(cfg["start_msg"])


# Універсальна зупинка: /thief_stop, /thief2_stop ... /thief5_stop
@router.message(F.text.regexp(r"^/thief([1-5])?_stop$"))
async def any_thief_stop(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    cmd = message.text.split()[0]
    num = cmd.replace("/thief", "").replace("_stop", "") or "1"
    cfg = THIEVES[num]

    await settings_collection.update_one(
        {"_id": "main"},
        {"$unset": {f"thief_{num}_end": ""}}
    )
    await message.answer(cfg["stop_msg"])


# Перевірка всіх активних ворів
async def try_steal(user_id: int):
    settings = await settings_collection.find_one({"_id": "main"})
    if not settings:
        return

    user = await ensure_user(user_id)
    now = time.time()

    for num, cfg in THIEVES.items():
        end_time = settings.get(f"thief_{num}_end", 0)
        if now > end_time:
            continue

        # Перевірка рівня охорони
        lvl = cfg["protect_level"]
        if lvl == 1 and (user.get("has_protection") or user.get("has_protection2")):
            continue
        if lvl == 2 and user.get("has_protection2"):
            continue

        # Окремий таймер на 20 годин для кожного вора
        last = user.get(f"last_stolen_{num}_at", 0)
        if now - last < 20 * 3600:
            continue

        balance = user.get("balance", 0)
        if balance < 5:
            continue

        stolen = max(1, int(balance * cfg["percent"]))
        await update_balance(user_id, -stolen)
        user["balance"] -= stolen  # Оновлюємо локально, якщо активні одразу 2 вори

        await users_collection.update_one(
            {"user_id": user_id},
            {"$set": {f"last_stolen_{num}_at": now}}
        )

        pct_display = int(cfg["percent"] * 100)
            
        # 1. Отправляем в личку игроку
        try:
            await bot.send_message(user_id, f"🕵️ {cfg['name']} вкрав у тебе {stolen}$ ({pct_display}%)")
        except Exception:
            pass

        # 2. Получаем имя игрока и отправляем в группу
        try:
            chat_user = await bot.get_chat(user_id)
            name = chat_user.first_name or str(user_id)
        except Exception:
            name = str(user_id)

        try:
            await bot.send_message(
                GROUP_ID,
                f"🕵️‍♂️ <b>Вор!</b> <a href='tg://user?id={user_id}'>{name}</a> обікрали на {stolen}$!",
                parse_mode="HTML"
            )
        except Exception:
            pass

@router.message(Command("policia"))
async def policia_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    end_time = time.time() + 1 * 24 * 3600
    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {"policia_end": end_time}},
        upsert=True
    )
    await message.answer("👮‍♂️ поліція пішла ловити злочинців")

@router.message(Command("policia_stop"))
async def policia_stop(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await settings_collection.update_one(
        {"_id": "main"},
        {"$unset": {"policia_end": ""}}
    )
    await message.answer("Міліція закінчила розшук")

async def try_arest(user_id: int):
    settings = await settings_collection.find_one({"_id": "main"})
    if not settings or "policia_end" not in settings:
        return
    if time.time() > settings["policia_end"]:
        return

    user = await ensure_user(user_id)

    # Вже сидить
    if user.get("arest"):
        return

    # Вже є активний вибір (чекаємо рішення)
    if user_id in pending_arest:
        return

    # Кулдаун 24 години між спробами
    last = user.get("last_zaderjanie_at", 0)
    if time.time() - last < 24 * 3600:
        return

# Перевірка адвоката
    if user.get("has_advocat"):
        zashiti_mene = random.randint(1, 5)
        if zashiti_mene >= 3:
            await users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "has_advocat": False,
                        "last_zaderjanie_at": time.time()   # ← додав
                    }
                }
            )
            try:
                await bot.send_message(user_id, "⚖️ Твій адвокат відмазав тебе від ментів, але його послуги закінчились.")
            except Exception:
                pass
            return

    # Ставимо в очікування вибору
    expire = time.time() + AREST_CHOICE_TIME
    pending_arest[user_id] = expire

    # Відправляємо вибір
    text = (
        "👮‍♂️ <b>Міліція!</b>\n\n"
        "Тебе прижала міліція. Вибирай:\n"
        "• Арест на 1 день (без ферми, шопа та продажу)\n"
        "• Дати взятку 100$ (<b>Увага:</b> шанс 25%, що все одно посадять)"
    )
    buttons = [
        [InlineKeyboardButton(text="🔒 Піти в тюрму на 1 день", callback_data="choose_arest")],
        [InlineKeyboardButton(text="💸 Дати взятку 100$ (ризик 25%)", callback_data="try_bribe")]
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Отримуємо ім'я для згадки
    try:
        chat_user = await bot.get_chat(user_id)
        name = chat_user.first_name or str(user_id)
    except Exception:
        name = str(user_id)

    try:
        await bot.send_message(
            GROUP_ID,
            f"👮‍♂️ <b>Міліція!</b>\n\n"
            f"<a href='tg://user?id={user_id}'>{name}</a>, тебе прижала міліція.\n\n"
            f"Вибирай протягом 10 хвилин:\n"
            f"• Арест на 1 день\n"
            f"• Дати взятку 100$ (шанс 25%, що все одно посадять)",
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception:
        # Якщо не вийшло надіслати в групу — одразу саджаємо
        await force_arest(user_id)
        return

    asyncio.create_task(auto_arest())

async def force_arest(user_id: int):
    """Примусово саджає людину"""
    end_arest = time.time() + 24 * 3600
    await users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "arest": True,
                "arest_end": end_arest,
                "last_zaderjanie_at": time.time()
            }
        }
    )

    # Повідомлення в групу
    try:
        chat_user = await bot.get_chat(user_id)
        name = chat_user.first_name or str(user_id)
    except Exception:
        name = str(user_id)

    try:
        await bot.send_message(
            GROUP_ID,
            f"🚨 Міліція прийшла до <a href='tg://user?id={user_id}'>{name}</a> і закрила його на 1 день!",
            parse_mode="HTML"
        )
    except Exception:
        pass

async def auto_arest():
    while True:
        await asyncio.sleep(10)  # Проверяем каждые 10 секунд
        now = time.time()
        expired_users = []
        
        for user_id, expire_time in list(pending_arest.items()):
            if now >= expire_time:
                expired_users.append(user_id)
                del pending_arest[user_id]
        
        for user_id in expired_users:
            await force_arest(user_id)
            try:
                await bot.send_message(
                    GROUP_ID,
                    f"⏰ Час вийшов! <a href='tg://user?id={user_id}'>Гравець</a> проігнорував міліцію і відправився в тюрму автоматично.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

@router.message(Command("econom_send"))
async def cmd_econom_broadcast(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args or command.args.strip() not in ECONOM_MESSAGES:
        await message.answer(
            "Формат: /econom 1\n"
            "Доступні варіанти: 1, 2, 3"
        )
        return

    msg_key = command.args.strip()
    text = ECONOM_MESSAGES[msg_key]

    cursor = users_collection.find({"has_econom": True})
    users = await cursor.to_list(length=None)

    if not users:
        await message.answer("Немає користувачів з has_econom = true")
        return

    success = 0
    failed = 0

    for user in users:
        try:
            await bot.send_message(user["user_id"], text)
            success += 1
            await asyncio.sleep(0.05)  # щоб не зловити флуд
        except Exception:
            failed += 1

    await message.answer(
        f"✅ Розсилка «{msg_key}» завершена\n"
        f"Успішно: {success}\n"
        f"Не вдалося: {failed}"
    )

@router.message(Command("padinnia_dolary"))
async def update_prices2(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    new_seed_prices = {}
    for key, data in ITEMS.items():
        change = data.get("zmina", 0)
        new_seed_prices[key] = max(1, data["seed_price"] + change)

    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {"seed_prices": new_seed_prices}},
        upsert=True
    )
    await message.answer(f"📉 Ціни на насіння виросли, долар впав!\n{new_seed_prices}")

@router.message(Command("rost_dolary"))
async def update_prices3(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    new_seed_prices = {}
    for key, data in ITEMS.items():
        change = random.randint(-data["fluct"], -1)
        new_seed_prices[key] = max(1, data["seed_price"] + change)

    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {"seed_prices": new_seed_prices}},
        upsert=True
    )
    await message.answer(f"📈 Ціни на насіння впали, долар виріс!\n{new_seed_prices}")

@router.message(Command("stop_dolary"))
async def reset_prices_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    # Повертаємо базові ціни тільки для насіння
    base_seed_prices = {k: v["seed_price"] for k, v in ITEMS.items()}

    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {"seed_prices": base_seed_prices}},
        upsert=True
    )
    await message.answer("🔄 Ціни на насіння стабілізовано!")

@router.message(Command("update_prices"))
async def update_prices(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    new_prices = {}
    for key, data in ITEMS.items():
        # трохи рандомимо навколо бази
        change = random.randint(-data["fluct"], data["fluct"])
        new_prices[key] = max(1, data["base_avg"] + change)

    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {"prices": new_prices}},
        upsert=True
    )
    await message.answer(f"Ціни оновлено:\n{new_prices}")

@router.message(Command("deficit"))
async def cmd_deficit(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    if not command.args:
        # Показуємо поточний статус і підказку
        settings = await settings_collection.find_one({"_id": "main"}) or {}
        def_list = settings.get("deficit_items", [])
        items_keys = ", ".join(ITEMS.keys())
        await message.answer(
            f"📦 <b>Керування дефіцитом</b>\n\n"
            f"Зараз у дефіциті: <code>{def_list if def_list else 'нічого'}</code>\n\n"
            f"Використання:\n"
            f"<code>/deficit назва</code> — вкл/викл дефіцит на товар\n"
            f"<code>/deficit all</code> — закрити весь магазин\n"
            f"<code>/deficit clear</code> — зняти весь дефіцит\n\n"
            f"Доступні ключі: <code>{items_keys}</code>",
            parse_mode="HTML"
        )
        return

    arg = command.args.strip().lower()
    settings = await settings_collection.find_one({"_id": "main"}) or {}
    def_list = set(settings.get("deficit_items", []))

    if arg == "clear":
        await settings_collection.update_one(
            {"_id": "main"},
            {"$set": {"deficit_items": []}},
            upsert=True
        )
        await message.answer("✅ Дефіцит повністю знято. Весь товар знову в наявності!")
        return

    if arg == "all":
        all_keys = list(ITEMS.keys())
        await settings_collection.update_one(
            {"_id": "main"},
            {"$set": {"deficit_items": all_keys}},
            upsert=True
        )
        await message.answer("🚨 Оголошено тотальний дефіцит! Весь товар у магазині закінчився.")
        return

    if arg not in ITEMS:
        await message.answer(f"❌ Невідомий товар. Доступні: {', '.join(ITEMS.keys())}")
        return

    # Перемикач: якщо товар вже в дефіциті — прибираємо, якщо ні — додаємо
    item_name = ITEMS[arg]["name"]
    if arg in def_list:
        def_list.remove(arg)
        status_text = f"✅ Дефіцит на <b>{item_name}</b> знято. Товар знову продається!"
    else:
        def_list.add(arg)
        status_text = f"🚨 Товар <b>{item_name}</b> тепер у дефіциті (немає в наявності)!"

    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {"deficit_items": list(def_list)}},
        upsert=True
    )
    await message.answer(status_text, parse_mode="HTML")

@router.message(Command("krizis"))
async def cmd_krizis(message: Message, command: CommandObject):
    global krizis
    if message.from_user.id != ADMIN_ID:
        return
    
    krizis = not krizis
    if krizis:
        await message.answer("Все, пізда. Криза почалась")
    else:
        await message.answer("✅ Криза закінчилась, працюємо далі")

@router.message(Command("sen"))
async def admin_send(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return
    if not command.args:
        await message.reply("Пиши: /sen текст")
        return
    try:
        await bot.send_message(GROUP_ID, command.args)
        await message.reply("✅ Кинув в групу")
    except Exception as e:
        await message.reply(f"❌ {e}")

@router.message(Command("senid"))
async def admin_send_id(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return
    if not command.args:
        await message.reply("Пиши: /senid ID текст")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Треба: /senid ID текст")
        return
    try:
        target_id = int(parts[0])
        await bot.send_message(target_id, parts[1])
        await message.reply(f"✅ Кинув {target_id}")
    except Exception as e:
        await message.reply(f"❌ {e}")

# ================== Запуск ==================
dp.include_router(router)

async def main():
    print("Бот стартує...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    asyncio.run(main())
