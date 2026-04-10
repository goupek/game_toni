"""launcher.py  —  Unified entry point for the Russian Learning Games.

Pastel candy UI: palette #9C89B8, #F0A6CA, #EFC3E6, #F0E6EF, #B8BEDD.
Design resolution 1280×720; soft shadows, rounded shapes, mascot.

Flow: Home → Level Test → A1/A2 Hub → Game (subprocess) → back to Hub.
"""

import os
import sys
import json
import math
import random
import subprocess
import pygame
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
_HERE  = Path(__file__).resolve().parent
_ROOT  = _HERE.parent
PYTHON = sys.executable
PROFILE_FILE = _HERE / "player_profile.json"

CMD: dict[str, list[str]] = {
    "level_test":   [PYTHON, str(_HERE / "lvl_game_connected.py")],
    "game_animals": [PYTHON, str(_ROOT / "main.py")],
    "game_colors":  [PYTHON, str(_HERE / "game2_connected.py")],
    "game_words":   [PYTHON, str(_ROOT / "game3.py")],
}

# ── design resolution (prompt: 1280×720) ────────────────────────────────────────
DW, DH = 1280, 720
FPS    = 60

# ── palette (exact hex) ──────────────────────────────────────────────────────
PURPLE   = (156, 137, 184)   # #9C89B8  primary accent, badge, shadows
PINK     = (240, 166, 202)   # #F0A6CA  header, progress fill, mascot body
LIGHT_P  = (239, 195, 230)   # #EFC3E6  gradient bottom, secondary btn
CREAM    = (240, 230, 239)   # #F0E6EF  background, text on dark
LAVENDER = (184, 190, 221)   # #B8BEDD  level card, exit, cloud blobs

# Dark purple-gray text (derived from PURPLE, no harsh black)
TEXT_DARK = (58, 50, 72)
TEXT_DARK_80 = (78, 68, 95)

def _alpha(c: tuple, a: float) -> tuple:
    """Return (r,g,b) blended with CREAM for ~opacity on light bg, or use for surfaces."""
    r = int(c[0] * a + CREAM[0] * (1 - a))
    g = int(c[1] * a + CREAM[1] * (1 - a))
    b = int(c[2] * a + CREAM[2] * (1 - a))
    return (r, g, b)


def _sc(v: float, s: float) -> int:
    return max(1, int(v * s))


def _best_font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ("Nunito", "Baloo 2", "Ubuntu", "Noto Sans", "DejaVu Sans", "Arial", ""):
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f:
                return f
        except Exception:
            pass
    return pygame.font.Font(None, size)


def load_profile() -> dict | None:
    try:
        if PROFILE_FILE.exists():
            return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _make_env() -> dict:
    e = os.environ.copy()
    if Path("/usr/lib/x86_64-linux-gnu/dri").exists():
        e["LIBGL_DRIVERS_PATH"] = "/usr/lib/x86_64-linux-gnu/dri"
    return e


