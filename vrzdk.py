import asyncio
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

bot = Bot(
    token="8582878752:AAGQGx8-6w-vf4AxDmnk-IcNHVF2oP2U4x4",
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
router = Router()
dp.include_router(router)
API_ID = 38227474
API_HASH = 'f6b6f1b384cf0b3517ee0cff3291ab50'

def run():
    async def main():
        print("bot is running...")
        await dp.start_polling(bot)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("bot stopped...")