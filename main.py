import pygame
import subprocess
import sys

pygame.init()
pygame.mixer.init()

SCREEN_W, SCREEN_H = 800, 480
screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.FULLSCREEN)
font = pygame.font.SysFont("Arial", 40)

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

images = [pygame.transform.scale(pygame.image.load(p), (250, 150)) for p in image_paths]
sounds = [pygame.mixer.Sound(a) for a in audio_paths]


# ----------------------------
# HELPER: draw a button
# ----------------------------
def draw_button(text, x, y, w, h, color=(200, 200, 200)):
    pygame.draw.rect(screen, color, (x, y, w, h))
    label = font.render(text, True, (0, 0, 0))
    screen.blit(
        label,
        (x + (w - label.get_width()) // 2,
         y + (h - label.get_height()) // 2),
    )
    return pygame.Rect(x, y, w, h)


# ----------------------------
# PAGE 1: MAIN MENU
# ----------------------------
def menu_screen():
    while True:
        screen.fill((255, 255, 255))

        talk_btn = draw_button("Talk", 275, 120, 250, 80)
        game_btn = draw_button("Game", 275, 260, 250, 80)
        exit_btn = draw_button("Exit", 275, 400, 250, 60)

        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if talk_btn.collidepoint(event.pos):
                    talk_screen()
                if game_btn.collidepoint(event.pos):
                    game_screen()
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
# PAGE 3: GAME SCREEN (INTERACTIVE)
# ----------------------------
def game_screen():
    # Positions of the 6 rectangles
    grid_positions = [
        (50, 100), (300, 100), (550, 100),
        (50, 270), (300, 270), (550, 270),
    ]

    # Rects for mouse hit detection
    grid_rects = [pygame.Rect(x, y, 200, 130) for (x, y) in grid_positions]

    game_started = False       # becomes True after pressing "Start Game"
    current_index = None       # which animal is currently visible
    sound_end_time = 0         # time when the current sound should end (ms)

    running = True
    while running:
        now = pygame.time.get_ticks()

        # If a sound is playing, check if it should stop showing the image
        if current_index is not None and now >= sound_end_time:
            current_index = None  # hide the animal after sound finishes

        screen.fill((255, 255, 255))

        # Toolbar
        menu_btn = draw_button("Menu", 20, 10, 150, 60)
        start_btn = draw_button("Start Game", 230, 10, 200, 60)
        exit_btn = draw_button("Exit", 560, 10, 200, 60)

        # Draw grid: either empty rectangles or show the image if it's active
        for i, (x, y) in enumerate(grid_positions):
            rect = grid_rects[i]
            pygame.draw.rect(screen, (0, 0, 0), rect, 3)
            if game_started and current_index == i:
                img = images[i]
                screen.blit(img, (x, y))

        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.MOUSEBUTTONDOWN:
                # Menu: go back to main menu
                if menu_btn.collidepoint(event.pos):
                    return  # back to menu_screen

                # Exit: close the whole program
                if exit_btn.collidepoint(event.pos):
                    pygame.quit()
                    sys.exit()

                # Start Game: enable clicking rectangles
                if start_btn.collidepoint(event.pos):
                    game_started = True
                    current_index = None
                    continue

                # If game has started, handle clicks on rectangles
                if game_started:
                    # Only allow starting a new sound if none is currently active
                    if current_index is None:
                        for i, rect in enumerate(grid_rects):
                            if rect.collidepoint(event.pos):
                                current_index = i
                                sounds[i].play()
                                length_ms = int(sounds[i].get_length() * 1000)
                                sound_end_time = pygame.time.get_ticks() + length_ms
                                break


# ----------------------------
# START PROGRAM
# ----------------------------
menu_screen()
