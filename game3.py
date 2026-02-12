import pygame
import random
import time
from pathlib import Path

# -----------------------
# Config & Virtual Resolution
# -----------------------
V_WIDTH, V_HEIGHT = 1280, 720 
FPS = 60

# Layout Constants
HEADER_H = 160
BTN_H = 50
BTN_W = 140
PADDING = 20

# Colors
BG_COLOR = (245, 247, 250)
HEADER_BG = (255, 255, 255)
TEXT_COLOR = (40, 45, 60)
MUTED_COLOR = (100, 110, 125)
GREEN = (46, 204, 113)
RED = (231, 76, 60)
BLUE_ACCENT = (52, 152, 219)
SHADOW = (0, 0, 0, 30)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Tolerances
TOL_ON = 25
MARGIN_SIDE = 25
TOL_INSIDE = 10
TOL_BETWEEN = 15

# -----------------------
# Paths (UPDATED FOR FLAT STRUCTURE)
# -----------------------
BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "images"
AUDIO_DIR = BASE_DIR / "audio"

# Since you don't have subfolders, we point these to the main audio folder
INSTR_DIR = AUDIO_DIR 
FEEDBACK_DIR = AUDIO_DIR 

# -----------------------
# Russian Dictionary
# -----------------------
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

# -----------------------
# UI Helpers
# -----------------------
def draw_text_wrapped(surface, text, font, color, rect, align="center"):
    words = text.split(' ')
    space_w, _ = font.size(' ')
    
    lines = []
    current_line = []
    current_w = 0
    
    for word in words:
        word_w, word_h = font.size(word)
        if current_w + word_w >= rect.width:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_w = word_w
        else:
            current_line.append(word)
            current_w += word_w + space_w
    lines.append(" ".join(current_line))

    # Calculate total height of text block
    total_h = len(lines) * font.get_linesize()
    y_offset = rect.y + (rect.height - total_h) // 2
    
    # Return the rect of the text block (useful for placing the button next to it)
    text_block_rect = pygame.Rect(rect.x, y_offset, rect.width, total_h)

    for line in lines:
        fw, fh = font.size(line)
        if align == "center":
            tx = rect.x + (rect.width - fw) // 2
        elif align == "right":
            tx = rect.right - fw
        else:
            tx = rect.x
            
        surf = font.render(line, True, color)
        surface.blit(surf, (tx, y_offset))
        y_offset += font.get_linesize()
        
    return text_block_rect

class Button:
    def __init__(self, x, y, w, h, label, bg_color=HEADER_BG, text_color=TEXT_COLOR, icon_only=False):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.bg_color = bg_color
        self.text_color = text_color
        self.hovered = False
        self.icon_only = icon_only

    def draw(self, screen, font):
        # Shadow
        shadow_rect = self.rect.copy()
        shadow_rect.y += 4
        pygame.draw.rect(screen, SHADOW, shadow_rect, border_radius=12)

        # Body
        col = (min(self.bg_color[0]+10, 255), min(self.bg_color[1]+10, 255), min(self.bg_color[2]+10, 255)) if self.hovered else self.bg_color
        pygame.draw.rect(screen, col, self.rect, border_radius=12)
        
        # Border
        border_col = BLUE_ACCENT if self.hovered else (200, 200, 200)
        pygame.draw.rect(screen, border_col, self.rect, 2, border_radius=12)

        if self.icon_only:
            # Draw a simple "Speaker" icon
            cx, cy = self.rect.center
            # Speaker body
            icon_color = WHITE if self.bg_color == BLUE_ACCENT else self.text_color
            
            pygame.draw.polygon(screen, icon_color, [
                (cx - 5, cy - 5), (cx - 5, cy + 5), (cx + 5, cy + 5), (cx + 5, cy - 5)
            ])
            # Speaker cone
            pygame.draw.polygon(screen, icon_color, [
                (cx + 5, cy - 5), (cx + 12, cy - 10), (cx + 12, cy + 10), (cx + 5, cy + 5)
            ])
        else:
            # Text
            txt = font.render(self.label, True, self.text_color)
            screen.blit(txt, txt.get_rect(center=self.rect.center))

    def check_hover(self, mouse_pos):
        self.hovered = self.rect.collidepoint(mouse_pos)

    def hit(self, mouse_pos):
        return self.rect.collidepoint(mouse_pos)

# -----------------------
# Asset Loading
# -----------------------
_image_cache = {}
_sound_cache = {}

