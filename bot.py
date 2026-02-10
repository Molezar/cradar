import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import WebAppInfo
from aiogram.filters import Command

from config import BOT_TOKEN, WEBAPP_URL
from onchain import btc_inflow_last_minutes

bot = Bot(token=BOT_TOKEN)
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
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ]
        ],
        resize_keyboard=True
    )

    await message.answer("Open MiniApp 👇", reply_markup=keyboard)

async def background_alerts():
    global latest_inflow
    while True:
        try:
            latest_inflow = btc_inflow_last_minutes(60)

            if latest_inflow > 1000:
                for chat_id in subscribers:
                    await bot.send_message(
                        chat_id,
                        f"🔥 Whale inflow!\n{latest_inflow} BTC sent to Binance"
                    )
        except Exception as e:
            print("Alert error:", e)

        await asyncio.sleep(120)

async def main():
    asyncio.create_task(background_alerts())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())