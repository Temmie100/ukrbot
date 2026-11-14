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

# Подключение к MongoDB Atlas
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["casino_bot_db"]
users_collection = db["users"]

last_farm_time = {}
FARM_COOLDOWN = 3600  # 1 година

# Сховище для активних ігор у казино: {message_id: game_data}
active_casino_games = {}


# ================== Функції для роботи з MongoDB ==================

async def get_balance(user_id: int) -> int:
    user = await users_collection.find_one({"user_id": user_id})
    if user is None:
        # Если юзера нет в базе, создаем с балансом 0
        await users_collection.insert_one({"user_id": user_id, "balance": 0})
        return 0
    return user["balance"]

async def update_balance(user_id: int, delta: int):
    # Гарантируем, что документ существует перед обновлением
    await get_balance(user_id)
    await users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": delta}}
    )


# ================== Команди казино ==================

@router.message(Command("casino"))
async def cmd_casino(message: Message, command: CommandObject):
    user_id = message.from_user.id
    
    if not command.args:
        await message.answer(
            "Бля, ось так пиши:\n"
            "<code>/casino сума</code>\n\n"
            "Приклад: <code>/casino 100</code>\n",
            parse_mode="HTML"
        )
        return

    try:
        amount = int(command.args)
    except ValueError:
        await message.answer("Сума повинна бути числом.")
        return

    if amount < 1:
        await message.answer("Мінімальна ставка — від 1$!")
        return

    balance = await get_balance(user_id)
    if balance < amount:
        await message.answer(f"Недостаточно доларів. У тебе: {balance}")
        return

    # Спишаем ставку
    await update_balance(user_id, -amount)

    # Генеруємо набір із 9 смайликів
    pool_templates = [
        ("😂", "😂", "😂"),  # 3
        ("😒", "😒"),        # 2
        ("👍", "👍"),        # 2
        ("🙊",),             # 1
        ("👌",)              # 1
    ]
    all_emojis = []
    for item in pool_templates:
        all_emojis.extend(item)
    
    random.shuffle(all_emojis)

    keyboard_rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            row.append(InlineKeyboardButton(text="⬛", callback_data=f"cas_{user_id}_{idx}"))
        keyboard_rows.append(row)
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    sent_msg = await message.answer(
        f" Ставка: <b>{amount} $</b>\n"
        f"Відкрийте 3 ячейки.",
        reply_markup=markup,
        parse_mode="HTML"
    )

    active_casino_games[sent_msg.message_id] = {
        "user_id": user_id,
        "amount": amount,
        "emojis": all_emojis,
        "opened": set()
    }


@router.callback_query(F.data.startswith("cas_"))
async def process_casino_click(callback: CallbackQuery):
    data_parts = callback.data.split("_")
    owner_id = int(data_parts[1])
    cell_idx = int(data_parts[2])
    user_id = callback.from_user.id

    if user_id != owner_id:
        await callback.answer("Це не твоя гра, братан!", show_alert=True)
        return

    msg = callback.message
    game = active_casino_games.get(msg.message_id)

    if not game:
        await callback.answer(" Ця гра вже завершена.", show_alert=True)
        return

    if cell_idx in game["opened"]:
        await callback.answer("Ця ячейка вже відкрита!")
        return

    game["opened"].add(cell_idx)
    opened_count = len(game["opened"])

    if opened_count < 3:
        keyboard_rows = []
        for r in range(3):
            row = []
            for c in range(3):
                idx = r * 3 + c
                if idx in game["opened"]:
                    row.append(InlineKeyboardButton(text=game["emojis"][idx], callback_data="noop"))
                else:
                    row.append(InlineKeyboardButton(text="⬛", callback_data=f"cas_{user_id}_{idx}"))
            keyboard_rows.append(row)
        
        await msg.edit_text(
            f" Ставка: <b>{game['amount']} $</b>\n"
            f"Відкрийте ще {3 - opened_count} ячейки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
            parse_mode="HTML"
        )
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
                row.append(InlineKeyboardButton(text="⬛", callback_data="noop"))
        keyboard_rows.append(row)

    final_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    chosen_emojis = [game["emojis"][i] for i in game["opened"]]
    counts = Counter(chosen_emojis)
    max_count = max(counts.values())

    amount = game["amount"]
    win = 0
    result_text = ""

    if max_count == 3:
        win = amount * 3
        await update_balance(user_id, win)
        result_text = f"Виграш (×3): <b>+{win} $</b>"
    elif max_count == 2:
        win = amount * 2
        await update_balance(user_id, win)
        result_text = f"Виграш (×2): <b>+{win} $</b>"
    else:
        result_text = f"Програш: <b>-{amount} $</b>"

    current_balance = await get_balance(user_id)

    final_text = (
        f" Ставка: <b>{amount} $</b>\n"
        f"Результат:\n\n"
        f"{result_text}\n"
        f" Баланс: <b>{current_balance} $</b>"
    )

    await msg.edit_text(final_text, reply_markup=final_markup, parse_mode="HTML")
    
    del active_casino_games[msg.message_id]
    await callback.answer()


