import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import Command
from onchain import btc_inflow_last_minutes

API_TOKEN = "1841355292:AAEXOIZkYOe4UJmmXJWNkHQUz0Z7YxWA_1k"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

subscribers = set()
latest_inflow = 0

@dp.message(Command("start"))
async def start(message: types.Message):
    chat_id = message.chat.id
    subscribers.add(chat_id)

    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(
                    text="Open MiniApp",
                    web_app=WebAppInfo(url="https://b241660030b141d7-194-242-96-14.serveousercontent.com")
                )
            ]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "You are subscribed.\nOpen MiniApp to view BTC inflow.",
        reply_markup=keyboard
    )

@dp.message(Command("inflow"))
async def inflow(message: types.Message):
    await message.answer(f"📥 Binance BTC inflow last 60 min: {latest_inflow} BTC")

async def background_alerts():
    global latest_inflow
    while True:
        try:
            latest_inflow = btc_inflow_last_minutes(60)

            if latest_inflow > 1000:
                for chat_id in subscribers:
                    await bot.send_message(
                        chat_id,
                        f"🔥 Whale inflow!\n{latest_inflow} BTC sent to Binance in 1h"
                    )
        except:
            pass

        await asyncio.sleep(120)

async def main():
    asyncio.create_task(background_alerts())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())