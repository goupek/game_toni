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
import sys
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

# Pastel style (match launcher.py palette)
PURPLE   = (156, 137, 184)   # #9C89B8
PINK     = (240, 166, 202)   # #F0A6CA
LIGHT_P  = (239, 195, 230)   # #EFC3E6
CREAM    = (240, 230, 239)   # #F0E6EF
LAVENDER = (184, 190, 221)   # #B8BEDD
TEXT_DARK = (58, 50, 72)
SHADOW_FILL = (190, 185, 174)
BG    = CREAM
WHITE = CREAM
BLACK = TEXT_DARK
GRAY  = LAVENDER
DARK  = PURPLE
BLUE  = PURPLE
GREEN = (129, 199, 132)      # soft green (correct)
RED   = (239, 150, 150)      # soft red (wrong)

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
        self.bg          = bg if bg is not None else LAVENDER
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
        # Soft shadow (pastel)
        shadow_r = self.rect.move(3, 4)
        pygame.draw.rect(screen, SHADOW_FILL, shadow_r, border_radius=14)
        pygame.draw.rect(screen, self.bg, self.rect, border_radius=14)
        pygame.draw.rect(screen, self.border, self.rect, width=border_w, border_radius=14)

        replay_space = int(90 * s) if self.show_replay else 0
        text_area    = self.rect.copy()
        text_area.w -= replay_space

        txt = font.render(self.label, True, self.text_color)
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

        self.font_title      = _best_font(sc(76), bold=True)
        self.font_prompt     = _best_font(sc(54))
        self.font_btn        = _best_font(sc(54))
        self.font_small      = _best_font(sc(30))
        self.font_menu_title = _best_font(sc(90), bold=True)
        self.font_menu_btn   = _best_font(sc(60))

        self.border_w = max(2, sc(6))

        side_margin   = sc(60)
        content_left  = side_margin
        content_right = w - side_margin
        content_w     = content_right - content_left

        v_gap   = sc(24)
        h_gap   = sc(40)
        top_pad = sc(10)

        self.title_area = pygame.Rect(content_left, top_pad, content_w, sc(70))
        self.prompt_area = pygame.Rect(
            content_left,
            self.title_area.bottom + sc(15),
            content_w,
            sc(150),
        )

        rep_size = sc(64)
        rep_pad  = sc(12)
        self.prompt_replay = pygame.Rect(
            self.prompt_area.right - rep_size - rep_pad,
            self.prompt_area.y + rep_pad,
            rep_size, rep_size,
        )

        progress_h           = sc(24)
        progress_bottom_pad  = sc(60)
        self.progress_bar = pygame.Rect(
            content_left,
            h - progress_bottom_pad,
            content_w,
            progress_h,
        )

        top_y    = self.prompt_area.bottom + v_gap
        bottom_y = self.progress_bar.y - v_gap
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
        self.menu_play  = pygame.Rect((w - menu_btn_w) // 2, sc(330), menu_btn_w, menu_btn_h)
        self.menu_exit  = pygame.Rect((w - menu_btn_w) // 2, sc(480), menu_btn_w, menu_btn_h)
        self.finish_menu = pygame.Rect((w - menu_btn_w) // 2, sc(500), menu_btn_w, menu_btn_h)

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
    play_btn = Button(ui.menu_play, "Play", bg=PURPLE, text_color=CREAM)
    exit_btn = Button(ui.menu_exit, "Exit")

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

        screen.fill(BG)
        # Pastel header strip
        header_h = int(140 * ui.s)
        pygame.draw.rect(screen, PINK, (0, 0, ui.w, header_h - 6))
        pygame.draw.rect(screen, LIGHT_P, (0, header_h - 6, ui.w, 6))
        title = ui.font_menu_title.render("Game 2 (adaptive)", True, CREAM)
        screen.blit(title, title.get_rect(center=(ui.w // 2, header_h // 2)))

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

        # NEW: use filtered generator instead of generate_round
        self.rounds = [
            generate_round_filtered(option_count=3, max_count=4)
            for _ in range(ROUNDS_PER_GAME)
        ]

        self.index  = 0
        self.score  = 0

        self.locked               = False
        self.pending_feedback_audio = None
        self.feedback_time_ms     = 0
        self.advance_time_ms      = 0

        self.buttons   = []
        self.fit_image = None
        self.raw_image = None

        self.audio = AudioBank()
        self.load_round(0)

    def load_round(self, idx):
        self.index = idx
        rd = self.rounds[self.index]

        self.locked               = False
        self.pending_feedback_audio = None
        self.feedback_time_ms     = 0
        self.advance_time_ms      = 0

        self.buttons = []
        for rect, label in zip(self.ui.button_rects, rd["options"]):
            self.buttons.append(Button(rect, label, show_replay=True))

        self.rescale_current_image()
        self.audio.play_sequence(question_clips(rd))

    def speak_question(self):
        rd = self.rounds[self.index]
        self.audio.play_sequence(question_clips(rd))

    def speak_option(self, label):
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
        self.rescale_current_image()

    def draw_progress(self):
        total = len(self.rounds)
        bar   = self.ui.progress_bar

        pygame.draw.rect(self.screen, GRAY, bar, border_radius=8)
        fill_w = int(bar.w * ((self.index + 1) / total))
        pygame.draw.rect(self.screen, BLUE, (bar.x, bar.y, fill_w, bar.h), border_radius=8)
        pygame.draw.rect(self.screen, DARK, bar, 2, border_radius=8)

        label = "Progress: {}/{}".format(self.index + 1, total)
        txt   = self.ui.font_small.render(label, True, BLACK)
        self.screen.blit(txt, (bar.x, bar.y - txt.get_height() - 6))

    def draw(self):
        self.screen.fill(BG)

        title = self.ui.font_title.render("Game 2", True, BLACK)
        self.screen.blit(title, (self.ui.title_area.x, self.ui.title_area.y))

        pygame.draw.rect(self.screen, SHADOW_FILL, self.ui.prompt_area.move(3, 4), border_radius=14)
        pygame.draw.rect(self.screen, LAVENDER, self.ui.prompt_area, border_radius=14)
        pygame.draw.rect(self.screen, DARK, self.ui.prompt_area, 3, border_radius=14)

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
            t = self.ui.font_prompt.render(line, True, BLACK)
            self.screen.blit(t, (self.ui.prompt_area.x + max(5, int(15 * self.ui.s)), y))
            y += t.get_height() + max(2, int(8 * self.ui.s))

        pygame.draw.rect(self.screen, WHITE, self.ui.prompt_replay, border_radius=12)
        pygame.draw.rect(self.screen, DARK, self.ui.prompt_replay, 2, border_radius=12)
        if self.ui.prompt_replay_icon:
            icon_rect = self.ui.prompt_replay_icon.get_rect(
                center=self.ui.prompt_replay.center,
            )
            self.screen.blit(self.ui.prompt_replay_icon, icon_rect)

        pygame.draw.rect(self.screen, SHADOW_FILL, self.ui.image_area.move(3, 4), border_radius=14)
        pygame.draw.rect(self.screen, LAVENDER, self.ui.image_area, border_radius=14)
        pygame.draw.rect(self.screen, DARK, self.ui.image_area, 3, border_radius=14)

        if self.fit_image:
            img_rect = self.fit_image.get_rect(center=self.ui.image_area.center)
            self.screen.blit(self.fit_image, img_rect)
        else:
            miss = self.ui.font_small.render("No image", True, RED)
            self.screen.blit(miss, (self.ui.image_area.x + 20, self.ui.image_area.y + 20))

        for b in self.buttons:
            b.draw(
                self.screen, self.ui.font_btn,
                self.ui.border_w, self.ui.s,
                replay_icon_surf=self.ui.btn_replay_icon,
            )

        self.draw_progress()

    def on_choice(self, label, now_ms):
        self.speak_option(label)
        correct = self.rounds[self.index]["correct"]

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
            self.advance_time_ms = 0

    def update_timers(self, now_ms):
        if self.pending_feedback_audio and now_ms >= self.feedback_time_ms:
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

    def run(self):
        while True:
            now_ms = pygame.time.get_ticks()
            self.audio.update()

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
    menu_btn = Button(ui.finish_menu, "Menu")

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

        screen.fill(BG)
        # Pastel header strip
        header_h = int(160 * ui.s)
        pygame.draw.rect(screen, LIGHT_P, (0, 0, ui.w, header_h - 6))
        pygame.draw.rect(screen, LAVENDER, (0, header_h - 6, ui.w, 6))
        t1 = ui.font_menu_title.render("Ready!", True, BLACK)
        t2 = ui.font_menu_btn.render("Score: {}/{}".format(score, total), True, PURPLE)
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
            res  = game.run()

            if res == "quit":
                break
            if res == "menu":
                continue
            if res == "finished":
                res2 = finish_screen(game.screen, ui, game.score, len(game.rounds))
                if res2 == "quit":
                    break

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
