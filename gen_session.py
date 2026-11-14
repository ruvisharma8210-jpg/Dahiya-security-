"""Apne computer par chalayein: python gen_session.py
Phone number + Telegram login code (+ 2FA password agar hai) maangega aur Telethon session string print karega.
Ye string bot ke /sessions -> ➕ Add New Session me paste karein. Kisi aur ke saath share na karein!
"""
import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()


async def main():
    api_id = int(os.getenv("API_ID") or input("API_ID: ").strip())
    api_hash = os.getenv("API_HASH") or input("API_HASH: ").strip()
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        me = await client.get_me()
        print(f"\n✅ Logged in as {me.first_name} (id {me.id})\n")
        print("👇 Aapki SESSION STRING (secret rakhein):\n")
        print(client.session.save())
        print()


if __name__ == "__main__":
    asyncio.run(main())
