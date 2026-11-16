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

active_casino_games = {}

# ================== Константи ==================
ITEMS = {
    "marijuana": {"name": "Марихуана", "seed_price": 15, "base_avg": 17, "fluct": 5},
    "hashish":   {"name": "Гашиш",     "seed_price": 30, "base_avg": 35, "fluct": 10},
    "poppy":     {"name": "Мак",       "seed_price": 60, "base_avg": 70, "fluct": 20},
    "cocaine":   {"name": "Кокаїн",    "seed_price": 120, "base_avg": 140, "fluct": 40},
}

CASINO_BETS = [10, 50, 300]
CASINO_PRICE = 300
PROTECTION_PRICE = 150

# ================== Допоміжні функції ==================

async def ensure_user(user_id: int):
    user = await users_collection.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "balance": 0,
            "has_protection": False,
            "inventory": {
                "marijuana": {"normal": 0, "frozen": 0},
                "hashish": {"normal": 0, "frozen": 0},
                "poppy": {"normal": 0, "frozen": 0},
                "cocaine": {"normal": 0, "frozen": 0},
            },
            "last_stolen_at": 0
        }
        await users_collection.insert_one(user)
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
    field = "frozen" if frozen else "normal"
    await users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {f"inventory.{item}.{field}": amount}}
    )

async def remove_item(user_id: int, item: str, frozen: bool = False, amount: int = 1) -> bool:
    user = await ensure_user(user_id)
    field = "frozen" if frozen else "normal"
    current = user["inventory"].get(item, {}).get(field, 0)
    if current < amount:
        return False
    await users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {f"inventory.{item}.{field}": -amount}}
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
        "ферма — бабло рубати\n"
        "/top — топ бариг",
        parse_mode="HTML"
    )

# ================== Баланс ==================

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id)
    await try_steal(user_id)
    balance = await get_balance(user_id)
    user = await users_collection.find_one({"user_id": user_id})
    prot = "✅ Є охорона" if user.get("has_protection") else "❌ Немає охорони"

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

    now = time.time()
    if user_id in last_farm_time:
        left = FARM_COOLDOWN - (now - last_farm_time[user_id])
        if left > 0:
            minutes = int(left // 60)
            seconds = int(left % 60)
            await message.answer(f"⏳ Ще рано, бля. Чекай {minutes} хв {seconds} сек")
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
    await ensure_user(message.from_user.id)

    text = "🛒 <b>Магазин</b>\n\n"
    text += "<b>Насіння</b> (одразу дає врожай):\n"
    for key, data in ITEMS.items():
        text += f"• {data['name']} — {data['seed_price']}$\n"

    text += f"\n🛡 Охорона (назавжди) — {PROTECTION_PRICE}$\n"
    text += f"🎰 Казино — {CASINO_PRICE}$\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Марихуана 15$", callback_data="buy_seed_marijuana")],
        [InlineKeyboardButton(text="Гашиш 30$", callback_data="buy_seed_hashish")],
        [InlineKeyboardButton(text="Мак 60$", callback_data="buy_seed_poppy")],
        [InlineKeyboardButton(text="Кокаїн 120$", callback_data="buy_seed_cocaine")],
        [InlineKeyboardButton(text=f"Охорона {PROTECTION_PRICE}$", callback_data="buy_protection")],
        [InlineKeyboardButton(text=f"Купити казино {CASINO_PRICE}$", callback_data="buy_casino")],
    ])

    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_seed_"))
async def buy_seed(callback: CallbackQuery):
    user_id = callback.from_user.id
    item = callback.data.replace("buy_seed_", "")
    if item not in ITEMS:
        await callback.answer("Хуйня якась", show_alert=True)
        return

    price = ITEMS[item]["seed_price"]
    balance = await get_balance(user_id)

    if balance < price:
        await callback.answer("Немає бабла, бля", show_alert=True)
        return

    await update_balance(user_id, -price)
    await add_item(user_id, item, frozen=False, amount=1)

    await callback.answer()
    await callback.message.answer(
        f"✅ Купив {ITEMS[item]['name']} за {price}$\n"
        f"Врожай вже в інвентарі. Дивись /inv"
    )

