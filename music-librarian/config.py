from dotenv import load_dotenv
import os

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "dbname": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

LOCAL_MUSICSTREAM_URL = os.getenv("LOCAL_MUSICSTREAM_URL", "http://localhost:5217")
NAVIDROME_USER = os.getenv("NAVIDROME_USER", "admin")
NAVIDROME_PASSWORD = os.getenv("NAVIDROME_PASSWORD", "admin")

ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")