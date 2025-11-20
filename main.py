import pygame
import subprocess
import sys

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

images = [pygame.transform.scale(pygame.image.load(p), (int(SCREEN_W * 0.25), int(SCREEN_H * 0.35))) for p in image_paths]
sounds = [pygame.mixer.Sound(a) for a in audio_paths]


# ----------------------------
# HELPER: draw a button
# x, y - Top Left point
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

def generate_grid(w_r, h_r, k = 1, l = 1, x1 = 0, y1 = 0, x2 = 100, y2 = 100):
    """
    Generate grid points for a grid of rectangles
    
    Parameters:
        x1, y1  (float) Top Left point of a rect space (in a ratio)
        x2, y2  (float) Bottom Right point of a rect space (in a ratio)
        w_r, h_r (float) width and height for each rectangle (in a ratio)
        k (int) Number of colums
        l (int) Number of rows
        
    Raises:
        ValueError: if the rectangles are too big for allocated space
    """    
    if w_r * k > (x2 - x1) or h_r * l > (y2 - y1):
        raise ValueError("k x l rectangles of such size don't fit in the allocated space")
    matrix = []
    hor_pad = ((x2 - x1) - w_r * k) / (k - 1) if k > 1 else 0
    ver_pad = ((y2 - y1) - h_r * l) / (l - 1) if l > 1 else 0
    for j in range(l):
        for i in range(k):
            matrix.append((int((x1 + i * (hor_pad + w_r)) * SCREEN_W), int((y1 + j * (ver_pad + h_r))*SCREEN_H)))
    return matrix

# ----------------------------
# PAGE 1: MAIN MENU
# ----------------------------
def menu_screen():
    while True:
        screen.fill((255, 255, 255))
        w_r, h_r = 0.25, 0.20
        w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
        grid = generate_grid(w_r, h_r, 1, 3, 0.375, 0.15, 1-0.375, 1-0.15)
        talk_btn = draw_button("Talk", grid[0][0], grid[0][1], w, h)
        game_btn = draw_button("Game", grid[1][0], grid[1][1], w, h)
        exit_btn = draw_button("Exit", grid[2][0], grid[2][1], w, h)

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
    w_r, h_r = 0.25, 0.35
    w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
    grid_positions = generate_grid(w_r, h_r, 3, 2, 0.075, 0.20, 0.925, 0.95)
    # Rects for mouse hit detection
    grid_rects = [pygame.Rect(x, y, w, h) for (x, y) in grid_positions]

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
        w_r, h_r = 0.20, 0.10
        w, h = int(SCREEN_W * w_r), int(SCREEN_H * h_r)
        grid = generate_grid(w_r, h_r, 3, 1, 0.10, 0.05, 0.90, 0.20)
        menu_btn = draw_button("Menu", grid[0][0], grid[0][1], w, h)
        start_btn = draw_button("Start Game", grid[1][0], grid[1][1], w, h)
        exit_btn = draw_button("Exit", grid[2][0], grid[2][1], w, h)
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
