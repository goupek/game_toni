"""
Pygame port of lvl_game_connected.py.

Goal:
- keep the original core game logic intact:
  * topic / word loading
  * embedding cache
  * semantic distractors
  * A1/A2 progression logic
  * no-repeat logic
  * result saving via update_from_level_game()
- replace only the Tkinter UI layer with a Pygame UI.

Recommended placement:
- put this file next to the original lvl_game_connected.py inside lvl_games/

Run directly:
    python lvl_games/lvl_game_connected_pygame.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pygame
import requests

# Make sure we can import from the original level/ folder and the repo root
_HERE = Path(__file__).resolve().parent
_LEVEL = _HERE.parent / "level"
_ROOT = _HERE.parent

for p in [str(_HERE), str(_LEVEL), str(_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from word_knowledge import update_from_level_game
from database.db_queries import get_topics_with_words


# ============================================================
# Constants from the original file (kept)
# ============================================================
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


# ============================================================
# Cosine similarity helpers (unchanged)
# ============================================================
def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: List[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def cosine_similarity(a: List[float], b: List[float]) -> float:
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


# ============================================================
# Embedding cache (unchanged)
# ============================================================
class EmbeddingCache:
    def __init__(self, ollama_url: str, model: str, cache_path: Path):
        self.url = f"{ollama_url}/api/embeddings"
        self.model = model
        self.cache_path = cache_path
        self._cache: Dict[str, List[float]] = {}
        self._lock = threading.Lock()
        self._load_from_disk()

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
        for w in words:
            self.get(w)


# ============================================================
# Difficulty helpers (unchanged)
# ============================================================
def _difficulty_from_similarities(sims: List[float]) -> float:
    if not sims:
        return 0.5
    return sum(sims) / len(sims)



def _skill_delta(is_correct: bool, difficulty: float) -> float:
    base_up = 0.040
    base_down = 0.070
    scale = 0.5 + difficulty
    if is_correct:
        return base_up * scale
    return -(base_down / scale)


# ============================================================
# UI helpers
# ============================================================
Color = Tuple[int, int, int]
V_W, V_H = 1280, 820
FPS = 60

BG_TOP: Color = (128, 183, 181)
BG_BOTTOM: Color = (109, 164, 172)
BG_POLY_1: Color = (117, 170, 166)
BG_POLY_2: Color = (100, 151, 160)
BG_POLY_3: Color = (92, 142, 154)

PANEL_FILL: Color = (229, 222, 189)
PANEL_BORDER: Color = (181, 156, 106)
PANEL_INNER: Color = (243, 237, 210)

RIBBON_FILL: Color = (236, 81, 127)
RIBBON_DARK: Color = (193, 48, 92)
RIBBON_LIGHT: Color = (248, 118, 157)

TEXT_DARK: Color = (77, 43, 64)
TEXT_SOFT: Color = (98, 70, 89)
TEXT_LIGHT: Color = (255, 248, 235)
OUTLINE_DARK: Color = (99, 61, 81)

SHADOW_SOFT: Color = (153, 136, 148)
SHADOW_DEEP: Color = (115, 97, 113)

BTN_BLUE: Color = (37, 205, 230)
BTN_BLUE_DARK: Color = (93, 86, 210)
BTN_GREEN: Color = (117, 217, 102)
BTN_GREEN_DARK: Color = (72, 172, 71)
BTN_RED: Color = (245, 112, 112)
BTN_RED_DARK: Color = (196, 58, 61)
BTN_YELLOW: Color = (251, 224, 64)
BTN_YELLOW_DARK: Color = (236, 174, 44)
BTN_CREAM: Color = (245, 240, 230)
BTN_CREAM_DARK: Color = (177, 163, 174)
BTN_ORANGE: Color = (255, 191, 53)
BTN_ORANGE_DARK: Color = (220, 139, 27)

HUD_CREAM: Color = (236, 231, 205)
HUD_BORDER: Color = (187, 173, 121)

DEFAULT_CHOICE_FILL = BTN_BLUE
DEFAULT_CHOICE_DEPTH = BTN_BLUE_DARK
CORRECT_FILL = BTN_GREEN
CORRECT_DEPTH = BTN_GREEN_DARK
WRONG_FILL = BTN_RED
WRONG_DEPTH = BTN_RED_DARK


def compute_scale_and_offset(window_size, virtual_size):
    w, h = window_size
    vw, vh = virtual_size
    scale = min(w / vw, h / vh) if vw and vh else 1.0
    new_w, new_h = int(vw * scale), int(vh * scale)
    ox, oy = (w - new_w) // 2, (h - new_h) // 2
    return scale, (new_w, new_h), (ox, oy)



def map_mouse_to_virtual(mouse_pos, scale, offset):
    mx, my = mouse_pos
    ox, oy = offset
    return ((mx - ox) / scale, (my - oy) / scale)



def blit_scaled(screen, canvas, new_size, offset):
    scaled = pygame.transform.smoothscale(canvas, new_size)
    if offset[0] > 0 or offset[1] > 0:
        screen.fill((35, 40, 46))
    screen.blit(scaled, offset)
    pygame.display.flip()



def _best_font(size: int, bold: bool = True) -> pygame.font.Font:
    for name in ("Baloo 2", "Fredoka", "Nunito", "Arial", "DejaVu Sans", ""):
        try:
            f = pygame.font.SysFont(name, max(14, size), bold=bold)
            if f:
                return f
        except Exception:
            continue
    return pygame.font.Font(None, max(14, size))



def lighten(color: Color, amount: int) -> Color:
    return tuple(min(255, c + amount) for c in color)



def darken(color: Color, amount: int) -> Color:
    return tuple(max(0, c - amount) for c in color)



def wrap_text(text: str, font: pygame.font.Font, max_width: int) -> List[str]:
    words = str(text).split()
    lines: List[str] = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if font.size(trial)[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines



def draw_background(surface: pygame.Surface):
    w, h = surface.get_size()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        pygame.draw.line(surface, (r, g, b), (0, y), (w, y))

    polys = [
        (BG_POLY_1, [(0, h * 0.18), (w * 0.28, 0), (w * 0.5, h * 0.22), (w * 0.2, h * 0.42)]),
        (BG_POLY_2, [(w * 0.66, 0), (w, 0), (w, h * 0.34), (w * 0.8, h * 0.26)]),
        (BG_POLY_3, [(0, h), (w * 0.22, h * 0.7), (w * 0.4, h), (0, h)]),
        (BG_POLY_2, [(w * 0.58, h), (w * 0.78, h * 0.62), (w, h), (w * 0.78, h)]),
        (BG_POLY_1, [(w * 0.3, h * 0.45), (w * 0.52, h * 0.3), (w * 0.64, h * 0.58), (w * 0.42, h * 0.7)]),
    ]
    for color, pts in polys:
        pygame.draw.polygon(surface, color, pts)



def draw_shadow(surface: pygame.Surface, rect: pygame.Rect, radius: int, dy: int = 6):
    pygame.draw.rect(surface, SHADOW_SOFT, rect.move(0, dy), border_radius=radius)



def draw_panel(surface: pygame.Surface, rect: pygame.Rect, radius: int = 28):
    draw_shadow(surface, rect, radius, dy=8)
    pygame.draw.rect(surface, PANEL_FILL, rect, border_radius=radius)
    pygame.draw.rect(surface, PANEL_BORDER, rect, width=4, border_radius=radius)
    inner = rect.inflate(-10, -10)
    pygame.draw.rect(surface, PANEL_INNER, inner, width=2, border_radius=max(10, radius - 6))



def draw_ribbon_title(surface: pygame.Surface, text: str, panel_rect: pygame.Rect, font: pygame.font.Font):
    ribbon_h = 72
    ribbon_w = int(panel_rect.w * 1.08)
    ribbon_x = panel_rect.centerx - ribbon_w // 2
    ribbon_y = panel_rect.y + 22
    ribbon = pygame.Rect(ribbon_x, ribbon_y, ribbon_w, ribbon_h)

    tail_w = 32
    left_tail = [
        (ribbon.left, ribbon.top + 14),
        (ribbon.left - tail_w, ribbon.top + 14),
        (ribbon.left - 12, ribbon.centery),
        (ribbon.left - tail_w, ribbon.bottom - 14),
        (ribbon.left, ribbon.bottom - 14),
    ]
    right_tail = [
        (ribbon.right, ribbon.top + 14),
        (ribbon.right + tail_w, ribbon.top + 14),
        (ribbon.right + 12, ribbon.centery),
        (ribbon.right + tail_w, ribbon.bottom - 14),
        (ribbon.right, ribbon.bottom - 14),
    ]
    pygame.draw.polygon(surface, RIBBON_DARK, left_tail)
    pygame.draw.polygon(surface, RIBBON_DARK, right_tail)

    draw_shadow(surface, ribbon, 0, dy=6)
    pygame.draw.rect(surface, RIBBON_FILL, ribbon)
    pygame.draw.rect(surface, RIBBON_LIGHT, pygame.Rect(ribbon.x, ribbon.y, ribbon.w, 12))
    pygame.draw.line(surface, RIBBON_DARK, (ribbon.left, ribbon.bottom - 3), (ribbon.right, ribbon.bottom - 3), 3)

    shadow = font.render(text, True, OUTLINE_DARK)
    text_surf = font.render(text, True, TEXT_LIGHT)
    tr = text_surf.get_rect(center=ribbon.center)
    for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        surface.blit(shadow, shadow.get_rect(center=(tr.centerx + ox, tr.centery + oy)))
    surface.blit(text_surf, tr)



def draw_badge(surface: pygame.Surface, rect: pygame.Rect, icon: str, value: str, font: pygame.font.Font, icon_font: pygame.font.Font):
    pygame.draw.rect(surface, HUD_CREAM, rect, border_radius=rect.h // 2)
    pygame.draw.rect(surface, HUD_BORDER, rect, width=2, border_radius=rect.h // 2)

    icon_rect = pygame.Rect(rect.x - rect.h // 3, rect.y - 4, rect.h + 8, rect.h + 8)
    draw_round_icon(surface, icon_rect, icon, icon_font)

    shadow = font.render(str(value), True, OUTLINE_DARK)
    text = font.render(str(value), True, TEXT_LIGHT)
    center = (rect.x + int(rect.w * 0.58), rect.centery)
    surface.blit(shadow, shadow.get_rect(center=(center[0] + 1, center[1] + 1)))
    surface.blit(text, text.get_rect(center=center))



def draw_round_icon(surface: pygame.Surface, rect: pygame.Rect, icon: str, font: pygame.font.Font):
    pygame.draw.ellipse(surface, BTN_ORANGE_DARK, rect.move(0, 5))
    pygame.draw.ellipse(surface, BTN_ORANGE, rect)
    pygame.draw.ellipse(surface, lighten(BTN_ORANGE, 12), rect.inflate(-8, -8), width=2)
    pygame.draw.ellipse(surface, PANEL_BORDER, rect, width=2)
    shadow = font.render(icon, True, OUTLINE_DARK)
    text = font.render(icon, True, TEXT_LIGHT)
    surface.blit(shadow, shadow.get_rect(center=(rect.centerx + 1, rect.centery + 2)))
    surface.blit(text, text.get_rect(center=rect.center))



def draw_button(surface: pygame.Surface, rect: pygame.Rect, label: str, fill: Color, depth: Color,
                font: pygame.font.Font, text_color: Color = TEXT_DARK, enabled: bool = True,
                hovered: bool = False):
    base_fill = fill if enabled else darken(BTN_CREAM, 10)
    base_depth = depth if enabled else darken(BTN_CREAM_DARK, 10)
    top_fill = lighten(base_fill, 10) if hovered and enabled else base_fill

    pygame.draw.rect(surface, base_depth, rect.move(0, 7), border_radius=18)
    pygame.draw.rect(surface, top_fill, rect, border_radius=18)
    pygame.draw.rect(surface, lighten(top_fill, 18), (rect.x + 6, rect.y + 5, rect.w - 12, 12), border_radius=10)
    pygame.draw.rect(surface, PANEL_BORDER, rect, width=2, border_radius=18)

    shadow = font.render(label, True, OUTLINE_DARK)
    text = font.render(label, True, text_color if enabled else TEXT_SOFT)
    tr = text.get_rect(center=(rect.centerx, rect.centery + 1))
    surface.blit(shadow, shadow.get_rect(center=(tr.centerx + 1, tr.centery + 2)))
    surface.blit(text, tr)


class PygameButton:
    def __init__(self, rect: pygame.Rect, label: str, fill: Color, depth: Color, text_color: Color = TEXT_DARK):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.fill = fill
        self.depth = depth
        self.text_color = text_color
        self.enabled = True
        self.hovered = False

    def hit(self, pos) -> bool:
        return self.enabled and self.rect.collidepoint(pos)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        draw_button(surface, self.rect, self.label, self.fill, self.depth, font, self.text_color, self.enabled, self.hovered)


# ============================================================
# Main game class: same logic, Pygame UI
# ============================================================
class ImprovedRussianGame:
    def __init__(self, db_path: Optional[str] = None):
        pygame.init()
        try:
            pygame.mixer.init()
        except Exception:
            pass

        self.screen = pygame.display.set_mode((V_W, V_H), pygame.RESIZABLE)
        pygame.display.set_caption("🧸 Диагностика уровня (Русский)")
        self.clock = pygame.time.Clock()

        self.ollama_url = "http://localhost:11434"
        self.model = "qwen2.5:1.7b"
        self.embed_model = "bge-m3"
        self.ai_enabled = self.check_ai()

        cache_file = _LEVEL / "embedding_cache.json"
        self.emb_cache = EmbeddingCache(self.ollama_url, self.embed_model, cache_file)

        self.emoji_dir = _LEVEL / "assets" / "emoji_png"
        self.emoji_dir.mkdir(parents=True, exist_ok=True)
        self._emoji_download_lock = threading.Lock()
        self._emoji_surface_cache: Dict[Tuple[str, int], Optional[pygame.Surface]] = {}
        self.current_emoji_surface: Optional[pygame.Surface] = None
        self.current_emoji_text: str = FALLBACK_TOPIC_ICON

        self.skill = 0.35
        self.skill_history: List[float] = []
        self.history: List[Dict[str, Any]] = []
        self.max_history = 80

        self._current_difficulty: float = 0.5

        self.level_stats: Dict[str, Dict[str, int]] = {
            "A1": {"asked": 0, "correct": 0},
            "A2": {"asked": 0, "correct": 0},
        }
        self.a1_gate_questions = 8
        self.a1_gate_accuracy = 0.70
        self._current_word_level: str = "A1"

        self.correct_answer = ""
        self.current_question: Dict[str, Any] = {}
        self.is_generating = False

        self.auto_advance_ms = 750
        self.auto_switch_every_n = 2
        self._asked_total = 0
        self._topic_recent: List[str] = []

        self.min_questions_for_stop = 20
        self.max_questions_hard_stop = 40
        self.stability_window = 10
        self.stability_eps = 0.035
        self.high_acc_threshold = 0.85
        self.low_acc_threshold = 0.35

        self.seen_question_keys: set = set()

        self.db = get_topics_with_words()
        self.topics = self.build_topics_from_db(self.db)
        if not self.topics:
            raise RuntimeError("No topics found in DB. Check your JSON file structure.")

        self.current_topic = self.topics[0]

        # UI state
        self.running = True
        self.start_overlay = True
        self.result_overlay = False
        self.result_message = ""
        self.feedback_text = ""
        self.feedback_kind = "info"
        self.feedback_color = TEXT_DARK
        self.status_text = ""
        self.question_text = "Загружаем вопрос..."
        self.shown_text = ""
        self.live_level_text = "Уровень: ?"
        self.sub_text = "AI: online" if self.ai_enabled else "AI: offline • fallback DB mode"
        self.next_generate_at: Optional[int] = None
        self.close_after_result = False
        self.s = 1.0

        self.create_ui()

        threading.Thread(target=self._preload_all_emojis, daemon=True).start()
        threading.Thread(target=self._preload_all_embeddings, daemon=True).start()

    # ── AI / Ollama ──────────────────────────────────────────────────────────
    def check_ai(self) -> bool:
        try:
            r = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    # ── DB ───────────────────────────────────────────────────────────────────
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
                lvl = (w.get("level") or "A1").strip().upper()
                if ru and en:
                    norm.append({"ru": ru, "en": en, "pos": pos, "level": lvl})
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

    # ── Emoji PNG (logic preserved, UI adapted) ──────────────────────────────
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
        self.current_emoji_text = emoji if emoji else "?"
        key = (self.current_emoji_text, size)
        if key in self._emoji_surface_cache:
            self.current_emoji_surface = self._emoji_surface_cache[key]
            return

        local = self._download_emoji_png(emoji)
        if not local:
            self.current_emoji_surface = None
            self._emoji_surface_cache[key] = None
            return
        try:
            img = pygame.image.load(str(local)).convert_alpha()
            img = pygame.transform.smoothscale(img, (size, size))
            self.current_emoji_surface = img
            self._emoji_surface_cache[key] = img
        except Exception:
            self.current_emoji_surface = None
            self._emoji_surface_cache[key] = None

    def _preload_all_emojis(self):
        for t in self.topics:
            if t.get("icon"):
                self._download_emoji_png(t["icon"])

    def _preload_all_embeddings(self):
        words: List[str] = []
        for t in self.topics:
            for w in t["words"]:
                words.append(w["en"])
                words.append(w["ru"])
        self.emb_cache.prefetch_many(words)

    # ── UI ───────────────────────────────────────────────────────────────────
    def create_ui(self):
        self.main_panel = pygame.Rect(120, 92, 1040, 650)
        self.question_card = pygame.Rect(184, 176, 912, 210)
        self.answer_area = pygame.Rect(184, 410, 912, 250)

        self.btn_close = PygameButton(pygame.Rect(V_W - 180, 40, 120, 54), "Exit", BTN_RED, BTN_RED_DARK, TEXT_LIGHT)
        self.btn_start = PygameButton(pygame.Rect(V_W // 2 - 150, V_H // 2 + 150, 300, 72), "Start", BTN_YELLOW, BTN_YELLOW_DARK)
        self.btn_result_close = PygameButton(pygame.Rect(V_W // 2 - 150, V_H // 2 + 210, 300, 72), "Close", BTN_YELLOW, BTN_YELLOW_DARK)

        choice_w, choice_h = 400, 88
        x1, x2 = 205, 675
        y1, y2 = 430, 540
        self.choice_buttons: List[PygameButton] = [
            PygameButton(pygame.Rect(x1, y1, choice_w, choice_h), "", DEFAULT_CHOICE_FILL, DEFAULT_CHOICE_DEPTH, TEXT_LIGHT),
            PygameButton(pygame.Rect(x2, y1, choice_w, choice_h), "", DEFAULT_CHOICE_FILL, DEFAULT_CHOICE_DEPTH, TEXT_LIGHT),
            PygameButton(pygame.Rect(x1, y2, choice_w, choice_h), "", DEFAULT_CHOICE_FILL, DEFAULT_CHOICE_DEPTH, TEXT_LIGHT),
            PygameButton(pygame.Rect(x2, y2, choice_w, choice_h), "", DEFAULT_CHOICE_FILL, DEFAULT_CHOICE_DEPTH, TEXT_LIGHT),
        ]
        for btn in self.choice_buttons:
            btn.enabled = False

    def _draw_difficulty_bar(self, surface: pygame.Surface, rect: pygame.Rect, difficulty: float):
        draw_shadow(surface, rect, rect.h // 2, dy=4)
        pygame.draw.rect(surface, BTN_CREAM, rect, border_radius=rect.h // 2)
        pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=rect.h // 2)
        filled = max(0, min(rect.w, int(rect.w * difficulty)))
        fill_rect = pygame.Rect(rect.x, rect.y, filled, rect.h)
        r = int(255 * difficulty)
        g = int(200 * (1 - difficulty))
        color = (r, g, 64)
        pygame.draw.rect(surface, color, fill_rect, border_radius=rect.h // 2)
        label = f"Сложность вопроса: {difficulty:.2f}"
        txt = self.font_small.render(label, True, TEXT_DARK)
        surface.blit(txt, txt.get_rect(center=rect.center))

    def _header_text_for_topic(self, topic: Dict[str, Any]) -> str:
        return f"{topic.get('icon', FALLBACK_TOPIC_ICON)} {topic['name_ru']} ({topic['name_en']})"

    def _set_current_topic(self, topic: Dict[str, Any]):
        self.current_topic = topic
        self._topic_recent.append(topic["id"])
        self._topic_recent = self._topic_recent[-6:]

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

    # ── A1 / A2 level helpers ────────────────────────────────────────────────
    def _level_accuracy(self, level: str) -> Optional[float]:
        s = self.level_stats.get(level, {})
        asked = s.get("asked", 0)
        if asked == 0:
            return None
        return s["correct"] / asked

    def _a2_unlocked(self) -> bool:
        s = self.level_stats["A1"]
        if s["asked"] < self.a1_gate_questions:
            return False
        acc = self._level_accuracy("A1")
        return acc is not None and acc >= self.a1_gate_accuracy

    def _cefr_verdict(self) -> str:
        a1_acc = self._level_accuracy("A1")
        a2_acc = self._level_accuracy("A2")
        a1_asked = self.level_stats["A1"]["asked"]
        a2_asked = self.level_stats["A2"]["asked"]

        if a1_asked == 0:
            return "Недостаточно данных"

        a1_pct = int((a1_acc or 0) * 100)
        a2_pct = int((a2_acc or 0) * 100) if a2_acc is not None else None

        if a1_pct < 50:
            verdict = "Ниже A1 — нужна дополнительная практика базовых слов"
        elif a1_pct < 70:
            verdict = "Начальный A1 — базовые слова частично усвоены"
        elif a2_asked < 4:
            verdict = f"Уверенный A1 ({a1_pct}%) — A2 слова ещё не проверялись"
        elif a2_pct is not None and a2_pct >= 75:
            verdict = f"Уверенный A2 ({a2_pct}%) — отличный результат!"
        elif a2_pct is not None and a2_pct >= 50:
            verdict = f"Переходный A1→A2 — A1: {a1_pct}%, A2: {a2_pct}%"
        else:
            verdict = f"Уверенный A1 ({a1_pct}%) — A2 пока трудно ({a2_pct}%)"
        return verdict

    def _live_level_text(self) -> str:
        a1_acc = self._level_accuracy("A1")
        a2_acc = self._level_accuracy("A2")
        a1_str = "—" if a1_acc is None else f"{int(a1_acc * 100)}%"
        a2_str = "—" if a2_acc is None else f"{int(a2_acc * 100)}%"
        unlocked = "✓" if self._a2_unlocked() else "🔒"
        return f"A1: {a1_str}  |  A2 {unlocked}: {a2_str}"

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

    # ── Finish ───────────────────────────────────────────────────────────────
    def _finish_and_show_result(self, reason: str = ""):
        import datetime as _dt

        try:
            update_from_level_game(self.history)
            knowledge_note = "\n\n💾 Results saved to database"
        except Exception as exc:
            knowledge_note = f"\n\n⚠️ Could not save results: {exc}"

        a1_s = self.level_stats["A1"]
        a2_s = self.level_stats["A2"]
        a1_acc = self._level_accuracy("A1")
        a2_acc = self._level_accuracy("A2")

        if a2_s["asked"] >= 4 and a2_acc is not None and a2_acc >= 0.60:
            cefr_level = "A2"
        else:
            cefr_level = "A1"

        profile = {
            "level": cefr_level,
            "a1_accuracy": a1_acc,
            "a2_accuracy": a2_acc,
            "a1_questions": a1_s["asked"],
            "a2_questions": a2_s["asked"],
            "verdict": self._cefr_verdict(),
            "assessed_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }
        try:
            (_HERE / "player_profile.json").write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

        acc = self._recent_accuracy(10)
        acc_txt = "—" if acc is None else f"{acc:.0%}"
        a1_txt = "—" if a1_acc is None else f"{a1_acc:.0%}  ({a1_s['correct']}/{a1_s['asked']} correct)"
        a2_txt = "—" if a2_acc is None else f"{a2_acc:.0%}  ({a2_s['correct']}/{a2_s['asked']} correct)"

        weighted_score = weighted_total = 0.0
        for h in self.history:
            d = h.get("difficulty", 0.5)
            weighted_total += d + 0.5
            if h["ok"]:
                weighted_score += d + 0.5
        w_acc = (weighted_score / weighted_total) if weighted_total else 0
        verdict = self._cefr_verdict()

        msg = (
            "🏁 Diagnosis complete!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  A1 level: {a1_txt}\n"
            f"  A2 level: {a2_txt}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  Result: {verdict}\n"
            f"  Assigned level: {cefr_level}\n\n"
            f"  Recent accuracy (last 10): {acc_txt}\n"
            f"  Weighted accuracy:         {w_acc:.0%}\n"
            f"  Questions answered:        {self._asked_total}\n"
        )
        if reason:
            msg += f"\n  Reason for stopping: {reason}\n"
        msg += "\nYou may close this window."
        msg += knowledge_note

        self.result_message = msg
        self.result_overlay = True
        self.close_after_result = True

    # ── No-repeat helpers ────────────────────────────────────────────────────
    def _q_key(self, direction: str, shown: str) -> str:
        return f"{direction}|shown|{shown.strip().lower()}"

    def _mark_seen(self, direction: str, shown: str, correct: str):
        self.seen_question_keys.add(self._q_key(direction, shown))
        self.seen_question_keys.add(f"{direction}|correct|{correct.strip().lower()}")

    def _available_words_for_topic(
        self,
        topic: Dict[str, Any],
        direction: str,
        word_level: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        out = []
        for w in topic["words"]:
            if word_level and w.get("level", "A1") != word_level:
                continue
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

    # ── Semantic distractor selection ────────────────────────────────────────
    def _target_distractor_similarity(self) -> float:
        return 0.10 + self.skill * 0.70

    def _semantic_distractors(
        self,
        correct: str,
        pool: List[str],
        n: int = 3,
    ) -> Tuple[List[str], float]:
        target_sim = self._target_distractor_similarity()
        correct_vec = self.emb_cache.get(correct)
        if correct_vec is None:
            pool_clean = [p for p in pool if p.strip().lower() != correct.strip().lower()]
            random.shuffle(pool_clean)
            return pool_clean[:n], 0.3

        scored: List[Tuple[float, str, float]] = []
        for word in pool:
            w = word.strip()
            if w.lower() == correct.strip().lower():
                continue
            vec = self.emb_cache.get(w)
            if vec is None:
                continue
            sim = cosine_similarity(correct_vec, vec)
            dist_to_target = abs(sim - target_sim)
            scored.append((dist_to_target, w, sim))

        if not scored:
            pool_clean = [p for p in pool if p.strip().lower() != correct.strip().lower()]
            random.shuffle(pool_clean)
            return pool_clean[:n], 0.3

        scored.sort(key=lambda x: x[0])
        best = scored[: max(n * 2, 6)]
        random.shuffle(best)
        chosen = best[:n]

        distractors = [e[1] for e in chosen]
        avg_sim = sum(e[2] for e in chosen) / len(chosen) if chosen else 0.3
        return distractors, avg_sim

    def _build_choices_semantic(
        self,
        correct: str,
        pool: List[str],
        n: int = 4,
    ) -> Tuple[List[str], float]:
        distractors, avg_sim = self._semantic_distractors(correct, pool, n=n - 1)

        seen: set = {correct.lower().strip()}
        clean: List[str] = []
        for d in distractors:
            k = d.lower().strip()
            if k not in seen:
                seen.add(k)
                clean.append(d)

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

    # ── Pools ────────────────────────────────────────────────────────────────
    def _all_en_pool(self, mix_topics: bool, word_level: Optional[str] = None) -> List[str]:
        topics = self.topics if mix_topics else [self.current_topic]
        return [
            w["en"] for t in topics for w in t["words"]
            if word_level is None or w.get("level", "A1") == word_level
        ]

    def _all_ru_pool(self, mix_topics: bool, word_level: Optional[str] = None) -> List[str]:
        topics = self.topics if mix_topics else [self.current_topic]
        return [
            w["ru"] for t in topics for w in t["words"]
            if word_level is None or w.get("level", "A1") == word_level
        ]

    # ── LLM question selection ───────────────────────────────────────────────
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

    def _target_word_level(self) -> str:
        if not self._a2_unlocked():
            return "A1"
        return "A2" if random.random() < 0.60 else "A1"

    def _candidate_words_for_topic(
        self,
        topic: Dict[str, Any],
        direction: str,
        word_level: str = "A1",
    ) -> List[Dict[str, str]]:
        available = self._available_words_for_topic(topic, direction, word_level=word_level)
        if not available:
            available = self._available_words_for_topic(topic, direction)
        if not available:
            return []
        target = 4 + int(self.skill * 6)
        scored = []
        for w in available:
            score = abs(len(w["ru"]) - target)
            scored.append((score, {
                "ru": w["ru"],
                "en": w["en"],
                "pos": w.get("pos", ""),
                "level": w.get("level", "A1"),
            }))
        scored.sort(key=lambda x: x[0])
        return [x[1] for x in scored[:18]]

    def _show_llm_question(self) -> bool:
        topic = self.current_topic
        dir_try = ["ru_to_en", "en_to_ru"]
        random.shuffle(dir_try)
        mix = self.skill >= 0.55
        word_level = self._target_word_level()

        for direction in dir_try:
            candidates = self._candidate_words_for_topic(topic, direction, word_level=word_level)
            if len(candidates) < 4:
                continue

            acc = self._recent_accuracy(10)
            acc_txt = "null" if acc is None else f"{acc:.2f}"
            a2_unlocked = self._a2_unlocked()

            prompt = f"""
