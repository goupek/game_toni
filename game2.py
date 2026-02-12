import os
import sys
import pygame

# -----------------------------
# SETTINGS
# -----------------------------
DESIGN_W, DESIGN_H = 1024, 768   # original design resolution
FPS = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "images")
AUDIO_DIR = os.path.join(BASE_DIR, "audio")

# Colors
BG = (245, 248, 255)
WHITE = (255, 255, 255)
BLACK = (15, 15, 15)
GRAY = (230, 230, 230)
DARK = (90, 90, 90)
BLUE = (70, 130, 240)
GREEN = (40, 190, 90)
RED = (235, 60, 60)

# Timing
WORD_TO_FEEDBACK_DELAY_MS = 1000
CORRECT_NEXT_DELAY_MS = 2000

# Replay icon file (put this in ./images/)
REPLAY_ICON_FILE = "replay.jpg"   # you said you placed replay.jpg in images/

# -----------------------------
# PATH HELPERS
# -----------------------------
def audio_path(filename: str) -> str:
    return os.path.join(AUDIO_DIR, filename)

def image_path(filename: str) -> str:
    return os.path.join(IMG_DIR, filename)

# -----------------------------
# AUDIO (single channel, no overlap)
# -----------------------------
def play_audio(filename: str):
    if not filename:
        return
    path = audio_path(filename)
    if not os.path.exists(path):
        print(f"[WARN] Missing audio: {path}")
        return
    try:
        pygame.mixer.music.stop()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
    except pygame.error as e:
        print(f"[WARN] Could not play audio {path}: {e}")

# -----------------------------
# TEXT WRAP
# -----------------------------
def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    cur = ""
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
# IMAGE LOADING + FIT (NO CROP)
# -----------------------------
def load_image(filename: str):
    path = image_path(filename)
    if not os.path.exists(path):
        print(f"[WARN] Missing image: {path}")
        return None
    img = pygame.image.load(path)
    if filename.lower().endswith(".png"):
        return img.convert_alpha()
    return img.convert()

def scale_fit(surface: pygame.Surface, target_w: int, target_h: int) -> pygame.Surface:
    sw, sh = surface.get_size()
    if sw == 0 or sh == 0:
        return surface
    scale = min(target_w / sw, target_h / sh)
    new_w, new_h = max(1, int(sw * scale)), max(1, int(sh * scale))
    return pygame.transform.smoothscale(surface, (new_w, new_h))

# -----------------------------
# UI BUTTON (with replay icon area)
# -----------------------------
class Button:
    def __init__(self, rect, label, show_replay=False):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.border = DARK
        self.bg = WHITE
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

    def draw(self, screen, font, border_w: int, s: float, replay_icon_surf=None):
        pygame.draw.rect(screen, self.bg, self.rect, border_radius=12)
        pygame.draw.rect(screen, self.border, self.rect, width=border_w, border_radius=12)

        replay_space = int(90 * s) if self.show_replay else 0
        text_area = self.rect.copy()
        text_area.w -= replay_space

        txt = font.render(self.label, True, BLACK)
        screen.blit(txt, txt.get_rect(center=text_area.center))

        if self.show_replay:
            icon_size = int(54 * s)
            icon_pad = int(12 * s)
            self.replay_rect = pygame.Rect(
                self.rect.right - icon_size - icon_pad,
                self.rect.centery - icon_size // 2,
                icon_size,
                icon_size
            )
            pygame.draw.rect(screen, WHITE, self.replay_rect, border_radius=10)
            pygame.draw.rect(screen, DARK, self.replay_rect, 2, border_radius=10)

            if replay_icon_surf:
                # replay_icon_surf is already scaled to the icon size
                icon_rect = replay_icon_surf.get_rect(center=self.replay_rect.center)
                screen.blit(replay_icon_surf, icon_rect)
        else:
            self.replay_rect = None

