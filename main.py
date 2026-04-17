import pygame
import subprocess
import sys
import random
import math

from pipeline_mem.llm_tts_hint import HintSession

pygame.init()
pygame.mixer.init()
infoObject = pygame.display.Info()
SCREEN_W, SCREEN_H = infoObject.current_w, infoObject.current_h
screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.FULLSCREEN)

# ----------------------------
# LOAD IMAGES & AUDIO
# ----------------------------
image_paths = [
    "images/1_cat.jpg", "images/2_dog.jpg", "images/3_pig.jpg",
    "images/4_bird.jpg", "images/5_horse.jpg", "images/6_mouse.jpg"
]

audio_paths = [
    "audio/1_cat.wav", "audio/2_dog.wav", "audio/3_pig.wav",
    "audio/4_bird.wav", "audio/5_horse.wav", "audio/6_mouse.wav"
]

# Make images a bit smaller than the grid cells so there's a visible border
IMG_W = int(SCREEN_W * 0.25)
IMG_H = int(SCREEN_H * 0.35)
images = [pygame.transform.scale(pygame.image.load(p), (IMG_W, IMG_H)) for p in image_paths]
sounds = [pygame.mixer.Sound(a) for a in audio_paths]

# Names for animals (order must match image_paths and audio_paths)
animal_names = ["Cat", "Dog", "Pig", "Bird", "Horse", "Mouse"]
ANIMAL_NAMES_RU = {
    "Cat": "кошка",
    "Dog": "собака",
    "Pig": "свинья",
    "Bird": "птица",
    "Horse": "лошадь",
    "Mouse": "мышь",
}

# For now we reuse the same animal sounds as the "Where is the ...?" question audio.
question_sounds = sounds
NUM_ANIMALS = len(images)

# Optional feedback sounds for Play mode
try:
    correct_sound = pygame.mixer.Sound("audio/correct.mp3")
except pygame.error:
    correct_sound = None

try:
    incorrect_sound = pygame.mixer.Sound("audio/incorrect.mp3")
except pygame.error:
    incorrect_sound = None

# ----------------------------
# Launcher Style
# ----------------------------
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
SHADOW = (153, 136, 148)

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

PURPLE = BTN_BLUE_DARK
PINK = RIBBON_FILL
LIGHT_P = RIBBON_LIGHT
CREAM = PANEL_INNER
LAVENDER = BTN_CREAM
CORRECT_HL = BTN_GREEN
WRONG_HL = BTN_RED

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


def draw_shadow(rect, radius, dy=6):
    pygame.draw.rect(screen, SHADOW, rect.move(0, dy), border_radius=radius)


