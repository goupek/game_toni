from __future__ import annotations

"""
Sharper styled pygame launcher for the Russian Learning Games.

Changes vs launcher_styled.py:
- draws directly at the real window size (no scaled 1280x720 canvas), so text stays sharp
- reorganized home screen spacing
- progress bar shortened and stats moved to the right of it
- exit button sits outside the main panel in the bottom-right corner
- keeps launcher flow / subprocess logic unchanged
"""

import json
import math
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pygame

# ── paths ────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
PYTHON = sys.executable
PROFILE_FILE = _HERE / "player_profile.json"
BOXY_PIPELINE = _ROOT / "pipeline_mem" / "g4-e2b-boxy_streaming.py"
BOXY_SILERO_MODEL = _ROOT / "models" / "silero" / "v5_ru.pt"


def _pick_script(*candidates: str) -> str:
    for name in candidates:
        here = _HERE / name
        root = _ROOT / name
        if here.exists():
            return str(here)
        if root.exists():
            return str(root)
    return str(_HERE / candidates[0])


CMD: dict[str, list[str]] = {
    "level_test": [PYTHON, _pick_script("lvl_game_connected_pygame_fixed.py", "lvl_game_connected_pygame.py", "lvl_game_connected.py")],
    "game_animals": [PYTHON, _pick_script("main.py")],
    "game_colors": [PYTHON, _pick_script("game2_connected_styled.py", "game2_connected.py")],
    "game_words": [PYTHON, _pick_script("game3.py")],
}

DW, DH = 1280, 720
FPS = 60
Color = Tuple[int, int, int]

# ── shared cartoon theme ────────────────────────────────────────────────────
BG_TOP: Color = (128, 183, 181)
BG_BOTTOM: Color = (109, 164, 172)
BG_POLY_1: Color = (117, 170, 166)
BG_POLY_2: Color = (100, 151, 160)
BG_POLY_3: Color = (92, 142, 154)

PANEL_FILL: Color = (229, 222, 189)
PANEL_BORDER: Color = (181, 156, 106)
PANEL_INNER: Color = (243, 237, 210)

RIBBON_FILL: Color = (236, 81, 127)
RIBBON_DARK: Color = (193, 48, 92)
RIBBON_LIGHT: Color = (248, 118, 157)

TEXT_DARK: Color = (77, 43, 64)
TEXT_SOFT: Color = (98, 70, 89)
TEXT_LIGHT: Color = (255, 248, 235)
OUTLINE_DARK: Color = (99, 61, 81)

SHADOW_SOFT: Color = (153, 136, 148)

BTN_BLUE: Color = (37, 205, 230)
BTN_BLUE_DARK: Color = (93, 86, 210)
BTN_GREEN: Color = (166, 231, 12)
BTN_GREEN_DARK: Color = (111, 179, 26)
BTN_RED: Color = (245, 112, 112)
BTN_RED_DARK: Color = (196, 58, 61)
BTN_YELLOW: Color = (251, 224, 64)
BTN_YELLOW_DARK: Color = (236, 174, 44)
BTN_CREAM: Color = (245, 240, 230)
BTN_CREAM_DARK: Color = (177, 163, 174)
BTN_ORANGE: Color = (255, 191, 53)
BTN_ORANGE_DARK: Color = (220, 139, 27)

HUD_CREAM: Color = (236, 231, 205)
HUD_BORDER: Color = (187, 173, 121)
SUCCESS_FILL: Color = (204, 245, 190)
ERROR_FILL: Color = (255, 213, 213)
INFO_FILL: Color = (217, 239, 255)


@lru_cache(maxsize=256)
def _best_font(size: int, bold: bool = False) -> pygame.font.Font:
    size = max(12, int(size))
    for name in ("Baloo 2", "Fredoka", "Nunito", "Ubuntu", "Noto Sans", "DejaVu Sans", "Arial", ""):
        try:
            f = pygame.font.SysFont(name, size, bold=bold)
            if f:
                return f
        except Exception:
            pass
    return pygame.font.Font(None, size)


def lighten(color: Color, amount: int) -> Color:
    return tuple(min(255, c + amount) for c in color)


def darken(color: Color, amount: int) -> Color:
    return tuple(max(0, c - amount) for c in color)