@router.callback_query(F.data == "buy_protection")
async def buy_protection(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await ensure_user(user_id)

    if user.get("has_protection"):
        await callback.answer("У тебе вже є охорона, нахуй повторно", show_alert=True)
        return

    balance = await get_balance(user_id)
    if balance < PROTECTION_PRICE:
        await callback.answer("Не вистачає бабла", show_alert=True)
        return

    await update_balance(user_id, -PROTECTION_PRICE)
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"has_protection": True}}
    )
    await callback.answer()
    await callback.message.answer("🛡 Охорону купив. Тепер вор тебе не дістане.")

@router.callback_query(F.data == "buy_casino")
async def buy_casino(callback: CallbackQuery):
    user_id = callback.from_user.id
    casino = await get_casino()

    if casino.get("owner_id"):
        await callback.answer("Казино вже хтось купив", show_alert=True)
        return

    balance = await get_balance(user_id)
    if balance < CASINO_PRICE:
        await callback.answer("Немає стількох бабок", show_alert=True)
        return

    await update_balance(user_id, -CASINO_PRICE)
    await set_casino_owner(user_id)
    await callback.answer()
    await callback.message.answer(
        f"🎰 Вітаю, ти купив казино за {CASINO_PRICE}$.\n"
        f"Тепер всі лохи грають на тебе."
    )

# ================== Інвентар ==================

@router.message(Command("inv"))
async def cmd_inv(message: Message):
    user_id = message.from_user.id
    inv = await get_inventory(user_id)

    text = "🎒 <b>Твій інвентар:</b>\n\n"
    has_anything = False
    buttons = []

    for key, data in ITEMS.items():
        normal = inv.get(key, {}).get("normal", 0)
        frozen = inv.get(key, {}).get("frozen", 0)

        if normal > 0 or frozen > 0:
            has_anything = True
            text += f"<b>{data['name']}</b>\n"
            if normal > 0:
                text += f"  • Звичайний: {normal}\n"
                buttons.append([
                    InlineKeyboardButton(text=f"Продати боту {data['name']}", callback_data=f"sellbot_{key}"),
                    InlineKeyboardButton(text=f"Заморозити", callback_data=f"freeze_{key}")
                ])
                buttons.append([
                    InlineKeyboardButton(text=f"На дошку {data['name']}", callback_data=f"market_add_{key}_0")
                ])
            if frozen > 0:
                text += f"  • Заморожений: {frozen}\n"
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
    item = callback.data.replace("sellbot_", "")
    user_id = callback.from_user.id

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

    success = await remove_item(user_id, item, frozen=False, amount=1)
    if not success:
        await callback.answer("Немає звичайного врожаю", show_alert=True)
        return

    await add_item(user_id, item, frozen=True, amount=1)
    await callback.answer()
    await callback.message.answer(f"❄️ {ITEMS[item]['name']} заморозив.")

@router.callback_query(F.data.startswith("unfreeze_"))
async def unfreeze_item(callback: CallbackQuery):
    item = callback.data.replace("unfreeze_", "")
    user_id = callback.from_user.id

    success = await remove_item(user_id, item, frozen=True, amount=1)
    if not success:
        await callback.answer("Немає замороженого", show_alert=True)
        return

    await add_item(user_id, item, frozen=False, amount=1)
    await callback.answer()
    await callback.message.answer(f"🌡 {ITEMS[item]['name']} розморозив.")

# ================== Дошка оголошень ==================