def draw_background():
    for y in range(SCREEN_H):
        t = y / max(1, SCREEN_H - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        pygame.draw.line(screen, (r, g, b), (0, y), (SCREEN_W, y))
    polys = [
        (BG_POLY_1, [(0, SCREEN_H * 0.18), (SCREEN_W * 0.28, 0), (SCREEN_W * 0.5, SCREEN_H * 0.22), (SCREEN_W * 0.2, SCREEN_H * 0.42)]),
        (BG_POLY_2, [(SCREEN_W * 0.66, 0), (SCREEN_W, 0), (SCREEN_W, SCREEN_H * 0.34), (SCREEN_W * 0.8, SCREEN_H * 0.26)]),
        (BG_POLY_3, [(0, SCREEN_H), (SCREEN_W * 0.22, SCREEN_H * 0.7), (SCREEN_W * 0.4, SCREEN_H), (0, SCREEN_H)]),
        (BG_POLY_2, [(SCREEN_W * 0.58, SCREEN_H), (SCREEN_W * 0.78, SCREEN_H * 0.62), (SCREEN_W, SCREEN_H), (SCREEN_W * 0.78, SCREEN_H)]),
    ]
    for color, pts in polys:
        pygame.draw.polygon(screen, color, pts)


def draw_panel(rect, radius=28):
    draw_shadow(rect, radius, dy=8)
    pygame.draw.rect(screen, PANEL_FILL, rect, border_radius=radius)
    pygame.draw.rect(screen, PANEL_BORDER, rect, width=4, border_radius=radius)
    inner = rect.inflate(-10, -10)
    pygame.draw.rect(screen, PANEL_INNER, inner, width=2, border_radius=max(12, radius - 6))


def draw_ribbon_title(text, panel_rect, font):
    ribbon_h = max(56, int(SCREEN_H * 0.085))
    ribbon_w = int(panel_rect.w * 1.08)
    ribbon_x = panel_rect.centerx - ribbon_w // 2
    ribbon_y = panel_rect.y + max(18, int(SCREEN_H * 0.025))
    ribbon = pygame.Rect(ribbon_x, ribbon_y, ribbon_w, ribbon_h)
    tail_w = max(20, int(SCREEN_W * 0.02))
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
    draw_shadow(ribbon, 0, dy=6)
    pygame.draw.rect(screen, RIBBON_FILL, ribbon)
    pygame.draw.rect(screen, RIBBON_LIGHT, pygame.Rect(ribbon.x, ribbon.y, ribbon.w, max(8, ribbon_h // 7)))
    pygame.draw.line(screen, RIBBON_DARK, (ribbon.left, ribbon.bottom - 3), (ribbon.right, ribbon.bottom - 3), 3)
    txt = render_tracked_text(font, text, TEXT_LIGHT, tracking=1)
    screen.blit(txt, txt.get_rect(center=ribbon.center))
    return ribbon

# ----------------------------
# HELPER: draw a button (rounded, soft shadow, pastel)
# ----------------------------
def draw_button(text, x, y, w, h, color, text_color=TEXT_DARK, radius=None):
    if radius is None:
        radius = min(w, h) // 4
    rect = pygame.Rect(x, y, w, h)
    depth = BTN_CREAM_DARK
    if color == BTN_BLUE:
        depth = BTN_BLUE_DARK
    elif color == BTN_GREEN:
        depth = BTN_GREEN_DARK
    elif color == BTN_RED:
        depth = BTN_RED_DARK
    elif color == BTN_YELLOW:
        depth = BTN_YELLOW_DARK
    pygame.draw.rect(screen, depth, rect.move(0, 7), border_radius=radius)
    pygame.draw.rect(screen, color, rect, border_radius=radius)
    pygame.draw.rect(screen, lighten(color, 18), (x + 6, y + 5, w - 12, min(12, h // 3)), border_radius=10)
    pygame.draw.rect(screen, PANEL_BORDER, rect, 2, border_radius=radius)
    font = _best_font(min(w, h) // 2, bold=True)
    label = render_tracked_text(font, text, text_color, tracking=1)
    screen.blit(label, label.get_rect(center=(x + w // 2, y + h // 2)))
    return pygame.Rect(x, y, w, h)


def draw_icon_button(x, y, w, h, color, text_color=TEXT_LIGHT, radius=None):
    rect = draw_button("", x, y, w, h, color, text_color=text_color, radius=radius)
    cx, cy = rect.center
    pygame.draw.polygon(screen, text_color, [
        (cx - 6, cy - 6), (cx - 6, cy + 6), (cx + 2, cy + 6), (cx + 2, cy - 6)
    ])
    pygame.draw.polygon(screen, text_color, [
        (cx + 2, cy - 6), (cx + 11, cy - 11), (cx + 11, cy + 11), (cx + 2, cy + 6)
    ])
    return rect


def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if font.size(candidate)[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_hint_card(body_text, loading):
    if not loading and not body_text:
        return

    title_font = _best_font(int(SCREEN_H * 0.035), bold=True)
    body_font = _best_font(int(SCREEN_H * 0.028))
    card_w = int(SCREEN_W * 0.48)
    card_h = int(SCREEN_H * 0.16)
    card_rect = pygame.Rect(
        (SCREEN_W - card_w) // 2,
        SCREEN_H - card_h - 28,
        card_w,
        card_h,
    )
    pad = max(12, int(SCREEN_W * 0.012))
    title_gap = max(6, int(SCREEN_H * 0.008))

    draw_shadow(card_rect, 18, dy=5)
    pygame.draw.rect(screen, BTN_CREAM, card_rect, border_radius=18)
    pygame.draw.rect(screen, PANEL_BORDER, card_rect, 3, border_radius=18)

    title = render_tracked_text(title_font, "Подсказка", TEXT_DARK, tracking=1)
    screen.blit(title, (card_rect.x + pad, card_rect.y + pad))

    body = "Думаю над подсказкой..." if loading else body_text
    y = card_rect.y + pad + title.get_height() + title_gap
    for line in wrap_text(body, body_font, card_rect.w - pad * 2)[:3]:
        txt = render_tracked_text(body_font, line, TEXT_DARK, tracking=1)
        screen.blit(txt, (card_rect.x + pad, y))
        y += txt.get_height() + 6


def animal_search_zone(target_index):
    row_zone = "верхний ряд" if target_index < 3 else "нижний ряд"
    col = target_index % 3
    if col == 0:
        side_zone = "слева"
    elif col == 2:
        side_zone = "справа"
    else:
        side_zone = "ближе к центру"
    return row_zone, side_zone


def animal_hint_round(target_index):
    row_zone, side_zone = animal_search_zone(target_index)
    target_name = animal_names[target_index]
    target_ru = ANIMAL_NAMES_RU.get(target_name, target_name.lower())
    return {
        "hint_prompt_context": {
            "game_type": "animal_find",
            "target_animal_ru": target_ru,
            "board_layout_ru": "шесть картинок в двух рядах по три",
            "broad_search_zone_ru": row_zone,
            "secondary_search_zone_ru": side_zone,
        },
        "hint_goal_ru": (
            "Подскажи, как искать нужную картинку с животным, не называя само животное "
            "и не указывая точную клетку."
        ),
        "hint_extra_rules_ru": (
            "Не называй животных по названию. Не описывай их внешний вид, звук или привычки. "
            "Можно советовать только порядок поиска и одну широкую область вроде верхнего ряда "
            "или левой стороны."
        ),
        "hint_fallback": "Сначала спокойно проверь все картинки по порядку слева направо.",
        "hint_fallback_retry": (
            f"Проверь сначала {row_zone}, потом просмотри остальные картинки по одной."
        ),
        "forbidden_terms": list(ANIMAL_NAMES_RU.values()),
    }


def generate_grid(w_r, h_r, k=1, l=1, x1=0, y1=0, x2=100, y2=100):
    """
    Generate grid points for the positions of the elements.
    w_r, h_r: width/height ratios (relative to screen)
    k: columns, l: rows
    """
    if x1 < 0 or x2 > 1 or y1 < 0 or y2 > 1 or x1 >= x2 or y1 >= y2:
        raise ValueError("Invalid grid boundaries")

    x1 = max(0, min(1, x1))
    x2 = max(0, min(1, x2))
    y1 = max(0, min(1, y1))
    y2 = max(0, min(1, y2))

    if x2 - x1 < w_r * k or y2 - y1 < h_r * l:
        raise ValueError("Grid cells do not fit in the allocated space")

    matrix = []
    hor_pad = ((x2 - x1) - w_r * k) / (k - 1) if k > 1 else 0
    ver_pad = ((y2 - y1) - h_r * l) / (l - 1) if l > 1 else 0
    for j in range(l):
        for i in range(k):
            matrix.append((int((x1 + i * (hor_pad + w_r)) * SCREEN_W),
                           int((y1 + j * (ver_pad + h_r)) * SCREEN_H)))
    return matrix


def grid_layout_in_rect(area_rect, cols=3, rows=2, gap_ratio=0.06):
    gap_x = int(area_rect.w * gap_ratio)
    gap_y = int(area_rect.h * gap_ratio)
    cell_w = (area_rect.w - gap_x * (cols - 1)) // cols
    cell_h = (area_rect.h - gap_y * (rows - 1)) // rows
    positions = []
    for row in range(rows):
        for col in range(cols):
            x = area_rect.x + col * (cell_w + gap_x)
            y = area_rect.y + row * (cell_h + gap_y)
            positions.append((x, y))
    return cell_w, cell_h, positions


# ----------------------------
# GAME OVER SCREEN (for Play mode)
# ----------------------------
def game_over_screen(score):
    font_big = _best_font(int(SCREEN_H * 0.08), bold=True)
    font_small = _best_font(int(SCREEN_H * 0.05))

    while True:
        draw_background()
        panel = pygame.Rect(int(SCREEN_W * 0.17), int(SCREEN_H * 0.12), int(SCREEN_W * 0.66), int(SCREEN_H * 0.72))
        draw_panel(panel, 30)
        draw_ribbon_title("Animal Game", panel, _best_font(int(SCREEN_H * 0.05), bold=True))

        title = render_tracked_text(font_big, "Game Ended", TEXT_DARK, tracking=1)
        title_y = panel.y + int(panel.h * 0.32)
        screen.blit(title, title.get_rect(center=(panel.centerx, title_y)))

        score_text = render_tracked_text(font_small, f"Your score: {score}", TEXT_SOFT, tracking=1)
        screen.blit(score_text, score_text.get_rect(center=(panel.centerx, title_y + int(SCREEN_H * 0.10))))

        w, h = int(SCREEN_W * 0.18), int(SCREEN_H * 0.10)
        gap = int(SCREEN_W * 0.04)
        btn_y = panel.bottom - int(SCREEN_H * 0.17)
        menu_btn = draw_button("Menu", panel.centerx - gap // 2 - w, btn_y, w, h, BTN_BLUE, TEXT_LIGHT)
        exit_btn = draw_button("Exit", panel.centerx + gap // 2, btn_y, w, h, BTN_CREAM, TEXT_DARK)

        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if menu_btn.collidepoint(event.pos):
                    return  # back to menu_screen
                if exit_btn.collidepoint(event.pos):
                    pygame.quit()
                    sys.exit()



# ----------------------------
# PAGE 1: MAIN MENU
# ----------------------------
def menu_screen():
    while True:
        draw_background()
        panel = pygame.Rect(int(SCREEN_W * 0.22), int(SCREEN_H * 0.07), int(SCREEN_W * 0.56), int(SCREEN_H * 0.84))
        draw_panel(panel, 32)
        draw_ribbon_title("Animal Game", panel, _best_font(int(SCREEN_H * 0.055), bold=True))
        subtitle = render_tracked_text(_best_font(int(SCREEN_H * 0.03), bold=True), "Choose a mode to begin", TEXT_SOFT, tracking=1)
        screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, panel.y + int(SCREEN_H * 0.20))))

        w, h = int(SCREEN_W * 0.24), int(SCREEN_H * 0.12)
        x = panel.centerx - w // 2
        gap = int(SCREEN_H * 0.05)
        total_h = 3 * h + 2 * gap
        start_y = panel.centery - total_h // 2 + int(SCREEN_H * 0.05)
        learn_btn = draw_button("Learn", x, start_y, w, h, BTN_YELLOW, TEXT_DARK)
        play_btn = draw_button("Play", x, start_y + (h + gap), w, h, BTN_BLUE, TEXT_LIGHT)
        exit_btn = draw_button("Exit", x, start_y + 2 * (h + gap), w, h, BTN_CREAM, TEXT_DARK)

        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if learn_btn.collidepoint(event.pos):
                    game_screen()   # Learn mode
                if play_btn.collidepoint(event.pos):
                    play_screen()   # Play/quiz mode
                if exit_btn.collidepoint(event.pos):
                    pygame.quit()
                    sys.exit()


# ----------------------------
# PAGE 2: TALK VIDEO
# ----------------------------
def talk_screen():
    # Plays video, then returns to the menu loop
    subprocess.call([
        "mpv",
        "--fs",
        "--no-osd-bar",
        "--quiet",
        "eyes.mp4",
    ])
    return


# ----------------------------
# PAGE 3: LEARN SCREEN
# ----------------------------
def game_screen():
    """Learn mode.
    Click a box to reveal the animal and hear its sound.
    Once revealed, the image stays on the screen."""
    game_started = False
    visible = [False] * NUM_ANIMALS
    current_animal_label = ""

    running = True
    grid_radius = 20
    while running:
        draw_background()
        panel = pygame.Rect(int(SCREEN_W * 0.05), int(SCREEN_H * 0.06), int(SCREEN_W * 0.90), int(SCREEN_H * 0.88))
        draw_panel(panel, 30)
        draw_ribbon_title("Animal Learn", panel, _best_font(int(SCREEN_H * 0.05), bold=True))
        play_area = pygame.Rect(panel.x + 30, panel.y + 130, panel.w - 60, panel.h - 170)
        pygame.draw.rect(screen, PANEL_INNER, play_area, border_radius=22)
        pygame.draw.rect(screen, PANEL_BORDER, play_area, 2, border_radius=22)

        w_toolbar, h_toolbar = int(SCREEN_W * 0.15), int(SCREEN_H * 0.085)
        btn_y = play_area.y + 20
        menu_btn = draw_button("Back", play_area.x + 20, btn_y, w_toolbar, h_toolbar, BTN_CREAM, TEXT_DARK)
        label_rect = pygame.Rect(play_area.centerx - w_toolbar // 2, btn_y, w_toolbar, h_toolbar)
        draw_shadow(label_rect, 14, dy=5)
        pygame.draw.rect(screen, BTN_CREAM, label_rect, border_radius=14)
        pygame.draw.rect(screen, PANEL_BORDER, label_rect, 2, border_radius=14)
        label_text = current_animal_label or "Animal"
        label = render_tracked_text(_best_font(int(h_toolbar * 0.42), bold=True), label_text, TEXT_DARK, tracking=1)
        screen.blit(label, label.get_rect(center=label_rect.center))
        start_btn = draw_button("Start", play_area.right - w_toolbar - 20, btn_y, w_toolbar, h_toolbar, BTN_YELLOW, TEXT_DARK)

        grid_area = pygame.Rect(play_area.x + 24, play_area.y + 120, play_area.w - 48, play_area.h - 150)
        w, h, grid_positions = grid_layout_in_rect(grid_area, cols=3, rows=2, gap_ratio=0.05)
        grid_rects = [pygame.Rect(x, y, w, h) for (x, y) in grid_positions]

        for i, (x, y) in enumerate(grid_positions):
            rect = grid_rects[i]
            draw_shadow(rect, grid_radius, dy=5)
            pygame.draw.rect(screen, BTN_CREAM, rect, border_radius=grid_radius)
            pygame.draw.rect(screen, PANEL_BORDER, rect, 2, border_radius=grid_radius)
            if game_started and visible[i]:
                img = pygame.transform.smoothscale(images[i], (rect.w, rect.h))
                screen.blit(img, (x, y))

        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.MOUSEBUTTONDOWN:
                # Menu: back to main menu
                if menu_btn.collidepoint(event.pos):
                    return

                # Start: enable clicking boxes
                if start_btn.collidepoint(event.pos):
                    game_started = True
                    current_animal_label = ""
                    continue

                # If learn mode has started, handle clicks on rectangles
                if game_started:
                    for i, rect in enumerate(grid_rects):
                        if rect.collidepoint(event.pos):
                            visible[i] = True  # keep this image on screen
                            current_animal_label = ANIMAL_NAMES_RU.get(animal_names[i], animal_names[i]).capitalize()
                            pygame.mixer.stop()
                            sounds[i].play()
                            break


# ----------------------------
# PAGE 4: PLAY (QUIZ) SCREEN
# ----------------------------
def play_screen():
    """Play mode.
    Each animal is asked exactly once.
    Correct -> green highlight and score increases.
    Incorrect -> red highlight on wrong choice, green on correct animal."""
    score = 0
    target_index = None
    game_finished = False

    # For highlighting: per-cell color + end-time
    highlight_until = [0] * NUM_ANIMALS
    highlight_color = [None] * NUM_ANIMALS

    # While feedback is active we ignore clicks
    feedback_active_until = 0
    next_question_time = 0

    # List of remaining animals to ask (indices), so each is used once
    remaining_indices = list(range(NUM_ANIMALS))
    round_attempt_number = 0
    round_wrong_answers = []

    font = _best_font(int(SCREEN_H * 0.05))
    hint_session = HintSession(stop_audio=lambda: pygame.mixer.stop())
    hint_session.invalidate()

    def clear_highlights():
        for i in range(NUM_ANIMALS):
            highlight_until[i] = 0
            highlight_color[i] = None

    def ask_new_question():
        nonlocal target_index, remaining_indices, round_attempt_number, round_wrong_answers
        clear_highlights()
        if not remaining_indices:
            return False  # no more animals to ask
        target_index = random.choice(remaining_indices)
        remaining_indices.remove(target_index)
        round_attempt_number = 0
        round_wrong_answers = []
        hint_session.invalidate()

        # Play the "Where is the ...?" question sound.
        if question_sounds and not hint_session.is_speaking():
            qs = question_sounds[target_index]
            pygame.mixer.stop()
            qs.play()
        return True

    # Ask the first question; if none, immediately finish
    if not ask_new_question():
        game_finished = True

    running = not game_finished
    try:
        while running:
            now = pygame.time.get_ticks()
            hint_session.poll()

            # After feedback, move on to the next question
            if next_question_time and now >= next_question_time:
                next_question_time = 0
                feedback_active_until = 0
                if not ask_new_question():
                    # no more animals -> end game
                    game_finished = True
                    break

            draw_background()
            panel = pygame.Rect(int(SCREEN_W * 0.05), int(SCREEN_H * 0.06), int(SCREEN_W * 0.90), int(SCREEN_H * 0.88))
            draw_panel(panel, 30)
            draw_ribbon_title("Animal Play", panel, _best_font(int(SCREEN_H * 0.05), bold=True))
            play_area = pygame.Rect(panel.x + 30, panel.y + 130, panel.w - 60, panel.h - 170)
            pygame.draw.rect(screen, PANEL_INNER, play_area, border_radius=22)
            pygame.draw.rect(screen, PANEL_BORDER, play_area, 2, border_radius=22)

            w_toolbar, h_toolbar = int(SCREEN_W * 0.14), int(SCREEN_H * 0.085)
            btn_y = play_area.y + 20
            menu_btn = draw_button("Back", play_area.x + 20, btn_y, w_toolbar, h_toolbar, BTN_CREAM, TEXT_DARK)
            mid_rect = pygame.Rect(play_area.centerx - w_toolbar // 2, btn_y, w_toolbar, h_toolbar)
            draw_shadow(mid_rect, 14, dy=5)
            pygame.draw.rect(screen, BTN_CREAM, mid_rect, border_radius=14)
            pygame.draw.rect(screen, PANEL_BORDER, mid_rect, 2, border_radius=14)
            animal_label = "Animal"
            if target_index is not None:
                animal_label = ANIMAL_NAMES_RU.get(animal_names[target_index], animal_names[target_index]).capitalize()
            label_font = _best_font(int(h_toolbar * 0.42), bold=True)
            label = render_tracked_text(label_font, animal_label, TEXT_DARK, tracking=1)
            screen.blit(label, label.get_rect(center=mid_rect.center))

            hint_label = "Thinking..." if hint_session.hint_loading else "Hint"
            icon_btn_w = int(h_toolbar * 1.05)
            hint_btn = draw_button(hint_label, play_area.right - w_toolbar - icon_btn_w - 32, btn_y, w_toolbar, h_toolbar, BTN_YELLOW, TEXT_DARK)
            start_btn = draw_icon_button(play_area.right - icon_btn_w - 20, btn_y, icon_btn_w, h_toolbar, BTN_BLUE, TEXT_LIGHT)

            grid_area = pygame.Rect(play_area.x + 24, play_area.y + 120, play_area.w - 48, play_area.h - 160)
            w, h, grid_positions = grid_layout_in_rect(grid_area, cols=3, rows=2, gap_ratio=0.05)
            grid_rects = [pygame.Rect(x, y, w, h) for (x, y) in grid_positions]

            grid_radius = 20
            for i, (x, y) in enumerate(grid_positions):
                rect = grid_rects[i]
                draw_shadow(rect, grid_radius, dy=5)
                pygame.draw.rect(screen, BTN_CREAM, rect, border_radius=grid_radius)
                img = pygame.transform.smoothscale(images[i], (rect.w, rect.h))
                screen.blit(img, (x, y))
                if highlight_color[i] is not None and now < highlight_until[i]:
                    color = highlight_color[i]
                    width = 7
                else:
                    color = PANEL_BORDER
                    width = 2
                pygame.draw.rect(screen, color, rect, width, border_radius=grid_radius)

            draw_hint_card(hint_session.hint_text, hint_session.hint_loading)

            pygame.display.update()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

                if event.type == pygame.MOUSEBUTTONDOWN:
                    # Menu: back to main menu
                    if menu_btn.collidepoint(event.pos):
                        return

                    if start_btn.collidepoint(event.pos):
                        if target_index is not None and question_sounds and not hint_session.is_speaking():
                            qs = question_sounds[target_index]
                            pygame.mixer.stop()
                            qs.play()
                        continue

                    if hint_btn.collidepoint(event.pos):
                        if target_index is not None and now >= feedback_active_until:
                            hint_session.request_hint(
                                animal_hint_round(target_index),
                                attempt_number=round_attempt_number,
                                wrong_answers=round_wrong_answers,
                            )
                        continue

                    # Ignore clicks while feedback is active
                    if now < feedback_active_until:
                        continue

                    # Check which animal was clicked
                    for i, rect in enumerate(grid_rects):
                        if rect.collidepoint(event.pos) and target_index is not None:
                            pygame.mixer.stop()
                            round_attempt_number += 1

                            # Default highlight duration
                            if correct_sound is not None or incorrect_sound is not None:
                                # approximate with the longer of the two if available
                                base_len = 0
                                if correct_sound is not None:
                                    base_len = max(base_len, correct_sound.get_length())
                                if incorrect_sound is not None:
                                    base_len = max(base_len, incorrect_sound.get_length())
                                feedback_len = int(base_len * 1000) if base_len > 0 else 2000
                            else:
                                feedback_len = 2000  # 2 seconds

                            # Correct answer
                            if i == target_index:
                                if correct_sound is not None:
                                    correct_sound.play()
                                score += 1
                                highlight_color[i] = CORRECT_HL
                                highlight_until[i] = now + feedback_len

                            else:
                                if incorrect_sound is not None:
                                    incorrect_sound.play()
                                round_wrong_answers.append(animal_names[i])
                                hint_session.invalidate()
                                highlight_color[i] = WRONG_HL
                                highlight_until[i] = now + feedback_len
                                highlight_color[target_index] = CORRECT_HL
                                highlight_until[target_index] = now + feedback_len

                            feedback_active_until = now + feedback_len
                            next_question_time = now + feedback_len + 300
                            break
    finally:
        hint_session.shutdown()

    if game_finished:
        game_over_screen(score)




# ----------------------------
# START PROGRAM
# ----------------------------
menu_screen()