def load_image(name: str, size):
    key = (name, size[0], size[1])
    if key in _image_cache: return _image_cache[key]
    path = IMG_DIR / f"{name}.png"
    if not path.exists():
        path_jpg = IMG_DIR / f"{name}.jpg"
        if path_jpg.exists():
            path = path_jpg
        else:
            print(f"⚠️ IMAGE MISSING: {path}")
            return None
    try:
        img = pygame.image.load(str(path)).convert_alpha()
        img = pygame.transform.smoothscale(img, size)
        _image_cache[key] = img
        return img
    except Exception as e:
        print(f"❌ IMAGE ERROR {name}: {e}")
        return None

def load_sound_debug(folder: Path, filename: str):
    path = folder / filename
    spath = str(path)
    
    if spath in _sound_cache: return _sound_cache[spath]
    
    if not path.exists():
        # Silent fail so it doesn't spam, but print once
        # print(f"⚠️ AUDIO MISSING: {path}")
        return None

    try:
        snd = pygame.mixer.Sound(spath)
        _sound_cache[spath] = snd
        print(f"✅ Loaded audio: {filename}")
        return snd
    except Exception as e:
        print(f"❌ AUDIO ERROR {filename}: {e}")
        return None

# -----------------------
# Logic Classes
# -----------------------
class Item:
    def __init__(self, name, x, y, w, h, fallback_col):
        self.name = name
        self.rect = pygame.Rect(x, y, w, h)
        self.start_rect = self.rect.copy()
        self.fallback_color = fallback_col
        self.image = load_image(name, (w, h))
        self._offset = (0, 0)

    def reset(self):
        self.rect = self.start_rect.copy()

    def draw(self, screen):
        if self.image:
            screen.blit(self.image, self.rect.topleft)
            pygame.draw.rect(screen, BLACK, self.rect, 2)
        else:
            pygame.draw.rect(screen, self.fallback_color, self.rect)
            pygame.draw.rect(screen, BLACK, self.rect, 2)

    def start_drag(self, pos):
        if self.rect.collidepoint(pos):
            self._offset = (pos[0] - self.rect.x, pos[1] - self.rect.y)
            return True
        return False

    def drag(self, pos):
        self.rect.x = pos[0] - self._offset[0]
        self.rect.y = pos[1] - self._offset[1]
        self.rect.x = max(0, min(self.rect.x, V_WIDTH - self.rect.w))
        self.rect.y = max(HEADER_H, min(self.rect.y, V_HEIGHT - self.rect.h))

# -----------------------
# Game Logic
# -----------------------
REL_MAP = {
    "on": lambda a, b: abs(a.rect.bottom - b.rect.top) <= TOL_ON and a.rect.centerx >= b.rect.left and a.rect.centerx <= b.rect.right and a.rect.centery < b.rect.centery,
    "under": lambda a, b: abs(a.rect.top - b.rect.bottom) <= TOL_ON and a.rect.centerx >= b.rect.left and a.rect.centerx <= b.rect.right and a.rect.centery > b.rect.centery,
    "left_of": lambda a, b: a.rect.right <= b.rect.left - MARGIN_SIDE,
    "right_of": lambda a, b: a.rect.left >= b.rect.right + MARGIN_SIDE,
    "inside": lambda a, b: b.rect.contains(a.rect.inflate(-TOL_INSIDE, -TOL_INSIDE)),
    "between": lambda a, b1, b2: a.rect.centerx >= min(b1.rect.centerx, b2.rect.centerx) + TOL_BETWEEN and a.rect.centerx <= max(b1.rect.centerx, b2.rect.centerx) - TOL_BETWEEN
}

def instruction_text(constraints):
    phrases = []
    for c in constraints:
        t = c["type"]
        a = get_rus_name(c["a"], "acc")
        if t == "between":
            phrases.append(f"{a} между {get_rus_name(c['b'][0], 'ins')} и {get_rus_name(c['b'][1], 'ins')}")
        elif t == "left_of": phrases.append(f"{a} слева от {get_rus_name(c['b'], 'gen')}")
        elif t == "right_of": phrases.append(f"{a} справа от {get_rus_name(c['b'], 'gen')}")
        elif t == "on": phrases.append(f"{a} на {get_rus_name(c['b'], 'acc')}")
        elif t == "under": phrases.append(f"{a} под {get_rus_name(c['b'], 'acc')}")
        elif t == "inside": phrases.append(f"{a} в {get_rus_name(c['b'], 'acc')}")
    
    prefix = "Поместите "
    if len(phrases) == 1: return f"{prefix}{phrases[0]}."
    if len(phrases) == 2: return f"{prefix}{phrases[0]} и {phrases[1]}."
    return f"{prefix}" + ", ".join(phrases[:-1]) + " и " + phrases[-1] + "."

