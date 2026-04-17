import math
import pygame
import random
import time
from pathlib import Path

from pipeline_mem.llm_tts_hint import HintSession

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

# Launcher palette
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
TEXT_DARK_80 = (98, 70, 89)
TEXT_LIGHT = (255, 248, 235)
OUTLINE_DARK = (99, 61, 81)
SHADOW_FILL = (153, 136, 148)

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
BTN_PINK = (240, 166, 202)
BTN_PINK_DARK = (193, 48, 92)

HUD_CREAM = (236, 231, 205)
HUD_BORDER = (187, 173, 121)
SUCCESS_FILL = (204, 245, 190)
ERROR_FILL = (255, 213, 213)

# Legacy names for minimal code change
BG_COLOR = PANEL_INNER
HEADER_BG = BTN_CREAM
TEXT_COLOR = TEXT_DARK
MUTED_COLOR = TEXT_DARK_80
GREEN = BTN_GREEN
RED = BTN_RED
BLUE_ACCENT = BTN_BLUE
SHADOW = SHADOW_FILL
WHITE = BTN_CREAM
BLACK = OUTLINE_DARK

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
RELATION_LABELS_RU = {
    "on": "на",
    "under": "под",
    "left_of": "слева",
    "right_of": "справа",
    "inside": "внутри",
    "between": "между",
}

def get_rus_name(eng_name, case="acc"):
    return RUS_DICT.get(eng_name, {}).get(case, eng_name)

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


def draw_shadow(surface, rect, radius, dy=6):
    pygame.draw.rect(surface, SHADOW_FILL, rect.move(0, dy), border_radius=radius)


def draw_background(surface):
    w, h = surface.get_size()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        pygame.draw.line(surface, (r, g, b), (0, y), (w, y))
    polys = [
        (BG_POLY_1, [(0, h * 0.18), (w * 0.28, 0), (w * 0.5, h * 0.22), (w * 0.2, h * 0.42)]),
        (BG_POLY_2, [(w * 0.66, 0), (w, 0), (w, h * 0.34), (w * 0.8, h * 0.26)]),
        (BG_POLY_3, [(0, h), (w * 0.22, h * 0.7), (w * 0.4, h), (0, h)]),
        (BG_POLY_2, [(w * 0.58, h), (w * 0.78, h * 0.62), (w, h), (w * 0.78, h)]),
    ]
    for color, pts in polys:
        pygame.draw.polygon(surface, color, pts)


def draw_panel(surface, rect, radius=28):
    draw_shadow(surface, rect, radius, dy=8)
    pygame.draw.rect(surface, PANEL_FILL, rect, border_radius=radius)
    pygame.draw.rect(surface, PANEL_BORDER, rect, width=4, border_radius=radius)
    inner = rect.inflate(-10, -10)
    pygame.draw.rect(surface, PANEL_INNER, inner, width=2, border_radius=max(12, radius - 6))


def draw_ribbon_title(surface, text, panel_rect, font):
    ribbon_h = 70
    ribbon_w = int(panel_rect.w * 1.08)
    ribbon_x = panel_rect.centerx - ribbon_w // 2
    ribbon_y = panel_rect.y + 20
    ribbon = pygame.Rect(ribbon_x, ribbon_y, ribbon_w, ribbon_h)

    tail_w = 28
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
    pygame.draw.polygon(surface, RIBBON_DARK, left_tail)
    pygame.draw.polygon(surface, RIBBON_DARK, right_tail)
    draw_shadow(surface, ribbon, 0, dy=6)
    pygame.draw.rect(surface, RIBBON_FILL, ribbon)
    pygame.draw.rect(surface, RIBBON_LIGHT, pygame.Rect(ribbon.x, ribbon.y, ribbon.w, 10))
    pygame.draw.line(surface, RIBBON_DARK, (ribbon.left, ribbon.bottom - 3), (ribbon.right, ribbon.bottom - 3), 3)
    txt = render_tracked_text(font, text, TEXT_LIGHT, tracking=1)
    surface.blit(txt, txt.get_rect(center=ribbon.center))
    return ribbon


