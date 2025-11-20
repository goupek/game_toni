import pygame
import subprocess
import sys
import random

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
# HELPER: draw a button
# ----------------------------
def draw_button(text, x, y, w, h, color=(200, 200, 200)):
    pygame.draw.rect(screen, color, (x, y, w, h))
    font = pygame.font.SysFont("Arial", h // 2)
    label = font.render(text, True, (0, 0, 0))
    screen.blit(
        label,
        (x + (w - label.get_width()) // 2,
         y + (h - label.get_height()) // 2),
    )
    return pygame.Rect(x, y, w, h)


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
    font_big = pygame.font.SysFont("Arial", int(SCREEN_H * 0.08))
    font_small = pygame.font.SysFont("Arial", int(SCREEN_H * 0.05))

    while True:
        screen.fill((255, 255, 255))

        title = font_big.render("Game ended", True, (0, 0, 0))
        title_x = (SCREEN_W - title.get_width()) // 2
        title_y = SCREEN_H // 3
        screen.blit(title, (title_x, title_y))

        score_text = font_small.render(f"Your score: {score}", True, (0, 0, 0))
        score_x = (SCREEN_W - score_text.get_width()) // 2
        score_y = title_y + title.get_height() + 40
        screen.blit(score_text, (score_x, score_y))

        # Buttons: Menu + Exit
        w_r, h_r = 0.20, 0.10
        w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
        # Give them plenty of horizontal space so the grid always fits
        grid = generate_grid(w_r, h_r, 2, 1, 0.25, 0.65, 0.75, 0.90)
        menu_btn = draw_button("Menu", grid[0][0], grid[0][1], w, h)
        exit_btn = draw_button("Exit", grid[1][0], grid[1][1], w, h)

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
        screen.fill((255, 255, 255))
        # 4 vertical buttons: Talk, Learn, Play, Exit
        w_r, h_r = 0.25, 0.18
        w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
        grid = generate_grid(w_r, h_r, 1, 4, 0.375, 0.10, 1 - 0.375, 0.90)
        talk_btn = draw_button("Talk", grid[0][0], grid[0][1], w, h)
        learn_btn = draw_button("Learn", grid[1][0], grid[1][1], w, h)
        play_btn = draw_button("Play", grid[2][0], grid[2][1], w, h)
        exit_btn = draw_button("Exit", grid[3][0], grid[3][1], w, h)

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
    while running:
        screen.fill((255, 255, 255))

        # Toolbar (top)
        w_r_toolbar, h_r_toolbar = 0.20, 0.10
        w_toolbar, h_toolbar = int(SCREEN_W * w_r_toolbar), int(SCREEN_H * h_r_toolbar)
        toolbar_grid = generate_grid(w_r_toolbar, h_r_toolbar, 3, 1, 0.10, 0.05, 0.90, 0.20)
        menu_btn = draw_button("Menu", toolbar_grid[0][0], toolbar_grid[0][1], w_toolbar, h_toolbar)
        start_btn = draw_button("Start", toolbar_grid[1][0], toolbar_grid[1][1], w_toolbar, h_toolbar)
        exit_btn = draw_button("Exit", toolbar_grid[2][0], toolbar_grid[2][1], w_toolbar, h_toolbar)

        # Draw grid: show images that have been revealed
        for i, (x, y) in enumerate(grid_positions):
            rect = grid_rects[i]
            pygame.draw.rect(screen, (0, 0, 0), rect, 3)
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

    font = pygame.font.SysFont("Arial", int(SCREEN_H * 0.05))

    def clear_highlights():
        for i in range(len(grid_rects)):
            highlight_until[i] = 0
            highlight_color[i] = None

    def ask_new_question():
        nonlocal target_index, remaining_indices
        clear_highlights()
        if not remaining_indices:
            return False  # no more animals to ask
        target_index = random.choice(remaining_indices)
        remaining_indices.remove(target_index)

        # Play the "Where is the ...?" question sound.
        if question_sounds:
            qs = question_sounds[target_index]
            pygame.mixer.stop()
            qs.play()
        return True

    # Ask the first question; if none, immediately finish
    if not ask_new_question():
        game_finished = True

    running = not game_finished
    while running:
        now = pygame.time.get_ticks()

        # After feedback, move on to the next question
        if next_question_time and now >= next_question_time:
            next_question_time = 0
            feedback_active_until = 0
            if not ask_new_question():
                # no more animals -> end game
                game_finished = True
                break

        screen.fill((255, 255, 255))

        # Toolbar
        w_r_toolbar, h_r_toolbar = 0.20, 0.10
        w_toolbar, h_toolbar = int(SCREEN_W * w_r_toolbar), int(SCREEN_H * h_r_toolbar)
        toolbar_grid = generate_grid(w_r_toolbar, h_r_toolbar, 3, 1, 0.10, 0.05, 0.90, 0.20)
        menu_btn = draw_button("Menu", toolbar_grid[0][0], toolbar_grid[0][1], w_toolbar, h_toolbar)

        # Middle area: show which animal to find
        pygame.draw.rect(screen, (230, 230, 230),
                         (toolbar_grid[1][0], toolbar_grid[1][1], w_toolbar, h_toolbar))
        if target_index is not None:
            label = font.render(f"Find Game", True, (0, 0, 0))
            screen.blit(label, (toolbar_grid[1][0] + (w_toolbar - label.get_width()) // 2,
                                toolbar_grid[1][1] + (h_toolbar - label.get_height()) // 2))

        exit_btn = draw_button("Exit", toolbar_grid[2][0], toolbar_grid[2][1], w_toolbar, h_toolbar)

        # Draw grid with all animals visible
        for i, (x, y) in enumerate(grid_positions):
            rect = grid_rects[i]

            # First draw the image fully inside the cell
            screen.blit(images[i], (x, y))

            # Then draw the border on top so it's always visible
            if highlight_color[i] is not None and now < highlight_until[i]:
                color = highlight_color[i]
                width = 7
            else:
                color = (0, 0, 0)
                width = 3
            pygame.draw.rect(screen, color, rect, width)

        # Draw score in bottom-right corner
        score_text = font.render(f"Score: {score}", True, (0, 0, 0))
        screen.blit(score_text, (SCREEN_W - score_text.get_width() - 20,
                                 SCREEN_H - score_text.get_height() - 20))

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

                # Ignore clicks while feedback is active
                if now < feedback_active_until:
                    continue

                # Check which animal was clicked
                for i, rect in enumerate(grid_rects):
                    if rect.collidepoint(event.pos) and target_index is not None:
                        pygame.mixer.stop()

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

                            # clicked cell = green
                            highlight_color[i] = (0, 255, 0)
                            highlight_until[i] = now + feedback_len

                        else:
                            # Incorrect answer
                            if incorrect_sound is not None:
                                incorrect_sound.play()

                            # wrong chosen cell = red
                            highlight_color[i] = (255, 0, 0)
                            highlight_until[i] = now + feedback_len

                            # correct animal = green
                            highlight_color[target_index] = (0, 255, 0)
                            highlight_until[target_index] = now + feedback_len

                        feedback_active_until = now + feedback_len
                        next_question_time = now + feedback_len + 300
                        break

    if game_finished:
        game_over_screen(score)




# ----------------------------
# START PROGRAM
# ----------------------------
menu_screen()