# -----------------------
# Scenarios
# -----------------------
SCENARIOS = [
    {"items": ["table", "chair", "cup"], "constraints": [{"type": "on", "a": "cup", "b": "table"}, {"type": "right_of", "a": "chair", "b": "table"}]},
    {"items": ["table", "cup", "ball"], "constraints": [{"type": "under", "a": "ball", "b": "table"}, {"type": "left_of", "a": "cup", "b": "table"}]},
    {"items": ["chair", "book", "cup"], "constraints": [{"type": "on", "a": "book", "b": "chair"}, {"type": "right_of", "a": "cup", "b": "chair"}]},
    {"items": ["box", "ball", "cup"], "constraints": [{"type": "inside", "a": "ball", "b": "box"}, {"type": "inside", "a": "cup", "b": "box"}]},
    {"items": ["table", "chair", "book", "cup"], "constraints": [{"type": "left_of", "a": "chair", "b": "table"}, {"type": "under", "a": "book", "b": "chair"}, {"type": "on", "a": "cup", "b": "table"}]},
    {"items": ["table", "chair", "ball"], "constraints": [{"type": "between", "a": "ball", "b": ["chair", "table"]}]},
    {"items": ["table", "chair", "box", "ball", "cup"], "constraints": [{"type": "on", "a": "cup", "b": "table"}, {"type": "on", "a": "ball", "b": "chair"}, {"type": "right_of", "a": "box", "b": "chair"}]},
]

def make_items(names):
    sizes = {"table": (280, 130), "chair": (150, 170), "cup": (80, 80), "box": (190, 150), "ball": (80, 80), "book": (130, 80)}
    colors = {"table": (222, 200, 150), "chair": (190, 210, 235), "cup": (240, 220, 235), "box": (215, 235, 210), "ball": (250, 210, 170), "book": (210, 220, 250)}
    items = {}
    for n in names:
        w, h = sizes[n]
        x = random.randint(50, V_WIDTH - w - 50)
        y = random.randint(HEADER_H + 50, V_HEIGHT - h - 50)
        items[n] = Item(n, x, y, w, h, colors.get(n, (200,200,200)))
    return items

