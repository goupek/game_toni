import tkinter as tk
from tkinter import messagebox
import random
import requests
import threading
import json
import math
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from PIL import Image, ImageTk


DEFAULT_DB_FILENAME = "vocab_db.json"

TOPIC_ICON_BY_ID = {
    "family": "👪",
    "greetings": "👋",
    "colors": "🎨",
    "numbers": "🔢",
    "body": "🧍",
    "actions": "🏃",
    "food": "🍎",
    "home": "🏠",
    "toys": "🧸",
    "clothes": "👕",
    "animals": "🐻",
    "nature": "🌤️",
    "transport": "🚌",
    "places": "🗺️",
    "feelings": "😊",
    "size": "📏",
    "school_supplies": "✏️",
}
FALLBACK_TOPIC_ICON = "🧸"


# ─────────────────────────────────────────────────────────────────────────────
# Cosine similarity helper
# ─────────────────────────────────────────────────────────────────────────────

def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: List[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def cosine_similarity(a: List[float], b: List[float]) -> float:
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


# ─────────────────────────────────────────────────────────────────────────────
# Embedding cache  (word → vector, persisted to disk)
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingCache:
    """
    Wraps Ollama /api/embeddings.  Results are cached in memory and optionally
    saved to a JSON file so they survive between sessions.
    """

    def __init__(self, ollama_url: str, model: str, cache_path: Path):
        self.url = f"{ollama_url}/api/embeddings"
        self.model = model
        self.cache_path = cache_path
        self._cache: Dict[str, List[float]] = {}
        self._lock = threading.Lock()
        self._load_from_disk()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load_from_disk(self):
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}

    def _save_to_disk(self):
        try:
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── public API ────────────────────────────────────────────────────────────

    def get(self, text: str) -> Optional[List[float]]:
        key = text.strip().lower()
        with self._lock:
            if key in self._cache:
                return self._cache[key]

        try:
            r = requests.post(
                self.url,
                json={"model": self.model, "prompt": key},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            vec = r.json().get("embedding")
            if not vec:
                return None
            with self._lock:
                self._cache[key] = vec
                self._save_to_disk()
            return vec
        except Exception:
            return None

    def similarity(self, a: str, b: str) -> Optional[float]:
        va = self.get(a)
        vb = self.get(b)
        if va is None or vb is None:
            return None
        return cosine_similarity(va, vb)

    def prefetch_many(self, words: List[str]):
        """Background-friendly: fetch all words that are not yet cached."""
        for w in words:
            self.get(w)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty helpers
# ─────────────────────────────────────────────────────────────────────────────

def _difficulty_from_similarities(sims: List[float]) -> float:
    """
    Average cosine similarity of distractors to the correct answer.
    0.0  → very easy (distractors are semantically unrelated)
    1.0  → very hard  (distractors are nearly synonymous)
    """
    if not sims:
        return 0.5
    return sum(sims) / len(sims)


def _skill_delta(is_correct: bool, difficulty: float) -> float:
    """
    Adaptive skill update: harder correct answers give bigger boosts,
    harder wrong answers give smaller penalties (expected to fail on hard).

    difficulty ∈ [0, 1]
    """
    # base magnitudes
    base_up   = 0.040
    base_down = 0.070

    # scale factor: easy questions (difficulty≈0) carry less information on
    # success but more on failure; hard questions the opposite
    scale = 0.5 + difficulty   # range [0.5, 1.5]

    if is_correct:
        return  base_up   * scale          # up to +0.060
    else:
        return -(base_down / scale)        # down to -0.047


# ─────────────────────────────────────────────────────────────────────────────
# Main game
# ─────────────────────────────────────────────────────────────────────────────

class ImprovedRussianGame:
    def __init__(self, root: tk.Tk, db_path: Optional[str] = None):
        self.root = root
        self.root.title("🧸 Диагностика уровня (Русский)")
        self.root.geometry("1200x950")
        self.root.configure(bg="#FFF9E6")

        # Ollama LLM + embeddings
        self.ollama_url = "http://localhost:11434"
        self.model = "qwen2.5:1.7b"
        self.embed_model = "bge-m3"   # was "nomic-embed-text"
        self.ai_enabled = self.check_ai()

        # Embedding cache (persisted to disk alongside the script)
        cache_file = Path(__file__).resolve().parent / "embedding_cache.json"
        self.emb_cache = EmbeddingCache(self.ollama_url, self.embed_model, cache_file)

        # Emoji PNG cache
        self.emoji_dir = Path(__file__).resolve().parent / "assets" / "emoji_png"
        self.emoji_dir.mkdir(parents=True, exist_ok=True)
        self._emoji_img_ref = None
        self._emoji_download_lock = threading.Lock()

        # Internal "estimated skill" 0..1
        self.skill = 0.35
        self.skill_history: List[float] = []
        self.history: List[Dict[str, Any]] = []
        self.max_history = 80

        # Track difficulty of the current question (updated each generate_question)
        self._current_difficulty: float = 0.5

        self.correct_answer = ""
        self.current_question: Dict[str, Any] = {}
        self.is_generating = False

        # Auto behavior
        self.auto_advance_ms = 750
        self.auto_switch_every_n = 2
        self._asked_total = 0
        self._topic_recent: List[str] = []

        # Stop conditions (level identification)
        self.min_questions_for_stop = 20
        self.max_questions_hard_stop = 40
        self.stability_window = 10
        self.stability_eps = 0.035
        self.high_acc_threshold = 0.85
        self.low_acc_threshold = 0.35

        # NO-REPEAT tracking
        self.seen_question_keys: set = set()

        # DB
        self.db_path = db_path or str(Path(__file__).resolve().parent / DEFAULT_DB_FILENAME)
        self.db = self.load_db(self.db_path)
        self.topics = self.build_topics_from_db(self.db)
        if not self.topics:
            raise RuntimeError("No topics found in DB. Check your JSON file structure.")

        self.current_topic = self.topics[0]

        # UI
        self.create_ui()

        # Background: preload emojis and embeddings
        threading.Thread(target=self._preload_all_emojis, daemon=True).start()
        threading.Thread(target=self._preload_all_embeddings, daemon=True).start()

        self.root.after(400, self.generate_question)

    # ── AI / Ollama ──────────────────────────────────────────────────────────

    def check_ai(self) -> bool:
        try:
            r = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    # ── DB ───────────────────────────────────────────────────────────────────

    def load_db(self, path: str) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            messagebox.showerror(
                "DB not found",
                f"Не найден файл словаря:\n{p}\n\n"
                f"Создай файл {DEFAULT_DB_FILENAME} рядом со скриптом и вставь туда JSON.",
            )
            raise FileNotFoundError(str(p))
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            messagebox.showerror("DB error", f"Ошибка чтения JSON:\n{e}")
            raise

    def build_topics_from_db(self, db: Dict[str, Any]) -> List[Dict[str, Any]]:
        palette = [
            "#FF6B9D", "#4ECDC4", "#F8B500", "#9B59B6",
            "#27AE60", "#E67E22", "#3498DB", "#E74C3C",
        ]
        out = []
        for i, t in enumerate(db.get("topics", [])):
            tid = t.get("id", f"topic_{i}")
            name_ru = t.get("name_ru", tid)
            words = t.get("words", [])
            if not isinstance(words, list) or len(words) < 4:
                continue
            norm = []
            for w in words:
                ru = (w.get("ru") or "").strip()
                en = (w.get("en") or "").strip()
                pos = (w.get("pos") or "").strip()
                if ru and en:
                    norm.append({"ru": ru, "en": en, "pos": pos})
            if len(norm) < 4:
                continue
            out.append({
                "id": tid,
                "name_ru": name_ru,
                "name_en": tid.replace("_", " ").title(),
                "icon": TOPIC_ICON_BY_ID.get(tid, FALLBACK_TOPIC_ICON),
                "color": palette[i % len(palette)],
                "words": norm,
            })
        return out

    # ── Emoji PNG (Twemoji) ───────────────────────────────────────────────────

    def _emoji_to_codepoints(self, s: str) -> str:
        return "-".join(f"{ord(ch):x}" for ch in s.strip())

    def _emoji_png_path(self, emoji: str) -> Path:
        return self.emoji_dir / f"{self._emoji_to_codepoints(emoji)}.png"

    def _download_emoji_png(self, emoji: str) -> Optional[Path]:
        emoji = (emoji or "").strip()
        if not emoji:
            return None
        path = self._emoji_png_path(emoji)
        if path.exists() and path.stat().st_size > 0:
            return path
        code = self._emoji_to_codepoints(emoji)
        url = f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{code}.png"
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200 and r.content:
                with self._emoji_download_lock:
                    if path.exists() and path.stat().st_size > 0:
                        return path
                    path.write_bytes(r.content)
                return path
        except Exception:
            return None
        return None

    def _set_emoji_image(self, emoji: str, size: int = 90):
        local = self._download_emoji_png(emoji)
        if not local:
            self.image_label.config(image="", text=emoji if emoji else "?")
            self._emoji_img_ref = None
            return
        try:
            img = Image.open(local).convert("RGBA")
            img = img.resize((size, size), Image.Resampling.LANCZOS)
            self._emoji_img_ref = ImageTk.PhotoImage(img)
            self.image_label.config(image=self._emoji_img_ref, text="")
        except Exception:
            self.image_label.config(image="", text=emoji if emoji else "?")
            self._emoji_img_ref = None

    def _preload_all_emojis(self):
        for t in self.topics:
            if t.get("icon"):
                self._download_emoji_png(t["icon"])

    def _preload_all_embeddings(self):
        """Pre-warm the embedding cache for every word in every topic."""
        words: List[str] = []
        for t in self.topics:
            for w in t["words"]:
                words.append(w["en"])
                words.append(w["ru"])
        self.emb_cache.prefetch_many(words)

    # ── UI ───────────────────────────────────────────────────────────────────

    def create_ui(self):
        top_bar = tk.Frame(self.root, bg="#2C3E50", height=80)
        top_bar.pack(fill=tk.X)
        top_bar.pack_propagate(False)

        left = tk.Frame(top_bar, bg="#2C3E50")
        left.pack(side=tk.LEFT, padx=30, pady=15)

        self.title_label = tk.Label(
            left, text="Диагностика уровня", font=("Arial", 18, "bold"),
            bg="#2C3E50", fg="#ECF0F1",
        )
        self.title_label.pack(anchor=tk.W)

        self.sub_label = tk.Label(
            left, text="", font=("Arial", 12), bg="#2C3E50", fg="#BDC3C7",
        )
        self.sub_label.pack(anchor=tk.W)

        right = tk.Frame(top_bar, bg="#2C3E50")
        right.pack(side=tk.RIGHT, padx=30, pady=15)
        self.q_label = tk.Label(
            right, text="Вопрос: 0", font=("Arial", 20, "bold"),
            bg="#2C3E50", fg="#F39C12",
        )
        self.q_label.pack()

        self.header = tk.Frame(self.root, bg=self.current_topic["color"], height=100)
        self.header.pack(fill=tk.X)
        self.header.pack_propagate(False)

        self.header_label = tk.Label(
            self.header,
            text=self._header_text_for_topic(self.current_topic),
            font=("Arial", 30, "bold"),
            bg=self.current_topic["color"],
            fg="white",
        )
        self.header_label.pack(pady=25)

        question_box = tk.Frame(self.root, bg="white", bd=3, relief=tk.RAISED)
        question_box.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)

        self.image_label = tk.Label(
            question_box, text="?", font=("Arial", 48, "bold"), bg="white",
        )
        self.image_label.pack(pady=(18, 6))

        self.question_label = tk.Label(
            question_box, text="Загружаем вопрос...",
            font=("Arial", 20, "bold"), bg="white", fg="#2C3E50",
        )
        self.question_label.pack(pady=(6, 6))

        self.word_label = tk.Label(
            question_box, text="", font=("Arial", 46, "bold"), bg="white", fg="#2C3E50",
        )
        self.word_label.pack(pady=(0, 10))

        self.status_label = tk.Label(
            question_box, text="", font=("Arial", 12), bg="white", fg="#7F8C8D",
        )
        self.status_label.pack()

        self.choices_frame = tk.Frame(question_box, bg="white")
        self.choices_frame.pack(pady=20, padx=50, fill=tk.BOTH, expand=True)

        self.choice_buttons: List[tk.Button] = []
        for i in range(4):
            btn = tk.Button(
                self.choices_frame,
                text="",
                font=("Arial", 24, "bold"),
                bg="#3498DB",
                fg="white",
                activebackground="#2980B9",
                relief=tk.RAISED,
                bd=6,
                padx=30,
                pady=30,
                cursor="hand2",
                state=tk.DISABLED,
            )
            btn.grid(row=i // 2, column=i % 2, padx=12, pady=12, sticky="nsew")
            self.choice_buttons.append(btn)

        self.choices_frame.grid_rowconfigure(0, weight=1)
        self.choices_frame.grid_rowconfigure(1, weight=1)
        self.choices_frame.grid_columnconfigure(0, weight=1)
        self.choices_frame.grid_columnconfigure(1, weight=1)

        self.feedback_label = tk.Label(
            self.root, text="", font=("Arial", 24, "bold"), bg="#FFF9E6", height=2,
        )
        self.feedback_label.pack(pady=10)

        # Difficulty indicator bar (thin, below feedback)
        self.diff_canvas = tk.Canvas(self.root, height=18, bg="#FFF9E6", bd=0, highlightthickness=0)
        self.diff_canvas.pack(fill=tk.X, padx=30, pady=(0, 6))

    def _draw_difficulty_bar(self, difficulty: float):
        """Render a colour-coded difficulty bar (0=easy/green … 1=hard/red)."""
        self.diff_canvas.delete("all")
        w = self.diff_canvas.winfo_width() or 800
        h = 18
        filled = int(w * difficulty)
        r = int(255 * difficulty)
        g = int(200 * (1 - difficulty))
        color = f"#{r:02x}{g:02x}40"
        self.diff_canvas.create_rectangle(0, 0, filled, h, fill=color, outline="")
        label = f"Сложность вопроса: {difficulty:.2f}"
        self.diff_canvas.create_text(w // 2, h // 2, text=label, font=("Arial", 10), fill="#555")

    def _header_text_for_topic(self, topic: Dict[str, Any]) -> str:
        return f"{topic.get('icon', FALLBACK_TOPIC_ICON)} {topic['name_ru']} ({topic['name_en']})"

    def _set_current_topic(self, topic: Dict[str, Any]):
        self.current_topic = topic
        self._topic_recent.append(topic["id"])
        self._topic_recent = self._topic_recent[-6:]
        self.header.config(bg=topic["color"])
        self.header_label.config(text=self._header_text_for_topic(topic), bg=topic["color"])

    def _choose_next_topic(self):
        current_id = self.current_topic["id"]
        recent = set(self._topic_recent[-2:])
        target = 4 + int(self.skill * 6)
        candidates = []
        for t in self.topics:
            if t["id"] == current_id:
                continue
            if t["id"] in recent and len(self.topics) > 3:
                continue
            avg_len = sum(len(w["ru"]) for w in t["words"]) / max(1, len(t["words"]))
            score = abs(avg_len - target)
            candidates.append((score, t))
        if not candidates:
            idx = self.topics.index(self.current_topic)
            next_topic = self.topics[(idx + 1) % len(self.topics)]
        else:
            candidates.sort(key=lambda x: x[0])
            best = candidates[: min(4, len(candidates))]
            next_topic = random.choice([t for _, t in best])
        self._set_current_topic(next_topic)

    # ── Stop logic ───────────────────────────────────────────────────────────

    def _recent_accuracy(self, n: int = 10) -> Optional[float]:
        h = self.history[-n:]
        if not h:
            return None
        return sum(1 for x in h if x["ok"]) / len(h)

    def _skill_is_stable(self) -> bool:
        if len(self.skill_history) < self.stability_window:
            return False
        window = self.skill_history[-self.stability_window:]
        return (max(window) - min(window)) <= self.stability_eps

    def _estimated_level_1_to_10(self) -> int:
        lvl = int(round(1 + self.skill * 9))
        return max(1, min(10, lvl))

    def _should_stop(self) -> bool:
        if self._asked_total >= self.max_questions_hard_stop:
            return True
        if self._asked_total < self.min_questions_for_stop:
            return False
        acc = self._recent_accuracy(10)
        stable = self._skill_is_stable()
        if stable and acc is not None:
            if acc >= self.high_acc_threshold:
                return True
            if acc <= self.low_acc_threshold:
                return True
        if stable and self._asked_total >= (self.min_questions_for_stop + 6):
            return True
        return False

    def _finish_and_show_result(self, reason: str = ""):
        lvl = self._estimated_level_1_to_10()
        acc = self._recent_accuracy(10)
        acc_txt = "—" if acc is None else f"{acc:.2f}"

        # weighted accuracy: weight correct answers by their difficulty
        weighted_score = 0.0
        weight_total = 0.0
        for h in self.history:
            d = h.get("difficulty", 0.5)
            weight_total += d + 0.5
            if h["ok"]:
                weighted_score += d + 0.5
        weighted_acc = (weighted_score / weight_total) if weight_total else 0

        msg = (
            "🏁 Диагностика завершена!\n\n"
            f"Оценка уровня: {lvl}/10\n"
            f"Skill: {self.skill:.2f}\n"
            f"Точность (последние 10): {acc_txt}\n"
            f"Взвешенная точность (по сложности): {weighted_acc:.2f}\n"
            f"Вопросов: {self._asked_total}\n"
        )
        if reason:
            msg += f"\nПричина: {reason}\n"
        msg += "\nМожно закрывать окно."

        messagebox.showinfo("Результат", msg)
        self.root.destroy()

    # ── No-repeat helpers ─────────────────────────────────────────────────────

    def _q_key(self, direction: str, shown: str) -> str:
        return f"{direction}|shown|{shown.strip().lower()}"

    def _mark_seen(self, direction: str, shown: str, correct: str):
        self.seen_question_keys.add(self._q_key(direction, shown))
        self.seen_question_keys.add(f"{direction}|correct|{correct.strip().lower()}")

    def _available_words_for_topic(self, topic: Dict[str, Any], direction: str) -> List[Dict[str, str]]:
        out = []
        for w in topic["words"]:
            shown = w["ru"] if direction == "ru_to_en" else w["en"]
            if self._q_key(direction, shown) not in self.seen_question_keys:
                out.append(w)
        return out

    def _available_topics_exist(self) -> bool:
        for t in self.topics:
            if self._available_words_for_topic(t, "ru_to_en"):
                return True
            if self._available_words_for_topic(t, "en_to_ru"):
                return True
        return False

    # ── Semantic distractor selection ─────────────────────────────────────────

    def _target_distractor_similarity(self) -> float:
        """
        Map skill [0..1] to a target cosine similarity for distractors.
        skill=0  → 0.10  (distractors are unrelated — very easy)
        skill=0.5→ 0.45  (moderately similar)
        skill=1  → 0.80  (highly similar — very hard)
        """
        return 0.10 + self.skill * 0.70

    def _semantic_distractors(
        self,
        correct: str,
        pool: List[str],
        n: int = 3,
    ) -> Tuple[List[str], float]:
        """
        Pick n distractors from pool whose embedding similarity to `correct`
        is closest to the target similarity for the current skill level.

        Returns (distractors, achieved_avg_similarity).
        Falls back to random if embeddings are unavailable.
        """
        target_sim = self._target_distractor_similarity()

        correct_vec = self.emb_cache.get(correct)
        if correct_vec is None:
            # no embeddings → random fallback, difficulty=0.3
            pool_clean = [p for p in pool if p.strip().lower() != correct.strip().lower()]
            random.shuffle(pool_clean)
            chosen = pool_clean[:n]
            return chosen, 0.3

        scored: List[Tuple[float, str]] = []
        for word in pool:
            w = word.strip()
            if w.lower() == correct.strip().lower():
                continue
            vec = self.emb_cache.get(w)
            if vec is None:
                continue
            sim = cosine_similarity(correct_vec, vec)
            distance_to_target = abs(sim - target_sim)
            scored.append((distance_to_target, w, sim))

        if not scored:
            pool_clean = [p for p in pool if p.strip().lower() != correct.strip().lower()]
            random.shuffle(pool_clean)
            return pool_clean[:n], 0.3

        scored.sort(key=lambda x: x[0])
        # pick from the best matches (slight randomness to avoid determinism)
        best = scored[: max(n * 2, 6)]
        random.shuffle(best)
        chosen_entries = best[:n]

        distractors = [e[1] for e in chosen_entries]
        avg_sim = sum(e[2] for e in chosen_entries) / len(chosen_entries) if chosen_entries else 0.3

        return distractors, avg_sim

    def _build_choices_semantic(
        self,
        correct: str,
        pool: List[str],
        n: int = 4,
    ) -> Tuple[List[str], float]:
        """
        Build n choices using semantic distractor selection.
        Returns (shuffled_choices, difficulty_score).
        """
        distractors, avg_sim = self._semantic_distractors(correct, pool, n=n - 1)

        # deduplicate
        seen: set = {correct.lower().strip()}
        clean: List[str] = []
        for d in distractors:
            k = d.lower().strip()
            if k not in seen:
                seen.add(k)
                clean.append(d)

        # pad with random if needed
        if len(clean) < n - 1:
            extras = [p for p in pool if p.lower().strip() not in seen]
            random.shuffle(extras)
            for e in extras:
                if len(clean) >= n - 1:
                    break
                k = e.lower().strip()
                if k not in seen:
                    seen.add(k)
                    clean.append(e)

        choices = clean[: n - 1] + [correct]
        while len(choices) < n:
            choices.append("—")
        random.shuffle(choices)
        return choices[:n], _difficulty_from_similarities([avg_sim] * (n - 1))

    # ── Pools ─────────────────────────────────────────────────────────────────

    def _all_en_pool(self, mix_topics: bool) -> List[str]:
        if not mix_topics:
            return [w["en"] for w in self.current_topic["words"]]
        return [w["en"] for t in self.topics for w in t["words"]]

    def _all_ru_pool(self, mix_topics: bool) -> List[str]:
        if not mix_topics:
            return [w["ru"] for w in self.current_topic["words"]]
        return [w["ru"] for t in self.topics for w in t["words"]]

    # ── LLM question selection ────────────────────────────────────────────────

    def _call_ollama_json(self, prompt: str) -> Optional[Dict[str, Any]]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 250},
        }
        try:
            r = requests.post(f"{self.ollama_url}/api/generate", json=payload, timeout=12)
            if r.status_code != 200:
                return None
            data = r.json()
            text = (data.get("response") or "").strip()
            return json.loads(text)
        except Exception:
            return None

    def _candidate_words_for_topic(self, topic: Dict[str, Any], direction: str) -> List[Dict[str, str]]:
        available = self._available_words_for_topic(topic, direction)
        if not available:
            return []
        target = 4 + int(self.skill * 6)
        scored = []
        for w in available:
            score = abs(len(w["ru"]) - target)
            scored.append((score, {"ru": w["ru"], "en": w["en"], "pos": w.get("pos", "")}))
        scored.sort(key=lambda x: x[0])
        return [x[1] for x in scored[:18]]

    def _show_llm_question(self) -> bool:
        topic = self.current_topic
        dir_try = ["ru_to_en", "en_to_ru"]
        random.shuffle(dir_try)
        mix = self.skill >= 0.55

        for direction in dir_try:
            candidates = self._candidate_words_for_topic(topic, direction)
            if len(candidates) < 4:
                continue

            acc = self._recent_accuracy(10)
            acc_txt = "null" if acc is None else f"{acc:.2f}"

            prompt = f"""
You are a tester to quickly IDENTIFY a toddler's Russian level.
Choose the NEXT multiple-choice question that is maximally informative.

Context:
- Current topic: {topic['id']} / {topic['name_ru']}
- Estimated skill (0..1): {self.skill:.2f}
- Recent accuracy (last 10): {acc_txt}
- Questions asked so far: {self._asked_total}

Hard rule:
- DO NOT repeat already asked words. You MUST choose correct word from candidates provided.

Rules:
- Output VALID JSON ONLY. No extra text.
- Pick only the word (shown + correct). Distractors will be chosen by the system using semantic similarity.
- Toddler-friendly.

Direction is fixed for this request: "{direction}"

Candidates (correct word MUST be from here):
{json.dumps(candidates, ensure_ascii=False)}

Return JSON schema:
{{
  "direction": "{direction}",
  "prompt_ru": "string",
  "shown": "string",
  "correct": "string"
}}

If direction == "ru_to_en": shown is Russian word, correct is English.
If direction == "en_to_ru": shown is English word, correct is Russian.
"""
            out = self._call_ollama_json(prompt)
            if not out:
                continue

            out_dir = out.get("direction")
            prompt_ru = (out.get("prompt_ru") or "").strip()
            shown = (out.get("shown") or "").strip()
            correct = (out.get("correct") or "").strip()

            if out_dir != direction or not prompt_ru or not shown or not correct:
                continue
            if self._q_key(direction, shown) in self.seen_question_keys:
                continue

            pool = (self._all_en_pool(mix) if direction == "ru_to_en" else self._all_ru_pool(mix))
            choices, difficulty = self._build_choices_semantic(correct, pool, n=4)

            self.correct_answer = correct
            self._current_difficulty = difficulty
            self.current_question = {
                "prompt": prompt_ru,
                "shown": shown,
                "direction": direction,
                "topic_id": topic["id"],
                "difficulty": difficulty,
            }
            self._display_question(prompt_ru, shown, choices, difficulty)
            self._mark_seen(direction, shown, correct)
            return True

        return False

    # ── Fallback DB question ──────────────────────────────────────────────────

    def _direction_fallback(self) -> str:
        if self.skill < 0.45:
            return "ru_to_en"
        return random.choice(["ru_to_en", "en_to_ru"])

    def _pick_unseen_word_any_topic(self, direction: str) -> Optional[Tuple[Dict[str, Any], Dict[str, str]]]:
        candidates = self._available_words_for_topic(self.current_topic, direction)
        if candidates:
            return self.current_topic, random.choice(candidates)
        topics_shuffled = self.topics[:]
        random.shuffle(topics_shuffled)
        for t in topics_shuffled:
            candidates = self._available_words_for_topic(t, direction)
            if candidates:
                return t, random.choice(candidates)
        return None

    def _show_db_question(self) -> bool:
        direction = self._direction_fallback()
        mix = self.skill >= 0.55

        picked = self._pick_unseen_word_any_topic(direction)
        if not picked:
            return False

        topic, w = picked
        if topic["id"] != self.current_topic["id"]:
            self._set_current_topic(topic)

        if direction == "ru_to_en":
            prompt = "Что это значит по-английски?"
            shown = w["ru"]
            correct = w["en"]
            pool = self._all_en_pool(mix_topics=mix)
        else:
            prompt = "Как сказать по-русски?"
            shown = w["en"]
            correct = w["ru"]
            pool = self._all_ru_pool(mix_topics=mix)

        choices, difficulty = self._build_choices_semantic(correct, pool, n=4)
        self.correct_answer = correct
        self._current_difficulty = difficulty
        self.current_question = {
            "prompt": prompt,
            "shown": shown,
            "direction": direction,
            "topic_id": self.current_topic["id"],
            "difficulty": difficulty,
        }
        self._display_question(prompt, shown, choices, difficulty)
        self._mark_seen(direction, shown, correct)
        return True

    # ── Display / flow ────────────────────────────────────────────────────────

    def _display_question(self, question: str, shown_text: str, choices: List[str], difficulty: float = 0.5):
        self._set_emoji_image(self.current_topic.get("icon", FALLBACK_TOPIC_ICON), size=90)
        self.question_label.config(text=question)
        self.word_label.config(text=shown_text)

        lvl = self._estimated_level_1_to_10()
        acc = self._recent_accuracy(10)
        acc_txt = "—" if acc is None else f"{acc:.2f}"
        self.status_label.config(
            text=f"Оценка: {lvl}/10 | skill={self.skill:.2f} | acc10={acc_txt}"
        )

        self.root.after(50, lambda: self._draw_difficulty_bar(difficulty))

        for i, btn in enumerate(self.choice_buttons):
            choice = choices[i]
            btn.config(
                text=choice,
                state=tk.NORMAL,
                bg="#3498DB",
                command=lambda c=choice: self.check_answer(c),
            )

        self.is_generating = False

    def generate_question(self):
        if self.is_generating:
            return

        if not self._available_topics_exist():
            self._finish_and_show_result("закончились уникальные слова для вопросов (без повторов)")
            return

        if self._should_stop():
            self._finish_and_show_result("уровень стабилизировался")
            return

        if self._asked_total > 0 and (self._asked_total % self.auto_switch_every_n == 0):
            self._choose_next_topic()

        self.is_generating = True
        self.feedback_label.config(text="")
        for btn in self.choice_buttons:
            btn.config(state=tk.DISABLED, bg="#3498DB")

        self._asked_total += 1
        self.q_label.config(text=f"Вопрос: {self._asked_total}")

        if self.ai_enabled and self._show_llm_question():
            return
        if self._show_db_question():
            return
        self._finish_and_show_result("не удалось сгенерировать новый уникальный вопрос")

    def check_answer(self, answer: str):
        for btn in self.choice_buttons:
            btn.config(state=tk.DISABLED)

        is_correct = answer.lower().strip() == self.correct_answer.lower().strip()
        difficulty = self._current_difficulty

        if is_correct:
            for btn in self.choice_buttons:
                if btn.cget("text").lower().strip() == self.correct_answer.lower().strip():
                    btn.config(bg="#27AE60")
            self.feedback_label.config(text="✅ Правильно", fg="#27AE60")
        else:
            for btn in self.choice_buttons:
                text = btn.cget("text").lower().strip()
                if text == answer.lower().strip():
                    btn.config(bg="#E74C3C")
                elif text == self.correct_answer.lower().strip():
                    btn.config(bg="#27AE60")
            self.feedback_label.config(
                text=f"❌ Неправильно: {self.correct_answer}", fg="#E74C3C"
            )

        # ── Difficulty-weighted skill update ──────────────────────────────────
        delta = _skill_delta(is_correct, difficulty)
        self.skill = max(0.0, min(1.0, self.skill + delta))

        self.skill_history.append(self.skill)
        self.skill_history = self.skill_history[-self.max_history :]

        self.history.append({
            "ok": bool(is_correct),
            "topic_id": self.current_question.get("topic_id"),
            "direction": self.current_question.get("direction"),
            "shown": self.current_question.get("shown"),
            "correct": self.correct_answer,
            "difficulty": difficulty,
        })
        self.history = self.history[-self.max_history :]

        self.root.after(self.auto_advance_ms, self.generate_question)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    messagebox.showinfo(
        "Старт",
        "Это тест для определения уровня.\n"
        "Он автоматически завершится, когда уровень станет понятен.\n"
        "Вопросы не повторяются.\n\n"
        "Примечание: первые вопросы могут загружаться чуть дольше,\n"
        "пока система кэширует смысловые векторы слов.",
    )
    ImprovedRussianGame(root)
    root.mainloop()


if __name__ == "__main__":
    main()