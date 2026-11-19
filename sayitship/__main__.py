"""Start the server: python -m sayitship"""

import os

import uvicorn
from dotenv import load_dotenv

from .config import load_settings

load_dotenv()
load_settings()  # fail fast on a bad .env, before the server starts
uvicorn.run(
    "sayitship.main:app",
    host=os.environ.get("HOST", "127.0.0.1"),  # set this to your Tailscale IP
    port=int(os.environ.get("PORT", "8787")),
)
