import os
import sys
import pygame

# -----------------------------
# SETTINGS
# -----------------------------
SCREEN_W, SCREEN_H = 1024, 768
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
WORD_TO_FEEDBACK_DELAY_MS = 1000   # wait 1 sec after word audio, then play great/try again
CORRECT_NEXT_DELAY_MS = 2000       # wait 2 sec after GREAT starts before next question

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
    new_w, new_h = int(sw * scale), int(sh * scale)
    return pygame.transform.smoothscale(surface, (new_w, new_h))

# -----------------------------
# UI BUTTON
# -----------------------------
class Button:
    def __init__(self, rect, label):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.border = DARK
        self.bg = WHITE

    def set_border(self, color):
        self.border = color

    def reset(self):
        self.border = DARK

    def draw(self, screen, font):
        pygame.draw.rect(screen, self.bg, self.rect)
        pygame.draw.rect(screen, self.border, self.rect, width=6)
        txt = font.render(self.label, True, BLACK)
        screen.blit(txt, txt.get_rect(center=self.rect.center))

    def hit(self, pos):
        return self.rect.collidepoint(pos)

# -----------------------------
# STORIES (5 QUESTIONS)
# NOTE: You MUST have these files inside /audio and /images
# -----------------------------
STORIES = [
    {
        "prompt_text": "Какого цвета эта кошка?",
        "prompt_audio": "cat_white_audio.mp3",
        "image": "cat_white.png",
        "options": ["черная", "оранжевая", "белая"],
        "correct": "белая",
        "option_audio": {
            "черная": "black.mp3",
            "оранжевая": "orange.mp3",
            "белая": "white.mp3",
        },
    },
    {
        "prompt_text": "Какого размера эта собака?",
        "prompt_audio": "dog_size_question.mp3",
        "image": "dog_small.jpg",
        "options": ["маленькая", "большая", "средняя"],
        "correct": "маленькая",
        "option_audio": {
            "маленькая": "small.mp3",
            "большая": "big.mp3",
            "средняя": "medium.mp3",
        },
    },
    # --- New 3 games ---
    {
        "prompt_text": "Сколько собак на картинке?",
        "prompt_audio": "dogs_count_question.mp3",
        "image": "dogs_three.png",   # put this image into /images
        "options": ["одна", "две", "три"],
        "correct": "три",
        "option_audio": {
            "одна": "one.mp3",
            "две": "two.mp3",
            "три": "three.mp3",
        },
    },
    {
        "prompt_text": "Какого цвета мяч?",
        "prompt_audio": "ball_color_question.mp3",
        "image": "ball_red.png",
        "options": ["красный", "синий", "зелёный"],
        "correct": "красный",
        "option_audio": {
            "красный": "red.mp3",
            "синий": "blue.mp3",
            "зелёный": "green.mp3",
        },
    },
    {
        "prompt_text": "Какого цвета эта машина?",
        "prompt_audio": "car_color_question.mp3",
        "image": "car_blue.png",
        "options": ["синяя", "красная", "чёрная"],
        "correct": "синяя",
        "option_audio": {
            "синяя": "blue.mp3",
            "красная": "red.mp3",
            "чёрная": "black.mp3",
        },
    },
]

SND_GREAT = "great.mp3"
SND_TRY_AGAIN = "try_again.mp3"

# -----------------------------
# MENU
# -----------------------------
def run_menu(screen):
    clock = pygame.time.Clock()
    title_font = pygame.font.SysFont(None, 90)
    btn_font = pygame.font.SysFont(None, 60)

    play_btn = Button((362, 330, 300, 120), "Play")
    exit_btn = Button((362, 480, 300, 120), "Exit")

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if play_btn.hit(event.pos):
                    return "play"
                if exit_btn.hit(event.pos):
                    return "quit"

        screen.fill(BG)
        title = title_font.render("Game 2", True, BLACK)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, 200)))

        play_btn.draw(screen, btn_font)
        exit_btn.draw(screen, btn_font)

        pygame.display.flip()
        clock.tick(FPS)