# -----------------------
# Main
# -----------------------
def main():
    pygame.init()
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    except:
        pygame.mixer.init()

    screen = pygame.display.set_mode((V_WIDTH, V_HEIGHT), pygame.RESIZABLE)
    pygame.display.set_caption("Prepositions Game")
    canvas = pygame.Surface((V_WIDTH, V_HEIGHT))
    clock = pygame.time.Clock()

    font_names = ["Arial", "Helvetica", "DejaVu Sans", "Segoe UI"]
    font_xl = pygame.font.SysFont(font_names, 42, bold=True)
    font_lg = pygame.font.SysFont(font_names, 32)
    font_md = pygame.font.SysFont(font_names, 24)
    font_sm = pygame.font.SysFont(font_names, 20)

    # UI Buttons
    btn_y = 30
    btn_check  = Button(V_WIDTH - (3 * (BTN_W + 10)) - 20, btn_y, BTN_W, BTN_H, "Check")
    btn_reset  = Button(V_WIDTH - (2 * (BTN_W + 10)) - 20, btn_y, BTN_W, BTN_H, "Reset")
    btn_next   = Button(V_WIDTH - (1 * (BTN_W + 10)) - 20, btn_y, BTN_W, BTN_H, "Next", bg_color=BLUE_ACCENT, text_color=WHITE)
    
    # Speaker Button (Blue accent to be visible)
    btn_speaker = Button(0, 0, 50, 50, "", bg_color=BLUE_ACCENT, text_color=WHITE, icon_only=True)
    
    buttons = [btn_check, btn_reset, btn_next, btn_speaker]

    ch_instr = pygame.mixer.Channel(0)
    ch_fb = pygame.mixer.Channel(1)
    
    idx = 0
    items = {}
    constraints = []
    text_instr = ""
    feedback = ""
    feedback_col = MUTED_COLOR
    fb_timer = 0
    dragging = None

    def play_instruction_audio(index):
        # Checks for "1.mp3", "01.mp3" in the audio folder
        filenames = [f"{index+1}.mp3", f"{index+1:02d}.mp3"]
        s = None
        for f in filenames:
            s = load_sound_debug(INSTR_DIR, f)
            if s: break
        
        if s: 
            ch_instr.stop()
            ch_instr.play(s)
        else:
            print(f"❌ Could not find audio for level {index+1} (checked: {filenames})")

    def load_level(i):
        nonlocal items, constraints, text_instr, feedback
        data = SCENARIOS[i]
        items = make_items(data["items"])
        constraints = data["constraints"]
        text_instr = instruction_text(constraints)
        feedback = ""
        
        play_instruction_audio(i)

    load_level(idx)

    running = True
    while running:
        w, h = screen.get_size()
        scale = min(w / V_WIDTH, h / V_HEIGHT)
        new_w, new_h = int(V_WIDTH * scale), int(V_HEIGHT * scale)
        offset_x, offset_y = (w - new_w) // 2, (h - new_h) // 2

        mouse_raw = pygame.mouse.get_pos()
        mx = (mouse_raw[0] - offset_x) / scale
        my = (mouse_raw[1] - offset_y) / scale
        mouse_game = (mx, my)

        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                
                if btn_speaker.hit(mouse_game):
                    play_instruction_audio(idx)

                elif btn_check.hit(mouse_game):
                    ok = True
                    for c in constraints:
                        a = items[c["a"]]
                        if c["type"] == "between":
                            if not REL_MAP["between"](a, items[c["b"][0]], items[c["b"][1]]): ok = False
                        else:
                            if not REL_MAP[c["type"]](a, items[c["b"]]): ok = False
                    if ok:
                        feedback = "Отлично! Всё верно."
                        feedback_col = GREEN
                        # Try "correct.wav" or "correct.mp3"
                        s = load_sound_debug(FEEDBACK_DIR, "correct.wav")
                        if not s: s = load_sound_debug(FEEDBACK_DIR, "correct.mp3")
                        if s: ch_fb.play(s)
                    else:
                        feedback = "Попробуйте ещё раз."
                        feedback_col = RED
                        # Try "incorrect.wav" or "incorrect.mp3"
                        s = load_sound_debug(FEEDBACK_DIR, "incorrect.wav")
                        if not s: s = load_sound_debug(FEEDBACK_DIR, "incorrect.mp3")
                        if s: ch_fb.play(s)
                    fb_timer = time.time()
                elif btn_reset.hit(mouse_game):
                    for it in items.values(): it.reset()
                    feedback = ""
                elif btn_next.hit(mouse_game):
                    idx = (idx + 1) % len(SCENARIOS)
                    load_level(idx)
                else:
                    curr_items = list(items.values())
                    for i in reversed(range(len(curr_items))):
                        it = curr_items[i]
                        if it.start_drag(mouse_game):
                            dragging = it
                            val = items.pop(it.name)
                            items[it.name] = val
                            break
            elif event.type == pygame.MOUSEBUTTONUP:
                dragging = None
            elif event.type == pygame.MOUSEMOTION and dragging:
                dragging.drag(mouse_game)

        for b in buttons: b.check_hover(mouse_game)
        if feedback and time.time() - fb_timer > 3: feedback = ""

        canvas.fill(BG_COLOR)
        pygame.draw.rect(canvas, HEADER_BG, (0, 0, V_WIDTH, HEADER_H))
        pygame.draw.line(canvas, (220, 225, 230), (0, HEADER_H), (V_WIDTH, HEADER_H), 2)
        
        title = font_xl.render(f"Пример {idx + 1} / {len(SCENARIOS)}", True, TEXT_COLOR)
        canvas.blit(title, (30, 35))
        
        for b in [btn_check, btn_reset, btn_next]:
            b.draw(canvas, font_md)

        instr_rect_area = pygame.Rect(100, 95, V_WIDTH - 200, 60)
        text_bounds = draw_text_wrapped(canvas, text_instr, font_lg, MUTED_COLOR, instr_rect_area)

        # Update speaker button pos to be left of text
        btn_speaker.rect.x = text_bounds.x - 60
        btn_speaker.rect.y = text_bounds.centery - 25
        btn_speaker.draw(canvas, font_md)

        hint_surf = font_sm.render("Перетащите объекты, следуя инструкции.", True, (160, 170, 180))
        canvas.blit(hint_surf, (V_WIDTH - hint_surf.get_width() - 20, V_HEIGHT - 30))

        if feedback:
            fb_surf = font_xl.render(feedback, True, feedback_col)
            fb_rect = fb_surf.get_rect(center=(V_WIDTH // 2, V_HEIGHT - 100))
            bg_rect = fb_rect.inflate(40, 20)
            s = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
            s.fill((255, 255, 255, 230))
            canvas.blit(s, bg_rect.topleft)
            pygame.draw.rect(canvas, (200, 200, 200), bg_rect, 2, border_radius=15)
            canvas.blit(fb_surf, fb_rect.topleft)

        for it in items.values():
            it.draw(canvas)

        scaled_surf = pygame.transform.smoothscale(canvas, (new_w, new_h))
        if offset_x > 0 or offset_y > 0: screen.fill((30, 30, 30)) 
        screen.blit(scaled_surf, (offset_x, offset_y))
        pygame.display.flip()

    pygame.quit()

if __name__ == "__main__":
    main()