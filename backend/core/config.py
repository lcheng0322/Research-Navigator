from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the project root directory (the parent of the 'backend' directory)
PROJECT_ROOT = Path(__file__).parent.parent

class Settings(BaseSettings):
    """
    A class to hold all application settings, loaded from a .env file and environment variables.
    Pydantic's BaseSettings handles the loading and type validation automatically.
    """
    # --- .env file configuration ---
    # Tell pydantic-settings where to find the .env file.
    # We construct an absolute path to ensure it's always found correctly.
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding='utf-8', extra='ignore')

    # --- Database Configuration ---
    DATABASE_FILE: Path = PROJECT_ROOT / "data" / "research_navigator.db"
    DATABASE_URL: str = f"sqlite:///{DATABASE_FILE.resolve()}"

    # --- Redis & Celery Configuration ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Directory Configuration ---
    UPLOAD_DIR: Path = PROJECT_ROOT / "data" / "uploads"

    # --- Vector Store Configuration ---
    CHROMA_PERSIST_DIR: Path = PROJECT_ROOT / "data" / "chroma_db"
    CHUNKS_COLLECTION_NAME: str = "document_chunks"
    SUMMARIES_COLLECTION_NAME: str = "document_summaries"
    CHAPTER_SUMMARIES_COLLECTION_NAME: str = "document_chapter_summaries"

    # --- Model Configuration ---
    # Switched to more powerful BGE models as per the optimization plan.
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-large-en-v1.5"
    CROSS_ENCODER_MODEL_NAME: str = "BAAI/bge-reranker-base"

    # --- LLM Configuration ---
    # The default values are used if the variable is not found in the .env file.
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_REASONER_MODEL_NAME: str = "deepseek-reasoner"
    DEEPSEEK_CHAT_MODEL_NAME: str = "deepseek-chat"

    # --- RAG Configuration ---
    RAG_QUERY_TOP_K: int = 10

    # --- Document Processor Configuration ---
    PROCESSOR_DOI_PRIMARY_SCAN_LIMIT: int = 20
    PROCESSOR_DOI_EXTENDED_SCAN_LIMIT: int = 120
    PROCESSOR_CROSSREF_TIMEOUT: int = 10
    PROCESSOR_LLM_METADATA_TRUNCATION: int = 4000
    PROCESSOR_LLM_SUMMARY_TRUNCATION: int = 15000
    PROCESSOR_CHUNK_SIZE: int = 3000
    PROCESSOR_CHUNK_OVERLAP: int = 300
    PROCESSOR_WIDE_TABLE_THRESHOLD: int = 8

    # --- Security & JWT Configuration ---
    # This key is used to sign JWTs. It should be a long, random, and secret string.
    # CRITICAL: Must be provided via environment variables or .env file.
    # To generate a new secret key, you can use: openssl rand -hex 32
    SECRET_KEY: str = "change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # --- Security: Rate Limiting ---
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    # --- Observability ---
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str | None = None

# Create a single, importable instance of the settings
settings = Settings()

# --- Directory Setup Function ---
def setup_directories():
    """Create necessary directories if they don't exist, based on the loaded settings."""
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    # Ensure the directory for the database file exists
    settings.DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)

# Run setup on import to ensure directories are ready when the app starts
setup_directories()