def get_layout_rects(view_w, view_h):
    ui_scale = min(view_w / 1280, view_h / 720)
    panel_margin_x = max(72, int(92 * ui_scale))
    panel_margin_y = max(36, int(44 * ui_scale))
    main_panel = pygame.Rect(
        panel_margin_x,
        panel_margin_y,
        view_w - 2 * panel_margin_x,
        view_h - 2 * panel_margin_y,
    )
    play_area = pygame.Rect(
        main_panel.x + max(30, int(38 * ui_scale)),
        main_panel.y + max(126, int(142 * ui_scale)),
        main_panel.w - 2 * max(30, int(38 * ui_scale)),
        main_panel.h - max(162, int(184 * ui_scale)),
    )
    return ui_scale, main_panel, play_area

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
            
        surf = render_tracked_text(font, line, color, tracking=1)
        surface.blit(surf, (tx, y_offset))
        y_offset += font.get_linesize()
        
    return text_block_rect


def draw_centered_wrapped_text(surface, text, font, color, center_x, y, max_width):
    lines = wrap_text_lines(text, font, max_width)
    total_h = len(lines) * font.get_linesize()
    text_block_rect = pygame.Rect(center_x - max_width // 2, y, max_width, total_h)
    cur_y = y
    for line in lines:
        surf = render_tracked_text(font, line, color, tracking=1)
        surface.blit(surf, surf.get_rect(center=(center_x, cur_y + font.get_linesize() // 2)))
        cur_y += font.get_linesize()
    return text_block_rect


def wrap_text_lines(text, font, max_width):
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


def wrap_tracked_text_lines(text, font, max_width, tracking=1):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if render_tracked_text(font, candidate, TEXT_DARK, tracking=tracking).get_width() <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

class Button:
    def __init__(self, x, y, w, h, label, bg_color=HEADER_BG, text_color=TEXT_COLOR, icon_only=False, depth_color=None):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.bg_color = bg_color
        self.text_color = text_color
        self.hovered = False
        self.icon_only = icon_only
        self.depth_color = depth_color or PANEL_BORDER

    def draw(self, screen, font):
        top_fill = lighten(self.bg_color, 10) if self.hovered else self.bg_color
        depth_rect = self.rect.move(0, 7)
        pygame.draw.rect(screen, self.depth_color, depth_rect, border_radius=max(14, self.rect.h // 4))
        pygame.draw.rect(screen, top_fill, self.rect, border_radius=max(14, self.rect.h // 4))
        pygame.draw.rect(
            screen,
            lighten(top_fill, 18),
            (self.rect.x + 6, self.rect.y + 5, self.rect.w - 12, min(12, self.rect.h // 3)),
            border_radius=10,
        )
        pygame.draw.rect(screen, PANEL_BORDER, self.rect, 2, border_radius=max(14, self.rect.h // 4))

        if self.icon_only:
            cx, cy = self.rect.center
            icon_color = TEXT_LIGHT if self.text_color == TEXT_LIGHT else self.text_color
            pygame.draw.polygon(screen, icon_color, [
                (cx - 5, cy - 5), (cx - 5, cy + 5), (cx + 5, cy + 5), (cx + 5, cy - 5)
            ])
            pygame.draw.polygon(screen, icon_color, [
                (cx + 5, cy - 5), (cx + 12, cy - 10), (cx + 12, cy + 10), (cx + 5, cy + 5)
            ])
        else:
            txt = render_tracked_text(font, self.label, self.text_color, tracking=1)
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

def _x_overlap_ratio(a: Item, b: Item) -> float:
    """How much the items overlap in X, as a fraction of the smaller width."""
    inter = max(0, min(a.rect.right, b.rect.right) - max(a.rect.left, b.rect.left))
    denom = max(1, min(a.rect.w, b.rect.w))
    return inter / denom

def _intersection_area(a: Item, b: Item) -> int:
    x1 = max(a.rect.left, b.rect.left)
    y1 = max(a.rect.top, b.rect.top)
    x2 = min(a.rect.right, b.rect.right)
    y2 = min(a.rect.bottom, b.rect.bottom)
    if x2 <= x1 or y2 <= y1:
        return 0
    return (x2 - x1) * (y2 - y1)

# NOTE: These checks are intentionally distance-invariant.
# If something is "to the right" it stays correct no matter how far right it is.
# We also allow slight overlaps (kid-friendly).

MIN_X_OVERLAP_FRAC = 0.25   # for ON/UNDER

def rel_on(a: Item, b: Item) -> bool:
    return (a.rect.centery < b.rect.centery) and (_x_overlap_ratio(a, b) >= MIN_X_OVERLAP_FRAC)

def rel_under(a: Item, b: Item) -> bool:
    return (a.rect.centery > b.rect.centery) and (_x_overlap_ratio(a, b) >= MIN_X_OVERLAP_FRAC)

def rel_left_of(a: Item, b: Item) -> bool:
    return a.rect.centerx < b.rect.centerx

def rel_right_of(a: Item, b: Item) -> bool:
    return a.rect.centerx > b.rect.centerx

def rel_inside(a: Item, b: Item) -> bool:
    # Mostly-inside check: center is inside AND at least 60% of area overlaps with the container.
    if not b.rect.collidepoint(a.rect.center):
        return False
    inter_area = _intersection_area(a, b)
    a_area = max(1, a.rect.w * a.rect.h)
    return (inter_area / a_area) >= 0.60

def rel_between(a: Item, b1: Item, b2: Item) -> bool:
    lo = min(b1.rect.centerx, b2.rect.centerx)
    hi = max(b1.rect.centerx, b2.rect.centerx)
    return lo <= a.rect.centerx <= hi

REL_MAP = {
    "on": rel_on,
    "under": rel_under,
    "left_of": rel_left_of,
    "right_of": rel_right_of,
    "inside": rel_inside,
    "between": rel_between,
}


def constraint_satisfied(constraint, items):
    item_a = items[constraint["a"]]
    if constraint["type"] == "between":
        return REL_MAP["between"](item_a, items[constraint["b"][0]], items[constraint["b"][1]])
    return REL_MAP[constraint["type"]](item_a, items[constraint["b"]])


def unique_in_order(values):
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def positions_hint_fallback(remaining_relations, retry=False):
    if not remaining_relations:
        return "Похоже, все условия уже выполнены. Нажми проверить."

    joined = " и ".join(remaining_relations[:2])
    if retry:
        return (
            f"Выбери одно условие со словами {joined} и доведи его до конца. "
            "Потом спокойно проверь остальные."
        )
    return (
        f"Проверь по одному условию. Начни с того, где важны слова {joined}."
    )


def positions_hint_round(constraints, items):
    all_relations = unique_in_order([RELATION_LABELS_RU[c["type"]] for c in constraints])
    remaining_relations = unique_in_order(
        [RELATION_LABELS_RU[c["type"]] for c in constraints if not constraint_satisfied(c, items)]
    )

    forbidden_terms = []
    for name in items.keys():
        forbidden_terms.extend(RUS_DICT.get(name, {}).values())

    return {
        "hint_prompt_context": {
            "game_type": "positions_drag",
            "total_conditions_count": len(constraints),
            "relations_in_level_ru": all_relations,
            "relations_still_need_work_ru": remaining_relations,
            "remaining_conditions_count": len(
                [c for c in constraints if not constraint_satisfied(c, items)]
            ),
        },
        "hint_goal_ru": (
            "Подскажи, как проверить расположение предметов по шагам, "
            "не называя сами предметы и не произнося готовое решение."
        ),
        "hint_extra_rules_ru": (
            "Не называй предметы из уровня. Не повторяй готовые пары и полные фразы из задания. "
            "Можно говорить только о типах отношений: на, под, слева, справа, внутри, между."
        ),
        "hint_fallback": positions_hint_fallback(remaining_relations, retry=False),
        "hint_fallback_retry": positions_hint_fallback(remaining_relations, retry=True),
        "forbidden_terms": forbidden_terms,
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

def make_items(names, spawn_rect=None):
    sizes = {"table": (280, 130), "chair": (150, 170), "cup": (80, 80), "box": (190, 150), "ball": (80, 80), "book": (130, 80)}
    colors = {"table": (222, 200, 150), "chair": (190, 210, 235), "cup": (240, 220, 235), "box": (215, 235, 210), "ball": (250, 210, 170), "book": (210, 220, 250)}
    items = {}
    if spawn_rect is None:
        spawn_rect = pygame.Rect(50, HEADER_H + 50, V_WIDTH - 100, V_HEIGHT - HEADER_H - 100)
    for n in names:
        w, h = sizes[n]
        min_x = spawn_rect.x
        max_x = max(min_x, spawn_rect.right - w)
        min_y = spawn_rect.y
        max_y = max(min_y, spawn_rect.bottom - h)
        x = random.randint(min_x, max_x)
        y = random.randint(min_y, max_y)
        items[n] = Item(n, x, y, w, h, colors.get(n, BTN_CREAM))
    return items


def draw_hint_card(surface, body_text, loading, title_font, body_font):
    if not loading and not body_text:
        return

    card_w = 420
    pad = 14
    title_gap = 6
    body = "Думаю над подсказкой..." if loading else body_text
    body_lines = wrap_tracked_text_lines(body, body_font, card_w - pad * 2 - 28, tracking=1)[:4]
    title_h = title_font.get_height()
    body_h = max(1, len(body_lines)) * (body_font.get_height() + 4)
    card_h = max(120, pad * 2 + title_h + title_gap + body_h + 10)
    card_rect = pygame.Rect(V_WIDTH - 460, V_HEIGHT - (card_h + 50), card_w, card_h)

    draw_shadow(surface, card_rect, 16, dy=5)
    pygame.draw.rect(surface, BTN_CREAM, card_rect, border_radius=16)
    pygame.draw.rect(surface, PANEL_BORDER, card_rect, 2, border_radius=16)

    title = render_tracked_text(title_font, "Подсказка", TEXT_DARK, tracking=1)
    surface.blit(title, (card_rect.x + pad, card_rect.y + pad))

    y = card_rect.y + pad + title.get_height() + title_gap
    for line in body_lines:
        txt = render_tracked_text(body_font, line, TEXT_COLOR, tracking=1)
        surface.blit(txt, (card_rect.x + pad, y))
        y += txt.get_height() + 4

# -----------------------
# Main
# -----------------------
def main():
    global V_WIDTH, V_HEIGHT
    pygame.init()
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    except:
        pygame.mixer.init()

    info = pygame.display.Info()
    V_WIDTH = max(960, info.current_w)
    V_HEIGHT = max(640, info.current_h)

    screen = pygame.display.set_mode((V_WIDTH, V_HEIGHT), pygame.RESIZABLE)
    pygame.display.set_caption("Prepositions Game")
    canvas = pygame.Surface((V_WIDTH, V_HEIGHT))
    clock = pygame.time.Clock()

    font_xl = _best_font(40, bold=True)
    font_lg = _best_font(34, bold=True)
    font_md = _best_font(20, bold=True)
    font_btn = _best_font(24, bold=True)
    font_instr = _best_font(24, bold=True)
    font_sm = _best_font(18)
    font_tiny = _best_font(16)

    row_btn_w = 156
    btn_check  = Button(0, 0, row_btn_w, BTN_H, "Check", bg_color=BTN_CREAM, text_color=TEXT_DARK, depth_color=BTN_CREAM_DARK)
    btn_reset  = Button(0, 0, row_btn_w, BTN_H, "Reset", bg_color=BTN_CREAM, text_color=TEXT_DARK, depth_color=BTN_CREAM_DARK)
    btn_hint   = Button(0, 0, row_btn_w, BTN_H, "Hint", bg_color=BTN_YELLOW, text_color=TEXT_DARK, depth_color=BTN_YELLOW_DARK)
    btn_next   = Button(0, 0, row_btn_w, BTN_H, "Next", bg_color=BTN_BLUE, text_color=TEXT_LIGHT, depth_color=BTN_BLUE_DARK)

    btn_speaker = Button(0, 0, 44, 44, "", bg_color=BTN_BLUE, text_color=TEXT_LIGHT, icon_only=True, depth_color=BTN_BLUE_DARK)

    btn_restart = Button(V_WIDTH // 2 - 160, V_HEIGHT // 2 + 80, 320, 60, "Сыграть снова", bg_color=BTN_BLUE, text_color=TEXT_LIGHT, depth_color=BTN_BLUE_DARK)

    buttons = [btn_check, btn_reset, btn_hint, btn_next, btn_speaker, btn_restart]

    ch_instr = pygame.mixer.Channel(0)
    ch_fb = pygame.mixer.Channel(1)

    def stop_game_audio():
        ch_instr.stop()
        ch_fb.stop()

    hint_session = HintSession(stop_audio=stop_game_audio)
    hint_session.invalidate()
    
    idx = 0
    score = 0
    solved = [False] * len(SCENARIOS)  # level counted in score already?
    game_over = False

    items = {}
    constraints = []
    text_instr = ""
    feedback = ""
    feedback_col = MUTED_COLOR
    fb_timer = 0
    dragging = None
    level_attempt_number = 0
    level_wrong_checks = []

    def play_instruction_audio(index):
        # Checks for "1.wav", "01.wav", "1.mp3", "01.mp3" in the audio folder
        if hint_session.is_speaking():
            return
        filenames = [
            f"{index+1}.wav", f"{index+1:02d}.wav",
            f"{index+1}.mp3", f"{index+1:02d}.mp3",
        ]
        s = None
        for f in filenames:
            s = load_sound_debug(INSTR_DIR, f)
            if s:
                break

        if s:
            ch_instr.stop()
            ch_instr.play(s)
        else:
            print(f"❌ Could not find audio for level {index+1} (checked: {filenames})")

    def load_level(i):
        nonlocal items, constraints, text_instr, feedback, level_attempt_number, level_wrong_checks
        data = SCENARIOS[i]
        ui_scale, _main_panel, play_area = get_layout_rects(V_WIDTH, V_HEIGHT)
        spawn_rect = pygame.Rect(
            play_area.x + max(18, int(22 * ui_scale)),
            play_area.y + BTN_H + max(42, int(52 * ui_scale)),
            play_area.w - 2 * max(18, int(22 * ui_scale)),
            play_area.h - BTN_H - max(70, int(84 * ui_scale)),
        )
        items = make_items(data["items"], spawn_rect)
        constraints = data["constraints"]
        text_instr = instruction_text(constraints)
        feedback = ""
        level_attempt_number = 0
        level_wrong_checks = []
        hint_session.invalidate()
        
        play_instruction_audio(i)

    load_level(idx)

    running = True
    try:
        while running:
            w, h = screen.get_size()
            scale = min(w / V_WIDTH, h / V_HEIGHT)
            new_w, new_h = int(V_WIDTH * scale), int(V_HEIGHT * scale)
            offset_x, offset_y = (w - new_w) // 2, (h - new_h) // 2
            ui_scale = min(V_WIDTH / 1280, V_HEIGHT / 720)

            mouse_raw = pygame.mouse.get_pos()
            mx = (mouse_raw[0] - offset_x) / scale
            my = (mouse_raw[1] - offset_y) / scale
            mouse_game = (mx, my)
            hint_session.poll()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if btn_speaker.hit(mouse_game) and not game_over:
                        play_instruction_audio(idx)

                    elif btn_hint.hit(mouse_game) and not game_over:
                        hint_session.request_hint(
                            positions_hint_round(constraints, items),
                            attempt_number=level_attempt_number,
                            wrong_answers=level_wrong_checks,
                        )

                    elif btn_check.hit(mouse_game) and not game_over:
                        level_attempt_number += 1
                        ok = all(constraint_satisfied(c, items) for c in constraints)

                        if ok:
                            # Count score only once per level
                            if not solved[idx]:
                                score += 1
                                solved[idx] = True

                            feedback = "Отлично! Всё верно."
                            feedback_col = GREEN
                            s = load_sound_debug(FEEDBACK_DIR, "correct.wav")
                            if not s:
                                s = load_sound_debug(FEEDBACK_DIR, "correct.mp3")
                            if s:
                                ch_fb.play(s)
                        else:
                            level_wrong_checks.append("ошибка")
                            hint_session.invalidate()
                            feedback = "Попробуйте ещё раз."
                            feedback_col = RED
                            s = load_sound_debug(FEEDBACK_DIR, "incorrect.wav")
                            if not s:
                                s = load_sound_debug(FEEDBACK_DIR, "incorrect.mp3")
                            if s:
                                ch_fb.play(s)

                        fb_timer = time.time()
                    elif btn_reset.hit(mouse_game) and not game_over:
                        for it in items.values():
                            it.reset()
                        hint_session.invalidate()
                        feedback = ""

                    elif btn_next.hit(mouse_game) and not game_over:
                        # Advance through levels; on the last level show the final score screen
                        if idx >= len(SCENARIOS) - 1:
                            game_over = True
                            feedback = ""
                            ch_instr.stop()
                        else:
                            idx += 1
                            load_level(idx)

                    elif btn_restart.hit(mouse_game) and game_over:
                        # Restart the whole game
                        idx = 0
                        score = 0
                        solved = [False] * len(SCENARIOS)
                        game_over = False
                        load_level(idx)

                    else:
                        # Drag only during gameplay
                        if not game_over:
                            curr_items = list(items.values())
                            for i in reversed(range(len(curr_items))):
                                it = curr_items[i]
                                if it.start_drag(mouse_game):
                                    dragging = it
                                    hint_session.invalidate()
                                    val = items.pop(it.name)
                                    items[it.name] = val
                                    break
                elif event.type == pygame.MOUSEBUTTONUP:
                    dragging = None
                elif event.type == pygame.MOUSEMOTION and dragging:
                    dragging.drag(mouse_game)

            for b in buttons:
                b.check_hover(mouse_game)
            if feedback and time.time() - fb_timer > 3:
                feedback = ""

            draw_background(canvas)
            ui_scale, main_panel, play_area = get_layout_rects(V_WIDTH, V_HEIGHT)
            draw_panel(canvas, main_panel, max(24, int(32 * ui_scale)))
            ribbon_rect = draw_ribbon_title(canvas, "Word Positions", main_panel, font_lg)
            pygame.draw.rect(canvas, PANEL_INNER, play_area, border_radius=max(18, int(22 * ui_scale)))
            pygame.draw.rect(canvas, HUD_BORDER, play_area, 2, border_radius=max(18, int(22 * ui_scale)))

            btn_gap = max(18, int(24 * ui_scale))
            top_row_y = play_area.y + max(16, int(20 * ui_scale))
            step_surf = render_tracked_text(font_xl, f"{idx + 1}/{len(SCENARIOS)}", TEXT_COLOR, tracking=1)
            step_rect = step_surf.get_rect(center=(play_area.centerx, top_row_y + BTN_H // 2))

            left_group_w = btn_check.rect.w + btn_reset.rect.w + btn_gap
            right_group_w = btn_hint.rect.w + btn_next.rect.w + btn_gap
            row_pad = max(18, int(24 * ui_scale))
            center_gap = max(34, int(44 * ui_scale))

            left_group_right = step_rect.left - center_gap
            left_group_x = max(play_area.x + row_pad, left_group_right - left_group_w)
            right_group_x = min(play_area.right - row_pad - right_group_w, step_rect.right + center_gap)

            btn_check.rect.topleft = (left_group_x, top_row_y)
            btn_reset.rect.topleft = (left_group_x + btn_check.rect.w + btn_gap, top_row_y)
            btn_hint.rect.topleft = (right_group_x, top_row_y)
            btn_next.rect.topleft = (right_group_x + btn_hint.rect.w + btn_gap, top_row_y)

            canvas.blit(step_surf, step_rect)

            if not game_over:
                btn_hint.label = "Thinking..." if hint_session.hint_loading else "Hint"
                for b in [btn_check, btn_reset, btn_hint, btn_next]:
                    b.draw(canvas, font_btn)

            if not game_over:
                instruction_band_top = ribbon_rect.bottom + max(8, int(10 * ui_scale))
                instruction_band_bottom = play_area.y - max(8, int(10 * ui_scale))
                instruction_band_h = max(40, instruction_band_bottom - instruction_band_top)
                speaker_margin = max(20, int(26 * ui_scale))
                btn_speaker.rect.x = main_panel.x + speaker_margin
                btn_speaker.rect.y = instruction_band_top + (instruction_band_h - btn_speaker.rect.h) // 2

                left_text_edge = btn_speaker.rect.right + max(18, int(22 * ui_scale))
                right_text_edge = main_panel.right - max(28, int(34 * ui_scale))
                text_max_width = min(
                    main_panel.w - 2 * max(110, int(130 * ui_scale)),
                    2 * min(main_panel.centerx - left_text_edge, right_text_edge - main_panel.centerx),
                )
                text_max_width = max(360, int(text_max_width))
                text_y = instruction_band_top + (instruction_band_h - font_instr.get_linesize()) // 2
                draw_centered_wrapped_text(
                    canvas,
                    text_instr,
                    font_instr,
                    TEXT_DARK,
                    main_panel.centerx,
                    text_y,
                    text_max_width,
                )

                btn_speaker.draw(canvas, font_md)

            # Final score overlay (pastel)
            if game_over:
                overlay = pygame.Surface((V_WIDTH, V_HEIGHT), pygame.SRCALPHA)
                overlay.fill((77, 43, 64, 120))
                canvas.blit(overlay, (0, 0))

                panel = pygame.Rect(V_WIDTH // 2 - 360, V_HEIGHT // 2 - 160, 720, 320)
                draw_panel(canvas, panel, 24)

                done_title = render_tracked_text(font_xl, "Игра окончена!", TEXT_COLOR, tracking=1)
                canvas.blit(done_title, done_title.get_rect(center=(V_WIDTH // 2, panel.top + 70)))

                score_big = render_tracked_text(font_xl, f"Ваш счёт: {score} / {len(SCENARIOS)}", TEXT_DARK, tracking=1)
                canvas.blit(score_big, score_big.get_rect(center=(V_WIDTH // 2, panel.top + 140)))

                tip = render_tracked_text(font_md, "Нажмите «Сыграть снова», чтобы начать заново.", MUTED_COLOR, tracking=1)
                canvas.blit(tip, tip.get_rect(center=(V_WIDTH // 2, panel.top + 205)))

                btn_restart.draw(canvas, font_md)

            # Draw items only during gameplay
            if not game_over:
                for it in items.values():
                    it.draw(canvas)

            if not game_over and (hint_session.hint_loading or hint_session.hint_text):
                draw_hint_card(canvas, hint_session.hint_text, hint_session.hint_loading, font_md, font_sm)

            # Feedback (near bottom, drawn AFTER objects so it stays on top)
            if feedback and not game_over:
                fb_surf = render_tracked_text(font_xl, feedback, TEXT_DARK, tracking=1)
                fb_rect = fb_surf.get_rect(center=(V_WIDTH // 2, V_HEIGHT - 95))
                bg_rect = fb_rect.inflate(40, 20)
                draw_shadow(canvas, bg_rect, 16, dy=5)
                fill = SUCCESS_FILL if feedback_col == GREEN else ERROR_FILL
                pygame.draw.rect(canvas, fill, bg_rect, border_radius=16)
                pygame.draw.rect(canvas, PANEL_BORDER, bg_rect, 2, border_radius=16)
                canvas.blit(fb_surf, fb_rect.topleft)

            scaled_surf = pygame.transform.smoothscale(canvas, (new_w, new_h))
            if offset_x > 0 or offset_y > 0:
                screen.fill(TEXT_DARK)
            screen.blit(scaled_surf, (offset_x, offset_y))
            pygame.display.flip()
    finally:
        hint_session.shutdown()
        pygame.quit()

if __name__ == "__main__":
    main()
