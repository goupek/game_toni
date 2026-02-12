import pygame
import sys

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