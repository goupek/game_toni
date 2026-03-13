import os
from dataclasses import dataclass, field
from typing import List
from pathlib import Path

@dataclass
class Config:
    # --- Ollama Settings (Recommended Backend) ---
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:1.5b"  # Best tool calling among small models

    # --- Embedding Model (Lightweight for Jetson) ---
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"  # 80MB model
    EMBEDDING_DEVICE: str = "cuda"  # Use GPU for embeddings, falls back to CPU
    EMBEDDING_BATCH_SIZE: int = 8

    # --- Memory Settings ---
    MAX_CONTEXT_MESSAGES: int = 10  # Rolling context window
    # Semantic search requires sentence-transformers + compatible pyarrow/datasets stack.
    # Set to False (default) to use fast text search with no ML dependencies.
    # Set to True only after verifying: pip install sentence-transformers datasets>=2.20.0 tf-keras
    USE_SEMANTIC_SEARCH: bool = False
    RECALL_MEMORY_LIMIT: int = 40     # Compress to archival after this limit

    # --- RAG Settings ---
    RAG_RECALL_K: int = 3             # Max recall search results per query
    RAG_ARCHIVAL_K: int = 3           # Max archival search results per query
    RAG_LAST_N_TURNS: int = 4         # Always include this many recent messages as "last dialogue"
    LEARNED_WORDS_MAX_LINES: int = 80 # Cap learned_words block; drop oldest when exceeded

    # --- FAISS Settings (Fast Vector Search) ---
    USE_FAISS: bool = True                       # Enable FAISS for O(log n) search
    FAISS_INDEX_PATH: str = "walle_faiss.index"  # Persistent index file
    FAISS_DIMENSION: int = 384                   # all-MiniLM-L6-v2 output dimension
    FAISS_REBUILD_THRESHOLD: int = 100           # Rebuild index after N insertions

    # --- Importance Decay Settings ---
    IMPORTANCE_DECAY_HALF_LIFE: float = 30.0     # Days until recency score halves
    IMPORTANCE_STATIC_WEIGHT: float = 0.7        # Weight for static importance (0-1)
    IMPORTANCE_RECENCY_WEIGHT: float = 0.3       # Weight for recency score (0-1)

    # --- Search Settings ---
    MAX_SEARCH_RESULTS: int = 5
    SEARCH_REGIONS: List[str] = field(default_factory=lambda: ["wt-wt", "us-en"])
    # Recency half-life (seconds) for recall text search scoring; recent messages rank higher
    RECALL_RECENCY_HALFLIFE_SECONDS: float = 3600.0  # 1 hour

    # --- Jhony mode: chat (friend) vs game (helper) ---
    # "chat" = friend, conversational Russian teacher as before
    # "game" = helper: Russian only, understands English from child, gives hints not answers
    JHONY_MODE: str = "chat"
    # In game mode: short description of current game/task for hint context (prompt-only)
    CURRENT_GAME_HINT: str = ""

    # --- Robot Settings ---
    SERIAL_PORT: str = None
    BAUD_RATE: int = 9600

    def validate(self) -> bool:
        """Validates Ollama configuration."""
        try:
            import requests
            # Check connection
            res = requests.get(self.OLLAMA_BASE_URL, timeout=5)
            if res.status_code != 200:
                print(f"⚠️ Warning: Ollama server not responding at {self.OLLAMA_BASE_URL}")
                return False

            # Check model
            res = requests.get(f"{self.OLLAMA_BASE_URL}/api/tags")
            models = [m['name'] for m in res.json().get('models', [])]
            if self.OLLAMA_MODEL not in models and f"{self.OLLAMA_MODEL}:latest" not in models:
                print(f"⚠️ Warning: Model '{self.OLLAMA_MODEL}' not found.")
                print(f"   Available models: {models}")
                print(f"   Run: ollama pull {self.OLLAMA_MODEL}")
                return False

            print(f"✅ Ollama validation passed - {self.OLLAMA_MODEL}")
            return True
        except Exception as e:
            print(f"⚠️ Ollama validation failed: {e}")
            print(f"   Make sure Ollama is running: ollama serve")
            return False

    @classmethod
    def load(cls):
        return cls()

conf = Config.load()
