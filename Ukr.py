from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask
from threading import Thread
import asyncio
import os
import random
import time
from collections import defaultdict
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
GROUP_ID = -1002128624256
ADMIN_ID = 1876083446

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

crypto_balances = defaultdict(int)
last_farm_time = {}

FARM_COOLDOWN = 3600  # 1 година


# ================== Команди ==================

@router.message(CommandStart())
async def start_command(message: Message):
    await message.reply(
        "Привіт\n"
        "Пиши ферма будеш бабло рубати.\n"
        "Команди: /balance, /pay, /top",
        parse_mode="HTML"
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    balance = crypto_balances[message.from_user.id]
    await message.answer(
        f"💰 У тебе в кишені: <b>{balance}</b> Долларів",
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

    crypto_balances[target_id] += amount

    await message.answer(
        f"✅ Кинув <b>{amount}</b> долларів на {target_name}\n"
        f"Тепер у нього: {crypto_balances[target_id]}",
        parse_mode="HTML"
    )




@router.message(F.text.lower() == "ферма")
async def ferma(message: Message):
    user_id = message.from_user.id
    now = time.time()

    # Перевірка кулдауну
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
        crypto_balances[user_id] += bablo
        await message.answer(
            f"💰 Заробив <b>{bablo}</b> долларів!\n"
            f"Тепер у тебе: {crypto_balances[user_id]}",
            parse_mode="HTML"
        )


@router.message(Command("top"))
async def cmd_top(message: Message):
    if not crypto_balances:
        await message.answer("Поки ніхто нічого не має 🤷‍♂️")
        return

    sorted_users = sorted(crypto_balances.items(), key=lambda x: x[1], reverse=True)[:10]
    
    text = "🏆 <b>Топ бариг:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7

    for i, (user_id, balance) in enumerate(sorted_users):
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
    print("Бот стартує...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    asyncio.run(main())