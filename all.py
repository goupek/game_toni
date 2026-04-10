# all.py  (FINAL)
# Put this file next to folders:
#   ./images/
#   ./audio/
# Optional for Game 1 Talk mode:
#   ./eyes.mp4
#
# Works on macOS with python3 + pygame installed.
# One launcher menu -> pick Game1 / Game2 / Game3 / Exit
# ESC always returns to launcher (or exits sub-screens to launcher).
# UI is resizable: everything is drawn on a 1280x720 virtual canvas and scaled.

import os
import sys
import time
import random
import subprocess
from pathlib import Path

import pygame

BASE_DIR = Path(__file__).resolve().parent


# ============================================================
# Shared helpers
# ============================================================
def abs_path(*parts) -> str:
    return str(BASE_DIR.joinpath(*parts))


def stop_all_audio():
    try:
        pygame.mixer.stop()
    except Exception:
        pass
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass


def set_display(size=(1280, 720), fullscreen=False, resizable=True, caption="Games Launcher"):
    flags = 0
    if fullscreen:
        flags |= pygame.FULLSCREEN
    if resizable:
        flags |= pygame.RESIZABLE
    screen = pygame.display.set_mode(size, flags)
    pygame.display.set_caption(caption)
    return screen


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
        screen.fill((30, 30, 30))
    screen.blit(scaled, offset)
    pygame.display.flip()


def draw_button(surface, text, rect, font, bg=(235, 235, 235), fg=(0, 0, 0), border=(70, 70, 70), border_w=4):
    pygame.draw.rect(surface, bg, rect, border_radius=14)
    pygame.draw.rect(surface, border, rect, width=border_w, border_radius=14)
    label = font.render(text, True, fg)
    surface.blit(label, label.get_rect(center=rect.center))
    return rect


def corner_rect(parent_rect: pygame.Rect, size=42, pad=10) -> pygame.Rect:
    return pygame.Rect(parent_rect.right - size - pad, parent_rect.bottom - size - pad, size, size)


def draw_repeat_icon(surface, rect, font):
    pygame.draw.rect(surface, (240, 240, 240), rect, border_radius=10)
    pygame.draw.rect(surface, (90, 90, 90), rect, width=3, border_radius=10)
    icon = font.render("🔁", True, (0, 0, 0))
    surface.blit(icon, icon.get_rect(center=rect.center))


def wrap_text(text, font, max_width):
    words = str(text).split()
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


