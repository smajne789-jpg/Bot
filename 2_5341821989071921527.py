# FINAL CASINO BOT ULTRA (ANTI-ABUSE + ADMIN + PREMIUM EMOJI)

import os
import random
import sqlite3
import string
import aiohttp
import asyncio
import time

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")

MIN_BET = 0.1
MIN_WITHDRAW = 1.5
MAX_BET = 100
BET_COOLDOWN = 3

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())

conn = sqlite3.connect("db.sqlite3")
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS invoices (id INTEGER, user_id INTEGER, amount REAL, status TEXT)")
conn.commit()

# анти абуз
user_last_bet = {}
user_checks_used = {}
checks = {}

# FSM
class DepositState(StatesGroup):
    amount = State()

class WithdrawState(StatesGroup):
    amount = State()

class BetState(StatesGroup):
    amount = State()
    game = State()

class CheckState(StatesGroup):
    amount = State()
    uses = State()
    min_dep = State()

# utils
def get_user(uid):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    u = cursor.fetchone()
    if not u:
        cursor.execute("INSERT INTO users VALUES (?,0)", (uid,))
        conn.commit()
        return (uid,0)
    return u

def update_balance(uid, amount):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    conn.commit()

def can_bet(uid):
    now = time.time()
    if uid in user_last_bet and now - user_last_bet[uid] < BET_COOLDOWN:
        return False
    user_last_bet[uid] = now
    return True

# CRYPTO
async def create_invoice(amount, uid):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    data = {"asset": "USDT", "amount": amount}

    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=data, headers=headers) as r:
            res = await r.json()
            inv = res['result']

            cursor.execute("INSERT INTO invoices VALUES (?,?,?,?)", (inv['invoice_id'], uid, amount, "pending"))
            conn.commit()

            return inv['pay_url']

async def check_invoices():
    while True:
        await asyncio.sleep(10)

        cursor.execute("SELECT * FROM invoices WHERE status='pending'")
        invoices = cursor.fetchall()

        for inv in invoices:
            invoice_id, uid, amount, status = inv

            url = "https://pay.crypt.bot/api/getInvoices"
            headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
            params = {"invoice_ids": invoice_id}

            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=headers, params=params) as r:
                    data = await r.json()

                    if data['result']['items']:
                        invoice = data['result']['items'][0]

                        if invoice['status'] == 'paid':
                            update_balance(uid, amount)

                            cursor.execute("UPDATE invoices SET status='paid' WHERE id=?", (invoice_id,))
                            conn.commit()

                            await bot.send_message(uid, f"<emoji id=5210952531676504517>💳</emoji> Пополнение +${amount}")

# MENU (НЕ INLINE)
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("👤 Профиль"), KeyboardButton("🎮 Играть"))
    return kb

# START
@dp.message_handler(commands=['start'])
async def start(msg: types.Message):
    get_user(msg.from_user.id)

    # чек активация
    if "check_" in msg.text:
        code = msg.text.split("check_")[1]

        if code in checks:
            if code not in user_checks_used:
                user_checks_used[code] = []

            if msg.from_user.id in user_checks_used[code]:
                return await msg.answer("❌ Уже использовал")

            check = checks[code]

            cursor.execute("SELECT SUM(amount) FROM invoices WHERE user_id=? AND status='paid'", (msg.from_user.id,))
            total_dep = cursor.fetchone()[0] or 0

            if total_dep < check['min_dep']:
                return await msg.answer("❌ Недостаточно депозита")

            update_balance(msg.from_user.id, check['amount'])
            check['uses'] -= 1
            user_checks_used[code].append(msg.from_user.id)

            await msg.answer(f"🎉 Чек активирован +${check['amount']}")

    await msg.answer(
        "<emoji id=5409048419211682843>🎰</emoji> Добро пожаловать в PAVLUCK CASINO",
        reply_markup=main_menu()
    )

# PROFILE
@dp.message_handler(lambda m: m.text == "👤 Профиль")
async def profile(msg: types.Message):
    u = get_user(msg.from_user.id)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💳 Пополнить", callback_data="dep"))
    kb.add(InlineKeyboardButton("💸 Вывод", callback_data="wd"))

    await msg.answer(
        f"<emoji id=5206607081334906820>👤</emoji> ID: {u[0]}\nБаланс: ${u[1]:.2f}",
        reply_markup=kb
    )