# -----------------------------
# STORIES
# -----------------------------
STORIES = [
    {
        "prompt_text": "Какого цвета эта кошка?",
        "prompt_audio": "cat_white_audio.mp3",
        "image": "cat_white.png",
        "options": ["черная", "оранжевая", "белая"],
        "correct": "белая",
        "option_audio": {"черная": "black.mp3", "оранжевая": "orange.mp3", "белая": "white.mp3"},
    },
    {
        "prompt_text": "Какого размера эта собака?",
        "prompt_audio": "dog_size_question.mp3",
        "image": "dog_small.jpg",
        "options": ["маленькая", "большая", "средняя"],
        "correct": "маленькая",
        "option_audio": {"маленькая": "small.mp3", "большая": "big.mp3", "средняя": "medium.mp3"},
    },
    {
        "prompt_text": "Сколько собак на картинке?",
        "prompt_audio": "dogs_count_question.mp3",
        "image": "dogs_three.png",
        "options": ["одна", "две", "три"],
        "correct": "три",
        "option_audio": {"одна": "one.mp3", "две": "two.mp3", "три": "three.mp3"},
    },
    {
        "prompt_text": "Какого цвета мяч?",
        "prompt_audio": "ball_color_question.mp3",
        "image": "ball_red.png",
        "options": ["красный", "синий", "зелёный"],
        "correct": "красный",
        "option_audio": {"красный": "red.mp3", "синий": "blue.mp3", "зелёный": "green.mp3"},
    },
    {
        "prompt_text": "Какого цвета эта машина?",
        "prompt_audio": "car_color_question.mp3",
        "image": "car_blue.png",
        "options": ["синяя", "красная", "чёрная"],
        "correct": "синяя",
        "option_audio": {"синяя": "blue_she.mp3", "красная": "red_she.mp3", "чёрная": "black_she.mp3"},
    },
]

SND_GREAT = "great.mp3"
SND_TRY_AGAIN = "try_again.mp3"

