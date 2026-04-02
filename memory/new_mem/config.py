import os
from dataclasses import dataclass, field
from typing import List


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    # --- llama.cpp Settings (default backend) ---
    LLAMA_CPP_BASE_URL: str = field(default_factory=lambda: os.getenv("LLAMA_CPP_BASE_URL", "http://localhost:8080"))
    LLAMA_CPP_MODEL: str = field(default_factory=lambda: os.getenv("LLAMA_CPP_MODEL", "auto"))
    LLAMA_CPP_API_KEY: str = field(default_factory=lambda: os.getenv("LLAMA_CPP_API_KEY", "llama.cpp"))
    LLAMA_CPP_TIMEOUT_SECONDS: int = field(default_factory=lambda: int(os.getenv("LLAMA_CPP_TIMEOUT_SECONDS", "5")))
    LLAMA_CPP_FALLBACK_MODEL: str = field(default_factory=lambda: os.getenv("LLAMA_CPP_FALLBACK_MODEL", "gemma-3-1b-it"))
    PREFER_TEXT_TOOL_CALLS_FOR_SMALL_GEMMA: bool = field(
        default_factory=lambda: _env_bool("PREFER_TEXT_TOOL_CALLS_FOR_SMALL_GEMMA", True)
    )

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
    USE_FAISS: bool = True                        # Enable FAISS for O(log n) search
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

    # --- Runtime caches ---
    _resolved_model: str = field(default="", init=False, repr=False)

    @property
    def OLLAMA_BASE_URL(self) -> str:
        """Backward-compatible alias for older code paths."""
        return self.LLAMA_CPP_BASE_URL

    @property
    def OLLAMA_MODEL(self) -> str:
        """Backward-compatible alias for older code paths."""
        return self.LLAMA_CPP_MODEL

    def http_base_url(self) -> str:
        return self.LLAMA_CPP_BASE_URL.rstrip("/")

    def openai_base_url(self) -> str:
        base = self.http_base_url()
        return base if base.endswith("/v1") else f"{base}/v1"

    def create_client(self):
        from openai import OpenAI

        return OpenAI(base_url=self.openai_base_url(), api_key=self.LLAMA_CPP_API_KEY)

    def fetch_available_models(self) -> List[str]:
        import requests

        response = requests.get(
            f"{self.openai_base_url()}/models",
            timeout=self.LLAMA_CPP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        payload = response.json()
        models = payload.get("data", [])
        ids = [item.get("id", "").strip() for item in models if item.get("id")]
        return [model for model in ids if model]

    def _match_requested_model(self, available_models: List[str]) -> str:
        requested = self.LLAMA_CPP_MODEL.strip()
        if not requested or requested.lower() in {"auto", "default"}:
            return ""

        requested_lower = requested.lower()
        for model in available_models:
            if model.lower() == requested_lower:
                return model
        for model in available_models:
            if requested_lower in model.lower():
                return model
        return ""

    def _pick_default_model(self, available_models: List[str]) -> str:
        preferred_checks = (
            lambda name: "gemma-3" in name and ("1b" in name or "2b" in name),
            lambda name: "gemma" in name and ("1b" in name or "2b" in name),
        )

        lowered = [(model, model.lower()) for model in available_models]
        for check in preferred_checks:
            for original, model_lower in lowered:
                if check(model_lower):
                    return original

        return available_models[0] if available_models else self.LLAMA_CPP_FALLBACK_MODEL

    def resolve_model(self, refresh: bool = False) -> str:
        if self._resolved_model and not refresh:
            return self._resolved_model

        available_models: List[str] = []
        try:
            available_models = self.fetch_available_models()
        except Exception:
            available_models = []

        matched = self._match_requested_model(available_models)
        if matched:
            self._resolved_model = matched
            return matched

        requested = self.LLAMA_CPP_MODEL.strip()
        if requested and requested.lower() not in {"auto", "default"}:
            self._resolved_model = requested
            return requested

        self._resolved_model = self._pick_default_model(available_models)
        return self._resolved_model

    def should_use_text_tool_calls(self, model_name: str | None = None) -> bool:
        if not self.PREFER_TEXT_TOOL_CALLS_FOR_SMALL_GEMMA:
            return False

        target = (model_name or self.resolve_model()).lower()
        return "gemma" in target and ("1b" in target or "2b" in target)

    def validate(self) -> bool:
        """Validate llama.cpp connectivity and resolve a usable model id."""
        try:
            available_models = self.fetch_available_models()
            if not available_models:
                print(f"⚠️ Warning: llama.cpp responded at {self.http_base_url()} but returned no models.")
                print("   Start it with a Gemma model, for example:")
                print("   llama-server -m /path/to/gemma-3-1b-it.gguf --port 8080 --jinja --chat-template gemma")
                return False

            model_name = self.resolve_model(refresh=True)
            if model_name not in available_models:
                print(f"⚠️ Warning: Requested model '{model_name}' was not listed by llama.cpp.")
                print(f"   Available models: {available_models}")
                return False

            print(f"✅ llama.cpp validation passed - {model_name}")
            if self.should_use_text_tool_calls(model_name):
                print("   Small Gemma detected: defaulting to text-tool-call mode for better stability.")
            return True
        except Exception as e:
            print(f"⚠️ llama.cpp validation failed: {e}")
            print("   Make sure llama.cpp is running, for example:")
            print("   llama-server -m /path/to/gemma-3-1b-it.gguf --port 8080 --jinja --chat-template gemma")
            return False

    @classmethod
    def load(cls):
        return cls()


conf = Config.load()
