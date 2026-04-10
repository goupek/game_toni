import pygame
import subprocess
import sys
import random

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
# PASTEL STYLE (match launcher.py palette)
# ----------------------------
PURPLE   = (156, 137, 184)   # #9C89B8
PINK     = (240, 166, 202)   # #F0A6CA
LIGHT_P  = (239, 195, 230)   # #EFC3E6
CREAM    = (240, 230, 239)   # #F0E6EF
LAVENDER = (184, 190, 221)   # #B8BEDD
TEXT_DARK = (58, 50, 72)
SHADOW   = (190, 185, 174)
# Feedback colors (pastel, in-palette where possible)
CORRECT_HL = (129, 199, 132)   # soft green
WRONG_HL   = (239, 150, 150)   # soft red (pink-tinted)

def _best_font(size, bold=False):
    for name in ("Nunito", "Baloo 2", "Ubuntu", "Noto Sans", "DejaVu Sans", "Arial", ""):
        try:
            f = pygame.font.SysFont(name, max(14, size), bold=bold)
            if f:
                return f
        except Exception:
            pass
    return pygame.font.Font(None, max(14, size))

# ----------------------------
# HELPER: draw a button (rounded, soft shadow, pastel)
# ----------------------------
def draw_button(text, x, y, w, h, color, text_color=TEXT_DARK, radius=None):
    if radius is None:
        radius = min(w, h) // 4
    # soft shadow
    pygame.draw.rect(screen, SHADOW, (x + 4, y + 4, w, h), border_radius=radius)
    pygame.draw.rect(screen, color, (x, y, w, h), border_radius=radius)
    font = _best_font(min(w, h) // 2)
    label = font.render(text, True, text_color)
    screen.blit(label, label.get_rect(center=(x + w // 2, y + h // 2)))
    return pygame.Rect(x, y, w, h)


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

    pygame.draw.rect(screen, SHADOW, card_rect.move(4, 5), border_radius=18)
    pygame.draw.rect(screen, CREAM, card_rect, border_radius=18)
    pygame.draw.rect(screen, PURPLE, card_rect, 3, border_radius=18)

    title = title_font.render("Подсказка", True, PURPLE)
    screen.blit(title, (card_rect.x + pad, card_rect.y + pad))

    body = "Думаю над подсказкой..." if loading else body_text
    y = card_rect.y + pad + title.get_height() + title_gap
    for line in wrap_text(body, body_font, card_rect.w - pad * 2)[:3]:
        txt = body_font.render(line, True, TEXT_DARK)
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


# ----------------------------
# GAME OVER SCREEN (for Play mode)
# ----------------------------
def game_over_screen(score):
    font_big = _best_font(int(SCREEN_H * 0.08), bold=True)
    font_small = _best_font(int(SCREEN_H * 0.05))

    while True:
        screen.fill(CREAM)
        # Soft header strip
        pygame.draw.rect(screen, LIGHT_P, (0, 0, SCREEN_W, int(SCREEN_H * 0.14)))
        pygame.draw.rect(screen, LAVENDER, (0, int(SCREEN_H * 0.14) - 6, SCREEN_W, 6))

        title = font_big.render("Game ended", True, TEXT_DARK)
        title_x = (SCREEN_W - title.get_width()) // 2
        title_y = SCREEN_H // 3
        screen.blit(title, (title_x, title_y))

        score_text = font_small.render(f"Your score: {score}", True, TEXT_DARK)
        score_x = (SCREEN_W - score_text.get_width()) // 2
        score_y = title_y + title.get_height() + 40
        screen.blit(score_text, (score_x, score_y))

        # Buttons: Menu + Exit (pastel rounded)
        w_r, h_r = 0.20, 0.10
        w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
        grid = generate_grid(w_r, h_r, 2, 1, 0.25, 0.65, 0.75, 0.90)
        menu_btn = draw_button("Menu", grid[0][0], grid[0][1], w, h, PURPLE, CREAM)
        exit_btn = draw_button("Exit", grid[1][0], grid[1][1], w, h, LAVENDER, TEXT_DARK)

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
        screen.fill(CREAM)
        # Header bar (pastel style)
        header_h = int(SCREEN_H * 0.12)
        pygame.draw.rect(screen, PINK, (0, 0, SCREEN_W, header_h))
        pygame.draw.rect(screen, LIGHT_P, (0, header_h - 8, SCREEN_W, 8))
        title_font = _best_font(int(SCREEN_H * 0.055), bold=True)
        title = title_font.render("Animal Game", True, CREAM)
        screen.blit(title, title.get_rect(center=(SCREEN_W // 2, header_h // 2)))
        # 4 vertical buttons: Talk, Learn, Play, Exit
        w_r, h_r = 0.25, 0.18
        w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
        grid = generate_grid(w_r, h_r, 1, 4, 0.375, 0.18, 1 - 0.375, 0.92)
        talk_btn = draw_button("Talk", grid[0][0], grid[0][1], w, h, PINK, CREAM)
        learn_btn = draw_button("Learn", grid[1][0], grid[1][1], w, h, PURPLE, CREAM)
        play_btn = draw_button("Play", grid[2][0], grid[2][1], w, h, PURPLE, CREAM)
        exit_btn = draw_button("Exit", grid[3][0], grid[3][1], w, h, LAVENDER, TEXT_DARK)

        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if talk_btn.collidepoint(event.pos):
                    talk_screen()
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
    # Positions of the 6 rectangles
    w_r, h_r = 0.25, 0.35
    w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
    grid_positions = generate_grid(w_r, h_r, 3, 2, 0.075, 0.20, 0.925, 0.95)
    # Rects for mouse hit detection
    grid_rects = [pygame.Rect(x, y, w, h) for (x, y) in grid_positions]

    game_started = False
    # Track which animals are already revealed
    visible = [False] * len(grid_rects)

    running = True
    grid_radius = 20
    while running:
        screen.fill(CREAM)
        # Toolbar (top) pastel
        w_r_toolbar, h_r_toolbar = 0.20, 0.10
        w_toolbar, h_toolbar = int(SCREEN_W * w_r_toolbar), int(SCREEN_H * h_r_toolbar)
        toolbar_grid = generate_grid(w_r_toolbar, h_r_toolbar, 3, 1, 0.10, 0.05, 0.90, 0.20)
        menu_btn = draw_button("Menu", toolbar_grid[0][0], toolbar_grid[0][1], w_toolbar, h_toolbar, LAVENDER, TEXT_DARK)
        start_btn = draw_button("Start", toolbar_grid[1][0], toolbar_grid[1][1], w_toolbar, h_toolbar, PINK, CREAM)
        exit_btn = draw_button("Exit", toolbar_grid[2][0], toolbar_grid[2][1], w_toolbar, h_toolbar, LAVENDER, TEXT_DARK)

        # Draw grid: rounded cells, PURPLE border; show images when revealed
        for i, (x, y) in enumerate(grid_positions):
            rect = grid_rects[i]
            pygame.draw.rect(screen, SHADOW, (rect.x + 3, rect.y + 3, rect.w, rect.h), border_radius=grid_radius)
            pygame.draw.rect(screen, LAVENDER, rect, border_radius=grid_radius)
            pygame.draw.rect(screen, PURPLE, rect, 2, border_radius=grid_radius)
            if game_started and visible[i]:
                img = images[i]
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

                # Exit: close program
                if exit_btn.collidepoint(event.pos):
                    pygame.quit()
                    sys.exit()

                # Start: enable clicking boxes
                if start_btn.collidepoint(event.pos):
                    game_started = True
                    continue

                # If learn mode has started, handle clicks on rectangles
                if game_started:
                    for i, rect in enumerate(grid_rects):
                        if rect.collidepoint(event.pos):
                            visible[i] = True  # keep this image on screen
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
    # Positions of the 6 rectangles
    w_r, h_r = 0.25, 0.35
    w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
    grid_positions = generate_grid(w_r, h_r, 3, 2, 0.075, 0.20, 0.925, 0.95)
    grid_rects = [pygame.Rect(x, y, w, h) for (x, y) in grid_positions]

    score = 0
    target_index = None
    game_finished = False

    # For highlighting: per-cell color + end-time
    highlight_until = [0] * len(grid_rects)
    highlight_color = [None] * len(grid_rects)

    # While feedback is active we ignore clicks
    feedback_active_until = 0
    next_question_time = 0

    # List of remaining animals to ask (indices), so each is used once
    remaining_indices = list(range(len(grid_rects)))
    round_attempt_number = 0
    round_wrong_answers = []

    font = _best_font(int(SCREEN_H * 0.05))
    hint_session = HintSession(stop_audio=lambda: pygame.mixer.stop())
    hint_session.invalidate()

    def clear_highlights():
        for i in range(len(grid_rects)):
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

            screen.fill(CREAM)
            # Toolbar pastel
            w_r_toolbar, h_r_toolbar = 0.17, 0.10
            w_toolbar, h_toolbar = int(SCREEN_W * w_r_toolbar), int(SCREEN_H * h_r_toolbar)
            toolbar_grid = generate_grid(w_r_toolbar, h_r_toolbar, 4, 1, 0.08, 0.05, 0.92, 0.20)
            menu_btn = draw_button("Menu", toolbar_grid[0][0], toolbar_grid[0][1], w_toolbar, h_toolbar, LAVENDER, TEXT_DARK)

            mid_rect = pygame.Rect(toolbar_grid[1][0], toolbar_grid[1][1], w_toolbar, h_toolbar)
            pygame.draw.rect(screen, SHADOW, (mid_rect.x + 3, mid_rect.y + 3, mid_rect.w, mid_rect.h), border_radius=14)
            pygame.draw.rect(screen, LAVENDER, mid_rect, border_radius=14)
            if target_index is not None:
                label = font.render("Find Game", True, TEXT_DARK)
                screen.blit(label, label.get_rect(center=(mid_rect.centerx, mid_rect.centery)))

            hint_label = "Thinking..." if hint_session.hint_loading else "Hint"
            hint_btn = draw_button(hint_label, toolbar_grid[2][0], toolbar_grid[2][1], w_toolbar, h_toolbar, PURPLE, CREAM)
            exit_btn = draw_button("Exit", toolbar_grid[3][0], toolbar_grid[3][1], w_toolbar, h_toolbar, LAVENDER, TEXT_DARK)

            # Draw grid with all animals visible; rounded cells, pastel highlights
            grid_radius = 20
            for i, (x, y) in enumerate(grid_positions):
                rect = grid_rects[i]
                screen.blit(images[i], (x, y))
                if highlight_color[i] is not None and now < highlight_until[i]:
                    color = highlight_color[i]
                    width = 7
                else:
                    color = PURPLE
                    width = 2
                pygame.draw.rect(screen, color, rect, width, border_radius=grid_radius)

            draw_hint_card(hint_session.hint_text, hint_session.hint_loading)

            # Score in bottom-right, pastel style
            score_text = font.render(f"Score: {score}", True, TEXT_DARK)
            screen.blit(score_text, (SCREEN_W - score_text.get_width() - 24, SCREEN_H - score_text.get_height() - 24))

            pygame.display.update()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

                if event.type == pygame.MOUSEBUTTONDOWN:
                    # Menu: back to main menu
                    if menu_btn.collidepoint(event.pos):
                        return

                    # Exit: close program
                    if exit_btn.collidepoint(event.pos):
                        pygame.quit()
                        sys.exit()

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
