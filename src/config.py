"""
Configuration module for Multi-Plant Order Allocation System.

Loads all settings from environment variables with sensible defaults.
Uses python-dotenv to read from .env file in project root.

Environment Variables:
    LLM_PROVIDER: LLM provider to use (default: "gemini")
    LLM_MODEL: Specific model identifier (default: "gemini-2.0-flash")
    GEMINI_API_KEY: API key for Google Gemini
    MOCK_LLM: If "true", uses deterministic mock instead of real LLM calls
    DATABASE_URL: SQLite connection string (default: "sqlite:///./allocation.db")
    LOG_LEVEL: Logging level (default: "INFO")
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    """Central configuration class. All values sourced from environment variables."""

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.0-flash")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LOCAL_LLM_URL: str = os.getenv("LOCAL_LLM_URL", "http://localhost:8080")
    MOCK_LLM: bool = os.getenv("MOCK_LLM", "true").lower() == "true"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./allocation.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


# Singleton settings instance used across the application
settings = Settings()