You are a tester to quickly IDENTIFY a toddler's Russian level.
Choose the NEXT multiple-choice question that is maximally informative.

Context:
- Current topic: {topic['id']} / {topic['name_ru']}
- Estimated skill (0..1): {self.skill:.2f}
- Recent accuracy (last 10): {acc_txt}
- Questions asked so far: {self._asked_total}
- Target word level for this question: {word_level}
- A2 unlocked: {a2_unlocked}

Hard rule:
- DO NOT repeat already asked words. You MUST choose correct word from candidates provided.
- Prefer words matching level \"{word_level}\".

Rules:
- Output VALID JSON ONLY. No extra text.
- Pick only the word (shown + correct). Distractors will be chosen by the system using semantic similarity.
- Toddler-friendly.

Direction is fixed for this request: \"{direction}\"

Candidates (correct word MUST be from here):
{json.dumps(candidates, ensure_ascii=False)}

Return JSON schema:
{{
  \"direction\": \"{direction}\",
  \"prompt_ru\": \"string\",
  \"shown\": \"string\",
  \"correct\": \"string\"
}}

If direction == \"ru_to_en\": shown is Russian word, correct is English.
If direction == \"en_to_ru\": shown is English word, correct is Russian.
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

            actual_level = word_level
            for c in candidates:
                shown_field = c["ru"] if direction == "ru_to_en" else c["en"]
                if shown_field.strip().lower() == shown.strip().lower():
                    actual_level = c.get("level", word_level)
                    break

            pool = self._all_en_pool(mix) if direction == "ru_to_en" else self._all_ru_pool(mix)
            choices, difficulty = self._build_choices_semantic(correct, pool, n=4)

            self.correct_answer = correct
            self._current_difficulty = difficulty
            self._current_word_level = actual_level
            self.current_question = {
                "prompt": prompt_ru,
                "shown": shown,
                "direction": direction,
                "topic_id": topic["id"],
                "difficulty": difficulty,
                "word_level": actual_level,
            }
            self._display_question(prompt_ru, shown, choices, difficulty, actual_level)
            self._mark_seen(direction, shown, correct)
            return True

        return False

    # ── Fallback DB question ─────────────────────────────────────────────────
    def _direction_fallback(self) -> str:
        if self.skill < 0.45:
            return "ru_to_en"
        return random.choice(["ru_to_en", "en_to_ru"])

    def _pick_unseen_word_any_topic(
        self,
        direction: str,
        word_level: str = "A1",
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, str]]]:
        candidates = self._available_words_for_topic(
            self.current_topic, direction, word_level=word_level,
        )
        if candidates:
            return self.current_topic, random.choice(candidates)

        topics_shuffled = self.topics[:]
        random.shuffle(topics_shuffled)
        for t in topics_shuffled:
            candidates = self._available_words_for_topic(t, direction, word_level=word_level)
            if candidates:
                return t, random.choice(candidates)

        for t in topics_shuffled:
            candidates = self._available_words_for_topic(t, direction)
            if candidates:
                return t, random.choice(candidates)
        return None

    def _show_db_question(self) -> bool:
        direction = self._direction_fallback()
        mix = self.skill >= 0.55
        word_level = self._target_word_level()

        picked = self._pick_unseen_word_any_topic(direction, word_level=word_level)
        if not picked:
            return False

        topic, w = picked
        if topic["id"] != self.current_topic["id"]:
            self._set_current_topic(topic)

        actual_level = w.get("level", "A1")

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
        self._current_word_level = actual_level
        self.current_question = {
            "prompt": prompt,
            "shown": shown,
            "direction": direction,
            "topic_id": self.current_topic["id"],
            "difficulty": difficulty,
            "word_level": actual_level,
        }
        self._display_question(prompt, shown, choices, difficulty, actual_level)
        self._mark_seen(direction, shown, correct)
        return True

    # ── Display / flow ───────────────────────────────────────────────────────
    def _display_question(
        self,
        question: str,
        shown_text: str,
        choices: List[str],
        difficulty: float = 0.5,
        word_level: str = "A1",
    ):
        self._set_emoji_image(self.current_topic.get("icon", FALLBACK_TOPIC_ICON), size=self.emoji_size)
        self.question_text = question
        self.shown_text = shown_text

        acc = self._recent_accuracy(10)
        acc_txt = "—" if acc is None else f"{acc:.0%}"
        self.status_text = f"Слово уровня {word_level}  |  skill={self.skill:.2f}  |  acc={acc_txt}"
        self.live_level_text = self._live_level_text()

        for i, btn in enumerate(self.choice_buttons):
            btn.label = choices[i]
            btn.enabled = True
            btn.fill = DEFAULT_CHOICE_FILL
            btn.depth = DEFAULT_CHOICE_DEPTH
            btn.text_color = TEXT_LIGHT

        self.feedback_text = ""
        self.feedback_kind = "info"
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
        self.feedback_text = ""
        for btn in self.choice_buttons:
            btn.enabled = False
            btn.fill = DEFAULT_CHOICE_FILL
            btn.depth = DEFAULT_CHOICE_DEPTH

        self._asked_total += 1

        if self.ai_enabled and self._show_llm_question():
            return
        if self._show_db_question():
            return
        self._finish_and_show_result("не удалось сгенерировать новый уникальный вопрос")

    def check_answer(self, answer: str):
        for btn in self.choice_buttons:
            btn.enabled = False

        is_correct = answer.lower().strip() == self.correct_answer.lower().strip()
        difficulty = self._current_difficulty
        word_level = self._current_word_level

        if is_correct:
            for btn in self.choice_buttons:
                if btn.label.lower().strip() == self.correct_answer.lower().strip():
                    btn.fill = CORRECT_FILL
                    btn.depth = CORRECT_DEPTH
                    btn.text_color = TEXT_LIGHT
            self.feedback_text = "✅ Правильно"
            self.feedback_kind = "success"
        else:
            for btn in self.choice_buttons:
                text = btn.label.lower().strip()
                if text == answer.lower().strip():
                    btn.fill = WRONG_FILL
                    btn.depth = WRONG_DEPTH
                    btn.text_color = TEXT_LIGHT
                elif text == self.correct_answer.lower().strip():
                    btn.fill = CORRECT_FILL
                    btn.depth = CORRECT_DEPTH
                    btn.text_color = TEXT_LIGHT
            self.feedback_text = f"❌ Неправильно: {self.correct_answer}"
            self.feedback_kind = "error"

        if word_level in self.level_stats:
            self.level_stats[word_level]["asked"] += 1
            if is_correct:
                self.level_stats[word_level]["correct"] += 1

        delta = _skill_delta(is_correct, difficulty)
        self.skill = max(0.0, min(1.0, self.skill + delta))

        self.skill_history.append(self.skill)
        self.skill_history = self.skill_history[-self.max_history:]

        self.history.append({
            "ok": bool(is_correct),
            "topic_id": self.current_question.get("topic_id"),
            "direction": self.current_question.get("direction"),
            "shown": self.current_question.get("shown"),
            "correct": self.correct_answer,
            "difficulty": difficulty,
            "word_level": word_level,
        })
        self.history = self.history[-self.max_history:]

        self.next_generate_at = pygame.time.get_ticks() + self.auto_advance_ms

    # ── Pygame event/update/draw loop ───────────────────────────────────────
    def _start_test(self):
        self.start_overlay = False
        self.next_generate_at = pygame.time.get_ticks() + 400

    def handle_event(self, event, mouse_v):
        if event.type == pygame.QUIT:
            self.running = False
            return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.running = False
                return
            if self.start_overlay and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._start_test()
                return
            if self.result_overlay and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.running = False
                return

        if event.type == pygame.MOUSEMOTION:
            self.btn_close.hovered = self.btn_close.rect.collidepoint(mouse_v)
            self.btn_start.hovered = self.btn_start.rect.collidepoint(mouse_v)
            self.btn_result_close.hovered = self.btn_result_close.rect.collidepoint(mouse_v)
            for btn in self.choice_buttons:
                btn.hovered = btn.rect.collidepoint(mouse_v) and btn.enabled

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.btn_close.hit(mouse_v):
                self.running = False
                return

            if self.start_overlay:
                if self.btn_start.hit(mouse_v):
                    self._start_test()
                return

            if self.result_overlay:
                if self.btn_result_close.hit(mouse_v):
                    self.running = False
                return

            if not self.is_generating:
                for btn in self.choice_buttons:
                    if btn.hit(mouse_v):
                        self.check_answer(btn.label)
                        break

    def update(self, now_ms: int):
        if self.start_overlay or self.result_overlay:
            return
        if self.next_generate_at is not None and now_ms >= self.next_generate_at:
            self.next_generate_at = None
            self.generate_question()

    def _draw_text_block(self, surface: pygame.Surface, text: str, rect: pygame.Rect,
                         font: pygame.font.Font, color: Color, align: str = "center", max_lines: int = 5):
        lines = wrap_text(text, font, rect.w)
        lines = lines[:max_lines]
        y = rect.y + max(0, (rect.h - len(lines) * font.get_linesize()) // 2)
        for line in lines:
            txt = font.render(line, True, color)
            if align == "left":
                x = rect.x
            else:
                x = rect.centerx - txt.get_width() // 2
            surface.blit(txt, (x, y))
            y += font.get_linesize() + 2

    def draw(self):
        c = self.canvas
        draw_background(c)
        draw_panel(c, self.main_panel)
        draw_ribbon_title(c, "Диагностика уровня", self.main_panel, self.font_title)

        self.btn_close.draw(c, self.font_button)

        draw_badge(c, pygame.Rect(880, 54, 190, 46), "★", str(self._asked_total), self.font_small, self.font_icon)
        draw_badge(c, pygame.Rect(880, 112, 190, 46), "✓", self.live_level_text or "A1: —  |  A2 🔒: —", self.font_small, self.font_icon)

        # Topic banner
        topic_rect = pygame.Rect(210, 116, 760, 58)
        pygame.draw.rect(c, BTN_CREAM, topic_rect, border_radius=18)
        pygame.draw.rect(c, PANEL_BORDER, topic_rect, 2, border_radius=18)
        self._draw_text_block(c, self._header_text_for_topic(self.current_topic), topic_rect, self.font_header, TEXT_DARK, max_lines=2)

        # Question card
        draw_panel(c, self.question_card, radius=24)

        emoji_slot = pygame.Rect(self.question_card.x + 26, self.question_card.y + 32, 112, 112)
        pygame.draw.rect(c, HUD_CREAM, emoji_slot, border_radius=18)
        pygame.draw.rect(c, HUD_BORDER, emoji_slot, 2, border_radius=18)
        if self.current_emoji_surface is not None:
            c.blit(self.current_emoji_surface, self.current_emoji_surface.get_rect(center=emoji_slot.center))
        else:
            emoji_f = _best_font(48, bold=True)
            t = emoji_f.render(self.current_emoji_text or "?", True, TEXT_DARK)
            c.blit(t, t.get_rect(center=emoji_slot.center))

        question_text_rect = pygame.Rect(self.question_card.x + 160, self.question_card.y + 28, 690, 56)
        self._draw_text_block(c, self.question_text, question_text_rect, self.font_question, TEXT_SOFT, align="left", max_lines=2)

        word_box = pygame.Rect(self.question_card.x + 160, self.question_card.y + 86, 690, 68)
        pygame.draw.rect(c, lighten(BTN_YELLOW, 8), word_box, border_radius=18)
        pygame.draw.rect(c, PANEL_BORDER, word_box, 2, border_radius=18)
        self._draw_text_block(c, self.shown_text, word_box, self.font_word, TEXT_DARK, max_lines=1)

        status_rect = pygame.Rect(self.question_card.x + 160, self.question_card.y + 158, 690, 28)
        status_color = CORRECT_FILL if self._current_word_level == "A1" else BTN_ORANGE_DARK
        self._draw_text_block(c, self.status_text, status_rect, self.font_small, status_color, align="left", max_lines=1)

        # Difficulty bar
        self._draw_difficulty_bar(c, pygame.Rect(245, 664, 670, 24), self._current_difficulty)

        # Choices
        for btn in self.choice_buttons:
            btn.draw(c, self.font_button)

        # Sub text
        sub = self.font_small.render(self.sub_text, True, TEXT_DARK)
        c.blit(sub, (180, 704))

        if self.is_generating and not self.start_overlay and not self.result_overlay:
            loader_rect = pygame.Rect(390, 720, 500, 54)
            draw_button(c, loader_rect, "Generating question...", BTN_CREAM, BTN_CREAM_DARK, self.font_button, TEXT_DARK, enabled=False)

        if self.feedback_text and not self.start_overlay and not self.result_overlay:
            kind_fill = BTN_CREAM
            kind_border = CORRECT_FILL if self.feedback_kind == "success" else WRONG_FILL if self.feedback_kind == "error" else BTN_BLUE
            pill = pygame.Rect(360, 716, 560, 58)
            draw_shadow(c, pill, 22, dy=4)
            pygame.draw.rect(c, kind_fill, pill, border_radius=22)
            pygame.draw.rect(c, kind_border, pill, 3, border_radius=22)
            self._draw_text_block(c, self.feedback_text, pill, self.font_button, TEXT_DARK, max_lines=1)

        if self.start_overlay:
            overlay = pygame.Surface((V_W, V_H), pygame.SRCALPHA)
            overlay.fill((20, 22, 30, 120))
            c.blit(overlay, (0, 0))
            panel = pygame.Rect(V_W // 2 - 360, V_H // 2 - 220, 720, 430)
            draw_panel(c, panel)
            draw_ribbon_title(c, "Start", panel, self.font_title)
            info_rect = pygame.Rect(panel.x + 56, panel.y + 110, panel.w - 112, 200)
            intro = (
                "Это тест для определения уровня A1 / A2.\n\n"
                "• Сначала вопросы по словам уровня A1.\n"
                "• Когда A1 будет освоен — добавятся слова A2.\n"
                "• Вопросы не повторяются.\n"
                "• Тест завершится автоматически.\n\n"
                "После завершения результаты будут сохранены."
            )
            self._draw_text_block(c, intro, info_rect, self.font_question, TEXT_DARK, max_lines=10)
            self.btn_start.draw(c, self.font_button)

        if self.result_overlay:
            overlay = pygame.Surface((V_W, V_H), pygame.SRCALPHA)
            overlay.fill((20, 22, 30, 140))
            c.blit(overlay, (0, 0))
            panel = pygame.Rect(V_W // 2 - 420, V_H // 2 - 260, 840, 520)
            draw_panel(c, panel)
            draw_ribbon_title(c, "Result", panel, self.font_title)
            result_rect = pygame.Rect(panel.x + 48, panel.y + 104, panel.w - 96, 300)
            self._draw_text_block(c, self.result_message, result_rect, self.font_small, TEXT_DARK, align="left", max_lines=16)
            self.btn_result_close.draw(c, self.font_button)

    def run(self):
        while self.running:
            scale, new_size, offset = compute_scale_and_offset(self.screen.get_size(), (V_W, V_H))
            mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)
            now_ms = pygame.time.get_ticks()

            for event in pygame.event.get():
                self.handle_event(event, mouse_v)

            self.update(now_ms)
            self.draw()
            blit_scaled(self.screen, self.canvas, new_size, offset)
            self.clock.tick(FPS)

        pygame.quit()


# ============================================================
# Entry point
# ============================================================
def main():
    game = ImprovedRussianGame()
    game.run()


if __name__ == "__main__":
    main()
