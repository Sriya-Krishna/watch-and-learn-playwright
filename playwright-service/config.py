import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# LLM
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

# Playwright
PLAYWRIGHT_SERVICE_PORT = int(os.getenv("PLAYWRIGHT_SERVICE_PORT", "3001"))
PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
PLAYWRIGHT_TIMEOUT = int(os.getenv("PLAYWRIGHT_TIMEOUT", "60000"))  # ms

# Self-heal
MAX_HEAL_ATTEMPTS = int(os.getenv("MAX_HEAL_ATTEMPTS", "3"))

# Storage
SCRIPT_STORAGE_PATH = os.getenv("SCRIPT_STORAGE_PATH", "./scripts")
DB_PATH = os.getenv("DB_PATH", "./playwright_service.db")
