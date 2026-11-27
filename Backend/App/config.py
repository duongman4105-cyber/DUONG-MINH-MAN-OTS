import os
from pathlib import Path
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent

# Tự động nạp file .env ở thư mục Backend/ hoặc Backend/App/
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(APP_DIR / ".env")

STATIC_DIR = APP_DIR / "static"
CROPS_DIR = STATIC_DIR / "crops"
UPLOADS_DIR = STATIC_DIR / "uploads"

CROPS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:password@127.0.0.1:3306/mtmct_db",
)
WORKER_API_KEY = os.getenv("WORKER_API_KEY", "dev-worker-key")

_raw_origins = os.getenv("CORS_ORIGINS", "*").strip()
CORS_ORIGINS = ["*"] if _raw_origins == "*" else [o.strip() for o in _raw_origins.split(",") if o.strip()]

MAX_CAMERAS = int(os.getenv("MAX_CAMERAS", "10"))
MAX_PENDING_JOBS = int(os.getenv("MAX_PENDING_JOBS", "10"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))

HEARTBEAT_OFFLINE_SEC = int(os.getenv("HEARTBEAT_OFFLINE_SEC", "90"))
JOB_TIMEOUT_SEC = int(os.getenv("JOB_TIMEOUT_SEC", "300"))
JOB_MAX_RETRIES = int(os.getenv("JOB_MAX_RETRIES", "3"))

MATCH_THR_AUTO = float(os.getenv("MATCH_THR_AUTO", "0.55"))
MATCH_THR_CANDIDATE = float(os.getenv("MATCH_THR_CANDIDATE", "0.40"))
MATCH_MAX_GAP_S = int(os.getenv("MATCH_MAX_GAP_S", "60"))