def wrap_text(text: str, font: pygame.font.Font, max_width: int) -> List[str]:
    words = str(text).split()
    lines: List[str] = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_shadow(surface: pygame.Surface, rect: pygame.Rect, radius: int, dy: int = 6):
    pygame.draw.rect(surface, SHADOW_SOFT, rect.move(0, dy), border_radius=radius)


def render_tracked_text(font: pygame.font.Font, text: str, color: Color, tracking: int = 1) -> pygame.Surface:
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


def draw_background(surface: pygame.Surface):
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
        (BG_POLY_1, [(w * 0.3, h * 0.45), (w * 0.52, h * 0.3), (w * 0.64, h * 0.58), (w * 0.42, h * 0.7)]),
    ]
    for color, pts in polys:
        pygame.draw.polygon(surface, color, pts)


def draw_panel(surface: pygame.Surface, rect: pygame.Rect, radius: int = 28):
    draw_shadow(surface, rect, radius, dy=8)
    pygame.draw.rect(surface, PANEL_FILL, rect, border_radius=radius)
    pygame.draw.rect(surface, PANEL_BORDER, rect, width=4, border_radius=radius)
    inner = rect.inflate(-10, -10)
    pygame.draw.rect(surface, PANEL_INNER, inner, width=2, border_radius=max(12, radius - 6))


def draw_ribbon_title(surface: pygame.Surface, text: str, panel_rect: pygame.Rect, font: pygame.font.Font, s: float):
    ribbon_h = max(56, int(72 * s))
    ribbon_w = int(panel_rect.w * 1.08)
    ribbon_x = panel_rect.centerx - ribbon_w // 2
    ribbon_y = panel_rect.y + max(18, int(22 * s))
    ribbon = pygame.Rect(ribbon_x, ribbon_y, ribbon_w, ribbon_h)

    tail_w = max(20, int(32 * s))
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

    draw_shadow(surface, ribbon, 0, dy=max(4, int(6 * s)))
    pygame.draw.rect(surface, RIBBON_FILL, ribbon)
    pygame.draw.rect(surface, RIBBON_LIGHT, pygame.Rect(ribbon.x, ribbon.y, ribbon.w, max(8, int(12 * s))))
    pygame.draw.line(surface, RIBBON_DARK, (ribbon.left, ribbon.bottom - 3), (ribbon.right, ribbon.bottom - 3), 3)

    txt = render_tracked_text(font, text, TEXT_LIGHT, tracking=1)
    tr = txt.get_rect(center=ribbon.center)
    surface.blit(txt, tr)


def draw_round_icon(surface: pygame.Surface, rect: pygame.Rect, icon: str, font: pygame.font.Font):
    pygame.draw.ellipse(surface, BTN_ORANGE_DARK, rect.move(0, 4))
    pygame.draw.ellipse(surface, BTN_ORANGE, rect)
    pygame.draw.ellipse(surface, lighten(BTN_ORANGE, 12), rect.inflate(-8, -8), width=2)
    pygame.draw.ellipse(surface, PANEL_BORDER, rect, width=2)
    txt = font.render(icon, True, TEXT_LIGHT)
    surface.blit(txt, txt.get_rect(center=rect.center))


