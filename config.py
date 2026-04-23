"""
Shared configuration loader for all scripts.
Reads .env once, provides consistent database name and URI parsing.
"""

import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    def load_dotenv() -> None:
        return None

load_dotenv()


def get_config():
    """Return a config dict used by all scripts."""
    neo4j_uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
    database = os.getenv("NEO4J_DATABASE", "")

    # Backward compatibility: if someone still has db name in URI
    if not database and '/' in neo4j_uri:
        parts = neo4j_uri.rsplit('/', 1)
        if not parts[-1].startswith('7'):  # not a port number
            neo4j_uri = parts[0]
            database = parts[1]

    if not database:
        database = "neo4j"

    return {
        "neo4j_uri":       neo4j_uri,
        "neo4j_database":  database,
        "neo4j_username":  os.getenv("NEO4J_USERNAME", "neo4j"),
        "neo4j_password":  os.getenv("NEO4J_PASSWORD", "neo4j"),
        "llm_provider":    os.getenv("LLM_PROVIDER", "ollama"),
        "llm_model":       os.getenv("LLM_MODEL", "phi3:mini"),
        "embedding_model": os.getenv("EMBEDDING_MODEL"),
        "docs_path":       os.getenv("DOCS_PATH", "./documents"),
        "chunk_size":      int(os.getenv("CHUNK_SIZE", "1500")),
        "chunk_overlap":   int(os.getenv("CHUNK_OVERLAP", "100")),
        "tesseract_cmd":   os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        "poppler_path":    os.getenv("POPPLER_PATH", r"C:\poppler-25.12.0\Library\bin"),
    }
