import pygame
import os
import sys

TEMPLATE_FILES = {
    "ball": "ball_template.png",
    "cat": "cat_template.png",
    "car": "car_template.png",
    "dog": "dog_template.png",
}

def load_template(images_dir, noun_key):
    filename = TEMPLATE_FILES.get(noun_key)
    if not filename:
        return None

    path = os.path.join(images_dir, filename)
    if not os.path.exists(path):
        return None

    img = pygame.image.load(path)
    return img.convert_alpha()

def sprite_centers_for_count(count, area_rect):
    x_50 = area_rect.centerx
    x_25 = area_rect.left + area_rect.width * 1 // 4
    x_75 = area_rect.left + area_rect.width * 3 // 4
    
    y_50 = area_rect.centery
    y_25 = area_rect.top + area_rect.height * 1 // 4
    y_75 = area_rect.top + area_rect.height * 3 // 4

    if count <= 1:
        return [(x_50, y_50)]

    if count == 2:
        return [
            (x_25, y_50),
            (x_75, y_50),
        ]

    if count == 3:
        # Triangle: one top, two bottom
        return [
            (x_50, y_25),
            (x_25, y_75),
            (x_75, y_75),
        ]

    if count == 4:
        # Rectangle corners
        return [
            (x_25, y_25),
            (x_75, y_25),
            (x_25, y_75),
            (x_75, y_75),
        ]

def sprite_size_for_count(count, W, H):
    S = min(W, H)  # square side reference

    if count <= 1:
        a = int(S * 0.70)
    elif count == 2:
        a = int(S * 0.48)
    elif count == 3:
        a = int(S * 0.42)
    elif count == 4:
        a = int(S * 0.38)
    return (a, a)
    
def compose_sprites_on_canvas(sprite, count, canvas_size):
    W, H = canvas_size
    card = pygame.Surface((W, H), pygame.SRCALPHA)
    card.fill((255, 255, 255, 255))

    # Square reference
    S = min(W, H)

    # Square "play area" centered inside the canvas
    pad = int(min(W, H) * 0.08)
    area = pygame.Rect(pad, pad, W - 2 * pad, H - 2 * pad)

    # Square sprite size
    sw, sh = sprite_size_for_count(count, S, S)  # should return (a, a)
    spr = pygame.transform.smoothscale(sprite, (sw, sh))

    centers = sprite_centers_for_count(count, area)
    for (cx, cy) in centers[:count]:
        r = spr.get_rect(center=(cx, cy))
        card.blit(spr, r)

    return card

def build_round_surface(images_dir, round_data, canvas_size=(900, 650)):
    noun_key = round_data["noun_key"]
    count = round_data["count"]
    adj_key = round_data["adj_key"]  # keep semantic key (useful later)
    rgb = round_data["rgb"]

    template = load_template(images_dir, noun_key)
    if template is None:
        return None

    sprite = recolor_template(template, rgb)
    return compose_sprites_on_canvas(sprite, count, canvas_size)

def blend(c, target, t):
    return tuple(int(c[i] + (target[i] - c[i]) * t) for i in range(3))

def make_shades(main_rgb):
    light = blend(main_rgb, (255, 255, 255), 0.3)
    dark  = blend(main_rgb, (0, 0, 0), 0.3)
    return light, dark

def recolor_template(surface, main_rgb):
    out = surface.copy()
    px = pygame.PixelArray(out)

    light_rgb, dark_rgb = make_shades(main_rgb)

    MAIN  = (255, 0, 255)
    LIGHT = (255, 128, 255)
    DARK  = (128, 0, 128)

    width, height = out.get_size()

    for x in range(width):
        for y in range(height):
            color = out.unmap_rgb(px[x, y])[:3]

            if color == MAIN:
                px[x, y] = main_rgb
            elif color == LIGHT:
                px[x, y] = light_rgb
            elif color == DARK:
                px[x, y] = dark_rgb

    del px  # unlock surface
    return out

# pygame.init()
# screen = pygame.display.set_mode((500, 500))
# pygame.display.set_caption("Recolor Test")

# # Load template
# dog = pygame.image.load("dog_template.png").convert()

# # Recolor to blue
# BLUE = (70, 130, 240)
# dog_blue = recolor_template(dog, BLUE)
# scaled = pygame.transform.smoothscale(dog_blue, (256, 256))

# running = True
# while running:
#     for event in pygame.event.get():
#         if event.type == pygame.QUIT:
#             running = False

#     screen.fill((240, 240, 240))
#     screen.blit(scaled, (200, 100))
#     pygame.display.flip()

# pygame.quit()
# sys.exit()