# -----------------------------
# GAME
# -----------------------------
class StoryGame:
    def __init__(self, screen):
        self.screen = screen
        self.clock = pygame.time.Clock()

        self.font_title = pygame.font.SysFont(None, 76)
        self.font_prompt = pygame.font.SysFont(None, 54)
        self.font_btn = pygame.font.SysFont(None, 54)
        self.font_small = pygame.font.SysFont(None, 30)

        self.title_area = pygame.Rect(60, 10, SCREEN_W - 120, 70)
        self.prompt_area = pygame.Rect(60, 95, SCREEN_W - 120, 140)

        top_y = 260
        self.image_area = pygame.Rect(80, top_y, 520, 420)

        bx, by, bw, bh, gap = 650, top_y, 300, 110, 30
        self.button_rects = [
            (bx, by + 0 * (bh + gap), bw, bh),
            (bx, by + 1 * (bh + gap), bw, bh),
            (bx, by + 2 * (bh + gap), bw, bh),
        ]

        self.index = 0
        self.score = 0

        self.locked = False
        self.pending_feedback_audio = None
        self.feedback_time_ms = 0
        self.advance_time_ms = 0

        self.buttons = []
        self.fit_image = None

        self.load_round(0)

    def load_round(self, idx):
        self.index = idx
        story = STORIES[self.index]

        self.locked = False
        self.pending_feedback_audio = None
        self.feedback_time_ms = 0
        self.advance_time_ms = 0

        self.buttons = []
        for rect, label in zip(self.button_rects, story["options"]):
            self.buttons.append(Button(rect, label))

        raw = load_image(story["image"])
        if raw:
            self.fit_image = scale_fit(raw, self.image_area.w - 20, self.image_area.h - 20)
        else:
            self.fit_image = None

        play_audio(story["prompt_audio"])

    def draw_progress(self):
        total = len(STORIES)
        bar = pygame.Rect(60, SCREEN_H - 60, SCREEN_W - 120, 24)
        pygame.draw.rect(self.screen, GRAY, bar)

        fill_w = int(bar.w * ((self.index + 1) / total))
        pygame.draw.rect(self.screen, BLUE, (bar.x, bar.y, fill_w, bar.h))
        pygame.draw.rect(self.screen, DARK, bar, 2)

        label = f"Progress: {self.index + 1}/{total}"
        txt = self.font_small.render(label, True, BLACK)
        self.screen.blit(txt, (bar.x, bar.y - 28))

    def draw(self):
        self.screen.fill(BG)

        title = self.font_title.render("Game 2", True, BLACK)
        self.screen.blit(title, (self.title_area.x, self.title_area.y))

        pygame.draw.rect(self.screen, WHITE, self.prompt_area)
        pygame.draw.rect(self.screen, DARK, self.prompt_area, 3)

        prompt = STORIES[self.index]["prompt_text"]
        lines = wrap_text(prompt, self.font_prompt, self.prompt_area.w - 30)

        y = self.prompt_area.y + 25
        for line in lines[:2]:
            t = self.font_prompt.render(line, True, BLACK)
            self.screen.blit(t, (self.prompt_area.x + 15, y))
            y += t.get_height() + 8

        pygame.draw.rect(self.screen, WHITE, self.image_area)
        pygame.draw.rect(self.screen, DARK, self.image_area, 3)

        if self.fit_image:
            img_rect = self.fit_image.get_rect(center=self.image_area.center)
            self.screen.blit(self.fit_image, img_rect)
        else:
            miss = self.font_small.render("No image", True, RED)
            self.screen.blit(miss, (self.image_area.x + 20, self.image_area.y + 20))

        for b in self.buttons:
            b.draw(self.screen, self.font_btn)

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

        # play clicked word audio now
        play_audio(story["option_audio"].get(label, ""))

        # schedule feedback in 1 second
        self.pending_feedback_audio = SND_GREAT if label == correct else SND_TRY_AGAIN
        self.feedback_time_ms = now_ms + WORD_TO_FEEDBACK_DELAY_MS

        # if correct: advance 2 seconds after feedback starts
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

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return "menu"
                    if event.key == pygame.K_SPACE:
                        play_audio(STORIES[self.index]["prompt_audio"])

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if not self.locked:
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
def finish_screen(screen, score, total):
    clock = pygame.time.Clock()
    font_title = pygame.font.SysFont(None, 90)
    font_text = pygame.font.SysFont(None, 60)

    menu_btn = Button((362, 500, 300, 120), "Menu")

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return "menu"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if menu_btn.hit(event.pos):
                    return "menu"

        screen.fill(BG)
        t1 = font_title.render("Ready!", True, BLACK)
        t2 = font_text.render(f"Score: {score}/{total}", True, BLACK)
        screen.blit(t1, t1.get_rect(center=(SCREEN_W // 2, 240)))
        screen.blit(t2, t2.get_rect(center=(SCREEN_W // 2, 330)))

        menu_btn.draw(screen, font_text)

        pygame.display.flip()
        clock.tick(FPS)

# -----------------------------
# APP
# -----------------------------
def main():
    pygame.init()
    pygame.mixer.init()

    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Game 2")

    while True:
        action = run_menu(screen)
        if action == "quit":
            break

        if action == "play":
            game = StoryGame(screen)
            res = game.run()

            if res == "quit":
                break
            if res == "menu":
                continue
            if res == "finished":
                res2 = finish_screen(screen, game.score, len(STORIES))
                if res2 == "quit":
                    break

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
