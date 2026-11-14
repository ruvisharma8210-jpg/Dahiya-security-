import asyncio

from bot.main import main

if __name__ == "__main__":
    # Python 3.14 no longer creates an event loop automatically,
    # and python-telegram-bot's run_polling() expects one to exist.
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
