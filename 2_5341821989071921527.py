# FINAL CASINO BOT (AUTO CRYPTO + LIMITS + CHANNEL WITHDRAW)

import os
import random
import sqlite3
import string
import aiohttp
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

conn = sqlite3.connect("db.sqlite3")
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS invoices (id INTEGER, user_id INTEGER, amount REAL, status TEXT)")
conn.commit()

# FSM
class DepositState(StatesGroup):
    amount = State()

class WithdrawState(StatesGroup):
    amount = State()

class BetState(StatesGroup):
    amount = State()
    game = State()

# UTILS
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

                            try:
                                await bot.send_message(uid, f"✅ Пополнение +${amount}")
                            except:
                                pass

# MENU
def main_menu():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Профиль", callback_data="profile"))
    kb.add(InlineKeyboardButton("Игры", callback_data="games"))
    return kb

# PROFILE
@dp.callback_query_handler(lambda c: c.data=="profile")
async def profile(call: types.CallbackQuery):
    u = get_user(call.from_user.id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Пополнить", callback_data="dep"))
    kb.add(InlineKeyboardButton("Вывод", callback_data="wd"))
    await call.message.edit_text(f"ID:{u[0]}\nБаланс:${u[1]:.2f}", reply_markup=kb)

# DEPOSIT
@dp.callback_query_handler(lambda c: c.data=="dep")
async def dep(call: types.CallbackQuery):
    await call.message.answer("Сумма:")
    await DepositState.amount.set()

@dp.message_handler(state=DepositState.amount)
async def dep_amount(msg: types.Message, state: FSMContext):
    amount = float(msg.text)
    url = await create_invoice(amount, msg.from_user.id)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Оплатить", url=url))

    await msg.answer("Оплати счет:", reply_markup=kb)
    await state.finish()

# WITHDRAW
@dp.callback_query_handler(lambda c: c.data=="wd")
async def wd(call: types.CallbackQuery):
    await call.message.answer(f"Мин вывод: {MIN_WITHDRAW}$\nВведите сумму:")
    await WithdrawState.amount.set()

@dp.message_handler(state=WithdrawState.amount)
async def wd_amount(msg: types.Message, state: FSMContext):
    amount = float(msg.text)
    user = get_user(msg.from_user.id)

    if amount < MIN_WITHDRAW:
        return await msg.answer("Слишком мало")

    if user[1] < amount:
        return await msg.answer("Недостаточно средств")

    update_balance(msg.from_user.id, -amount)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Подтвердить", callback_data=f"ok_{msg.from_user.id}_{amount}"))
    kb.add(InlineKeyboardButton("Отклонить", callback_data=f"no_{msg.from_user.id}_{amount}"))

    await bot.send_message(CHANNEL_ID, f"💸 Вывод\nID:{msg.from_user.id}\n${amount}", reply_markup=kb)
    await msg.answer("Заявка отправлена")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith("ok_"))
async def ok(call: types.CallbackQuery):
    await call.message.edit_text("✅ Выплачено")

@dp.callback_query_handler(lambda c: c.data.startswith("no_"))
async def no(call: types.CallbackQuery):
    _, uid, amount = call.data.split("_")
    update_balance(int(uid), float(amount))
    await call.message.edit_text("❌ Отклонено")

# GAMES
@dp.callback_query_handler(lambda c: c.data=="games")
async def games(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Чёт", callback_data="even"))
    kb.add(InlineKeyboardButton("Нечёт", callback_data="odd"))
    kb.add(InlineKeyboardButton("Ровно 7", callback_data="seven"))
    kb.add(InlineKeyboardButton("Произведение 18", callback_data="prod18"))
    kb.add(InlineKeyboardButton("Кит 🐋", callback_data="whale"))
    await call.message.edit_text("Игры:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data in ["even","odd","seven","whale","prod18"])
async def start_game(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(game=call.data)
    await call.message.answer(f"Мин ставка: {MIN_BET}$\\nВведите ставку:")
    await BetState.amount.set()

@dp.message_handler(state=BetState.amount)
async def play(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    game = data['game']
    bet = float(msg.text)

    user = get_user(msg.from_user.id)

    if bet < MIN_BET:
        return await msg.answer("Ставка слишком маленькая")

    if user[1] < bet:
        return await msg.answer("Недостаточно средств")

    update_balance(msg.from_user.id, -bet)

    if game == "even":
        r=random.randint(1,6)
        if r%2==0:
            win=bet*2
            update_balance(msg.from_user.id, win)
            await msg.answer(f"{r} Победа +${win}")
        else:
            await msg.answer(f"{r} Проигрыш")

    elif game == "odd":
        r=random.randint(1,6)
        if r%2==1:
            win=bet*2
            update_balance(msg.from_user.id, win)
            await msg.answer(f"{r} Победа +${win}")
        else:
            await msg.answer(f"{r} Проигрыш")

    elif game == "seven":
        a,b=random.randint(1,6),random.randint(1,6)
        if a+b==7:
            win=bet*5
            update_balance(msg.from_user.id, win)
            await msg.answer(f"{a}+{b}=7 +${win}")
        else:
            await msg.answer(f"{a}+{b} Проигрыш")

    elif game == "prod18":
        a,b=random.randint(1,6),random.randint(1,6)
        result = a * b
        if result >= 18:
            win = bet * 3
            update_balance(msg.from_user.id, win)
            await msg.answer(f"{a} × {b} = {result}
Победа +${win}")
        else:
            await msg.answer(f"{a} × {b} = {result}
Проигрыш")

    elif game == "whale":
        r=random.randint(1,100)
        if r==100:
            win=bet*100
            update_balance(msg.from_user.id, win)
            await msg.answer(f"🐋 JACKPOT +${win}")
        else:
            await msg.answer(f"{r} Проигрыш")

    await state.finish()

# START
@dp.message_handler(commands=['start'])
async def start(msg: types.Message):
    get_user(msg.from_user.id)
    await msg.answer("🎰 Казино запущено", reply_markup=main_menu())

# RUN
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.create_task(check_invoices())
    executor.start_polling(dp)
