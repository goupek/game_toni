"""
game2 connected to the SQLite word-knowledge store.

Identical to game2.py with one change:
  generate_round() is replaced by generate_round_filtered() so that rounds
  only use words the kid has NOT yet mastered (according to DB progress).

Run directly:
    python lvl_games/game2_connected.py

Workflow
--------
1. Run lvl_game_connected.py  → plays the level-identification game
                               → saves results to the database
2. Run game2_connected.py     → reads progress from the database
                               → skips words the kid already knows
"""

import os
import queue
import sys
import threading
from pathlib import Path

# Allow imports from the repo root (image_utils, question_generation, …)
_HERE   = Path(__file__).resolve().parent   # lvl_games/
_ROOT   = _HERE.parent                      # repo root

for p in [str(_HERE), str(_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pygame

from question_generation_filtered import generate_round_filtered   # NEW (replaces generate_round)
from question_generation import NOUNS, ADJECTIVES, NUM_WORD
from image_utils import build_round_surface
from pipeline_mem.llm_tts_hint import HintEngine
from word_knowledge import update_from_level_game, _NUM_EN_MAP

# -----------------------------
# SETTINGS  (unchanged)
# -----------------------------
DESIGN_W, DESIGN_H = 1024, 768
FPS = 60

ROUNDS_PER_GAME = 10
ROUND_CANVAS_SIZE = (800, 800)

BASE_DIR  = str(_ROOT)
IMG_DIR   = os.path.join(BASE_DIR, "images")
AUDIO_DIR = os.path.join(BASE_DIR, "audio")

# Launcher style
BG_TOP = (128, 183, 181)
BG_BOTTOM = (109, 164, 172)
BG_POLY_1 = (117, 170, 166)
BG_POLY_2 = (100, 151, 160)
BG_POLY_3 = (92, 142, 154)

PANEL_FILL = (229, 222, 189)
PANEL_BORDER = (181, 156, 106)
PANEL_INNER = (243, 237, 210)

RIBBON_FILL = (236, 81, 127)
RIBBON_DARK = (193, 48, 92)
RIBBON_LIGHT = (248, 118, 157)

TEXT_DARK = (77, 43, 64)
TEXT_SOFT = (98, 70, 89)
TEXT_LIGHT = (255, 248, 235)
OUTLINE_DARK = (99, 61, 81)
SHADOW_FILL = (153, 136, 148)

BTN_BLUE = (37, 205, 230)
BTN_BLUE_DARK = (93, 86, 210)
BTN_GREEN = (166, 231, 12)
BTN_GREEN_DARK = (111, 179, 26)
BTN_RED = (245, 112, 112)
BTN_RED_DARK = (196, 58, 61)
BTN_YELLOW = (251, 224, 64)
BTN_YELLOW_DARK = (236, 174, 44)
BTN_CREAM = (245, 240, 230)
BTN_CREAM_DARK = (177, 163, 174)

SUCCESS_FILL = (204, 245, 190)
ERROR_FILL = (255, 213, 213)

BG    = PANEL_INNER
WHITE = BTN_CREAM
BLACK = TEXT_DARK
GRAY  = BTN_CREAM
DARK  = PANEL_BORDER
BLUE  = BTN_BLUE
GREEN = BTN_GREEN
RED   = BTN_RED

WORD_TO_FEEDBACK_DELAY_MS = 1000
CORRECT_NEXT_DELAY_MS     = 2000

REPLAY_ICON_FILE = "replay.jpg"

SND_GREAT     = "great.mp3"
SND_TRY_AGAIN = "try_again.mp3"

TTS_DIR = os.path.join(BASE_DIR, "tts_out")

# -----------------------------
# PATH HELPERS
# -----------------------------
def audio_path(filename):
    return os.path.join(AUDIO_DIR, filename)

def image_path(filename):
    return os.path.join(IMG_DIR, filename)

def _best_font(size, bold=False):
    for name in ("Nunito", "Baloo 2", "Ubuntu", "Noto Sans", "DejaVu Sans", "Arial", ""):
        try:
            f = pygame.font.SysFont(name, max(14, size), bold=bold)
            if f:
                return f
        except Exception:
            pass
    return pygame.font.Font(None, max(14, size))


def lighten(color, amount):
    return tuple(min(255, c + amount) for c in color)


def render_tracked_text(font, text, color, tracking=1):
    text = str(text)
    if tracking <= 0 or len(text) < 2:
        return font.render(text, True, color)
    glyphs = [font.render(ch, True, color) for ch in text]
    width = sum(g.get_width() for g in glyphs) + tracking * (len(glyphs) - 1)
    height = max((g.get_height() for g in glyphs), default=font.get_height())
    surface = pygame.Surface((max(1, width), max(1, height)), pygame.SRCALPHA)
    x = 0
    for glyph in glyphs:
        surface.blit(glyph, (x, (height - glyph.get_height()) // 2))
        x += glyph.get_width() + tracking
    return surface


def draw_background(screen, w, h):
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        pygame.draw.line(screen, (r, g, b), (0, y), (w, y))
    polys = [
        (BG_POLY_1, [(0, h * 0.18), (w * 0.28, 0), (w * 0.5, h * 0.22), (w * 0.2, h * 0.42)]),
        (BG_POLY_2, [(w * 0.66, 0), (w, 0), (w, h * 0.34), (w * 0.8, h * 0.26)]),
        (BG_POLY_3, [(0, h), (w * 0.22, h * 0.7), (w * 0.4, h), (0, h)]),
        (BG_POLY_2, [(w * 0.58, h), (w * 0.78, h * 0.62), (w, h), (w * 0.78, h)]),
    ]
    for color, pts in polys:
        pygame.draw.polygon(screen, color, pts)


def draw_shadow(screen, rect, radius, dy=6):
    pygame.draw.rect(screen, SHADOW_FILL, rect.move(0, dy), border_radius=radius)


def draw_panel(screen, rect, radius=28):
    draw_shadow(screen, rect, radius, dy=8)
    pygame.draw.rect(screen, PANEL_FILL, rect, border_radius=radius)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=4, border_radius=radius)
    inner = rect.inflate(-10, -10)
    pygame.draw.rect(screen, PANEL_INNER, inner, width=2, border_radius=max(12, radius - 6))


def draw_ribbon_title(screen, text, panel_rect, font, s):
    ribbon_h = max(56, int(72 * s))
    ribbon_w = int(panel_rect.w * 1.08)
    ribbon_x = panel_rect.centerx - ribbon_w // 2
    ribbon_y = panel_rect.y + max(18, int(22 * s))
    ribbon = pygame.Rect(ribbon_x, ribbon_y, ribbon_w, ribbon_h)
    tail_w = max(20, int(32 * s))
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
    pygame.draw.polygon(screen, RIBBON_DARK, left_tail)
    pygame.draw.polygon(screen, RIBBON_DARK, right_tail)
    draw_shadow(screen, ribbon, 0, dy=max(4, int(6 * s)))
    pygame.draw.rect(screen, RIBBON_FILL, ribbon)
    pygame.draw.rect(screen, RIBBON_LIGHT, pygame.Rect(ribbon.x, ribbon.y, ribbon.w, max(8, int(12 * s))))
    pygame.draw.line(screen, RIBBON_DARK, (ribbon.left, ribbon.bottom - 3), (ribbon.right, ribbon.bottom - 3), 3)
    txt = render_tracked_text(font, text, TEXT_LIGHT, tracking=1)
    screen.blit(txt, txt.get_rect(center=ribbon.center))

# -----------------------------
# TTS AUDIO
# -----------------------------
def _build_tts_files(nouns, adjectives, num_word):
    result = {}

    for noun_key, forms in nouns.items():
        for form_type, form_value in forms.items():
            if form_type != "gender":
                result[f"{noun_key}_{form_type}.wav"] = form_value

    for adj_key, forms in adjectives.items():
        adj_filename = adj_key.replace(" ", "_")
        for gender, form_value in forms.items():
            result[f"{adj_filename}_{gender}.wav"] = form_value

    for num_key, forms in num_word.items():
        values = list(forms.values())
        if len(set(values)) == 1:
            result[f"{num_key}.wav"] = values[0]
        else:
            for gender, form_value in forms.items():
                result[f"{num_key}_{gender}.wav"] = form_value

    result.update({
        "q_color.wav": "Какого цвета",
        "q_count.wav": "Сколько",
        "q_tail.wav":  "на картинке?",
    })
    return result


TTS_FILES = _build_tts_files(NOUNS, ADJECTIVES, NUM_WORD)

WORD_TO_WAV = {v: k for k, v in TTS_FILES.items()}

def tts_path(filename):
    return os.path.join(TTS_DIR, filename)

# -----------------------------
# AUDIO
# -----------------------------
class AudioBank:
    def __init__(self):
        self.cache = {}
        self.ch    = pygame.mixer.Channel(0)
        self.queue = []

    def _load(self, filename):
        if not filename:
            return None
        if filename not in self.cache:
            path = tts_path(filename)
            if not os.path.exists(path):
                print("[WARN] Missing TTS wav:", path)
                return None
            self.cache[filename] = pygame.mixer.Sound(path)
        return self.cache[filename]

    def play(self, filename):
        snd = self._load(filename)
        if not snd:
            return
        self.queue = []
        self.ch.stop()
        self.ch.play(snd)

    def play_sequence(self, filenames):
        self.queue = list(filenames)
        self._play_next()

    def _play_next(self):
        if not self.queue:
            return
        fn  = self.queue.pop(0)
        snd = self._load(fn)
        if snd:
            self.ch.play(snd)

    def update(self):
        if not self.ch.get_busy() and self.queue:
            self._play_next()

def wav_for_word(word_or_phrase):
    return WORD_TO_WAV.get(word_or_phrase)

def noun_clip(noun_key, form_key):
    return "{}_{}.wav".format(noun_key, form_key)

def question_clips(round_data):
    noun_key = round_data["noun_key"]
    count    = round_data["count"]
    qtype    = round_data["qtype"]

    if qtype == "count":
        return ["q_count.wav", noun_clip(noun_key, "gen_pl"), "q_tail.wav"]

    form = "sg" if count == 1 else "pl"
    return ["q_color.wav", noun_clip(noun_key, form), "q_tail.wav"]


def play_audio(filename):
    if not filename:
        return
    path = audio_path(filename)
    if not os.path.exists(path):
        print("[WARN] Missing audio:", path)
        return
    try:
        pygame.mixer.music.stop()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
    except pygame.error as e:
        print("[WARN] Could not play audio:", path, e)

# -----------------------------
# TEXT WRAP
# -----------------------------
def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    cur   = ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

# -----------------------------
# IMAGE LOADING
# -----------------------------
def load_image(filename):
    path = image_path(filename)
    if not os.path.exists(path):
        print("[WARN] Missing image:", path)
        return None
    img = pygame.image.load(path)
    if filename.lower().endswith(".png"):
        return img.convert_alpha()
    return img.convert()

def scale_fit(surface, target_w, target_h):
    sw, sh = surface.get_size()
    if sw == 0 or sh == 0:
        return surface
    scale = min(target_w / sw, target_h / sh)
    new_w = max(1, int(sw * scale))
    new_h = max(1, int(sh * scale))
    return pygame.transform.smoothscale(surface, (new_w, new_h))

# -----------------------------
# BUTTON
# -----------------------------
class Button:
    def __init__(self, rect, label, show_replay=False, bg=None, text_color=None):
        self.rect        = pygame.Rect(rect)
        self.label       = label
        self.border      = DARK
        self.bg          = bg if bg is not None else BTN_CREAM
        self.text_color  = text_color if text_color is not None else BLACK
        self.show_replay = show_replay
        self.replay_rect = None

    def set_border(self, color):
        self.border = color

    def reset(self):
        self.border = DARK

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def hit_replay(self, pos):
        return self.replay_rect is not None and self.replay_rect.collidepoint(pos)

    def draw(self, screen, font, border_w, s, replay_icon_surf=None):
        depth = BTN_CREAM_DARK
        if self.bg == BTN_BLUE:
            depth = BTN_BLUE_DARK
        elif self.bg == BTN_YELLOW:
            depth = BTN_YELLOW_DARK
        elif self.bg == BTN_GREEN:
            depth = BTN_GREEN_DARK
        elif self.bg == BTN_RED:
            depth = BTN_RED_DARK
        pygame.draw.rect(screen, depth, self.rect.move(0, max(4, int(7 * s))), border_radius=14)
        pygame.draw.rect(screen, self.bg, self.rect, border_radius=14)
        pygame.draw.rect(
            screen,
            lighten(self.bg, 18),
            (self.rect.x + 6, self.rect.y + 5, self.rect.w - 12, min(12, self.rect.h // 3)),
            border_radius=10,
        )
        pygame.draw.rect(screen, self.border, self.rect, width=border_w, border_radius=14)

        replay_space = int(90 * s) if self.show_replay else 0
        text_area    = self.rect.copy()
        text_area.w -= replay_space

        txt = render_tracked_text(font, self.label, self.text_color, tracking=1)
        screen.blit(txt, txt.get_rect(center=text_area.center))

        if self.show_replay:
            icon_size = int(54 * s)
            icon_pad  = int(12 * s)
            self.replay_rect = pygame.Rect(
                self.rect.right - icon_size - icon_pad,
                self.rect.centery - icon_size // 2,
                icon_size, icon_size,
            )
            pygame.draw.rect(screen, WHITE, self.replay_rect, border_radius=12)
            pygame.draw.rect(screen, DARK, self.replay_rect, 2, border_radius=12)
            if replay_icon_surf:
                icon_rect = replay_icon_surf.get_rect(center=self.replay_rect.center)
                screen.blit(replay_icon_surf, icon_rect)
        else:
            self.replay_rect = None

# -----------------------------
# UI
# -----------------------------
class UI:
    def __init__(self, w, h):
        self.replay_raw        = load_image(REPLAY_ICON_FILE)
        self.prompt_replay_icon = None
        self.btn_replay_icon   = None
        self.rebuild(w, h)

    def rebuild(self, w, h):
        self.w, self.h = w, h
        sx = w / DESIGN_W
        sy = h / DESIGN_H
        self.s = min(sx, sy)

        def sc(v):
            return max(1, int(v * self.s))

        self.font_title      = _best_font(sc(54), bold=True)
        self.font_prompt     = _best_font(sc(40), bold=True)
        self.font_btn        = _best_font(sc(34), bold=True)
        self.font_hint       = _best_font(sc(28))
        self.font_small      = _best_font(sc(24), bold=True)
        self.font_menu_title = _best_font(sc(60), bold=True)
        self.font_menu_btn   = _best_font(sc(38), bold=True)

        self.border_w = max(2, sc(6))

        panel_margin_x = max(sc(72), int(92 * self.s))
        panel_margin_y = max(sc(36), int(44 * self.s))
        self.panel_rect = pygame.Rect(
            panel_margin_x,
            panel_margin_y,
            w - 2 * panel_margin_x,
            h - 2 * panel_margin_y,
        )

        inner_pad_x = max(sc(22), int(28 * self.s))
        inner_pad_y = max(sc(18), int(22 * self.s))
        content_left  = self.panel_rect.x + inner_pad_x
        content_right = self.panel_rect.right - inner_pad_x
        content_w     = content_right - content_left

        v_gap   = sc(22)
        h_gap   = sc(34)
        top_pad = self.panel_rect.y + inner_pad_y

        self.title_area = pygame.Rect(content_left, top_pad, content_w, sc(54))
        hint_w = sc(220)
        hint_h = sc(64)
        progress_h = sc(24)
        top_row_gap = max(sc(16), int(18 * self.s))
        progress_w = max(sc(280), content_w - hint_w - top_row_gap)
        progress_y = top_pad + (hint_h - progress_h) // 2
        self.progress_bar = pygame.Rect(
            content_left,
            progress_y,
            progress_w,
            progress_h,
        )
        self.hint_button = pygame.Rect(
            content_right - hint_w,
            top_pad,
            hint_w,
            hint_h,
        )
        prompt_gap = max(sc(12), int(14 * self.s))
        self.prompt_area = pygame.Rect(
            content_left,
            self.hint_button.bottom + prompt_gap,
            content_w,
            sc(118),
        )

        rep_size = sc(64)
        rep_pad  = sc(12)
        self.prompt_replay = pygame.Rect(
            self.prompt_area.right - rep_size - rep_pad,
            self.prompt_area.y + rep_pad,
            rep_size, rep_size,
        )

        top_y    = self.prompt_area.bottom + v_gap
        bottom_y = self.panel_rect.bottom - inner_pad_y
        content_h = max(1, bottom_y - top_y)

        image_w   = int(content_w * 0.58)
        btn_w     = content_w - image_w - h_gap
        min_btn_w = sc(260)
        if btn_w < min_btn_w:
            btn_w   = min_btn_w
            image_w = max(sc(260), content_w - btn_w - h_gap)

        self.image_area = pygame.Rect(content_left, top_y, image_w, content_h)
        bx = self.image_area.right + h_gap

        btn_gap = sc(24)
        btn_h   = max(sc(80), (content_h - 2 * btn_gap) // 3)
        self.button_rects = [
            (bx, top_y + 0 * (btn_h + btn_gap), btn_w, btn_h),
            (bx, top_y + 1 * (btn_h + btn_gap), btn_w, btn_h),
            (bx, top_y + 2 * (btn_h + btn_gap), btn_w, btn_h),
        ]

        menu_btn_w, menu_btn_h = sc(300), sc(120)
        menu_start_y = self.panel_rect.y + sc(240)
        self.menu_play  = pygame.Rect((w - menu_btn_w) // 2, menu_start_y, menu_btn_w, menu_btn_h)
        self.menu_exit  = pygame.Rect((w - menu_btn_w) // 2, menu_start_y + sc(150), menu_btn_w, menu_btn_h)
        self.finish_menu = pygame.Rect((w - menu_btn_w) // 2, self.panel_rect.bottom - sc(170), menu_btn_w, menu_btn_h)

        if self.replay_raw:
            ps = max(1, int(self.prompt_replay.w * 0.70))
            self.prompt_replay_icon = scale_fit(self.replay_raw, ps, ps)
            bs = max(1, int(54 * self.s * 0.80))
            self.btn_replay_icon    = scale_fit(self.replay_raw, bs, bs)
        else:
            self.prompt_replay_icon = None
            self.btn_replay_icon    = None

# -----------------------------
# MENU
# -----------------------------
def run_menu(screen, ui):
    clock    = pygame.time.Clock()
    play_btn = Button(ui.menu_play, "Play", bg=BTN_BLUE, text_color=TEXT_LIGHT)
    exit_btn = Button(ui.menu_exit, "Exit", bg=BTN_CREAM, text_color=TEXT_DARK)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                ui.rebuild(event.w, event.h)
                play_btn.rect = ui.menu_play
                exit_btn.rect = ui.menu_exit
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if play_btn.hit(event.pos):
                    return "play"
                if exit_btn.hit(event.pos):
                    return "quit"

        draw_background(screen, ui.w, ui.h)
        draw_panel(screen, ui.panel_rect, max(24, int(32 * ui.s)))
        draw_ribbon_title(screen, "Game 2", ui.panel_rect, ui.font_menu_title, ui.s)

        play_btn.draw(screen, ui.font_menu_btn, ui.border_w, ui.s, replay_icon_surf=None)
        exit_btn.draw(screen, ui.font_menu_btn, ui.border_w, ui.s, replay_icon_surf=None)

        pygame.display.flip()
        clock.tick(FPS)

# -----------------------------
# GAME  (only change: generate_round_filtered)
# -----------------------------
class StoryGame:
    def __init__(self, screen, ui):
        self.screen = screen
        self.ui     = ui
        self.clock  = pygame.time.Clock()
        self.hint_engine = HintEngine()
        self.hint_results: "queue.Queue[tuple[int, str]]" = queue.Queue()
        self.hint_button = Button(ui.hint_button, "Подсказка", bg=BTN_YELLOW, text_color=TEXT_DARK)

        # NEW: use filtered generator instead of generate_round
        self.rounds = [
            generate_round_filtered(option_count=3, max_count=4)
            for _ in range(ROUNDS_PER_GAME)
        ]

        self.index   = 0
        self.score   = 0
        self.history = []
        self.round_attempt_number = 0

        self.locked               = False
        self.pending_feedback_audio = None
        self.feedback_time_ms     = 0
        self.advance_time_ms      = 0

        self.buttons   = []
        self.fit_image = None
        self.raw_image = None

        self.audio = AudioBank()
        self.round_serial = 0
        self.round_wrong_answers = []
        self.hint_text = ""
        self.hint_loading = False
        self.load_round(0)

    def load_round(self, idx):
        self.index = idx
        rd = self.rounds[self.index]
        self.round_serial += 1

        self.locked               = False
        self.pending_feedback_audio = None
        self.feedback_time_ms     = 0
        self.advance_time_ms      = 0
        self.round_attempt_number = 0
        self.round_wrong_answers  = []
        self.hint_text            = ""
        self.hint_loading         = False

        self.buttons = []
        for rect, label in zip(self.ui.button_rects, rd["options"]):
            self.buttons.append(Button(rect, label, show_replay=True))

        self.rescale_current_image()
        self.audio.play_sequence(question_clips(rd))

    def speak_question(self):
        if self.hint_engine.is_speaking():
            return
        rd = self.rounds[self.index]
        self.audio.play_sequence(question_clips(rd))

    def speak_option(self, label):
        if self.hint_engine.is_speaking():
            return
        fn = wav_for_word(label)
        if not fn:
            print("[WARN] No wav for option:", label)
            return
        self.audio.play(fn)

    def rescale_current_image(self):
        rd       = self.rounds[self.index]
        target_w = max(1, self.ui.image_area.w)
        target_h = max(1, self.ui.image_area.h)

        self.raw_image = build_round_surface(IMG_DIR, rd, canvas_size=(target_w, target_h))

        pad = max(2, int(20 * self.ui.s))
        self.fit_image = (
            scale_fit(self.raw_image, target_w - pad, target_h - pad)
            if self.raw_image else None
        )

    def on_resize(self, new_w, new_h):
        self.ui.rebuild(new_w, new_h)
        new_buttons = []
        for rect, old_btn in zip(self.ui.button_rects, self.buttons):
            b           = Button(rect, old_btn.label, show_replay=True)
            b.border    = old_btn.border
            b.bg        = old_btn.bg
            b.text_color = getattr(old_btn, 'text_color', BLACK)
            new_buttons.append(b)
        self.buttons = new_buttons
        self.hint_button.rect = self.ui.hint_button
        self.rescale_current_image()

    def stop_audio(self):
        self.audio.queue = []
        self.audio.ch.stop()
        pygame.mixer.music.stop()

    def _hint_round_snapshot(self):
        rd = dict(self.rounds[self.index])
        rd["options"] = list(rd.get("options", []))
        return rd

    def request_hint(self):
        if self.locked or self.hint_loading:
            return

        self.stop_audio()

        if self.hint_text:
            if not self.hint_engine.is_speaking():
                self.hint_engine.speak(self.hint_text)
            return

        self.hint_loading = True
        round_serial = self.round_serial
        round_data = self._hint_round_snapshot()
        attempt_number = self.round_attempt_number
        wrong_answers = list(self.round_wrong_answers)

        threading.Thread(
            target=self._hint_worker,
            args=(round_serial, round_data, attempt_number, wrong_answers),
            daemon=True,
        ).start()

    def _hint_worker(self, round_serial, round_data, attempt_number, wrong_answers):
        hint_text = self.hint_engine.generate_hint(
            round_data,
            attempt_number=attempt_number,
            wrong_answers=wrong_answers,
        )
        self.hint_results.put((round_serial, hint_text))

    def _poll_hint_results(self):
        while True:
            try:
                round_serial, hint_text = self.hint_results.get_nowait()
            except queue.Empty:
                break

            if round_serial != self.round_serial:
                continue

            self.hint_loading = False
            self.hint_text = hint_text
            self.stop_audio()
            self.hint_engine.speak(hint_text)

    def draw_hint_card(self):
        if not self.hint_loading and not self.hint_text:
            return

        body = "Думаю над подсказкой..." if self.hint_loading else self.hint_text
        pad = max(8, int(16 * self.ui.s))
        title_gap = max(6, int(8 * self.ui.s))
        card_h = max(int(128 * self.ui.s), self.ui.font_small.get_height() + self.ui.font_hint.get_height() * 3 + pad * 2)
        card_rect = pygame.Rect(
            self.ui.image_area.x + pad,
            self.ui.image_area.bottom - card_h - pad,
            self.ui.image_area.w - pad * 2,
            card_h,
        )

        draw_shadow(self.screen, card_rect, 14, dy=5)
        pygame.draw.rect(self.screen, BTN_CREAM, card_rect, border_radius=14)
        pygame.draw.rect(self.screen, PANEL_BORDER, card_rect, 3, border_radius=14)

        title = render_tracked_text(self.ui.font_small, "Hint", TEXT_DARK, tracking=1)
        self.screen.blit(title, (card_rect.x + pad, card_rect.y + pad))

        lines = wrap_text(body, self.ui.font_hint, card_rect.w - pad * 2)
        y = card_rect.y + pad + title.get_height() + title_gap
        for line in lines[:3]:
            txt = render_tracked_text(self.ui.font_hint, line, BLACK, tracking=1)
            self.screen.blit(txt, (card_rect.x + pad, y))
            y += txt.get_height() + max(2, int(4 * self.ui.s))

    def draw_progress(self):
        total = len(self.rounds)
        bar   = self.ui.progress_bar

        pygame.draw.rect(self.screen, BTN_CREAM, bar, border_radius=8)
        fill_w = int(bar.w * ((self.index + 1) / total))
        pygame.draw.rect(self.screen, BTN_BLUE, (bar.x, bar.y, fill_w, bar.h), border_radius=8)
        pygame.draw.rect(self.screen, PANEL_BORDER, bar, 2, border_radius=8)

        label = "Progress: {}/{}".format(self.index + 1, total)
        txt   = render_tracked_text(self.ui.font_small, label, BLACK, tracking=1)
        self.screen.blit(txt, (bar.x, bar.y - txt.get_height() - 6))

    def draw(self):
        draw_background(self.screen, self.ui.w, self.ui.h)
        draw_panel(self.screen, self.ui.panel_rect, max(24, int(32 * self.ui.s)))
        self.hint_button.label = "Thinking..." if self.hint_loading else "Hint"
        self.hint_button.bg = BTN_CREAM if (self.hint_loading or self.locked) else BTN_YELLOW
        self.hint_button.text_color = BLACK
        self.hint_button.draw(
            self.screen,
            self.ui.font_small,
            self.ui.border_w,
            self.ui.s,
            replay_icon_surf=None,
        )

        draw_shadow(self.screen, self.ui.prompt_area, 14, dy=5)
        pygame.draw.rect(self.screen, BTN_CREAM, self.ui.prompt_area, border_radius=14)
        pygame.draw.rect(self.screen, PANEL_BORDER, self.ui.prompt_area, 3, border_radius=14)

        prompt    = self.rounds[self.index]["prompt_text"]
        text_max_w = (
            self.ui.prompt_area.w
            - max(10, int(30 * self.ui.s))
            - self.ui.prompt_replay.w
            - max(6, int(12 * self.ui.s))
        )
        lines = wrap_text(prompt, self.ui.font_prompt, text_max_w)

        y = self.ui.prompt_area.y + max(5, int(25 * self.ui.s))
        for line in lines[:2]:
            t = render_tracked_text(self.ui.font_prompt, line, BLACK, tracking=1)
            self.screen.blit(t, (self.ui.prompt_area.x + max(5, int(15 * self.ui.s)), y))
            y += t.get_height() + max(2, int(8 * self.ui.s))

        pygame.draw.rect(self.screen, BTN_CREAM, self.ui.prompt_replay, border_radius=12)
        pygame.draw.rect(self.screen, PANEL_BORDER, self.ui.prompt_replay, 2, border_radius=12)
        if self.ui.prompt_replay_icon:
            icon_rect = self.ui.prompt_replay_icon.get_rect(
                center=self.ui.prompt_replay.center,
            )
            self.screen.blit(self.ui.prompt_replay_icon, icon_rect)

        draw_shadow(self.screen, self.ui.image_area, 14, dy=5)
        pygame.draw.rect(self.screen, BTN_CREAM, self.ui.image_area, border_radius=14)
        pygame.draw.rect(self.screen, PANEL_BORDER, self.ui.image_area, 3, border_radius=14)

        if self.fit_image:
            img_rect = self.fit_image.get_rect(center=self.ui.image_area.center)
            self.screen.blit(self.fit_image, img_rect)
        else:
            miss = render_tracked_text(self.ui.font_small, "No image", TEXT_DARK, tracking=1)
            self.screen.blit(miss, (self.ui.image_area.x + 20, self.ui.image_area.y + 20))

        for b in self.buttons:
            b.draw(
                self.screen, self.ui.font_btn,
                self.ui.border_w, self.ui.s,
                replay_icon_surf=self.ui.btn_replay_icon,
            )

        self.draw_hint_card()
        self.draw_progress()

    def on_choice(self, label, now_ms):
        self.speak_option(label)
        rd      = self.rounds[self.index]
        correct = rd["correct"]
        self.round_attempt_number += 1

        # Record attempt for DB persistence
        en_key = rd["adj_key"] if rd["qtype"] == "color" else _NUM_EN_MAP.get(rd["count"], str(rd["count"]))
        self.history.append({
            "direction": "en_to_ru",
            "shown":     en_key,
            "correct":   correct,
            "ok":        label == correct,
            "attempt_number": self.round_attempt_number,
        })

        self.locked = True

        for b in self.buttons:
            b.reset()

        clicked_btn = None
        for b in self.buttons:
            if b.label == label:
                clicked_btn = b
                break

        if clicked_btn:
            clicked_btn.set_border(GREEN if label == correct else RED)

        self.pending_feedback_audio = SND_GREAT if label == correct else SND_TRY_AGAIN
        self.feedback_time_ms       = now_ms + WORD_TO_FEEDBACK_DELAY_MS

        if label == correct:
            self.score += 1
            self.advance_time_ms = self.feedback_time_ms + CORRECT_NEXT_DELAY_MS
        else:
            self.round_wrong_answers.append(label)
            self.advance_time_ms = 0

    def update_timers(self, now_ms):
        if self.pending_feedback_audio and now_ms >= self.feedback_time_ms:
            if self.hint_engine.is_speaking():
                delay_ms = 120
                self.feedback_time_ms = now_ms + delay_ms
                if self.advance_time_ms:
                    self.advance_time_ms += delay_ms
                return None
            play_audio(self.pending_feedback_audio)
            self.pending_feedback_audio = None
            if self.advance_time_ms == 0:
                self.locked = False

        if self.advance_time_ms and now_ms >= self.advance_time_ms:
            if self.index + 1 < len(self.rounds):
                self.load_round(self.index + 1)
            else:
                return "finished"
        return None

    def shutdown(self):
        self.hint_engine.stop()

    def run(self):
        while True:
            now_ms = pygame.time.get_ticks()
            self.audio.update()
            self._poll_hint_results()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "quit"

                if event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode(
                        (event.w, event.h), pygame.RESIZABLE,
                    )
                    self.on_resize(event.w, event.h)

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return "menu"
                    if event.key == pygame.K_SPACE:
                        pass

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.hint_button.hit(event.pos):
                        self.request_hint()
                        continue

                    if self.ui.prompt_replay.collidepoint(event.pos):
                        self.speak_question()
                        continue

                    if not self.locked:
                        replayed = False
                        for b in self.buttons:
                            if b.hit_replay(event.pos):
                                self.speak_option(b.label)
                                replayed = True
                                break
                        if replayed:
                            continue
                        for b in self.buttons:
                            if b.hit(event.pos):
                                self.on_choice(b.label, now_ms)
                                break

            result = self.update_timers(now_ms)
            if result == "finished":
                return "finished"

            self.draw()
            pygame.display.flip()
            self.clock.tick(FPS)

# -----------------------------
# FINISH SCREEN
# -----------------------------
def finish_screen(screen, ui, score, total):
    clock    = pygame.time.Clock()
    menu_btn = Button(ui.finish_menu, "Menu", bg=BTN_BLUE, text_color=TEXT_LIGHT)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                ui.rebuild(event.w, event.h)
                menu_btn.rect = ui.finish_menu
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return "menu"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if menu_btn.hit(event.pos):
                    return "menu"

        draw_background(screen, ui.w, ui.h)
        draw_panel(screen, ui.panel_rect, max(24, int(32 * ui.s)))
        draw_ribbon_title(screen, "Game 2", ui.panel_rect, ui.font_menu_title, ui.s)
        t1 = render_tracked_text(ui.font_menu_title, "Ready!", BLACK, tracking=1)
        t2 = render_tracked_text(ui.font_menu_btn, "Score: {}/{}".format(score, total), TEXT_SOFT, tracking=1)
        screen.blit(t1, t1.get_rect(center=(ui.w // 2, int(240 * ui.s))))
        screen.blit(t2, t2.get_rect(center=(ui.w // 2, int(330 * ui.s))))

        menu_btn.draw(screen, ui.font_menu_btn, ui.border_w, ui.s, replay_icon_surf=None)

        pygame.display.flip()
        clock.tick(FPS)

# -----------------------------
# APP
# -----------------------------
def main():
    pygame.init()
    pygame.mixer.init()

    info    = pygame.display.Info()
    start_w = min(info.current_w, 1024)
    start_h = min(info.current_h, 600)

    screen = pygame.display.set_mode((start_w, start_h), pygame.RESIZABLE)
    pygame.display.set_caption("Game 2 (adaptive)")

    ui = UI(start_w, start_h)

    while True:
        action = run_menu(screen, ui)
        if action == "quit":
            break

        if action == "play":
            game = StoryGame(screen, ui)
            res = "quit"
            try:
                res = game.run()
            finally:
                game.shutdown()

            if res == "quit":
                break
            if res == "menu":
                continue
            if res == "finished":
                update_from_level_game(game.history, game_name="game2")
                res2 = finish_screen(game.screen, ui, game.score, len(game.rounds))
                if res2 == "quit":
                    break

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