def draw_badge(surface: pygame.Surface, rect: pygame.Rect, icon: str, value: str, font: pygame.font.Font, icon_font: pygame.font.Font):
    pygame.draw.rect(surface, HUD_CREAM, rect, border_radius=rect.h // 2)
    pygame.draw.rect(surface, HUD_BORDER, rect, width=2, border_radius=rect.h // 2)
    icon_rect = pygame.Rect(rect.x - rect.h // 3, rect.y - 4, rect.h + 8, rect.h + 8)
    draw_round_icon(surface, icon_rect, icon, icon_font)
    txt = render_tracked_text(font, str(value), TEXT_SOFT, tracking=1)
    center = (rect.x + int(rect.w * 0.58), rect.centery)
    surface.blit(txt, txt.get_rect(center=center))


def draw_button(surface: pygame.Surface, rect: pygame.Rect, label: str, fill: Color, depth: Color,
                font: pygame.font.Font, hovered: bool = False, pressed: bool = False,
                text_color: Color = TEXT_DARK):
    top_fill = lighten(fill, 10) if hovered else fill
    top_rect = rect.move(0, 3 if pressed else 0)
    depth_rect = rect.move(0, 7 if not pressed else 4)
    pygame.draw.rect(surface, depth, depth_rect, border_radius=max(14, rect.h // 4))
    pygame.draw.rect(surface, top_fill, top_rect, border_radius=max(14, rect.h // 4))
    pygame.draw.rect(surface, lighten(top_fill, 18), (top_rect.x + 6, top_rect.y + 5, top_rect.w - 12, min(12, top_rect.h // 3)), border_radius=10)
    pygame.draw.rect(surface, PANEL_BORDER, top_rect, width=2, border_radius=max(14, rect.h // 4))
    txt = render_tracked_text(font, label, text_color, tracking=1)
    tr = txt.get_rect(center=(top_rect.centerx, top_rect.centery))
    surface.blit(txt, tr)


def draw_feedback_pill(surface: pygame.Surface, rect: pygame.Rect, text: str, kind: str, font: pygame.font.Font):
    if kind == "success":
        fill, border = SUCCESS_FILL, BTN_GREEN_DARK
    elif kind == "error":
        fill, border = ERROR_FILL, BTN_RED_DARK
    else:
        fill, border = INFO_FILL, BTN_BLUE_DARK
    draw_shadow(surface, rect, rect.h // 2, dy=4)
    pygame.draw.rect(surface, fill, rect, border_radius=rect.h // 2)
    pygame.draw.rect(surface, border, rect, width=3, border_radius=rect.h // 2)
    txt = render_tracked_text(font, text, TEXT_DARK, tracking=1)
    surface.blit(txt, txt.get_rect(center=rect.center))


def draw_progress_bar(surface: pygame.Surface, rect: pygame.Rect, progress: float, font: pygame.font.Font):
    draw_shadow(surface, rect, rect.h // 2, dy=4)
    pygame.draw.rect(surface, HUD_CREAM, rect, border_radius=rect.h // 2)
    pygame.draw.rect(surface, HUD_BORDER, rect, width=2, border_radius=rect.h // 2)
    inner = rect.inflate(-10, -10)
    pygame.draw.rect(surface, BTN_CREAM, inner, border_radius=inner.h // 2)
    fill_w = max(inner.h, int(inner.w * max(0.0, min(progress, 1.0))))
    fill_rect = pygame.Rect(inner.x, inner.y, min(fill_w, inner.w), inner.h)
    pygame.draw.rect(surface, BTN_BLUE, fill_rect, border_radius=inner.h // 2)
    pygame.draw.rect(surface, BTN_BLUE_DARK, inner, width=2, border_radius=inner.h // 2)
    pct = render_tracked_text(font, f"{int(progress * 100)}%", TEXT_LIGHT, tracking=1)
    pct_x = inner.x + min(fill_rect.w, inner.w) // 2
    surface.blit(pct, pct.get_rect(center=(pct_x, inner.centery)))


def draw_avatar_bunny(surface: pygame.Surface, center: Tuple[int, int], radius: int):
    cx, cy = center
    face_r = int(radius * 0.88)
    outline_w = max(1, radius // 18)
    ear_w, ear_h = int(radius * 0.34), int(radius * 0.58)
    ear_y = cy - face_r - ear_h // 3
    for dx in (-1, 1):
        ex = cx + dx * int(radius * 0.52)
        er = pygame.Rect(ex - ear_w // 2, ear_y - ear_h, ear_w, ear_h)
        pygame.draw.ellipse(surface, RIBBON_LIGHT, er)
        pygame.draw.ellipse(surface, OUTLINE_DARK, er, outline_w)
    pygame.draw.circle(surface, RIBBON_LIGHT, (cx, cy - face_r // 2), face_r)
    pygame.draw.circle(surface, OUTLINE_DARK, (cx, cy - face_r // 2), face_r, outline_w)
    eye_r = max(2, radius // 14)
    pygame.draw.circle(surface, TEXT_DARK, (cx - face_r // 3, cy - int(face_r * 0.7)), eye_r)
    pygame.draw.circle(surface, TEXT_DARK, (cx + face_r // 3, cy - int(face_r * 0.7)), eye_r)
    pygame.draw.circle(surface, OUTLINE_DARK, (cx, cy - int(face_r * 0.42)), max(2, radius // 10))
    pygame.draw.arc(surface, OUTLINE_DARK, pygame.Rect(cx - radius // 3, cy - int(face_r * 0.25), int(radius * 0.66), radius // 2), 0.1, math.pi - 0.1, outline_w)


def load_profile() -> Optional[dict]:
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


class Launcher:
    def __init__(self):
        pygame.init()
        info = pygame.display.Info()
        sw = min(info.current_w, 1440)
        sh = min(info.current_h, 900)
        self.screen = pygame.display.set_mode((sw, sh), pygame.RESIZABLE)
        pygame.display.set_caption("Russian Learning Games")
        self.clock = pygame.time.Clock()

        self.profile = load_profile()
        self.state = "home"
        self.proc: subprocess.Popen | None = None
        self.chat_proc: subprocess.Popen | None = None
        self._env = _make_env()
        self._tick = 0
        self._hover: Optional[str] = None
        self._press: Optional[str] = None
        self._btns: Dict[str, pygame.Rect] = {}
        self._bar = 0.0
        self._chat_return_state = "home"
        self._chat_status = "Start Boxy and say \"Hello Boxy\" to begin."

    def _metrics(self):
        w, h = self.screen.get_size()
        s = min(w / DW, h / DH)
        return w, h, s

    def _fonts(self, s: float):
        return {
            "ribbon": _best_font(34 * s, True),
            "title": _best_font(28 * s, True),
            "big": _best_font(24 * s, True),
            "medium": _best_font(20 * s, True),
            "small": _best_font(17 * s, True),
            "tiny": _best_font(14 * s, False),
            "icon": _best_font(20 * s, True),
        }

    def _is_chat_running(self) -> bool:
        return self.chat_proc is not None and self.chat_proc.poll() is None

    def _open_chat(self):
        if self.state in {"home", "a1_hub", "a2_hub"}:
            self._chat_return_state = self.state
        self.state = "chat"

    def _launch_chat(self):
        if self._is_chat_running():
            self._chat_status = "Boxy is already running. Say \"Hello Boxy\" to wake it."
            return
        if not BOXY_PIPELINE.exists():
            self._chat_status = f"Assistant not found: {BOXY_PIPELINE.name}"
            return
        if not BOXY_SILERO_MODEL.exists():
            self._chat_status = f"TTS model not found: {BOXY_SILERO_MODEL.name}"
            return
        env = self._env.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self.chat_proc = subprocess.Popen([PYTHON, str(BOXY_PIPELINE)], cwd=str(_ROOT), env=env)
        self._chat_status = "Boxy is running. Microphone access and a llama.cpp server at localhost:8080 are required."

    def _stop_chat(self, announce: bool = True):
        if self.chat_proc is None:
            if announce:
                self._chat_status = "Boxy is already stopped."
            return
        proc = self.chat_proc
        self.chat_proc = None
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1.5)
            if announce:
                self._chat_status = "Voice assistant stopped."
        except Exception:
            if announce:
                self._chat_status = "Could not stop Boxy cleanly."

    def _poll_chat(self):
        if self.chat_proc is None:
            return
        rc = self.chat_proc.poll()
        if rc is None:
            return
        self.chat_proc = None
        self._chat_status = "Boxy finished running." if rc == 0 else f"Boxy exited with code {rc}."

    def _launch(self, key: str):
        if self._is_chat_running():
            self._stop_chat(announce=False)
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

    def _card_defs(self, level: str) -> list[tuple[str, str, str]]:
        game2 = ("game_colors", "Colors & Numbers", "Count objects and choose the right Russian answer.")
        if level == "A1":
            return [
                ("game_animals", "Animal Game", "Learn animal words through sound and matching."),
                game2,
            ]
        return [
            ("game_words", "Word Positions", "Practice spatial words and simple sentence meaning."),
            game2,
        ]

    def _button(self, key: str, rect: pygame.Rect, label: str, fill: Color, depth: Color,
                font: pygame.font.Font, text_color: Color = TEXT_DARK):
        draw_button(
            self.screen,
            rect,
            label,
            fill,
            depth,
            font,
            hovered=(self._hover == key),
            pressed=(self._press == key),
            text_color=text_color,
        )
        self._btns[key] = rect

    def draw_home(self):
        w, h, s = self._metrics()
        f = self._fonts(s)
        surf = self.screen
        draw_background(surf)
        self._btns = {}

        panel_margin_x = max(60, int(90 * s))
        panel_margin_top = max(38, int(44 * s))
        panel_bottom_gap = max(128, int(148 * s))
        panel = pygame.Rect(panel_margin_x, panel_margin_top, w - 2 * panel_margin_x, h - panel_margin_top - panel_bottom_gap)
        draw_panel(surf, panel, max(24, int(32 * s)))
        draw_ribbon_title(surf, "Russian Learning Games", panel, f["ribbon"], s)

        content_top = panel.y + max(118, int(132 * s))
        inner_left = panel.x + max(44, int(56 * s))
        inner_right = panel.right - max(44, int(56 * s))
        inner_w = inner_right - inner_left
        gap_y = max(18, int(22 * s))

        if self.profile:
            level = self.profile.get("level", "A1")
            a1_acc = float(self.profile.get("a1_accuracy") or 0.0)
            a2_acc = float(self.profile.get("a2_accuracy") or 0.0)
            progress = max(a1_acc, a2_acc if level == "A2" else 0.0)
            target = max(0.0, min(1.0, progress))
            self._bar += (target - self._bar) * 0.12
            if abs(self._bar - target) < 0.004:
                self._bar = target

            title_font = _best_font(max(30, int(34 * s)), True)
            title = render_tracked_text(title_font, "Your learning path is ready", TEXT_DARK, tracking=1)
            surf.blit(title, title.get_rect(center=(panel.centerx, content_top + title.get_height() // 2)))

            block_top = content_top + title.get_height() + max(24, int(28 * s))
            section = pygame.Rect(inner_left + int(inner_w * 0.06), block_top, int(inner_w * 0.74), max(230, int(260 * s)))
            right_x = section.right + max(28, int(34 * s))
            right_w = max(180, inner_right - right_x)

            prog_label_font = _best_font(max(26, int(30 * s)), True)
            prog_label = render_tracked_text(prog_label_font, "Progress", TEXT_DARK, tracking=1)
            surf.blit(prog_label, (section.x, section.y))

            bar_y = section.y + prog_label.get_height() + max(14, int(18 * s))
            bar_rect = pygame.Rect(section.x, bar_y, section.w, max(66, int(76 * s)))
            draw_progress_bar(surf, bar_rect, self._bar, _best_font(max(24, int(28 * s)), True))

            level_label_font = _best_font(max(26, int(30 * s)), True)
            level_label = render_tracked_text(level_label_font, "Level", TEXT_DARK, tracking=1)
            surf.blit(level_label, (right_x, section.y))
            badge_rect = pygame.Rect(right_x, bar_y, max(190, int(right_w * 0.98)), max(66, int(76 * s)))
            draw_badge(surf, badge_rect, "★", level, _best_font(max(26, int(30 * s)), True), _best_font(max(24, int(28 * s)), True))

            desc_y = bar_rect.bottom + max(28, int(34 * s))
            desc_font = _best_font(max(24, int(28 * s)), True)
            desc_lines = wrap_text(
                f"You are currently on level {level}. Open the level hub to play the games prepared for you.",
                desc_font,
                section.w + right_w - max(10, int(12 * s)),
            )
            for i, line in enumerate(desc_lines[:2]):
                txt = render_tracked_text(desc_font, line, TEXT_SOFT, tracking=1)
                surf.blit(txt, (section.x, desc_y + i * max(28, int(34 * s))))

            row_y = min(panel.bottom - max(112, int(126 * s)), desc_y + max(126, int(148 * s)))
            mascot_center = (panel.x + max(88, int(98 * s)), row_y + max(44, int(48 * s)))
            draw_avatar_bunny(surf, mascot_center, max(44, int(52 * s)))

            play_x = mascot_center[0] + max(64, int(74 * s))
            play_w = int(inner_w * 0.50)
            self._button("go", pygame.Rect(play_x, row_y, play_w, max(78, int(92 * s))), f"Play Level {level} Games", BTN_YELLOW, BTN_YELLOW_DARK, _best_font(max(28, int(32 * s)), True))

            small_w = max(150, int(170 * s))
            btn_gap = max(20, int(24 * s))
            ret_x = play_x + play_w + btn_gap
            self._button("retake_home", pygame.Rect(ret_x, row_y, small_w, max(78, int(92 * s))), "Retake", BTN_BLUE, BTN_BLUE_DARK, _best_font(max(24, int(28 * s)), True), TEXT_LIGHT)
            chat_x = ret_x + small_w + btn_gap
            self._button("chat_home", pygame.Rect(chat_x, row_y, small_w, max(78, int(92 * s))), "Boxy", BTN_GREEN, BTN_GREEN_DARK, _best_font(max(24, int(28 * s)), True))
        else:
            subtitle = render_tracked_text(_best_font(max(30, int(34 * s)), True), "First, let us find out your Russian level", TEXT_DARK, tracking=1)
            surf.blit(subtitle, subtitle.get_rect(center=(panel.centerx, content_top + subtitle.get_height() // 2)))

            info_card = pygame.Rect(inner_left + int(inner_w * 0.08), content_top + subtitle.get_height() + gap_y, int(inner_w * 0.84), max(120, int(132 * s)))
            draw_shadow(surf, info_card, max(18, int(22 * s)), dy=5)
            pygame.draw.rect(surf, BTN_CREAM, info_card, border_radius=max(18, int(22 * s)))
            pygame.draw.rect(surf, PANEL_BORDER, info_card, width=2, border_radius=max(18, int(22 * s)))
            info_lines = [
                "The level test asks A1 and A2 words.",
                "Words are not repeated, and the test finishes automatically.",
                "After that, the launcher opens the right game hub for your level.",
            ]
            info_font = _best_font(max(22, int(24 * s)), True)
            for i, line in enumerate(info_lines):
                txt = render_tracked_text(info_font, line, TEXT_SOFT, tracking=1)
                surf.blit(txt, (info_card.x + max(28, int(34 * s)), info_card.y + max(18, int(20 * s)) + i * max(28, int(32 * s))))

            start_rect = pygame.Rect(panel.centerx - max(250, int(290 * s)), info_card.bottom + gap_y + 8, max(500, int(580 * s)), max(78, int(88 * s)))
            self._button("start", start_rect, "Start Level Test", BTN_YELLOW, BTN_YELLOW_DARK, _best_font(max(28, int(32 * s)), True))
            chat_rect = pygame.Rect(panel.centerx - max(160, int(190 * s)), start_rect.bottom + gap_y, max(320, int(380 * s)), max(64, int(72 * s)))
            self._button("chat_home", chat_rect, "Chat with Boxy", BTN_GREEN, BTN_GREEN_DARK, _best_font(max(24, int(28 * s)), True))

        exit_w, exit_h = max(120, int(136 * s)), max(52, int(58 * s))
        exit_rect = pygame.Rect(w - panel_margin_x - exit_w, panel.bottom + max(36, int(44 * s)), exit_w, exit_h)
        self._button("exit", exit_rect, "Exit", BTN_CREAM, BTN_CREAM_DARK, _best_font(max(22, int(24 * s)), True))

    def draw_hub(self, level: str):
        w, h, s = self._metrics()
        f = self._fonts(s)
        surf = self.screen
        draw_background(surf)
        self._btns = {}

        panel = pygame.Rect(max(72, int(92 * s)), max(36, int(44 * s)), w - 2 * max(72, int(92 * s)), h - 2 * max(36, int(44 * s)))
        draw_panel(surf, panel, max(24, int(32 * s)))
        draw_ribbon_title(surf, f"Level {level} Hub", panel, f["ribbon"], s)

        cards = self._card_defs(level)
        card_gap = max(42, int(56 * s))
        side_pad = max(54, int(68 * s))
        card_w = int((panel.w - 2 * side_pad - card_gap) / 2)
        card_h = max(328, int(388 * s))
        card_y = panel.y + max(138, int(156 * s))
        x1 = panel.x + side_pad
        x2 = x1 + card_w + card_gap
        positions = [pygame.Rect(x1, card_y, card_w, card_h), pygame.Rect(x2, card_y, card_w, card_h)]

        for rect, (cmd_key, title, desc) in zip(positions, cards):
            draw_shadow(surf, rect, max(18, int(24 * s)), dy=6)
            pygame.draw.rect(surf, BTN_CREAM, rect, border_radius=max(18, int(24 * s)))
            pygame.draw.rect(surf, PANEL_BORDER, rect, width=3, border_radius=max(18, int(24 * s)))
            draw_avatar_bunny(surf, (rect.centerx, rect.y + max(76, int(92 * s))), max(34, int(40 * s)))
            card_title_font = _best_font(max(24, int(28 * s)), True)
            card_text_font = _best_font(max(20, int(23 * s)), True)
            tt = render_tracked_text(card_title_font, title, TEXT_DARK, tracking=1)
            surf.blit(tt, tt.get_rect(center=(rect.centerx, rect.y + max(146, int(170 * s)))))
            desc_width = rect.w - max(110, int(132 * s))
            lines = wrap_text(desc, card_text_font, desc_width)
            y = rect.y + max(184, int(212 * s))
            for line in lines[:3]:
                txt = render_tracked_text(card_text_font, line, TEXT_SOFT, tracking=1)
                surf.blit(txt, txt.get_rect(center=(rect.centerx, y)))
                y += max(26, int(30 * s))
            self._button(f"play_{cmd_key}", pygame.Rect(rect.x + (rect.w - max(220, int(240 * s))) // 2, rect.bottom - max(88, int(98 * s)), max(220, int(240 * s)), max(58, int(66 * s))), "Play!", BTN_YELLOW, BTN_YELLOW_DARK, card_title_font)

        bottom_y = panel.bottom - max(84, int(96 * s))
        home_w = max(180, int(210 * s))
        home_h = max(58, int(66 * s))
        self._button("hub_home", pygame.Rect(panel.centerx - home_w // 2, bottom_y, home_w, home_h), "Home", BTN_BLUE, BTN_BLUE_DARK, _best_font(max(24, int(28 * s)), True), TEXT_LIGHT)

    def draw_chat(self):
        w, h, s = self._metrics()
        f = self._fonts(s)
        surf = self.screen
        draw_background(surf)
        self._btns = {}

        panel = pygame.Rect(max(72, int(92 * s)), max(36, int(44 * s)), w - 2 * max(72, int(92 * s)), h - 2 * max(36, int(44 * s)))
        draw_panel(surf, panel, max(24, int(32 * s)))
        draw_ribbon_title(surf, "Boxy Voice Chat", panel, f["ribbon"], s)

        status_kind = "success" if self._is_chat_running() else "info"
        status_rect = pygame.Rect(panel.x + max(86, int(96 * s)), panel.y + max(120, int(138 * s)), panel.w - 2 * max(86, int(96 * s)), max(52, int(58 * s)))
        status_font = _best_font(max(19, int(22 * s)), False)
        draw_feedback_pill(surf, status_rect, self._chat_status[:140], status_kind, status_font)

        guide = pygame.Rect(panel.x + max(70, int(82 * s)), status_rect.bottom + max(22, int(26 * s)), panel.w - 2 * max(70, int(82 * s)), max(188, int(212 * s)))
        draw_shadow(surf, guide, max(18, int(20 * s)), dy=5)
        pygame.draw.rect(surf, BTN_CREAM, guide, border_radius=max(18, int(20 * s)))
        pygame.draw.rect(surf, PANEL_BORDER, guide, width=2, border_radius=max(18, int(20 * s)))
        guide_title_font = _best_font(max(24, int(28 * s)), True)
        guide_text_font = _best_font(max(20, int(23 * s)), False)
        title = render_tracked_text(guide_title_font, "How to use Boxy", TEXT_DARK, tracking=1)
        surf.blit(title, (guide.x + max(22, int(26 * s)), guide.y + max(14, int(18 * s))))
        lines = [
            "1. Press Start Boxy.",
            "2. Say \"Hello Boxy\" to wake the assistant.",
            "3. Speak in English or Russian and listen for the reply.",
            "4. Press Stop before starting another game.",
            "Needs microphone access and a llama.cpp server at localhost:8080.",
        ]
        y = guide.y + max(44, int(50 * s))
        for line in lines:
            txt = render_tracked_text(guide_text_font, line, TEXT_DARK, tracking=1)
            surf.blit(txt, (guide.x + max(22, int(26 * s)), y))
            y += max(24, int(28 * s))

        btn_w = max(240, int(290 * s))
        btn_h = max(66, int(76 * s))
        row_y = guide.bottom + max(18, int(22 * s))
        gap = max(28, int(36 * s))
        bottom_gap = max(16, int(20 * s))
        start_x = panel.centerx - btn_w - gap // 2
        button_font = _best_font(max(24, int(28 * s)), True)
        self._button("chat_start", pygame.Rect(start_x, row_y, btn_w, btn_h), "Start Boxy", BTN_GREEN, BTN_GREEN_DARK, button_font)
        self._button("chat_stop", pygame.Rect(start_x + btn_w + gap, row_y, btn_w, btn_h), "Stop Boxy", BTN_RED, BTN_RED_DARK, button_font, TEXT_LIGHT)
        back_y = min(row_y + btn_h + bottom_gap, panel.bottom - btn_h - max(20, int(24 * s)))
        self._button("chat_back", pygame.Rect(panel.centerx - btn_w // 2, back_y, btn_w, btn_h), "Back", BTN_BLUE, BTN_BLUE_DARK, button_font, TEXT_LIGHT)

    def draw_waiting(self, msg: str, sub: str):
        w, h, s = self._metrics()
        f = self._fonts(s)
        surf = self.screen
        draw_background(surf)
        self._btns = {}

        panel = pygame.Rect(w // 2 - max(320, int(390 * s)), h // 2 - max(130, int(150 * s)), max(640, int(780 * s)), max(250, int(300 * s)))
        draw_panel(surf, panel, max(24, int(30 * s)))
        draw_ribbon_title(surf, "Please Wait", panel, f["ribbon"], s)
        t1 = render_tracked_text(f["big"], msg, TEXT_DARK, tracking=1)
        surf.blit(t1, t1.get_rect(center=(panel.centerx, panel.y + max(122, int(138 * s)))))
        t2 = render_tracked_text(f["small"], sub, TEXT_SOFT, tracking=1)
        surf.blit(t2, t2.get_rect(center=(panel.centerx, panel.y + max(164, int(182 * s)))))
        dot_y = panel.y + max(214, int(236 * s))
        for i in range(3):
            x = panel.centerx - max(36, int(48 * s)) + i * max(36, int(48 * s))
            y = dot_y + int(math.sin(self._tick * 0.12 + i * 1.2) * max(6, int(10 * s)))
            pygame.draw.circle(surf, BTN_ORANGE, (x, y), max(10, int(14 * s)))
            pygame.draw.circle(surf, OUTLINE_DARK, (x, y), max(10, int(14 * s)), 2)

    def _on_click(self, key: str):
        if key == "exit":
            if self._is_chat_running():
                self._stop_chat(announce=False)
            pygame.quit()
            sys.exit()
        elif key == "start":
            self._launch("level_test")
        elif key == "go":
            self.state = f"{(self.profile or {}).get('level', 'A1').lower()}_hub"
        elif key in ("chat_home", "chat_hub"):
            self._open_chat()
        elif key == "chat_start":
            self._launch_chat()
        elif key == "chat_stop":
            self._stop_chat()
        elif key == "chat_back":
            self.state = self._chat_return_state
        elif key in ("retake_home", "retake_hub"):
            self._launch("level_test")
        elif key == "hub_home":
            self._bar = 0.0
            self.state = "home"
        elif key.startswith("play_"):
            self._launch(key[len("play_"):])

    def run(self):
        while True:
            self._tick += 1
            mouse = pygame.mouse.get_pos()
            self._poll_chat()

            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    if self.proc:
                        self.proc.terminate()
                    if self._is_chat_running():
                        self._stop_chat(announce=False)
                    pygame.quit()
                    sys.exit()
                if ev.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode((max(960, ev.w), max(640, ev.h)), pygame.RESIZABLE)
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE and self.state == "chat":
                    self.state = self._chat_return_state
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    self._press = None
                    for key, rect in self._btns.items():
                        if rect.collidepoint(mouse):
                            self._press = key
                            break
                if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    if self._press and self._press in self._btns and self._btns[self._press].collidepoint(mouse):
                        self._on_click(self._press)
                    self._press = None

            if self.state == "home":
                self.draw_home()
            elif self.state in ("a1_hub", "a2_hub"):
                self.draw_hub("A1" if self.state == "a1_hub" else "A2")
            elif self.state == "chat":
                self.draw_chat()
            elif self.state == "waiting":
                self.draw_waiting("Finding Your Level...", "Complete the test window to continue.")
                self._poll()
            elif self.state == "launching":
                self.draw_waiting("Game Running...", "Close the game window to return here.")
                self._poll()
            else:
                self.draw_home()

            self._hover = None
            for key, rect in self._btns.items():
                if rect.collidepoint(mouse):
                    self._hover = key
                    break

            pygame.display.flip()
            self.clock.tick(FPS)


if __name__ == "__main__":
    Launcher().run()
