"""Entry point: `python run_bot.py`. Loads .env, initializes DB, starts long-polling."""
from dotenv import load_dotenv
load_dotenv()

from bot.telegram_bot import main

if __name__ == "__main__":
    main()
