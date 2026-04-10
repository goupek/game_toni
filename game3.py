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

# Colors (pastel style — match launcher.py palette)
PURPLE   = (156, 137, 184)   # #9C89B8
PINK     = (240, 166, 202)   # #F0A6CA
LIGHT_P  = (239, 195, 230)   # #EFC3E6
CREAM    = (240, 230, 239)   # #F0E6EF
LAVENDER = (184, 190, 221)   # #B8BEDD
TEXT_DARK = (58, 50, 72)
TEXT_DARK_80 = (78, 68, 95)
SHADOW_FILL = (190, 185, 174)
# Legacy names for minimal code change
BG_COLOR = CREAM
HEADER_BG = LAVENDER
TEXT_COLOR = TEXT_DARK
MUTED_COLOR = TEXT_DARK_80
GREEN = (129, 199, 132)      # soft green (correct)
RED = (239, 150, 150)       # soft red (wrong)
BLUE_ACCENT = PURPLE
SHADOW = SHADOW_FILL
WHITE = CREAM
BLACK = PURPLE

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

class Button:
    def __init__(self, x, y, w, h, label, bg_color=HEADER_BG, text_color=TEXT_COLOR, icon_only=False):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.bg_color = bg_color
        self.text_color = text_color
        self.hovered = False
        self.icon_only = icon_only

    def draw(self, screen, font):
        # Soft shadow (pastel)
        shadow_rect = self.rect.copy()
        shadow_rect.x += 3
        shadow_rect.y += 4
        pygame.draw.rect(screen, SHADOW_FILL, shadow_rect, border_radius=14)
        # Body
        col = (min(self.bg_color[0] + 12, 255), min(self.bg_color[1] + 12, 255), min(self.bg_color[2] + 12, 255)) if self.hovered else self.bg_color
        pygame.draw.rect(screen, col, self.rect, border_radius=14)
        # Border
        border_col = PURPLE if self.hovered else LAVENDER
        pygame.draw.rect(screen, border_col, self.rect, 2, border_radius=14)

        if self.icon_only:
            cx, cy = self.rect.center
            icon_color = CREAM if self.bg_color == BLUE_ACCENT else self.text_color
            pygame.draw.polygon(screen, icon_color, [
                (cx - 5, cy - 5), (cx - 5, cy + 5), (cx + 5, cy + 5), (cx + 5, cy - 5)
            ])
            pygame.draw.polygon(screen, icon_color, [
                (cx + 5, cy - 5), (cx + 12, cy - 10), (cx + 12, cy + 10), (cx + 5, cy + 5)
            ])
        else:
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

def make_items(names):
    sizes = {"table": (280, 130), "chair": (150, 170), "cup": (80, 80), "box": (190, 150), "ball": (80, 80), "book": (130, 80)}
    colors = {"table": (222, 200, 150), "chair": (190, 210, 235), "cup": (240, 220, 235), "box": (215, 235, 210), "ball": (250, 210, 170), "book": (210, 220, 250)}
    items = {}
    for n in names:
        w, h = sizes[n]
        x = random.randint(50, V_WIDTH - w - 50)
        y = random.randint(HEADER_H + 50, V_HEIGHT - h - 50)
        items[n] = Item(n, x, y, w, h, colors.get(n, LAVENDER))
    return items