def _wrap(text: str, font: pygame.font.Font, max_w: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        cand = (line + " " + word).strip()
        if font.size(cand)[0] <= max_w:
            line = cand
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


# ── drawing helpers ───────────────────────────────────────────────────────────

def _draw_soft_shadow(surf: pygame.Surface, rect: pygame.Rect, radius: int,
                      color: tuple = PURPLE, alpha: float = 0.25, y_offset: int = 10,
                      blur_steps: int = 5):
    """Approximate blur 24px, y-offset 10px, color at alpha."""
    for i in range(blur_steps):
        o = y_offset + i * 2
        a = alpha * (1.0 - i * 0.2)
        if a <= 0:
            break
        r2 = pygame.Rect(rect.x - i * 2, rect.y + o, rect.w + i * 4, rect.h + i * 2)
        s = pygame.Surface((r2.w + 4, r2.h + 4))
        s.set_colorkey((0, 0, 0))
        s.fill((0, 0, 0))
        pygame.draw.rect(s, color, (2, 2, r2.w, r2.h), border_radius=radius + i)
        s.set_alpha(int(255 * a))
        surf.blit(s, (r2.x - 2, r2.y - 2))


def _draw_rounded_rect_alpha(surf: pygame.Surface, rect: pygame.Rect,
                             color: tuple, radius: int, alpha: float):
    s = pygame.Surface((rect.w + radius * 2, rect.h + radius * 2))
    s.set_colorkey((0, 0, 0))
    s.fill((0, 0, 0))
    pygame.draw.rect(s, color, (radius, radius, rect.w, rect.h), border_radius=radius)
    s.set_alpha(int(255 * alpha))
    surf.blit(s, (rect.x - radius, rect.y - radius))


def _draw_gradient_rect(surf: pygame.Surface, rect: pygame.Rect,
                        top_color: tuple, bottom_color: tuple, radius: int = 0):
    """Draw vertical gradient; then punch out corners with CREAM for rounded effect if radius > 0."""
    steps = max(1, rect.h // 2)
    for i in range(steps + 1):
        t = i / steps
        r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
        g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
        b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
        y = rect.y + int(rect.h * i / steps)
        h = max(1, rect.y + int(rect.h * (i + 1) / steps) - y)
        pygame.draw.rect(surf, (r, g, b), (rect.x, y, rect.w, h))
    if radius > 0:
        for (cx, cy) in [
            (rect.x + radius, rect.y + radius),
            (rect.right - radius, rect.y + radius),
            (rect.x + radius, rect.bottom - radius),
            (rect.right - radius, rect.bottom - radius),
        ]:
            pygame.draw.circle(surf, CREAM, (cx, cy), radius)


def _draw_progress_fill(surf: pygame.Surface, bar_rect: pygame.Rect,
                        progress: float, fill_color: tuple, radius: int):
    """Fill with smooth rounded end (left and right rounded)."""
    if progress <= 0.01:
        return
    w = max(radius * 2, int(bar_rect.w * min(progress, 1.0)))
    r = pygame.Rect(bar_rect.x, bar_rect.y, w, bar_rect.h)
    pygame.draw.rect(surf, fill_color, r, border_radius=radius)


def _draw_play_icon(surf: pygame.Surface, cx: int, cy: int, radius: int,
                    circle_alpha: float = 0.3, color: tuple = CREAM):
    col_circle = _alpha(color, circle_alpha)
    pygame.draw.circle(surf, col_circle, (cx, cy), radius)
    # triangle pointing right
    tri_r = radius - 6
    pts = [
        (cx - tri_r + 4, cy - tri_r),
        (cx - tri_r + 4, cy + tri_r),
        (cx + tri_r - 2, cy),
    ]
    pygame.draw.polygon(surf, color, pts)


def _draw_refresh_icon(surf: pygame.Surface, cx: int, cy: int, r: int, color: tuple = PURPLE):
    pygame.draw.circle(surf, color, (cx, cy), r, 2)
    # simple curved arrow: small arc + arrowhead
    for angle in range(-120, 91, 30):
        rad = math.radians(angle)
        x = cx + (r - 2) * math.cos(rad)
        y = cy + (r - 2) * math.sin(rad)
        pygame.draw.circle(surf, color, (int(x), int(y)), 2)
    pygame.draw.polygon(surf, color, [
        (cx + r - 4, cy - 6), (cx + r + 2, cy), (cx + r - 4, cy + 6)
    ])


def _draw_door_icon(surf: pygame.Surface, cx: int, cy: int, w: int, h: int, color: tuple = PURPLE):
    pygame.draw.rect(surf, color, (cx - w // 2, cy - h // 2, w, h), 2)
    pygame.draw.rect(surf, color, (cx - w // 2 + 2, cy - h // 2 + 2, w // 2 - 2, h - 4))


def _draw_star_small(surf: pygame.Surface, cx: int, cy: int, r: int, color: tuple):
    pts = []
    for i in range(5 * 2):
        angle = math.pi / 5 * i - math.pi / 2
        rad = r if i % 2 == 0 else r * 0.4
        pts.append((cx + rad * math.cos(angle), cy + rad * math.sin(angle)))
    if len(pts) >= 3:
        pygame.draw.polygon(surf, color, pts)


def _draw_avatar_sticker_shadow(surf: pygame.Surface, cx: int, cy: int, radius: int):
    """Soft drop shadow for sticker avatars: blur 10–14px, 15% opacity. Centered 6px below."""
    shadow_cy = cy + 6
    for i in range(4):
        r2 = radius + 6 + i * 2
        a = 0.15 * (1.0 - i * 0.22)
        if a <= 0:
            break
        s = pygame.Surface((r2 * 2 + 8, r2 * 2 + 8))
        s.set_colorkey((0, 0, 0))
        s.fill((0, 0, 0))
        pygame.draw.circle(s, PURPLE, (r2 + 4, r2 + 4), r2)
        s.set_alpha(int(255 * a))
        surf.blit(s, (cx - r2 - 4, shadow_cy - r2 - 4))


def _draw_avatar_animal(surf: pygame.Surface, cx: int, cy: int, radius: int):
    """Kawaii baby bunny face: rounded ears, dot eyes, gentle smile, blush. Palette only."""
    # All sizes relative to radius (same footprint as circle)
    face_r = int(radius * 0.88)
    outline_w = max(1, radius // 20)
    # Ears (rounded, above head)
    ear_w, ear_h = int(radius * 0.35), int(radius * 0.6)
    ear_y = cy - face_r - ear_h // 3
    for dx in (-1, 1):
        ex = cx + dx * int(radius * 0.52)
        er = pygame.Rect(ex - ear_w // 2, ear_y - ear_h, ear_w, ear_h)
        pygame.draw.ellipse(surf, PINK, er)
        pygame.draw.ellipse(surf, PURPLE, er, outline_w)
    # Face circle
    pygame.draw.circle(surf, PINK, (cx, cy), face_r)
    pygame.draw.circle(surf, PURPLE, (cx, cy), face_r, outline_w)
    # Eyes (simple ovals, dark purple-gray)
    eye_w, eye_h = int(radius * 0.18), int(radius * 0.22)
    for ex in (cx - int(radius * 0.28), cx + int(radius * 0.28)):
        ey = cy - int(radius * 0.12)
        pygame.draw.ellipse(surf, TEXT_DARK, (ex - eye_w // 2, ey - eye_h // 2, eye_w, eye_h))
    # Nose (tiny)
    nose_r = radius // 8
    pygame.draw.circle(surf, PURPLE, (cx, cy + int(radius * 0.08)), nose_r)
    # Smile (gentle arc)
    smile_y = cy + int(radius * 0.28)
    smile_w = int(radius * 0.35)
    for i in range(max(1, smile_w // 2)):
        t = i / max(1, smile_w // 2)
        x = cx - smile_w // 2 + i
        y = smile_y + int(4 * (1 - 4 * (t - 0.5) ** 2))
        pygame.draw.circle(surf, PURPLE, (x, y), outline_w)
    # Cheeks (blush)
    cheek_r = int(radius * 0.18)
    pygame.draw.circle(surf, LIGHT_P, (cx - int(radius * 0.5), cy + int(radius * 0.15)), cheek_r)
    pygame.draw.circle(surf, LIGHT_P, (cx + int(radius * 0.5), cy + int(radius * 0.15)), cheek_r)
    # Accent: small star near right ear
    star_cx = cx + int(radius * 0.72)
    star_cy = cy - int(radius * 0.55)
    _draw_star_small(surf, star_cx, star_cy, int(radius * 0.18), LAVENDER)


def _draw_avatar_robot(surf: pygame.Surface, cx: int, cy: int, radius: int):
    """Cute robot / little teacher: rounded head, antenna, screen face, floating 1 and heart."""
    head_r = int(radius * 0.9)
    outline_w = max(1, radius // 20)
    # Head
    pygame.draw.circle(surf, LAVENDER, (cx, cy), head_r)
    pygame.draw.circle(surf, PURPLE, (cx, cy), head_r, outline_w)
    # Antenna
    ant_y = cy - head_r - int(radius * 0.15)
    pygame.draw.line(surf, PURPLE, (cx, cy - head_r), (cx, ant_y), outline_w)
    pygame.draw.circle(surf, PINK, (cx, ant_y), int(radius * 0.12))
    pygame.draw.circle(surf, PURPLE, (cx, ant_y), int(radius * 0.12), outline_w)
    # Screen/face area (rounded rect inside head)
    screen_w, screen_h = int(radius * 0.9), int(radius * 0.5)
    screen_r = pygame.Rect(cx - screen_w // 2, cy - screen_h // 2 - int(radius * 0.08), screen_w, screen_h)
    pygame.draw.rect(surf, CREAM, screen_r, border_radius=int(radius * 0.2))
    pygame.draw.rect(surf, PURPLE, screen_r, outline_w, border_radius=int(radius * 0.2))
    # Smile on screen (simple curve)
    sy = cy + int(radius * 0.05)
    for i in range(screen_w // 2):
        t = i / max(1, screen_w // 2)
        x = screen_r.x + 4 + i * 2
        y = sy + int(6 * (1 - 4 * (t - 0.5) ** 2))
        pygame.draw.circle(surf, PURPLE, (x, y), outline_w)
    # Two dot eyes on screen
    pygame.draw.circle(surf, TEXT_DARK, (cx - int(radius * 0.2), cy - int(radius * 0.18)), outline_w * 2)
    pygame.draw.circle(surf, TEXT_DARK, (cx + int(radius * 0.2), cy - int(radius * 0.18)), outline_w * 2)
    # Floating accents: "1" and heart (simple rounded)
    acc_r = int(radius * 0.2)
    # "1" in PINK to the left
    one_cx, one_cy = cx - int(radius * 0.85), cy - int(radius * 0.5)
    try:
        f = _best_font(max(10, acc_r * 2), bold=True)
        lbl = f.render("1", True, PINK)
        surf.blit(lbl, lbl.get_rect(center=(one_cx, one_cy)))
    except Exception:
        pygame.draw.circle(surf, PINK, (one_cx, one_cy), acc_r // 2)
    # Heart (two circles + triangle) in LIGHT_P
    heart_cx, heart_cy = cx + int(radius * 0.82), cy - int(radius * 0.48)
    hr = acc_r // 2
    pygame.draw.circle(surf, LIGHT_P, (heart_cx - hr // 2, heart_cy - hr // 2), hr)
    pygame.draw.circle(surf, LIGHT_P, (heart_cx + hr // 2, heart_cy - hr // 2), hr)
    pts = [(heart_cx, heart_cy + hr), (heart_cx - hr - 2, heart_cy - 2), (heart_cx + hr + 2, heart_cy - 2)]
    pygame.draw.polygon(surf, LIGHT_P, pts)
    pygame.draw.polygon(surf, PURPLE, pts, min(1, outline_w))


def _draw_mascot(surf: pygame.Surface, x: int, y: int, scale: float):
    """Simple rounded mascot peeking from bottom-left; ~140px tall at scale 1."""
    h = _sc(140, scale)
    head_r = int(h * 0.38)
    body_w = int(h * 0.7)
    body_h = int(h * 0.5)
    cx = x + head_r + 8
    cy = y + h - head_r - 4
    # body (oval) behind head
    body_rect = pygame.Rect(cx - body_w // 2, cy - body_h // 2 + head_r // 2, body_w, body_h)
    pygame.draw.ellipse(surf, PINK, body_rect)
    pygame.draw.ellipse(surf, PURPLE, body_rect, 2)
    # head
    pygame.draw.circle(surf, PINK, (cx, cy - head_r // 2), head_r)
    pygame.draw.circle(surf, PURPLE, (cx, cy - head_r // 2), head_r, 2)
    # cheeks
    pygame.draw.circle(surf, LIGHT_P, (cx - head_r // 2, cy - head_r // 2 + 4), head_r // 4)
    pygame.draw.circle(surf, LIGHT_P, (cx + head_r // 2, cy - head_r // 2 + 4), head_r // 4)
    # eyes (two dots)
    pygame.draw.circle(surf, PURPLE, (cx - head_r // 4, cy - head_r // 2 - 4), 3)
    pygame.draw.circle(surf, PURPLE, (cx + head_r // 4, cy - head_r // 2 - 4), 3)


def _title_with_spacing(surf: pygame.Surface, text: str, font: pygame.font.Font,
                        color: tuple, cx: int, cy: int, letter_spacing: int = 1):
    """Render title with letter spacing; center at (cx, cy)."""
    total_w = sum(font.size(c)[0] for c in text) + letter_spacing * max(0, len(text) - 1)
    x = cx - total_w // 2
    for c in text:
        lbl = font.render(c, True, color)
        surf.blit(lbl, (x, cy - lbl.get_height() // 2))
        x += font.size(c)[0] + letter_spacing


def center_text(surf: pygame.Surface, text: str, font: pygame.font.Font,
               color: tuple, cx: int, cy: int):
    lbl = font.render(text, True, color)
    surf.blit(lbl, lbl.get_rect(center=(cx, cy)))


# ── Launcher ───────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self):
        pygame.init()
        info = pygame.display.Info()
        sw = min(info.current_w, DW)
        sh = min(info.current_h, DH)
        self.screen = pygame.display.set_mode((sw, sh), pygame.RESIZABLE)
        pygame.display.set_caption("Russian Learning Games")
        self.clock = pygame.time.Clock()
        self.profile = load_profile()
        self.state = "home"
        self.proc: subprocess.Popen | None = None
        self._env = _make_env()
        self._tick = 0
        self._hover: str | None = None
        self._press: str | None = None  # for pressed state (sink)
        self._pending_click: tuple[int, int] | None = None  # resolve _press when we have rects
        self._bar = 0.0  # progress bar animated (600ms ease-out target)

    def _scale(self) -> float:
        w, h = self.screen.get_size()
        return min(w / DW, h / DH)

    def _launch(self, key: str):
        self.proc = subprocess.Popen(CMD[key], cwd=str(_ROOT), env=self._env)
        self.state = "waiting" if key == "level_test" else "launching"

    def _poll(self):
        if self.proc is None or self.proc.poll() is None:
            return
        self.proc = None
        self.profile = load_profile()
        self._bar = 0.0
        if self.state == "waiting":
            if self.profile:
                level = self.profile.get("level", "A1")
                self.state = f"{level.lower()}_hub"
            else:
                self.state = "home"
        else:
            level = (self.profile or {}).get("level", "A1")
            self.state = f"{level.lower()}_hub"

    def draw_home(self) -> dict[str, pygame.Rect]:
        surf = self.screen
        w, h = surf.get_size()
        s = self._scale()
        # ── Background: solid CREAM + cloud blobs ─────────────────────────────
        surf.fill(CREAM)
        blob_opacity = 0.12
        blob_colors = [LIGHT_P, LAVENDER]
        for idx, (bx, by, bw, bh) in enumerate([
            (0, 0, _sc(320, s), _sc(280, s)),
            (w - _sc(280, s), 0, _sc(280, s), _sc(240, s)),
            (0, h - _sc(220, s), _sc(260, s), _sc(220, s)),
            (w - _sc(240, s), h - _sc(200, s), _sc(240, s), _sc(200, s)),
        ]):
            c = blob_colors[idx % 2]
            _draw_rounded_rect_alpha(surf, pygame.Rect(bx, by, bw, bh),
                                     c, _sc(80, s), blob_opacity)

        # ── Header: rounded banner, gradient, sparkles ────────────────────────
        margin = _sc(24, s)
        hdr_h = _sc(170, s)
        hdr_rect = pygame.Rect(margin, margin, w - 2 * margin, hdr_h - margin)
        _draw_soft_shadow(surf, hdr_rect, _sc(24, s), alpha=0.2, y_offset=6)
        _draw_gradient_rect(surf, hdr_rect, PINK, LIGHT_P, radius=_sc(24, s))
        # sparkles (dots) at 12% opacity
        rs = random.Random(42)
        for _ in range(24):
            sx = hdr_rect.x + rs.randint(0, hdr_rect.w - 1)
            sy = hdr_rect.y + rs.randint(0, hdr_rect.h - 1)
            pygame.draw.circle(surf, _alpha(CREAM, 0.12), (sx, sy), rs.randint(2, 4))
        # Title 64px extra-bold, letter-spacing +1, CREAM
        f_title = _best_font(_sc(64, s), bold=True)
        _title_with_spacing(surf, "Russian Learning Games", f_title, CREAM,
                            w // 2, margin + _sc(52, s), letter_spacing=_sc(1, s))
        f_sub = _best_font(_sc(28, s), bold=True)
        sub_color = _alpha(CREAM, 0.9)
        center_text(surf, "Учим русский вместе!", f_sub, sub_color,
                    w // 2, margin + _sc(108, s))

        btns: dict[str, pygame.Rect] = {}
        gap_40 = _sc(40, s)
        gap_36 = _sc(36, s)
        gap_22 = _sc(22, s)

        if self.profile:
            level = self.profile.get("level", "A1")
            a1_acc = self.profile.get("a1_accuracy") or 0.0
            a2_acc = self.profile.get("a2_accuracy")
            prog = a1_acc if level == "A1" else (a2_acc or 0.0)
            # Ease-out progress over ~600ms: quick start, slow end
            target = max(0.0, min(1.0, prog))
            self._bar += (target - self._bar) * 0.12
            if abs(self._bar - target) < 0.005:
                self._bar = target

            # ── Level Card 640×160, radius 32, bg LAVENDER ─────────────────────
            card_w, card_h = _sc(640, s), _sc(160, s)
            card = pygame.Rect((w - card_w) // 2, hdr_rect.bottom + gap_40, card_w, card_h)
            _draw_soft_shadow(surf, card, _sc(32, s), alpha=0.25, y_offset=_sc(10, s))
            pygame.draw.rect(surf, LAVENDER, card, border_radius=_sc(32, s))

            pad = _sc(36, s)
            f_label = _best_font(_sc(26, s), bold=True)
            surf.blit(f_label.render("Your Level", True, TEXT_DARK),
                      (card.x + pad, card.y + _sc(20, s)))
            # Pill badge 120×56, radius 28, PURPLE, "A1" + star
            pill_w, pill_h = _sc(120, s), _sc(56, s)
            pill = pygame.Rect(card.right - pad - pill_w, card.y + _sc(18, s), pill_w, pill_h)
            pygame.draw.rect(surf, PURPLE, pill, border_radius=_sc(28, s))
            center_text(surf, level, _best_font(_sc(30, s), bold=True), CREAM,
                        pill.centerx - _sc(10, s), pill.centery)
            _draw_star_small(surf, pill.centerx + _sc(28, s), pill.centery, _sc(8, s), CREAM)

            # Progress bar: full width minus padding, h 28, radius 14
            pb_y = card.y + _sc(78, s)
            pb_h = _sc(28, s)
            pb_rect = pygame.Rect(card.x + pad, pb_y, card.w - 2 * pad, pb_h)
            pygame.draw.rect(surf, CREAM, pb_rect, border_radius=_sc(14, s))
            _draw_progress_fill(surf, pb_rect, self._bar, PINK, _sc(14, s))
            pct_w = int(pb_rect.w * min(self._bar, 1.0))
            if pct_w > _sc(36, s):
                center_text(surf, f"{int(self._bar * 100)}%",
                            _best_font(_sc(18, s), bold=True), CREAM,
                            card.x + pad + pct_w // 2, pb_y + pb_h // 2)
            center_text(surf, "Keep going!", _best_font(_sc(20, s), bold=False),
                        _alpha(TEXT_DARK, 0.8), card.centerx, pb_y + pb_h + _sc(18, s))

            # ── Play button: 560×96, radius 36, PURPLE, lift/sink, breathing ───
            play_w, play_h = _sc(560, s), _sc(96, s)
            play_y_base = card.bottom + gap_36
            hovered = self._hover == "go"
            pressed = self._press == "go"
            lift = 2 if hovered and not pressed else (-2 if pressed else 0)
            play_y = play_y_base + lift
            go_rect = pygame.Rect((w - play_w) // 2, play_y, play_w, play_h)
            # Breathing glow 8% opacity
            breath = 0.92 + 0.08 * math.sin(self._tick * 0.04)
            glow_r = pygame.Rect(go_rect.x - 4, go_rect.y - 4, go_rect.w + 8, go_rect.h + 8)
            s_glow = pygame.Surface((glow_r.w + 8, glow_r.h + 8))
            s_glow.set_alpha(int(255 * 0.08 * breath))
            s_glow.fill(PURPLE)
            surf.blit(s_glow, (glow_r.x - 4, glow_r.y - 4))
            _draw_soft_shadow(surf, go_rect, _sc(36, s), alpha=0.3 if hovered else 0.25,
                             y_offset=12 if hovered else 10)
            btn_bg = LAVENDER if hovered and not pressed else (PURPLE if not pressed else _alpha(PURPLE, 0.85))
            pygame.draw.rect(surf, btn_bg, go_rect, border_radius=_sc(36, s))
            # Play icon left: circle 52px CREAM 30%, triangle CREAM
            icon_cx = go_rect.x + _sc(68, s)
            icon_cy = go_rect.centery
            _draw_play_icon(surf, icon_cx, icon_cy, _sc(26, s), 0.3, CREAM)
            f_play = _best_font(_sc(34, s), bold=True)
            lbl = f_play.render(f"Play Level {level} Games", True, CREAM)
            surf.blit(lbl, (go_rect.x + _sc(120, s), go_rect.centery - lbl.get_height() // 2))
            btns["go"] = go_rect

            # ── Retake: 420×72, radius 28, LIGHT_P, border PURPLE 35% ──────────
            ret_w, ret_h = _sc(420, s), _sc(72, s)
            ret_rect = pygame.Rect((w - ret_w) // 2, go_rect.bottom + gap_22, ret_w, ret_h)
            pygame.draw.rect(surf, LIGHT_P, ret_rect, border_radius=_sc(28, s))
            border_color = (
                int(PURPLE[0] * 0.35 + LIGHT_P[0] * 0.65),
                int(PURPLE[1] * 0.35 + LIGHT_P[1] * 0.65),
                int(PURPLE[2] * 0.35 + LIGHT_P[2] * 0.65),
            )
            pygame.draw.rect(surf, border_color, ret_rect, 3, border_radius=_sc(28, s))
            _draw_refresh_icon(surf, ret_rect.x + _sc(44, s), ret_rect.centery, _sc(14, s))
            center_text(surf, "Retake Level Test", _best_font(_sc(24, s), bold=True),
                        TEXT_DARK, ret_rect.centerx + _sc(12, s), ret_rect.centery)
            btns["retake_home"] = ret_rect

        else:
            # First visit: card + Start Level Test button (same style as Play)
            card_w, card_h = _sc(640, s), _sc(120, s)
            card = pygame.Rect((w - card_w) // 2, hdr_rect.bottom + gap_40, card_w, card_h)
            pygame.draw.rect(surf, LAVENDER, card, border_radius=_sc(32, s))
            center_text(surf, "First, let us find out your Russian level!",
                        _best_font(_sc(26, s), bold=True), TEXT_DARK, w // 2, card.centery)

            play_w, play_h = _sc(560, s), _sc(96, s)
            play_y = card.bottom + gap_36
            st_rect = pygame.Rect((w - play_w) // 2, play_y, play_w, play_h)
            _draw_soft_shadow(surf, st_rect, _sc(36, s), alpha=0.25)
            pygame.draw.rect(surf, PURPLE, st_rect, border_radius=_sc(36, s))
            _draw_play_icon(surf, st_rect.x + _sc(68, s), st_rect.centery, _sc(26, s), 0.3, CREAM)
            center_text(surf, "Start Level Test", _best_font(_sc(34, s), bold=True),
                        CREAM, st_rect.centerx + _sc(20, s), st_rect.centery)
            btns["start"] = st_rect

        # ── Exit: 160×64, radius 22, LAVENDER, 28px margin, door icon ───────────
        exit_margin = _sc(28, s)
        ew, eh = _sc(160, s), _sc(64, s)
        ex_rect = pygame.Rect(w - ew - exit_margin, h - eh - exit_margin, ew, eh)
        pygame.draw.rect(surf, LAVENDER, ex_rect, border_radius=_sc(22, s))
        _draw_door_icon(surf, ex_rect.x + _sc(28, s), ex_rect.centery, _sc(18, s), _sc(22, s), PURPLE)
        center_text(surf, "Exit", _best_font(_sc(22, s), bold=True), TEXT_DARK,
                    ex_rect.centerx + _sc(14, s), ex_rect.centery)
        btns["exit"] = ex_rect

        # ── Mascot bottom-left, ~140px ────────────────────────────────────────
        _draw_mascot(surf, _sc(8, s), h - _sc(148, s), s)

        # Resolve pressed state from pending click (so we don't draw in event loop)
        if self._pending_click is not None:
            for key, r in btns.items():
                if r.collidepoint(self._pending_click):
                    self._press = key
                    break
            self._pending_click = None
        return btns

    def draw_hub(self, level: str) -> dict[str, pygame.Rect]:
        surf = self.screen
        w, h = surf.get_size()
        s = self._scale()
        surf.fill(CREAM)
        for idx, (bx, by, bw, bh) in enumerate([
            (0, 0, _sc(280, s), _sc(220, s)),
            (w - _sc(260, s), 0, _sc(260, s), _sc(200, s)),
            (0, h - _sc(180, s), _sc(240, s), _sc(180, s)),
        ]):
            _draw_rounded_rect_alpha(surf, pygame.Rect(bx, by, bw, bh),
                                     [LIGHT_P, LAVENDER][idx % 2], _sc(60, s), 0.12)

        hdr_h = _sc(100, s)
        pygame.draw.rect(surf, PURPLE, (0, 0, w, hdr_h))
        center_text(surf, f"Level {level} — Choose a Game",
                    _best_font(_sc(32, s), bold=True), CREAM, w // 2, hdr_h // 2)

        btns = {}
        cw, ch = _sc(380, s), _sc(340, s)
        gap = _sc(32, s)
        cy = hdr_h + _sc(24, s)
        x1 = (w - cw * 2 - gap) // 2
        x2 = x1 + cw + gap
        avatar_radius = _sc(40, s)
        for pos_x, (cmd_key, title, desc) in zip([x1, x2], self._card_defs(level)):
            r = pygame.Rect(pos_x, cy, cw, ch)
            _draw_soft_shadow(surf, r, _sc(20, s), alpha=0.2)
            pygame.draw.rect(surf, LAVENDER, r, border_radius=_sc(20, s))
            icx, icy = pos_x + cw // 2, cy + _sc(64, s)
            _draw_avatar_sticker_shadow(surf, icx, icy, avatar_radius)
            if cmd_key == "game_colors":
                _draw_avatar_robot(surf, icx, icy, avatar_radius)
            else:
                _draw_avatar_animal(surf, icx, icy, avatar_radius)
            center_text(surf, title, _best_font(_sc(22, s), bold=True), TEXT_DARK, icx, cy + _sc(128, s))
            for i, line in enumerate(_wrap(desc, _best_font(_sc(15, s)), cw - _sc(32, s))[:3]):
                center_text(surf, line, _best_font(_sc(15, s)), TEXT_DARK_80, icx, cy + _sc(158, s) + i * _sc(20, s))
            pb = pygame.Rect(pos_x + (cw - _sc(140, s)) // 2, cy + ch - _sc(64, s), _sc(140, s), _sc(52, s))
            pygame.draw.rect(surf, PURPLE, pb, border_radius=_sc(26, s))
            center_text(surf, "Play!", _best_font(_sc(22, s), bold=True), CREAM, pb.centerx, pb.centery)
            btns[f"play_{cmd_key}"] = pb

        bar_y = cy + ch + _sc(16, s)
        hb = pygame.Rect(_sc(28, s), bar_y, _sc(120, s), _sc(52, s))
        pygame.draw.rect(surf, LAVENDER, hb, border_radius=_sc(22, s))
        center_text(surf, "Home", _best_font(_sc(20, s), bold=True), TEXT_DARK, hb.centerx, hb.centery)
        btns["hub_home"] = hb
        rb = pygame.Rect(w - _sc(220, s) - _sc(28, s), bar_y, _sc(220, s), _sc(52, s))
        pygame.draw.rect(surf, LIGHT_P, rb, border_radius=_sc(22, s))
        pygame.draw.rect(surf, PURPLE, rb, 2, border_radius=_sc(22, s))
        center_text(surf, "Retake Level Test", _best_font(_sc(18, s), bold=True), TEXT_DARK, rb.centerx, rb.centery)
        btns["retake_hub"] = rb
        if self._pending_click is not None:
            for key, r in btns.items():
                if r.collidepoint(self._pending_click):
                    self._press = key
                    break
            self._pending_click = None
        return btns

    def _card_defs(self, level: str) -> list[tuple]:
        game2 = ("game_colors", "Colors & Numbers", "Count objects and identify colours in pictures.")
        if level == "A1":
            return [("game_animals", "Animal Game", "Match animal images to their Russian names!"), game2]
        return [("game_words", "Word Positions", "Learn Russian cases and prepositions with scenes."), game2]

    def draw_waiting(self, msg: str = "Finding Your Level...", sub: str = "Complete the test window to continue"):
        surf = self.screen
        w, h = surf.get_size()
        s = self._scale()
        surf.fill(CREAM)
        for (bx, by, bw, bh) in [
            (0, 0, _sc(300, s), _sc(260, s)),
            (w - _sc(280, s), h - _sc(240, s), _sc(280, s), _sc(240, s)),
        ]:
            _draw_rounded_rect_alpha(surf, pygame.Rect(bx, by, bw, bh), LIGHT_P, _sc(70, s), 0.12)
        center_text(surf, msg, _best_font(_sc(36, s), bold=True), TEXT_DARK, w // 2, h // 2 - _sc(40, s))
        center_text(surf, sub, _best_font(_sc(20, s)), TEXT_DARK_80, w // 2, h // 2)
        for i in range(3):
            dx = int(math.sin(self._tick * 0.1 + i * 2.1) * _sc(12, s))
            pygame.draw.circle(surf, PINK, (w // 2 + (i - 1) * _sc(48, s), h // 2 + _sc(50, s) + dx), _sc(14, s))

    def run(self):
        while True:
            self._tick += 1
            events = pygame.event.get()
            clicks = []
            mouse_pos = pygame.mouse.get_pos()

            for ev in events:
                if ev.type == pygame.QUIT:
                    if self.proc:
                        self.proc.terminate()
                    pygame.quit()
                    sys.exit()
                if ev.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode((ev.w, ev.h), pygame.RESIZABLE)
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    clicks.append(ev.pos)
                    self._pending_click = ev.pos
                if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    self._press = None

            btns = {}
            if self.state == "home":
                btns = self.draw_home()
            elif self.state in ("a1_hub", "a2_hub"):
                btns = self.draw_hub("A1" if self.state == "a1_hub" else "A2")
            elif self.state == "waiting":
                self.draw_waiting()
                self._poll()
            elif self.state == "launching":
                self.draw_waiting(msg="Game Running...", sub="Close the game window to return here.")
                self._poll()

            self._hover = None
            for key, rect in btns.items():
                if rect.collidepoint(mouse_pos):
                    self._hover = key
                    break

            for pos in clicks:
                for key, rect in btns.items():
                    if rect.collidepoint(pos):
                        self._on_click(key)
                        break

            pygame.display.flip()
            self.clock.tick(FPS)

    def _on_click(self, key: str):
        if key == "exit":
            pygame.quit()
            sys.exit()
        elif key == "start":
            self._launch("level_test")
        elif key == "go":
            self.state = f"{(self.profile or {}).get('level', 'A1').lower()}_hub"
        elif key in ("retake_home", "retake_hub"):
            self._launch("level_test")
        elif key == "hub_home":
            self._bar = 0.0
            self.state = "home"
        elif key.startswith("play_"):
            self._launch(key[len("play_"):])


if __name__ == "__main__":
    Launcher().run()