# -----------------------------
# SCALING / LAYOUT
# -----------------------------
class UI:
    """
    Stores current window size, scale factor, fonts, layout rects, and scaled replay icons.
    Call ui.rebuild(w, h) on resize.
    """
    def __init__(self, w: int, h: int):
        self.replay_raw = load_image(REPLAY_ICON_FILE)  # load once
        self.prompt_replay_icon = None
        self.btn_replay_icon = None
        self.rebuild(w, h)

    def rebuild(self, w: int, h: int):
        self.w, self.h = w, h

        sx = w / DESIGN_W
        sy = h / DESIGN_H
        self.s = min(sx, sy)

        def sc(v):
            return max(1, int(v * self.s))

        # Fonts
        self.font_title = pygame.font.SysFont(None, sc(76))
        self.font_prompt = pygame.font.SysFont(None, sc(54))
        self.font_btn = pygame.font.SysFont(None, sc(54))
        self.font_small = pygame.font.SysFont(None, sc(30))
        self.font_menu_title = pygame.font.SysFont(None, sc(90))
        self.font_menu_btn = pygame.font.SysFont(None, sc(60))

        # Borders
        self.border_w = max(2, sc(6))

        # Areas
        self.title_area = pygame.Rect(sc(60), sc(10), w - sc(120), sc(70))
        self.prompt_area = pygame.Rect(sc(60), sc(95), w - sc(120), sc(140))

        # Prompt replay button (inside prompt area, top-right)
        rep_size = sc(64)
        pad = sc(12)
        self.prompt_replay = pygame.Rect(
            self.prompt_area.right - rep_size - pad,
            self.prompt_area.y + pad,
            rep_size,
            rep_size
        )

        top_y = sc(260)
        self.image_area = pygame.Rect(sc(80), top_y, sc(520), sc(420))

        # Buttons aligned to the RIGHT edge of the prompt box
        by, bw, bh, gap = top_y, sc(300), sc(110), sc(30)
        right_edge = self.prompt_area.right
        bx = right_edge - bw

        self.button_rects = [
            (bx, by + 0 * (bh + gap), bw, bh),
            (bx, by + 1 * (bh + gap), bw, bh),
            (bx, by + 2 * (bh + gap), bw, bh),
        ]

        # Menu buttons
        btn_w, btn_h = sc(300), sc(120)
        self.menu_play = pygame.Rect((w - btn_w) // 2, sc(330), btn_w, btn_h)
        self.menu_exit = pygame.Rect((w - btn_w) // 2, sc(480), btn_w, btn_h)
        self.finish_menu = pygame.Rect((w - btn_w) // 2, sc(500), btn_w, btn_h)

        # Progress bar
        self.progress_bar = pygame.Rect(sc(60), h - sc(60), w - sc(120), sc(24))

        # Scale replay icons for current UI sizes
        if self.replay_raw:
            # prompt icon size (slightly smaller than prompt button rect)
            ps = max(1, int(self.prompt_replay.w * 0.70))
            self.prompt_replay_icon = scale_fit(self.replay_raw, ps, ps)

            # button icon size matches Button icon_size (54*s)
            bs = max(1, int(54 * self.s * 0.80))
            self.btn_replay_icon = scale_fit(self.replay_raw, bs, bs)
        else:
            self.prompt_replay_icon = None
            self.btn_replay_icon = None

# -----------------------------
# MENU
# -----------------------------
def run_menu(screen, ui: UI):
    clock = pygame.time.Clock()
    play_btn = Button(ui.menu_play, "Play")
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
        title = ui.font_menu_title.render("Game 2", True, BLACK)
        screen.blit(title, title.get_rect(center=(ui.w // 2, int(200 * ui.s))))

        play_btn.draw(screen, ui.font_menu_btn, ui.border_w, ui.s, replay_icon_surf=None)
        exit_btn.draw(screen, ui.font_menu_btn, ui.border_w, ui.s, replay_icon_surf=None)

        pygame.display.flip()
        clock.tick(FPS)

# -----------------------------
# GAME
# -----------------------------
class StoryGame:
    def __init__(self, screen, ui: UI):
        self.screen = screen
        self.ui = ui
        self.clock = pygame.time.Clock()

        self.index = 0
        self.score = 0

        self.locked = False
        self.pending_feedback_audio = None
        self.feedback_time_ms = 0
        self.advance_time_ms = 0

        self.buttons = []
        self.fit_image = None
        self.raw_image = None

        self.option_audio_map = {}
        self.load_round(0)

    def load_round(self, idx):
        self.index = idx
        story = STORIES[self.index]

        self.locked = False
        self.pending_feedback_audio = None
        self.feedback_time_ms = 0
        self.advance_time_ms = 0

        self.buttons = []
        for rect, label in zip(self.ui.button_rects, story["options"]):
            self.buttons.append(Button(rect, label, show_replay=True))

        self.option_audio_map = dict(story.get("option_audio", {}))

        self.raw_image = load_image(story["image"])
        self.rescale_current_image()

        play_audio(story["prompt_audio"])

    def rescale_current_image(self):
        if self.raw_image:
            pad = max(2, int(20 * self.ui.s))
            self.fit_image = scale_fit(self.raw_image, self.ui.image_area.w - pad, self.ui.image_area.h - pad)
        else:
            self.fit_image = None

    def on_resize(self, new_w, new_h):
        self.ui.rebuild(new_w, new_h)

        new_buttons = []
        for rect, old_btn in zip(self.ui.button_rects, self.buttons):
            b = Button(rect, old_btn.label, show_replay=True)
            b.border = old_btn.border
            b.bg = old_btn.bg
            new_buttons.append(b)
        self.buttons = new_buttons

        self.rescale_current_image()

    def draw_progress(self):
        total = len(STORIES)
        bar = self.ui.progress_bar

        pygame.draw.rect(self.screen, GRAY, bar, border_radius=8)
        fill_w = int(bar.w * ((self.index + 1) / total))
        pygame.draw.rect(self.screen, BLUE, (bar.x, bar.y, fill_w, bar.h), border_radius=8)
        pygame.draw.rect(self.screen, DARK, bar, 2, border_radius=8)

        label = f"Progress: {self.index + 1}/{total}"
        txt = self.ui.font_small.render(label, True, BLACK)
        self.screen.blit(txt, (bar.x, bar.y - txt.get_height() - 6))

    def draw(self):
        self.screen.fill(BG)

        title = self.ui.font_title.render("Game 2", True, BLACK)
        self.screen.blit(title, (self.ui.title_area.x, self.ui.title_area.y))

        pygame.draw.rect(self.screen, WHITE, self.ui.prompt_area, border_radius=12)
        pygame.draw.rect(self.screen, DARK, self.ui.prompt_area, 3, border_radius=12)

        prompt = STORIES[self.index]["prompt_text"]

        # keep prompt text from going under replay button
        text_max_w = self.ui.prompt_area.w - max(10, int(30 * self.ui.s)) - self.ui.prompt_replay.w - max(6, int(12 * self.ui.s))
        lines = wrap_text(prompt, self.ui.font_prompt, text_max_w)

        y = self.ui.prompt_area.y + max(5, int(25 * self.ui.s))
        for line in lines[:2]:
            t = self.ui.font_prompt.render(line, True, BLACK)
            self.screen.blit(t, (self.ui.prompt_area.x + max(5, int(15 * self.ui.s)), y))
            y += t.get_height() + max(2, int(8 * self.ui.s))

        # Prompt replay button (image)
        pygame.draw.rect(self.screen, WHITE, self.ui.prompt_replay, border_radius=10)
        pygame.draw.rect(self.screen, DARK, self.ui.prompt_replay, 2, border_radius=10)
        if self.ui.prompt_replay_icon:
            icon_rect = self.ui.prompt_replay_icon.get_rect(center=self.ui.prompt_replay.center)
            self.screen.blit(self.ui.prompt_replay_icon, icon_rect)

        pygame.draw.rect(self.screen, WHITE, self.ui.image_area, border_radius=12)
        pygame.draw.rect(self.screen, DARK, self.ui.image_area, 3, border_radius=12)

        if self.fit_image:
            img_rect = self.fit_image.get_rect(center=self.ui.image_area.center)
            self.screen.blit(self.fit_image, img_rect)
        else:
            miss = self.ui.font_small.render("No image", True, RED)
            self.screen.blit(miss, (self.ui.image_area.x + 20, self.ui.image_area.y + 20))

        for b in self.buttons:
            b.draw(self.screen, self.ui.font_btn, self.ui.border_w, self.ui.s, replay_icon_surf=self.ui.btn_replay_icon)

        self.draw_progress()

    def on_choice(self, label: str, now_ms: int):
        story = STORIES[self.index]
        correct = story["correct"]

        self.locked = True

        for b in self.buttons:
            b.reset()

        clicked_btn = next((b for b in self.buttons if b.label == label), None)
        if clicked_btn:
            clicked_btn.set_border(GREEN if label == correct else RED)

        play_audio(self.option_audio_map.get(label, ""))

        self.pending_feedback_audio = SND_GREAT if label == correct else SND_TRY_AGAIN
        self.feedback_time_ms = now_ms + WORD_TO_FEEDBACK_DELAY_MS

        if label == correct:
            self.score += 1
            self.advance_time_ms = self.feedback_time_ms + CORRECT_NEXT_DELAY_MS
        else:
            self.advance_time_ms = 0

    def update_timers(self, now_ms: int):
        if self.pending_feedback_audio and now_ms >= self.feedback_time_ms:
            play_audio(self.pending_feedback_audio)
            self.pending_feedback_audio = None
            if self.advance_time_ms == 0:
                self.locked = False

        if self.advance_time_ms and now_ms >= self.advance_time_ms:
            if self.index + 1 < len(STORIES):
                self.load_round(self.index + 1)
            else:
                return "finished"
        return None

    def run(self):
        while True:
            now_ms = pygame.time.get_ticks()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "quit"

                if event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                    self.on_resize(event.w, event.h)

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return "menu"
                    if event.key == pygame.K_SPACE:
                        play_audio(STORIES[self.index]["prompt_audio"])

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # replay prompt audio anytime (even if locked)
                    if self.ui.prompt_replay.collidepoint(event.pos):
                        play_audio(STORIES[self.index]["prompt_audio"])
                        continue

                    if not self.locked:
                        # replay icon on answer buttons
                        replayed = False
                        for b in self.buttons:
                            if b.hit_replay(event.pos):
                                play_audio(self.option_audio_map.get(b.label, ""))
                                replayed = True
                                break
                        if replayed:
                            continue

                        # normal answer click
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
def finish_screen(screen, ui: UI, score, total):
    clock = pygame.time.Clock()
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
        t1 = ui.font_menu_title.render("Ready!", True, BLACK)
        t2 = ui.font_menu_btn.render(f"Score: {score}/{total}", True, BLACK)
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

    info = pygame.display.Info()
    start_w = min(info.current_w, 1280)
    start_h = min(info.current_h, 800)

    screen = pygame.display.set_mode((start_w, start_h), pygame.RESIZABLE)
    pygame.display.set_caption("Game 2")

    ui = UI(start_w, start_h)

    while True:
        action = run_menu(screen, ui)
        if action == "quit":
            break

        if action == "play":
            game = StoryGame(screen, ui)
            res = game.run()

            if res == "quit":
                break
            if res == "menu":
                continue
            if res == "finished":
                res2 = finish_screen(game.screen, ui, game.score, len(STORIES))
                if res2 == "quit":
                    break

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