# ============================================================
# Launcher Menu
# ============================================================
def launcher_menu(screen):
    V_W, V_H = 1280, 720
    canvas = pygame.Surface((V_W, V_H))
    clock = pygame.time.Clock()

    title_font = pygame.font.SysFont("Arial", 72, bold=True)
    btn_font = pygame.font.SysFont("Arial", 44, bold=True)

    btn_w, btn_h = 460, 95
    gap = 24
    x = (V_W - btn_w) // 2
    y0 = 220

    rect_game1 = pygame.Rect(x, y0 + 0 * (btn_h + gap), btn_w, btn_h)
    rect_game2 = pygame.Rect(x, y0 + 1 * (btn_h + gap), btn_w, btn_h)
    rect_game3 = pygame.Rect(x, y0 + 2 * (btn_h + gap), btn_w, btn_h)
    rect_exit  = pygame.Rect(x, y0 + 3 * (btn_h + gap), btn_w, btn_h)

    while True:
        scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
        mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "exit"
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return "exit"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if rect_game1.collidepoint(mouse_v):
                    return "game1"
                if rect_game2.collidepoint(mouse_v):
                    return "game2"
                if rect_game3.collidepoint(mouse_v):
                    return "game3"
                if rect_exit.collidepoint(mouse_v):
                    return "exit"

        canvas.fill((245, 248, 255))
        title = title_font.render("Choose a Game", True, (15, 15, 15))
        canvas.blit(title, title.get_rect(center=(V_W // 2, 120)))

        draw_button(canvas, "Game 1", rect_game1, btn_font)
        draw_button(canvas, "Game 2", rect_game2, btn_font)
        draw_button(canvas, "Game 3", rect_game3, btn_font)
        draw_button(canvas, "Exit", rect_exit, btn_font, bg=(255, 230, 230), border=(140, 0, 0))

        blit_scaled(screen, canvas, new_size, offset)
        clock.tick(60)


# ============================================================
# GAME 1
# ============================================================
def run_game1(screen):
    stop_all_audio()

    V_W, V_H = 1280, 720
    canvas = pygame.Surface((V_W, V_H))
    clock = pygame.time.Clock()

    # assets
    image_paths = [
        abs_path("images", "1_cat.jpg"), abs_path("images", "2_dog.jpg"), abs_path("images", "3_pig.jpg"),
        abs_path("images", "4_bird.jpg"), abs_path("images", "5_horse.jpg"), abs_path("images", "6_mouse.jpg"),
    ]
    audio_paths = [
        abs_path("audio", "1_cat.wav"), abs_path("audio", "2_dog.wav"), abs_path("audio", "3_pig.wav"),
        abs_path("audio", "4_bird.wav"), abs_path("audio", "5_horse.wav"), abs_path("audio", "6_mouse.wav"),
    ]

    RAW_IMAGES = []
    for p in image_paths:
        try:
            RAW_IMAGES.append(pygame.image.load(p).convert_alpha())
        except Exception:
            RAW_IMAGES.append(None)

    SOUNDS = []
    for a in audio_paths:
        try:
            SOUNDS.append(pygame.mixer.Sound(a))
        except Exception:
            SOUNDS.append(None)

    try:
        correct_sound = pygame.mixer.Sound(abs_path("audio", "correct.mp3"))
    except Exception:
        correct_sound = None
    try:
        incorrect_sound = pygame.mixer.Sound(abs_path("audio", "incorrect.mp3"))
    except Exception:
        incorrect_sound = None

    IMG_W = int(V_W * 0.25)
    IMG_H = int(V_H * 0.35)
    IMAGES = []
    for im in RAW_IMAGES:
        if im is None:
            IMAGES.append(None)
        else:
            IMAGES.append(pygame.transform.smoothscale(im, (IMG_W, IMG_H)))

    question_sounds = SOUNDS

    def generate_grid(w_r, h_r, k=1, l=1, x1=0, y1=0, x2=1, y2=1):
        if x1 < 0 or x2 > 1 or y1 < 0 or y2 > 1 or x1 >= x2 or y1 >= y2:
            raise ValueError("Invalid grid boundaries")
        if x2 - x1 < w_r * k or y2 - y1 < h_r * l:
            raise ValueError("Grid cells do not fit")
        matrix = []
        hor_pad = ((x2 - x1) - w_r * k) / (k - 1) if k > 1 else 0
        ver_pad = ((y2 - y1) - h_r * l) / (l - 1) if l > 1 else 0
        for j in range(l):
            for i in range(k):
                matrix.append((int((x1 + i * (hor_pad + w_r)) * V_W),
                               int((y1 + j * (ver_pad + h_r)) * V_H)))
        return matrix

    def talk_screen():
        try:
            subprocess.call(["mpv", "--fs", "--no-osd-bar", "--quiet", abs_path("eyes.mp4")])
        except Exception:
            pass

    def top_bar_rects():
        btn_w, btn_h = 150, 55
        menu_rect = pygame.Rect(20, 20, btn_w, btn_h)
        exit_rect = pygame.Rect(V_W - 20 - btn_w, 20, btn_w, btn_h)
        return menu_rect, exit_rect

    def game_over_screen(score):
        font_big = pygame.font.SysFont("Arial", 64, bold=True)
        font_small = pygame.font.SysFont("Arial", 42, bold=True)

        w_r, h_r = 0.22, 0.12
        bw, bh = int(V_W * w_r), int(V_H * h_r)
        grid = generate_grid(w_r, h_r, 2, 1, 0.24, 0.68, 0.76, 0.90)
        menu_rect = pygame.Rect(grid[0][0], grid[0][1], bw, bh)
        exit_rect = pygame.Rect(grid[1][0], grid[1][1], bw, bh)

        while True:
            scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
            mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "menu"
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return "menu"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if menu_rect.collidepoint(mouse_v):
                        return "menu"
                    if exit_rect.collidepoint(mouse_v):
                        return "quit"

            canvas.fill((255, 255, 255))
            t1 = font_big.render("Game ended", True, (0, 0, 0))
            canvas.blit(t1, t1.get_rect(center=(V_W // 2, V_H // 3)))

            t2 = font_small.render(f"Your score: {score}", True, (0, 0, 0))
            canvas.blit(t2, t2.get_rect(center=(V_W // 2, V_H // 3 + 110)))

            draw_button(canvas, "Menu", menu_rect, font_small, bg=(230, 245, 255), border=(30, 90, 160))
            draw_button(canvas, "Exit", exit_rect, font_small, bg=(255, 230, 230), border=(140, 0, 0))

            blit_scaled(screen, canvas, new_size, offset)
            clock.tick(60)

    def learn_screen():
        w_r, h_r = 0.25, 0.35
        cw, ch = int(V_W * w_r), int(V_H * h_r)
        grid_positions = generate_grid(w_r, h_r, 3, 2, 0.075, 0.22, 0.925, 0.95)
        grid_rects = [pygame.Rect(x, y, cw, ch) for (x, y) in grid_positions]

        game_started = False
        visible = [False] * len(grid_rects)

        font_btn = pygame.font.SysFont("Arial", 32, bold=True)
        menu_rect, exit_rect = top_bar_rects()
        start_rect = pygame.Rect((V_W - 170) // 2, 20, 170, 55)

        while True:
            scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
            mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "menu"
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return "menu"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if menu_rect.collidepoint(mouse_v):
                        return "menu"
                    if exit_rect.collidepoint(mouse_v):
                        return "quit"
                    if start_rect.collidepoint(mouse_v):
                        game_started = True
                        continue
                    if game_started:
                        for i, rect in enumerate(grid_rects):
                            if rect.collidepoint(mouse_v):
                                visible[i] = True
                                stop_all_audio()
                                if SOUNDS[i] is not None:
                                    SOUNDS[i].play()
                                break

            canvas.fill((255, 255, 255))
            draw_button(canvas, "Menu", menu_rect, font_btn, bg=(230, 245, 255), border=(30, 90, 160))
            draw_button(canvas, "Start", start_rect, font_btn)
            draw_button(canvas, "Exit", exit_rect, font_btn, bg=(255, 230, 230), border=(140, 0, 0))

            for i, rect in enumerate(grid_rects):
                pygame.draw.rect(canvas, (0, 0, 0), rect, 3)
                if game_started and visible[i] and IMAGES[i] is not None:
                    canvas.blit(IMAGES[i], rect.topleft)

            blit_scaled(screen, canvas, new_size, offset)
            clock.tick(60)

    def play_screen():
        w_r, h_r = 0.25, 0.35
        cw, ch = int(V_W * w_r), int(V_H * h_r)
        grid_positions = generate_grid(w_r, h_r, 3, 2, 0.075, 0.22, 0.925, 0.95)
        grid_rects = [pygame.Rect(x, y, cw, ch) for (x, y) in grid_positions]

        score = 0
        target_index = None
        highlight_until = [0] * len(grid_rects)
        highlight_color = [None] * len(grid_rects)
        feedback_active_until = 0
        next_question_time = 0
        remaining_indices = list(range(len(grid_rects)))

        font_btn = pygame.font.SysFont("Arial", 32, bold=True)
        font_info = pygame.font.SysFont("Arial", 34, bold=True)

        menu_rect, exit_rect = top_bar_rects()
        repeat_rect = pygame.Rect((V_W - 210) // 2, 20, 210, 55)

        def clear_highlights():
            for i in range(len(grid_rects)):
                highlight_until[i] = 0
                highlight_color[i] = None

        def ask_new_question():
            nonlocal target_index, remaining_indices
            clear_highlights()
            if not remaining_indices:
                return False
            target_index = random.choice(remaining_indices)
            remaining_indices.remove(target_index)
            stop_all_audio()
            snd = question_sounds[target_index]
            if snd is not None:
                snd.play()
            return True

        if not ask_new_question():
            return game_over_screen(score)

        while True:
            scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
            mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)
            now = pygame.time.get_ticks()

            if next_question_time and now >= next_question_time:
                next_question_time = 0
                feedback_active_until = 0
                if not ask_new_question():
                    return game_over_screen(score)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "menu"
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return "menu"
                    if event.key == pygame.K_SPACE:
                        if target_index is not None:
                            stop_all_audio()
                            snd = question_sounds[target_index]
                            if snd is not None:
                                snd.play()
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if menu_rect.collidepoint(mouse_v):
                        return "menu"
                    if exit_rect.collidepoint(mouse_v):
                        return "quit"
                    if repeat_rect.collidepoint(mouse_v):
                        if target_index is not None:
                            stop_all_audio()
                            snd = question_sounds[target_index]
                            if snd is not None:
                                snd.play()
                        continue

                    if now < feedback_active_until:
                        continue

                    for i, rect in enumerate(grid_rects):
                        if rect.collidepoint(mouse_v) and target_index is not None:
                            stop_all_audio()

                            base_len = 0
                            if correct_sound is not None:
                                base_len = max(base_len, correct_sound.get_length())
                            if incorrect_sound is not None:
                                base_len = max(base_len, incorrect_sound.get_length())
                            feedback_len = int(base_len * 1000) if base_len > 0 else 2000

                            if i == target_index:
                                if correct_sound is not None:
                                    correct_sound.play()
                                score += 1
                                highlight_color[i] = (0, 255, 0)
                                highlight_until[i] = now + feedback_len
                            else:
                                if incorrect_sound is not None:
                                    incorrect_sound.play()
                                highlight_color[i] = (255, 0, 0)
                                highlight_until[i] = now + feedback_len
                                highlight_color[target_index] = (0, 255, 0)
                                highlight_until[target_index] = now + feedback_len

                            feedback_active_until = now + feedback_len
                            next_question_time = now + feedback_len + 300
                            break

            canvas.fill((255, 255, 255))
            draw_button(canvas, "Menu", menu_rect, font_btn, bg=(230, 245, 255), border=(30, 90, 160))
            draw_button(canvas, "Repeat", repeat_rect, font_btn)
            draw_button(canvas, "Exit", exit_rect, font_btn, bg=(255, 230, 230), border=(140, 0, 0))

            for i, rect in enumerate(grid_rects):
                if IMAGES[i] is not None:
                    canvas.blit(IMAGES[i], rect.topleft)
                if highlight_color[i] is not None and now < highlight_until[i]:
                    color = highlight_color[i]
                    width = 7
                else:
                    color = (0, 0, 0)
                    width = 3
                pygame.draw.rect(canvas, color, rect, width)

            stext = font_info.render(f"Score: {score}", True, (0, 0, 0))
            canvas.blit(stext, (V_W - stext.get_width() - 20, V_H - stext.get_height() - 20))

            blit_scaled(screen, canvas, new_size, offset)
            clock.tick(60)

    # Game1 main menu
    font_title = pygame.font.SysFont("Arial", 64, bold=True)
    font_btn = pygame.font.SysFont("Arial", 44, bold=True)

    btn_w, btn_h = 420, 95
    x = (V_W - btn_w) // 2
    y0 = 200
    gap = 22

    talk_rect = pygame.Rect(x, y0 + 0 * (btn_h + gap), btn_w, btn_h)
    learn_rect = pygame.Rect(x, y0 + 1 * (btn_h + gap), btn_w, btn_h)
    play_rect = pygame.Rect(x, y0 + 2 * (btn_h + gap), btn_w, btn_h)
    menu_rect = pygame.Rect(x, y0 + 3 * (btn_h + gap), btn_w, btn_h)

    while True:
        scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
        mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "menu"
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return "menu"
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if talk_rect.collidepoint(mouse_v):
                    talk_screen()
                elif learn_rect.collidepoint(mouse_v):
                    res = learn_screen()
                    if res == "quit":
                        return "quit"
                elif play_rect.collidepoint(mouse_v):
                    res = play_screen()
                    if res == "quit":
                        return "quit"
                elif menu_rect.collidepoint(mouse_v):
                    return "menu"

        canvas.fill((245, 248, 255))
        t = font_title.render("Game 1", True, (0, 0, 0))
        canvas.blit(t, t.get_rect(center=(V_W // 2, 120)))

        draw_button(canvas, "Talk", talk_rect, font_btn)
        draw_button(canvas, "Learn", learn_rect, font_btn)
        draw_button(canvas, "Play", play_rect, font_btn)
        draw_button(canvas, "Menu", menu_rect, font_btn, bg=(230, 245, 255), border=(30, 90, 160))

        blit_scaled(screen, canvas, new_size, offset)
        clock.tick(60)


# ============================================================
# GAME 2  (FIXED, ALWAYS-ON 🔁 IN EACH ANSWER + QUESTION BOX)
# ============================================================
def run_game2(screen):
    stop_all_audio()

    V_W, V_H = 1280, 720
    canvas = pygame.Surface((V_W, V_H))
    clock = pygame.time.Clock()
    FPS = 60

    IMG_DIR = BASE_DIR / "images"
    AUDIO_DIR = BASE_DIR / "audio"

    BG = (245, 248, 255)
    WHITE = (255, 255, 255)
    BLACK = (15, 15, 15)
    GRAY = (230, 230, 230)
    DARK = (90, 90, 90)
    BLUE = (70, 130, 240)
    GREEN = (40, 190, 90)
    RED = (235, 60, 60)

    WORD_TO_FEEDBACK_DELAY_MS = 1000
    CORRECT_NEXT_DELAY_MS = 2000

    font_title = pygame.font.SysFont("Arial", 56, bold=True)
    font_prompt = pygame.font.SysFont("Arial", 40, bold=True)
    font_btn = pygame.font.SysFont("Arial", 34, bold=True)
    font_small = pygame.font.SysFont("Arial", 24, bold=True)

    def audio_path(filename: str) -> str:
        return str(AUDIO_DIR / filename)

    def image_path(filename: str) -> str:
        return str(IMG_DIR / filename)

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
        sc = min(target_w / sw, target_h / sh)
        return pygame.transform.smoothscale(surface, (int(sw * sc), int(sh * sc)))

    class Btn:
        def __init__(self, rect, label):
            self.rect = pygame.Rect(rect)
            self.label = label
            self.bg = (235, 235, 235)
            self.border = (70, 70, 70)
            self.border_w = 4

        def draw(self, surf, font, bg=None, border=None, fg=(0, 0, 0)):
            b = bg if bg is not None else self.bg
            br = border if border is not None else self.border
            pygame.draw.rect(surf, b, self.rect, border_radius=14)
            pygame.draw.rect(surf, br, self.rect, width=self.border_w, border_radius=14)
            txt = font.render(self.label, True, fg)
            surf.blit(txt, txt.get_rect(center=self.rect.center))

        def hit(self, pos):
            return self.rect.collidepoint(pos)

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

    # --- Game 2 menu
    menu_btn_w, menu_btn_h = 420, 90
    menu_x = (V_W - menu_btn_w) // 2
    menu_y0 = 240
    gap = 26
    m_play = Btn((menu_x, menu_y0 + 0 * (menu_btn_h + gap), menu_btn_w, menu_btn_h), "Play")
    m_menu = Btn((menu_x, menu_y0 + 1 * (menu_btn_h + gap), menu_btn_w, menu_btn_h), "Menu")
    m_exit = Btn((menu_x, menu_y0 + 2 * (menu_btn_h + gap), menu_btn_w, menu_btn_h), "Exit")

    def run_menu():
        while True:
            scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
            mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "menu"
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return "menu"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if m_play.hit(mouse_v):
                        return "play"
                    if m_menu.hit(mouse_v):
                        return "menu"
                    if m_exit.hit(mouse_v):
                        return "quit"

            canvas.fill(BG)
            title = font_title.render("Game 2", True, BLACK)
            canvas.blit(title, title.get_rect(center=(V_W // 2, 150)))

            m_play.draw(canvas, font_btn)
            m_menu.draw(canvas, font_btn, bg=(230, 245, 255), border=(30, 90, 160))
            m_exit.draw(canvas, font_btn, bg=(255, 230, 230), border=(140, 0, 0))

            blit_scaled(screen, canvas, new_size, offset)
            clock.tick(FPS)

    class StoryGame:
        def __init__(self):
            self.index = 0
            self.score = 0

            self.locked = False
            self.pending_feedback_audio = None
            self.feedback_time_ms = 0
            self.advance_time_ms = 0

            self.last_question_audio = ""
            self.last_answer_audios = {}  # label -> filename (always available)

            # Top bar: only Menu + Exit
            self.btn_menu = Btn((20, 20, 140, 55), "Menu")
            self.btn_exit = Btn((V_W - 160, 20, 140, 55), "Exit")

            # Areas
            self.prompt_area = pygame.Rect(60, 95, V_W - 120, 110)
            self.image_area = pygame.Rect(80, 230, 640, 420)

            bx = 780
            bw, bh, gap2 = 420, 95, 26
            self.option_rects = [
                pygame.Rect(bx, 250 + 0 * (bh + gap2), bw, bh),
                pygame.Rect(bx, 250 + 1 * (bh + gap2), bw, bh),
                pygame.Rect(bx, 250 + 2 * (bh + gap2), bw, bh),
            ]

            # repeats: always-on rects
            self.repeat_q_rect = corner_rect(self.prompt_area, size=42, pad=10)
            self.repeat_a_rects = [corner_rect(r, size=42, pad=10) for r in self.option_rects]

            self.options = []  # dicts: {btn, label, border, repeat_rect}
            self.fit_image = None

            self.load_round(0)

        def load_round(self, idx):
            self.index = idx
            story = STORIES[self.index]

            self.locked = False
            self.pending_feedback_audio = None
            self.feedback_time_ms = 0
            self.advance_time_ms = 0

            self.last_question_audio = story["prompt_audio"]
            self.last_answer_audios = dict(story.get("option_audio", {}))

            self.options = []
            for rect, label, rep_rect in zip(self.option_rects, story["options"], self.repeat_a_rects):
                b = Btn(rect, label)
                self.options.append({"btn": b, "label": label, "border": DARK, "repeat": rep_rect})

            raw = load_image(story["image"])
            self.fit_image = scale_fit(raw, self.image_area.w - 20, self.image_area.h - 20) if raw else None

            play_audio(self.last_question_audio)

        def draw_progress(self):
            total = len(STORIES)
            bar = pygame.Rect(60, V_H - 45, V_W - 120, 18)
            pygame.draw.rect(canvas, GRAY, bar)
            fill_w = int(bar.w * ((self.index + 1) / total))
            pygame.draw.rect(canvas, BLUE, (bar.x, bar.y, fill_w, bar.h))
            pygame.draw.rect(canvas, DARK, bar, 2)
            txt = font_small.render(f"Progress: {self.index + 1}/{total}   Score: {self.score}", True, BLACK)
            canvas.blit(txt, (60, V_H - 75))

        def draw(self):
            canvas.fill(BG)

            title = font_title.render("Game 2", True, BLACK)
            canvas.blit(title, (60, 20))

            self.btn_menu.draw(canvas, font_small, bg=(230, 245, 255), border=(30, 90, 160))
            self.btn_exit.draw(canvas, font_small, bg=(255, 230, 230), border=(140, 0, 0))

            # Prompt box
            pygame.draw.rect(canvas, WHITE, self.prompt_area, border_radius=14)
            pygame.draw.rect(canvas, DARK, self.prompt_area, 3, border_radius=14)

            prompt = STORIES[self.index]["prompt_text"]
            lines = wrap_text(prompt, font_prompt, self.prompt_area.w - 70)
            y = self.prompt_area.y + 18
            for line in lines[:2]:
                t = font_prompt.render(line, True, BLACK)
                canvas.blit(t, (self.prompt_area.x + 15, y))
                y += t.get_height() + 6

            # Repeat Q always in bottom-right of question box
            self.repeat_q_rect = corner_rect(self.prompt_area, size=42, pad=10)
            draw_repeat_icon(canvas, self.repeat_q_rect, font_small)

            # Image box
            pygame.draw.rect(canvas, WHITE, self.image_area, border_radius=14)
            pygame.draw.rect(canvas, DARK, self.image_area, 3, border_radius=14)
            if self.fit_image:
                canvas.blit(self.fit_image, self.fit_image.get_rect(center=self.image_area.center))
            else:
                miss = font_small.render("No image", True, RED)
                canvas.blit(miss, (self.image_area.x + 20, self.image_area.y + 20))

            # Options + repeat on every answer rectangle (always)
            for i, opt in enumerate(self.options):
                opt["btn"].draw(canvas, font_btn, bg=WHITE, border=opt["border"])
                # ensure repeat rect follows the button rect
                opt["repeat"] = corner_rect(opt["btn"].rect, size=42, pad=10)
                draw_repeat_icon(canvas, opt["repeat"], font_small)

            self.draw_progress()

        def on_choice(self, label, now_ms):
            story = STORIES[self.index]
            correct = story["correct"]
            self.locked = True

            for opt in self.options:
                opt["border"] = DARK

            clicked = None
            for opt in self.options:
                if opt["label"] == label:
                    clicked = opt
                    opt["border"] = GREEN if label == correct else RED

            # play clicked word audio now
            play_audio(self.last_answer_audios.get(label, ""))

            # schedule feedback
            self.pending_feedback_audio = SND_GREAT if label == correct else SND_TRY_AGAIN
            self.feedback_time_ms = now_ms + WORD_TO_FEEDBACK_DELAY_MS

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
                if self.index + 1 < len(STORIES):
                    self.load_round(self.index + 1)
                else:
                    return "finished"
            return None

        def run(self):
            while True:
                scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
                mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)
                now_ms = pygame.time.get_ticks()

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return "menu"

                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            return "menu"
                        if event.key == pygame.K_SPACE:
                            play_audio(self.last_question_audio)

                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        if self.btn_menu.hit(mouse_v):
                            return "menu"
                        if self.btn_exit.hit(mouse_v):
                            return "quit"

                        # Repeat question
                        if self.repeat_q_rect.collidepoint(mouse_v):
                            play_audio(self.last_question_audio)
                            continue

                        # Repeat answer from ANY answer box (always)
                        for opt in self.options:
                            if opt["repeat"].collidepoint(mouse_v):
                                play_audio(self.last_answer_audios.get(opt["label"], ""))
                                break
                        else:
                            # choice click
                            if not self.locked:
                                for opt in self.options:
                                    if opt["btn"].hit(mouse_v):
                                        self.on_choice(opt["label"], now_ms)
                                        break

                result = self.update_timers(now_ms)
                if result == "finished":
                    return "finished"

                self.draw()
                blit_scaled(screen, canvas, new_size, offset)
                clock.tick(FPS)

    def finish_screen(score, total):
        btn_back = pygame.Rect(V_W // 2 - 210, 430, 420, 90)
        while True:
            scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
            mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "menu"
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return "menu"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if btn_back.collidepoint(mouse_v):
                        return "menu"

            canvas.fill(BG)
            t1 = font_title.render("Finished!", True, BLACK)
            t2 = font_prompt.render(f"Score: {score}/{total}", True, BLACK)
            canvas.blit(t1, t1.get_rect(center=(V_W // 2, 250)))
            canvas.blit(t2, t2.get_rect(center=(V_W // 2, 320)))
            draw_button(canvas, "Menu", btn_back, font_btn, bg=(230, 245, 255), border=(30, 90, 160))

            blit_scaled(screen, canvas, new_size, offset)
            clock.tick(FPS)

    while True:
        action = run_menu()
        if action == "quit":
            return "quit"
        if action == "menu":
            return "menu"
        if action == "play":
            sg = StoryGame()
            res = sg.run()
            if res == "quit":
                return "quit"
            if res == "menu":
                return "menu"
            if res == "finished":
                return finish_screen(sg.score, len(STORIES))


# ============================================================
# GAME 3 (repeat question button always visible in instruction box)
# ============================================================
def run_game3(screen):
    stop_all_audio()

    V_W, V_H = 1280, 720
    canvas = pygame.Surface((V_W, V_H))
    clock = pygame.time.Clock()
    FPS = 60

    HEADER_H = 160
    BTN_H = 50
    BTN_W = 140

    BG_COLOR = (245, 247, 250)
    HEADER_BG = (255, 255, 255)
    TEXT_COLOR = (40, 45, 60)
    MUTED_COLOR = (100, 110, 125)
    GREEN = (46, 204, 113)
    RED = (231, 76, 60)
    BLUE_ACCENT = (52, 152, 219)
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    IMG_DIR = BASE_DIR / "images"
    AUDIO_DIR = BASE_DIR / "audio"

    RUS_DICT = {
        "table": {"acc": "стол",    "gen": "стола",   "ins": "столом"},
        "chair": {"acc": "стул",    "gen": "стула",   "ins": "стулом"},
        "cup":   {"acc": "чашку",   "gen": "чашки",   "ins": "чашкой"},
        "box":   {"acc": "коробку", "gen": "коробки", "ins": "коробкой"},
        "ball":  {"acc": "мяч",     "gen": "мяча",    "ins": "мячом"},
        "book":  {"acc": "книгу",   "gen": "книги",   "ins": "книгой"},
    }

    def get_rus_name(eng_name, case="acc"):
        return RUS_DICT.get(eng_name, {}).get(case, eng_name)

    def draw_text_wrapped(surface, text, font, color, rect):
        lines = wrap_text(text, font, rect.width)
        total_h = len(lines) * font.get_linesize()
        y = rect.y + (rect.height - total_h) // 2
        for line in lines[:3]:
            t = font.render(line, True, color)
            surface.blit(t, (rect.x + 10, y))
            y += font.get_linesize()

    class Button:
        def __init__(self, rect, label, bg=(255, 255, 255), fg=TEXT_COLOR):
            self.rect = pygame.Rect(rect)
            self.label = label
            self.bg = bg
            self.fg = fg
            self.hover = False

        def draw(self, surf, font, border=(200, 200, 200)):
            b = (min(self.bg[0]+10, 255), min(self.bg[1]+10, 255), min(self.bg[2]+10, 255)) if self.hover else self.bg
            pygame.draw.rect(surf, b, self.rect, border_radius=12)
            pygame.draw.rect(surf, border, self.rect, 2, border_radius=12)
            t = font.render(self.label, True, self.fg)
            surf.blit(t, t.get_rect(center=self.rect.center))

        def hit(self, pos):
            return self.rect.collidepoint(pos)

        def set_hover(self, pos):
            self.hover = self.rect.collidepoint(pos)

    # cache
    _img_cache = {}
    _snd_cache = {}

    def load_image(name, size):
        key = (name, size)
        if key in _img_cache:
            return _img_cache[key]
        p_png = IMG_DIR / f"{name}.png"
        p_jpg = IMG_DIR / f"{name}.jpg"
        path = p_png if p_png.exists() else (p_jpg if p_jpg.exists() else None)
        if not path:
            return None
        try:
            img = pygame.image.load(str(path)).convert_alpha()
            img = pygame.transform.smoothscale(img, size)
            _img_cache[key] = img
            return img
        except Exception:
            return None

    def load_sound(filename):
        path = AUDIO_DIR / filename
        if not path.exists():
            return None
        sp = str(path)
        if sp in _snd_cache:
            return _snd_cache[sp]
        try:
            s = pygame.mixer.Sound(sp)
            _snd_cache[sp] = s
            return s
        except Exception:
            return None

    class Item:
        def __init__(self, name, rect, fallback):
            self.name = name
            self.rect = pygame.Rect(rect)
            self.start = self.rect.copy()
            self.fallback = fallback
            self.image = load_image(name, (self.rect.w, self.rect.h))
            self.off = (0, 0)

        def reset(self):
            self.rect = self.start.copy()

        def draw(self, surf):
            if self.image:
                surf.blit(self.image, self.rect.topleft)
            else:
                pygame.draw.rect(surf, self.fallback, self.rect)
            pygame.draw.rect(surf, BLACK, self.rect, 2)

        def start_drag(self, pos):
            if self.rect.collidepoint(pos):
                self.off = (pos[0] - self.rect.x, pos[1] - self.rect.y)
                return True
            return False

        def drag(self, pos):
            self.rect.x = int(pos[0] - self.off[0])
            self.rect.y = int(pos[1] - self.off[1])
            self.rect.x = max(0, min(self.rect.x, V_W - self.rect.w))
            self.rect.y = max(HEADER_H, min(self.rect.y, V_H - self.rect.h))

    def x_overlap(a, b):
        inter = max(0, min(a.rect.right, b.rect.right) - max(a.rect.left, b.rect.left))
        denom = max(1, min(a.rect.w, b.rect.w))
        return inter / denom

    def inter_area(a, b):
        x1 = max(a.rect.left, b.rect.left)
        y1 = max(a.rect.top, b.rect.top)
        x2 = min(a.rect.right, b.rect.right)
        y2 = min(a.rect.bottom, b.rect.bottom)
        if x2 <= x1 or y2 <= y1:
            return 0
        return (x2 - x1) * (y2 - y1)

    def rel_on(a, b):
        return a.rect.centery < b.rect.centery and x_overlap(a, b) >= 0.25

    def rel_under(a, b):
        return a.rect.centery > b.rect.centery and x_overlap(a, b) >= 0.25

    def rel_left_of(a, b):
        return a.rect.centerx < b.rect.centerx

    def rel_right_of(a, b):
        return a.rect.centerx > b.rect.centerx

    def rel_inside(a, b):
        if not b.rect.collidepoint(a.rect.center):
            return False
        ia = inter_area(a, b)
        aa = max(1, a.rect.w * a.rect.h)
        return (ia / aa) >= 0.60

    def rel_between(a, b1, b2):
        lo = min(b1.rect.centerx, b2.rect.centerx)
        hi = max(b1.rect.centerx, b2.rect.centerx)
        return lo <= a.rect.centerx <= hi

    def instr_text(cons):
        phrases = []
        for c in cons:
            t = c["type"]
            a = get_rus_name(c["a"], "acc")
            if t == "between":
                phrases.append(f"{a} между {get_rus_name(c['b'][0], 'ins')} и {get_rus_name(c['b'][1], 'ins')}")
            elif t == "left_of":
                phrases.append(f"{a} слева от {get_rus_name(c['b'], 'gen')}")
            elif t == "right_of":
                phrases.append(f"{a} справа от {get_rus_name(c['b'], 'gen')}")
            elif t == "on":
                phrases.append(f"{a} на {get_rus_name(c['b'], 'acc')}")
            elif t == "under":
                phrases.append(f"{a} под {get_rus_name(c['b'], 'acc')}")
            elif t == "inside":
                phrases.append(f"{a} в {get_rus_name(c['b'], 'acc')}")
        if len(phrases) == 1:
            return "Поместите " + phrases[0] + "."
        if len(phrases) == 2:
            return "Поместите " + phrases[0] + " и " + phrases[1] + "."
        return "Поместите " + ", ".join(phrases[:-1]) + " и " + phrases[-1] + "."

    SCENARIOS = [
        {"items": ["table", "chair", "cup"], "constraints": [{"type": "on", "a": "cup", "b": "table"}, {"type": "right_of", "a": "chair", "b": "table"}]},
        {"items": ["table", "cup", "ball"], "constraints": [{"type": "under", "a": "ball", "b": "table"}, {"type": "left_of", "a": "cup", "b": "table"}]},
        {"items": ["chair", "book", "cup"], "constraints": [{"type": "on", "a": "book", "b": "chair"}, {"type": "right_of", "a": "cup", "b": "chair"}]},
        {"items": ["box", "ball", "cup"], "constraints": [{"type": "inside", "a": "ball", "b": "box"}, {"type": "inside", "a": "cup", "b": "box"}]},
        {"items": ["table", "chair", "book", "cup"], "constraints": [{"type": "left_of", "a": "chair", "b": "table"}, {"type": "under", "a": "book", "b": "chair"}, {"type": "on", "a": "cup", "b": "table"}]},
        {"items": ["table", "chair", "ball"], "constraints": [{"type": "between", "a": "ball", "b": ["chair", "table"]}]},
        {"items": ["table", "chair", "box", "ball", "cup"], "constraints": [{"type": "on", "a": "cup", "b": "table"}, {"type": "on", "a": "ball", "b": "chair"}, {"type": "right_of", "a": "box", "b": "chair"}]},
    ]

    sizes = {"table": (280, 130), "chair": (150, 170), "cup": (80, 80), "box": (190, 150), "ball": (80, 80), "book": (130, 80)}
    colors = {"table": (222, 200, 150), "chair": (190, 210, 235), "cup": (240, 220, 235), "box": (215, 235, 210), "ball": (250, 210, 170), "book": (210, 220, 250)}

    def make_items(names):
        out = {}
        for n in names:
            w, h = sizes[n]
            x = random.randint(60, V_W - w - 60)
            y = random.randint(HEADER_H + 60, V_H - h - 60)
            out[n] = Item(n, (x, y, w, h), colors.get(n, (200, 200, 200)))
        return out

    font_xl = pygame.font.SysFont("Arial", 42, bold=True)
    font_lg = pygame.font.SysFont("Arial", 32, bold=True)
    font_md = pygame.font.SysFont("Arial", 24, bold=True)
    font_sm = pygame.font.SysFont("Arial", 20, bold=True)

    btn_menu = Button((20, 30, 120, 50), "Menu", bg=WHITE)
    btn_check = Button((V_W - (3 * (BTN_W + 10)) - 20, 30, BTN_W, BTN_H), "Check", bg=WHITE)
    btn_reset = Button((V_W - (2 * (BTN_W + 10)) - 20, 30, BTN_W, BTN_H), "Reset", bg=WHITE)
    btn_next = Button((V_W - (1 * (BTN_W + 10)) - 20, 30, BTN_W, BTN_H), "Next", bg=BLUE_ACCENT, fg=WHITE)

    instr_box = pygame.Rect(100, 95, V_W - 200, 60)
    repeat_rect = corner_rect(instr_box, size=50, pad=8)  # ALWAYS on instruction box

    idx = 0
    score = 0
    solved = [False] * len(SCENARIOS)
    game_over = False

    items = make_items(SCENARIOS[idx]["items"])
    constraints = SCENARIOS[idx]["constraints"]
    instr = instr_text(constraints)

    dragging = None
    feedback = ""
    fb_col = MUTED_COLOR
    fb_t = 0

    ch_instr = pygame.mixer.Channel(0)
    ch_fb = pygame.mixer.Channel(1)

    def play_instr(i):
        filenames = [f"{i+1}.wav", f"{i+1:02d}.wav", f"{i+1}.mp3", f"{i+1:02d}.mp3"]
        s = None
        for f in filenames:
            s = load_sound(f)
            if s:
                break
        if s:
            ch_instr.stop()
            ch_instr.play(s)

    def load_level(i):
        nonlocal items, constraints, instr, feedback, game_over
        game_over = False
        items = make_items(SCENARIOS[i]["items"])
        constraints = SCENARIOS[i]["constraints"]
        instr = instr_text(constraints)
        feedback = ""
        play_instr(i)

    play_instr(idx)

    def check_constraints():
        for c in constraints:
            a = items[c["a"]]
            t = c["type"]
            if t == "between":
                b1 = items[c["b"][0]]
                b2 = items[c["b"][1]]
                if not rel_between(a, b1, b2):
                    return False
            else:
                b = items[c["b"]]
                if t == "on" and not rel_on(a, b): return False
                if t == "under" and not rel_under(a, b): return False
                if t == "left_of" and not rel_left_of(a, b): return False
                if t == "right_of" and not rel_right_of(a, b): return False
                if t == "inside" and not rel_inside(a, b): return False
        return True

    while True:
        scale, new_size, offset = compute_scale_and_offset(screen.get_size(), (V_W, V_H))
        mouse_v = map_mouse_to_virtual(pygame.mouse.get_pos(), scale, offset)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "menu"
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "menu"
                if event.key == pygame.K_r and not game_over:
                    play_instr(idx)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if btn_menu.hit(mouse_v):
                    return "menu"

                # repeat is ALWAYS present in bottom-right of instruction box
                if repeat_rect.collidepoint(mouse_v) and not game_over:
                    play_instr(idx)
                    continue

                if not game_over and btn_check.hit(mouse_v):
                    ok = check_constraints()
                    if ok:
                        if not solved[idx]:
                            score += 1
                            solved[idx] = True
                        feedback = "Отлично! Всё верно."
                        fb_col = GREEN
                        s = load_sound("correct.wav") or load_sound("correct.mp3")
                        if s:
                            ch_fb.play(s)
                    else:
                        feedback = "Попробуйте ещё раз."
                        fb_col = RED
                        s = load_sound("incorrect.wav") or load_sound("incorrect.mp3")
                        if s:
                            ch_fb.play(s)
                    fb_t = time.time()

                elif not game_over and btn_reset.hit(mouse_v):
                    for it in items.values():
                        it.reset()
                    feedback = ""

                elif not game_over and btn_next.hit(mouse_v):
                    if idx >= len(SCENARIOS) - 1:
                        game_over = True
                        feedback = ""
                        ch_instr.stop()
                    else:
                        idx += 1
                        load_level(idx)

                else:
                    if not game_over:
                        vals = list(items.values())
                        for i in reversed(range(len(vals))):
                            it = vals[i]
                            if it.start_drag(mouse_v):
                                dragging = it
                                # bring to front
                                items.pop(it.name)
                                items[it.name] = it
                                break

            if event.type == pygame.MOUSEBUTTONUP:
                dragging = None
            if event.type == pygame.MOUSEMOTION and dragging and not game_over:
                dragging.drag(mouse_v)

        if feedback and time.time() - fb_t > 3:
            feedback = ""

        # --- draw
        canvas.fill(BG_COLOR)
        pygame.draw.rect(canvas, HEADER_BG, (0, 0, V_W, HEADER_H))
        pygame.draw.line(canvas, (220, 225, 230), (0, HEADER_H), (V_W, HEADER_H), 2)

        btn_menu.set_hover(mouse_v)
        btn_menu.draw(canvas, font_md)

        # score + level
        s1 = font_lg.render(f"Счёт: {score}/{len(SCENARIOS)}", True, TEXT_COLOR)
        canvas.blit(s1, (160, 45))
        s2 = font_xl.render(f"{idx + 1}/{len(SCENARIOS)}", True, TEXT_COLOR)
        canvas.blit(s2, s2.get_rect(center=(V_W // 2, 60)))

        if not game_over:
            for b in (btn_check, btn_reset, btn_next):
                b.set_hover(mouse_v)
                b.draw(canvas, font_md)

            # instruction box + always repeat button
            pygame.draw.rect(canvas, WHITE, instr_box, border_radius=14)
            pygame.draw.rect(canvas, (200, 200, 200), instr_box, 2, border_radius=14)

            text_rect = instr_box.inflate(-80, 0)
            draw_text_wrapped(canvas, instr, font_lg, MUTED_COLOR, text_rect)

            repeat_rect = corner_rect(instr_box, size=50, pad=8)
            draw_repeat_icon(canvas, repeat_rect, font_sm)

            # items
            for it in items.values():
                it.draw(canvas)

            hint = font_sm.render("Перетащите объекты, следуя инструкции.", True, (160, 170, 180))
            canvas.blit(hint, (V_W - hint.get_width() - 20, V_H - 30))

            if feedback:
                fb = font_xl.render(feedback, True, fb_col)
                r = fb.get_rect(center=(V_W // 2, V_H - 95))
                bg = r.inflate(40, 20)
                pygame.draw.rect(canvas, (255, 255, 255), bg, border_radius=15)
                pygame.draw.rect(canvas, (200, 200, 200), bg, 2, border_radius=15)
                canvas.blit(fb, r.topleft)

        else:
            # final overlay
            overlay = pygame.Surface((V_W, V_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 120))
            canvas.blit(overlay, (0, 0))
            panel = pygame.Rect(V_W // 2 - 360, V_H // 2 - 160, 720, 320)
            pygame.draw.rect(canvas, (255, 255, 255), panel, border_radius=18)
            pygame.draw.rect(canvas, (200, 200, 200), panel, 2, border_radius=18)

            t = font_xl.render("Игра окончена!", True, TEXT_COLOR)
            canvas.blit(t, t.get_rect(center=(V_W // 2, panel.top + 70)))

            sc = font_xl.render(f"Ваш счёт: {score} / {len(SCENARIOS)}", True, BLUE_ACCENT)
            canvas.blit(sc, sc.get_rect(center=(V_W // 2, panel.top + 140)))

            tip = font_md.render("Нажмите ESC чтобы вернуться в меню.", True, MUTED_COLOR)
            canvas.blit(tip, tip.get_rect(center=(V_W // 2, panel.top + 215)))

        blit_scaled(screen, canvas, new_size, offset)
        clock.tick(FPS)


# ============================================================
# MAIN APP LOOP
# ============================================================
def main():
    pygame.init()
    try:
        pygame.mixer.init()
    except Exception:
        pass

    screen = set_display(size=(1280, 720), fullscreen=False, resizable=True, caption="Games Launcher")

    while True:
        choice = launcher_menu(screen)
        if choice == "exit":
            break

        if choice == "game1":
            res = run_game1(screen)
        elif choice == "game2":
            res = run_game2(screen)
        elif choice == "game3":
            res = run_game3(screen)
        else:
            res = "menu"

        stop_all_audio()
        if res == "quit":
            break

    stop_all_audio()
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