def draw_hint_card(surface, body_text, loading, title_font, body_font):
    if not loading and not body_text:
        return

    card_rect = pygame.Rect(V_WIDTH - 460, V_HEIGHT - 170, 420, 120)
    pad = 14
    title_gap = 6
    body = "Думаю над подсказкой..." if loading else body_text

    pygame.draw.rect(surface, SHADOW_FILL, card_rect.move(3, 4), border_radius=16)
    pygame.draw.rect(surface, WHITE, card_rect, border_radius=16)
    pygame.draw.rect(surface, PURPLE, card_rect, 2, border_radius=16)

    title = title_font.render("Подсказка", True, PURPLE)
    surface.blit(title, (card_rect.x + pad, card_rect.y + pad))

    y = card_rect.y + pad + title.get_height() + title_gap
    for line in wrap_text_lines(body, body_font, card_rect.w - pad * 2)[:3]:
        txt = body_font.render(line, True, TEXT_COLOR)
        surface.blit(txt, (card_rect.x + pad, y))
        y += txt.get_height() + 4

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

    font_xl = _best_font(42, bold=True)
    font_lg = _best_font(32)
    font_md = _best_font(24)
    font_sm = _best_font(20)

    # UI Buttons (pastel palette)
    btn_y = 30
    btn_check  = Button(V_WIDTH - (4 * (BTN_W + 10)) - 20, btn_y, BTN_W, BTN_H, "Check", bg_color=LAVENDER, text_color=TEXT_DARK)
    btn_reset  = Button(V_WIDTH - (3 * (BTN_W + 10)) - 20, btn_y, BTN_W, BTN_H, "Reset", bg_color=LAVENDER, text_color=TEXT_DARK)
    btn_hint   = Button(V_WIDTH - (2 * (BTN_W + 10)) - 20, btn_y, BTN_W, BTN_H, "Hint", bg_color=PINK, text_color=CREAM)
    btn_next   = Button(V_WIDTH - (1 * (BTN_W + 10)) - 20, btn_y, BTN_W, BTN_H, "Next", bg_color=PURPLE, text_color=CREAM)

    btn_speaker = Button(0, 0, 50, 50, "", bg_color=PINK, text_color=CREAM, icon_only=True)

    btn_restart = Button(V_WIDTH // 2 - 160, V_HEIGHT // 2 + 80, 320, 60, "Сыграть снова", bg_color=PURPLE, text_color=CREAM)

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
        items = make_items(data["items"])
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

            canvas.fill(BG_COLOR)
            pygame.draw.rect(canvas, PINK, (0, 0, V_WIDTH, HEADER_H - 8))
            pygame.draw.rect(canvas, LIGHT_P, (0, HEADER_H - 8, V_WIDTH, 8))
            pygame.draw.line(canvas, LAVENDER, (0, HEADER_H), (V_WIDTH, HEADER_H), 2)

            # Score (left) + example counter (center)
            score_surf = font_lg.render(f"Счёт: {score}/{len(SCENARIOS)}", True, TEXT_COLOR)
            canvas.blit(score_surf, (30, 45))

            ex_surf = font_xl.render(f"{idx + 1}/{len(SCENARIOS)}", True, TEXT_COLOR)
            canvas.blit(ex_surf, ex_surf.get_rect(center=(V_WIDTH // 2, 60)))

            if not game_over:
                btn_hint.label = "Thinking..." if hint_session.hint_loading else "Hint"
                for b in [btn_check, btn_reset, btn_hint, btn_next]:
                    b.draw(canvas, font_md)

            if not game_over:
                instr_rect_area = pygame.Rect(100, 95, V_WIDTH - 200, 60)
                text_bounds = draw_text_wrapped(canvas, text_instr, font_lg, MUTED_COLOR, instr_rect_area)

                # Update speaker button pos to be left of text
                btn_speaker.rect.x = text_bounds.x - 60
                btn_speaker.rect.y = text_bounds.centery - 25
                btn_speaker.draw(canvas, font_md)

            if not game_over and not (hint_session.hint_loading or hint_session.hint_text):
                hint_surf = font_sm.render("Перетащите объекты, следуя инструкции.", True, MUTED_COLOR)
                canvas.blit(hint_surf, (V_WIDTH - hint_surf.get_width() - 20, V_HEIGHT - 30))

            # Final score overlay (pastel)
            if game_over:
                overlay = pygame.Surface((V_WIDTH, V_HEIGHT), pygame.SRCALPHA)
                overlay.fill((58, 50, 72, 140))
                canvas.blit(overlay, (0, 0))

                panel = pygame.Rect(V_WIDTH // 2 - 360, V_HEIGHT // 2 - 160, 720, 320)
                panel_surf = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
                panel_surf.fill((*CREAM, 250))
                canvas.blit(panel_surf, panel.topleft)
                pygame.draw.rect(canvas, PURPLE, panel, 2, border_radius=20)

                done_title = font_xl.render("Игра окончена!", True, TEXT_COLOR)
                canvas.blit(done_title, done_title.get_rect(center=(V_WIDTH // 2, panel.top + 70)))

                score_big = font_xl.render(f"Ваш счёт: {score} / {len(SCENARIOS)}", True, PURPLE)
                canvas.blit(score_big, score_big.get_rect(center=(V_WIDTH // 2, panel.top + 140)))

                tip = font_md.render("Нажмите «Сыграть снова», чтобы начать заново.", True, MUTED_COLOR)
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
                fb_surf = font_xl.render(feedback, True, feedback_col)
                fb_rect = fb_surf.get_rect(center=(V_WIDTH // 2, V_HEIGHT - 95))
                bg_rect = fb_rect.inflate(40, 20)
                s = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
                s.fill((*LAVENDER, 248))
                canvas.blit(s, bg_rect.topleft)
                pygame.draw.rect(canvas, PURPLE, bg_rect, 2, border_radius=16)
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