@router.message(Command("market"))
async def cmd_market(message: Message):
    listings = await market_collection.find().sort("created_at", -1).limit(15).to_list(15)

    if not listings:
        await message.answer("Дошка пуста.")
        return

    text = "📋 <b>Дошка оголошень</b>\n\n"
    buttons = []

    for listing in listings:
        item_name = ITEMS[listing["item"]]["name"]
        frozen_text = " (зам)" if listing.get("frozen") else ""
        seller_name = listing.get("seller_name", str(listing["seller_id"]))
        text += f"• {item_name}{frozen_text} — <b>{listing['price']}$</b> від {seller_name}\n"

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
    parts = callback.data.split("_")
    item = parts[2]
    frozen = parts[3] == "1"
    await callback.answer()
    await callback.message.answer(
        f"Щоб виставити {ITEMS[item]['name']}{' (зам)' if frozen else ''}:\n"
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
        item = parts[0]
        frozen = parts[1] == "1"
        price = int(parts[2])
    except:
        await message.answer("Невірний формат, бля")
        return

    if item not in ITEMS:
        await message.answer("Невідомий предмет")
        return
    if price < 1:
        await message.answer("Ціна від 1$")
        return

    success = await remove_item(user_id, item, frozen=frozen, amount=1)
    if not success:
        await message.answer("У тебе немає цього лайна")
        return

    await market_collection.insert_one({
        "seller_id": user_id,
        "seller_name": message.from_user.first_name,
        "item": item,
        "frozen": frozen,
        "price": price,
        "created_at": time.time()
    })

    await message.answer(f"✅ Виставив {ITEMS[item]['name']} за {price}$")

@router.callback_query(F.data.startswith("market_buy_"))
async def market_buy(callback: CallbackQuery):
    listing_id = callback.data.replace("market_buy_", "")
    buyer_id = callback.from_user.id

    try:
        listing = await market_collection.find_one({"_id": ObjectId(listing_id)})
    except:
        await callback.answer("Оголошення не знайдено", show_alert=True)
        return

    if not listing:
        await callback.answer("Вже хтось купив", show_alert=True)
        return

    if listing["seller_id"] == buyer_id:
        await callback.answer("Своє купувати не можна", show_alert=True)
        return

    price = listing["price"]
    balance = await get_balance(buyer_id)
    if balance < price:
        await callback.answer("Не вистачає бабла", show_alert=True)
        return

    await update_balance(buyer_id, -price)
    await update_balance(listing["seller_id"], price)
    await add_item(buyer_id, listing["item"], frozen=listing.get("frozen", False), amount=1)
    await market_collection.delete_one({"_id": listing["_id"]})

    await callback.answer()
    await callback.message.answer(f"✅ Купив {ITEMS[listing['item']]['name']} за {price}$")

    try:
        await bot.send_message(listing["seller_id"], f"💰 Хтось купив твій товар за {price}$")
    except:
        pass

# ================== Казино (з жорстким захистом) ==================

@router.message(Command("casino"))
async def cmd_casino(message: Message):
    user_id = message.from_user.id
    await ensure_user(user_id)

    casino = await get_casino()
    if not casino.get("owner_id"):
        await message.answer("Казино зараз нікому не належить. Купи в /shop")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Ставка {bet}$", callback_data=f"casinobet_{bet}")]
        for bet in CASINO_BETS
    ])

    await message.answer(
        f"🎰 <b>Казино</b>\n"
        f"Власник: <code>{casino['owner_id']}</code>\n\n"
        f"Вибери ставку:",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("casinobet_"))
async def casino_choose_bet(callback: CallbackQuery):
    user_id = callback.from_user.id
    bet = int(callback.data.replace("casinobet_", ""))

    if bet not in CASINO_BETS:
        await callback.answer("Хуйня ставка", show_alert=True)
        return

    balance = await get_balance(user_id)
    if balance < bet:
        await callback.answer("Немає стількох бабок", show_alert=True)
        return

    casino = await get_casino()
    owner_id = casino.get("owner_id")
    if not owner_id:
        await callback.answer("Казино вже не працює", show_alert=True)
        return

    await update_balance(user_id, -bet)

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
        "finished": False,
        "locked": False
    }
    await callback.answer()

