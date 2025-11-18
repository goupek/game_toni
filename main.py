import pygame
import subprocess
import time
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
    screen.blit(label, (x + (w-label.get_width())//2, y + (h-label.get_height())//2))
    return pygame.Rect(x, y, w, h)


# ----------------------------
# PAGE 1: MAIN MENU
# ----------------------------
def menu_screen():
    while True:
        screen.fill((255, 255, 255))

        talk_btn = draw_button("Talk", 275, 120, 250, 80)
        game_btn = draw_button("Game", 275, 260, 250, 80)

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


# ----------------------------
# PAGE 2: TALK VIDEO
# ----------------------------
def talk_screen():
    subprocess.call([
        "mpv",
        "--fs",
        "--no-osd-bar",
        "--quiet",
        "eyes.mp4"
    ])
    menu_screen()


# ----------------------------
# PAGE 3: GAME SCREEN
# ----------------------------
def game_screen():
    grid_positions = [
        (50, 100), (300, 100), (550, 100),
        (50, 270), (300, 270), (550, 270),
    ]

    while True:
        screen.fill((255, 255, 255))

        # Toolbar
        menu_btn = draw_button("Menu", 20, 10, 150, 60)
        start_btn = draw_button("Start Game", 630, 10, 150, 60)

        # Empty grid borders
        for (x, y) in grid_positions:
            pygame.draw.rect(screen, (0, 0, 0), (x, y, 200, 130), 3)

        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if menu_btn.collidepoint(event.pos):
                    menu_screen()
                if start_btn.collidepoint(event.pos):
                    run_game(grid_positions)


# ----------------------------
# GAME SEQUENCE: show images + play audio
# ----------------------------
def run_game(grid_positions):
    for i in range(6):
        screen.fill((255, 255, 255))

        # Draw toolbar again
        draw_button("Menu", 20, 10, 150, 60)
        draw_button("Start Game", 630, 10, 150, 60)

        # Show image
        img = images[i]
        x, y = grid_positions[i]
        screen.blit(img, (x, y))

        pygame.display.update()

        # Play sound
        sounds[i].play()

        # Wait until audio finishes
        time.sleep(sounds[i].get_length())


# ----------------------------
# START PROGRAM
# ----------------------------
menu_screen()