# ================== Решта команд ==================

@router.message(CommandStart())
async def start_command(message: Message):
    await message.reply(
        "Привіт\n"
        "Пиши ферма будеш бабло рубати.\n"
        "Команди: /balance, /top, ферма, /casino",
        parse_mode="HTML"
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    balance = await get_balance(message.from_user.id)
    await message.answer(
        f"💰 У тебе в кишені: <b>{balance}</b> доларів",
        parse_mode="HTML"
    )


@router.message(Command("give"))
async def cmd_give(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Тільки адмін може кидати бабки, не лізь.")
        return

    args = message.text.split()

    if message.reply_to_message and len(args) == 2:
        try:
            amount = int(args[1])
            target_id = message.reply_to_message.from_user.id
            target_name = message.reply_to_message.from_user.first_name
        except ValueError:
            await message.answer("Пиши так: відповідай на повідомлення і /give 100")
            return
    elif len(args) == 3:
        try:
            target_id = int(args[1])
            amount = int(args[2])
            target_name = str(target_id)
        except ValueError:
            await message.answer("Пиши: /give ID кількість")
            return
    else:
        await message.answer(
            "Як кинути бабки:\n"
            "1. Відповідай на повідомлення /give 100\n"
            "2. Або /give ID 100"
        )
        return

    if amount <= 0:
        await message.answer("Кількість має бути більше нуля.")
        return

    await update_balance(target_id, amount)
    new_bal = await get_balance(target_id)

    await message.answer(
        f"✅ Кинув <b>{amount}</b> доларів на {target_name}\n"
        f"Тепер у нього: {new_bal}",
        parse_mode="HTML"
    )


@router.message(F.text.lower() == "ферма")
async def ferma(message: Message):
    user_id = message.from_user.id
    now = time.time()

    if user_id in last_farm_time:
        left = FARM_COOLDOWN - (now - last_farm_time[user_id])
        if left > 0:
            minutes = int(left // 60)
            seconds = int(left % 60)
            await message.answer(f"⏳ Ще рано. Чекай {minutes} хв {seconds} сек")
            return

    bablo = random.randint(0, 10)
    last_farm_time[user_id] = now

    if bablo == 0:
        await message.answer("Ніхуя не випало 😅 Спробуй пізніше")
    else:
        await update_balance(user_id, bablo)
        new_bal = await get_balance(user_id)
        await message.answer(
            f"💰 Заробив <b>{bablo}</b> доларів!\n"
            f"Тепер у тебе: {new_bal}",
            parse_mode="HTML"
        )


@router.message(Command("top"))
async def cmd_top(message: Message):
    # Достаем топ-10 пользователей, отсортированных по балансу
    cursor = users_collection.find().sort("balance", -1).limit(10)
    top_users = await cursor.to_list(length=10)

    if not top_users:
        await message.answer("Поки ніхто нічого не має 🤷‍♂️")
        return
    
    text = "🏆 <b>Топ бариг:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7

    for i, user_data in enumerate(top_users):
        user_id = user_data["user_id"]
        balance = user_data["balance"]
        try:
            user = await bot.get_chat(user_id)
            name = user.first_name or str(user_id)
        except:
            name = str(user_id)
        
        text += f"{medals[i]} {name} — <b>{balance}</b>\n"

    await message.answer(text, parse_mode="HTML")


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
        await message.reply(f"❌ Помилка: {e}")


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
        text = parts[1]
        await bot.send_message(target_id, text)
        await message.reply(f"✅ Кинув юзеру {target_id}")
    except ValueError:
        await message.reply("ID має бути числом")
    except Exception as e:
        await message.reply(f"❌ Помилка: {e}")


# ================== Запуск ==================
dp.include_router(router)

async def main():
    print("Бот стартує з MongoDB Atlas...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    asyncio.run(main())
if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    asyncio.run(main())