# DEPOSIT
@dp.callback_query_handler(lambda c: c.data=="dep")
async def dep(call: types.CallbackQuery):
    await call.message.answer("Сумма:")
    await DepositState.amount.set()

@dp.message_handler(state=DepositState.amount)
async def dep_amount(msg: types.Message, state: FSMContext):
    url = await create_invoice(float(msg.text), msg.from_user.id)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Оплатить", url=url))

    await msg.answer("Оплати:", reply_markup=kb)
    await state.finish()

# WITHDRAW (канал)
@dp.callback_query_handler(lambda c: c.data=="wd")
async def wd(call: types.CallbackQuery):
    await call.message.answer("Введите сумму:")
    await WithdrawState.amount.set()

@dp.message_handler(state=WithdrawState.amount)
async def wd_amount(msg: types.Message, state: FSMContext):
    amount = float(msg.text)
    user = get_user(msg.from_user.id)

    if amount < MIN_WITHDRAW or user[1] < amount:
        return await msg.answer("❌ Ошибка")

    update_balance(msg.from_user.id, -amount)

    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("✅ Выплатить", callback_data=f"pay_{msg.from_user.id}_{amount}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"deny_{msg.from_user.id}_{amount}")
    )

    await bot.send_message(
        CHANNEL_ID,
        f"💸 Заявка\nID:{msg.from_user.id}\n${amount}",
        reply_markup=kb
    )

    await msg.answer("⏳ Ожидайте")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("pay_"))
async def pay(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    _, uid, amount = call.data.split("_")
    await bot.send_message(uid, f"✅ Выплата ${amount}")
    await call.message.edit_text("✅ Выплачено")

@dp.callback_query_handler(lambda c: c.data.startswith("deny_"))
async def deny(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    _, uid, amount = call.data.split("_")
    update_balance(int(uid), float(amount))
    await bot.send_message(uid, "❌ Отказ")
    await call.message.edit_text("❌ Отклонено")

# GAMES
@dp.message_handler(lambda m: m.text == "🎮 Играть")
async def games(msg: types.Message):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎲 Чёт x2", callback_data="even"))
    kb.add(InlineKeyboardButton("🔥 7 x5", callback_data="seven"))
    kb.add(InlineKeyboardButton("💎 x3", callback_data="prod18"))
    kb.add(InlineKeyboardButton("🐋 x100", callback_data="whale"))

    await msg.answer("<emoji id=5271604874419647061>🎮</emoji> Игры:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data in ["even","seven","prod18","whale"])
async def start_game(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(game=call.data)
    await call.message.answer("Ставка:")
    await BetState.amount.set()

@dp.message_handler(state=BetState.amount)
async def play(msg: types.Message, state: FSMContext):
    if not can_bet(msg.from_user.id):
        return await msg.answer("⏳ Подожди")

    data = await state.get_data()
    game = data['game']
    bet = float(msg.text)

    if bet < MIN_BET or bet > MAX_BET:
        return await msg.answer("❌ Лимит")

    user = get_user(msg.from_user.id)
    if user[1] < bet:
        return await msg.answer("❌ Нет средств")

    update_balance(msg.from_user.id, -bet)

    r = random.randint(1,6)

    if game == "even" and r%2==0:
        win = bet*2
    elif game == "seven":
        win = bet*5 if random.randint(1,6)+random.randint(1,6)==7 else 0
    elif game == "prod18":
        win = bet*3 if random.randint(1,6)*random.randint(1,6)>=18 else 0
    elif game == "whale":
        win = bet*100 if random.randint(1,100)==100 else 0
    else:
        win = 0

    if win > 0:
        update_balance(msg.from_user.id, win)
        await msg.answer(f"<emoji id=5224607267797606837>💎</emoji> +${win}")
    else:
        await msg.answer("❌ Проигрыш")

    await state.finish()

# RUN
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(check_invoices())
    executor.start_polling(dp)