@router.callback_query(F.data.startswith("casopen_"))
async def casino_open_cell(callback: CallbackQuery):
    parts = callback.data.split("_")
    owner_of_game = int(parts[1])
    cell_idx = int(parts[2])
    user_id = callback.from_user.id

    if user_id != owner_of_game:
        await callback.answer("Це не твоя гра, бля!", show_alert=True)
        return

    msg_id = callback.message.message_id
    game = active_casino_games.get(msg_id)

    if not game:
        await callback.answer("Гра вже закінчена", show_alert=True)
        return

    # ЖОРСТКИЙ ЗАХИСТ
    if game.get("finished") or game.get("locked"):
        await callback.answer()
        return

    game["locked"] = True

    try:
        if cell_idx in game["opened"]:
            await callback.answer("Вже відкрито")
            return

        game["opened"].add(cell_idx)
        opened_count = len(game["opened"])

        if opened_count > 3:
            await callback.answer()
            return

        keyboard_rows = []
        for r in range(3):
            row = []
            for c in range(3):
                idx = r * 3 + c
                if idx in game["opened"]:
                    row.append(InlineKeyboardButton(text=game["emojis"][idx], callback_data="noop"))
                else:
                    if opened_count >= 3:
                        row.append(InlineKeyboardButton(text="⬛", callback_data="noop"))
                    else:
                        row.append(InlineKeyboardButton(text="⬛", callback_data=f"casopen_{user_id}_{idx}"))
            keyboard_rows.append(row)

        markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        if opened_count < 3:
            await callback.message.edit_text(
                f"Ставка: <b>{game['bet']}$</b>\nВідкрий ще {3 - opened_count}",
                reply_markup=markup,
                parse_mode="HTML"
            )
            await callback.answer()
            return

        # Гра закінчена
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
            result_text = f"💸 Програв, лох -{bet}$"

        if win_amount > 0:
            owner_balance = await get_balance(owner_id)
            if owner_balance >= win_amount:
                await update_balance(owner_id, -win_amount)
                await update_balance(user_id, win_amount)
            else:
                await update_balance(user_id, win_amount)
                await set_casino_owner(None)
                result_text += "\n\n⚠️ У власника кінчились бабки. Казино повернулось в магазин!"
        else:
            await update_balance(owner_id, bet)

        current_balance = await get_balance(user_id)

        await callback.message.edit_text(
            f"Ставка: <b>{bet}$</b>\n"
            f"{result_text}\n\n"
            f"Твій баланс: <b>{current_balance}$</b>",
            reply_markup=markup,
            parse_mode="HTML"
        )

        if msg_id in active_casino_games:
            del active_casino_games[msg_id]

        await callback.answer()

    finally:
        if msg_id in active_casino_games and not active_casino_games[msg_id].get("finished"):
            active_casino_games[msg_id]["locked"] = False

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



    await update_balance(target_id, amount)
    new_bal = await get_balance(target_id)
    await message.answer(f"✅ Кинув {amount}$ на {target_name}\nТепер: {new_bal}")

@router.message(Command("thief_start"))
async def thief_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    end_time = time.time() + 2 * 24 * 3600
    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {"thief_end": end_time}},
        upsert=True
    )
    await message.answer("🕵️ Вор вийшов на 2 дні")

@router.message(Command("thief_stop"))
async def thief_stop(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await settings_collection.update_one(
        {"_id": "main"},
        {"$unset": {"thief_end": ""}}
    )
    await message.answer("Вор сховався")

async def try_steal(user_id: int):
    settings = await settings_collection.find_one({"_id": "main"})
    if not settings or "thief_end" not in settings:
        return
    if time.time() > settings["thief_end"]:
        return

    user = await ensure_user(user_id)
    if user.get("has_protection"):
        return

    last = user.get("last_stolen_at", 0)
    if time.time() - last < 20 * 3600:
        return

    balance = user["balance"]
    if balance < 5:
        return

    stolen = max(1, int(balance * 0.20))
    await update_balance(user_id, -stolen)
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"last_stolen_at": time.time()}}
    )
    try:
        await bot.send_message(user_id, f"🕵️ Вор вкрав у тебе {stolen}$ (20%)")
    except:
        pass

@router.message(Command("update_prices"))
async def update_prices_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    new_prices = {}
    for key, data in ITEMS.items():
        change = random.randint(-data["fluct"], data["fluct"])
        new_prices[key] = max(1, data["base_avg"] + change)

    await settings_collection.update_one(
        {"_id": "main"},
        {"$set": {"prices": new_prices}},
        upsert=True
    )
    await message.answer(f"Ціни оновлено:\n{new_prices}")

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
