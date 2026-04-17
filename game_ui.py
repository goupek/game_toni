from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import pygame


# ============================================================
# Cartoon / mobile-game style UI kit for pygame
# Compatible with a virtual canvas workflow like 1280x720.
# Import this module into your game files and reuse the same
# theme + components everywhere.
# ============================================================

Color = Tuple[int, int, int]


# ============================================================
# Theme
# ============================================================
class Theme:
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

    SHADOW: Color = (115, 97, 113)
    SHADOW_SOFT: Color = (153, 136, 148)
    HIGHLIGHT: Color = (255, 255, 255)

    BTN_YELLOW: Color = (251, 224, 64)
    BTN_YELLOW_DARK: Color = (236, 174, 44)
    BTN_BLUE: Color = (37, 205, 230)
    BTN_BLUE_DARK: Color = (93, 86, 210)
    BTN_GREEN: Color = (166, 231, 12)
    BTN_GREEN_DARK: Color = (111, 179, 26)
    BTN_CREAM: Color = (245, 240, 230)
    BTN_CREAM_DARK: Color = (177, 163, 174)
    BTN_RED: Color = (252, 99, 84)
    BTN_RED_DARK: Color = (196, 58, 61)
    BTN_ORANGE: Color = (255, 191, 53)
    BTN_ORANGE_DARK: Color = (220, 139, 27)

    BADGE_FILL: Color = (236, 231, 205)
    BADGE_BORDER: Color = (187, 173, 121)

    SUCCESS: Color = (117, 217, 102)
    ERROR: Color = (245, 112, 112)
    INFO: Color = (72, 187, 255)

    PANEL_RADIUS = 28
    BUTTON_RADIUS = 18
    SMALL_RADIUS = 14
    ICON_RADIUS = 999

    SHADOW_DX = 0
    SHADOW_DY = 6

    FONT_CANDIDATES = (
        "Baloo 2",
        "Fredoka",
        "Nunito",
        "Comic Sans MS",
        "Arial",
        "DejaVu Sans",
        "",
    )


# ============================================================
# Fonts
# ============================================================
class FontBook:
    def __init__(self):
        self._cache: Dict[Tuple[int, bool], pygame.font.Font] = {}

    def get(self, size: int, bold: bool = True) -> pygame.font.Font:
        key = (size, bold)
        if key in self._cache:
            return self._cache[key]
        for name in Theme.FONT_CANDIDATES:
            try:
                f = pygame.font.SysFont(name, max(14, size), bold=bold)
                if f:
                    self._cache[key] = f
                    return f
            except Exception:
                continue
        f = pygame.font.Font(None, max(14, size))
        self._cache[key] = f
        return f


# ============================================================
# Low-level helpers
# ============================================================
def lighten(color: Color, amount: int) -> Color:
    return tuple(min(255, c + amount) for c in color)


def darken(color: Color, amount: int) -> Color:
    return tuple(max(0, c - amount) for c in color)


def draw_soft_shadow(surface: pygame.Surface, rect: pygame.Rect, radius: int, dy: int = None):
    dy = Theme.SHADOW_DY if dy is None else dy
    shadow_rect = rect.move(Theme.SHADOW_DX, dy)
    pygame.draw.rect(surface, Theme.SHADOW_SOFT, shadow_rect, border_radius=radius)


# ============================================================
# Background
# ============================================================
def draw_background(surface: pygame.Surface):
    w, h = surface.get_size()

    # vertical gradient
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(Theme.BG_TOP[0] * (1 - t) + Theme.BG_BOTTOM[0] * t)
        g = int(Theme.BG_TOP[1] * (1 - t) + Theme.BG_BOTTOM[1] * t)
        b = int(Theme.BG_TOP[2] * (1 - t) + Theme.BG_BOTTOM[2] * t)
        pygame.draw.line(surface, (r, g, b), (0, y), (w, y))

    # simple low-poly overlays
    polys = [
        (Theme.BG_POLY_1, [(0, h * 0.18), (w * 0.28, 0), (w * 0.5, h * 0.22), (w * 0.2, h * 0.42)]),
        (Theme.BG_POLY_2, [(w * 0.66, 0), (w, 0), (w, h * 0.34), (w * 0.8, h * 0.26)]),
        (Theme.BG_POLY_3, [(0, h), (w * 0.22, h * 0.7), (w * 0.4, h), (0, h)]),
        (Theme.BG_POLY_2, [(w * 0.58, h), (w * 0.78, h * 0.62), (w, h), (w * 0.78, h)]),
        (Theme.BG_POLY_1, [(w * 0.3, h * 0.45), (w * 0.52, h * 0.3), (w * 0.64, h * 0.58), (w * 0.42, h * 0.7)]),
    ]
    for color, pts in polys:
        pygame.draw.polygon(surface, color, pts)


# ============================================================
# Panel + ribbon
# ============================================================
def draw_panel(surface: pygame.Surface, rect: pygame.Rect):
    draw_soft_shadow(surface, rect, Theme.PANEL_RADIUS, dy=8)
    pygame.draw.rect(surface, Theme.PANEL_FILL, rect, border_radius=Theme.PANEL_RADIUS)
    pygame.draw.rect(surface, Theme.PANEL_BORDER, rect, width=4, border_radius=Theme.PANEL_RADIUS)

    inner = rect.inflate(-10, -10)
    pygame.draw.rect(surface, Theme.PANEL_INNER, inner, width=2, border_radius=Theme.PANEL_RADIUS - 6)


def draw_ribbon_title(
    surface: pygame.Surface,
    text: str,
    panel_rect: pygame.Rect,
    fonts: FontBook,
    close_button: bool = False,
) -> Optional[pygame.Rect]:
    ribbon_h = 74
    ribbon_w = int(panel_rect.w * 1.16)
    ribbon_x = panel_rect.centerx - ribbon_w // 2
    ribbon_y = panel_rect.y + 28
    ribbon = pygame.Rect(ribbon_x, ribbon_y, ribbon_w, ribbon_h)

    tail_w = 34
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
    pygame.draw.polygon(surface, Theme.RIBBON_DARK, left_tail)
    pygame.draw.polygon(surface, Theme.RIBBON_DARK, right_tail)

    draw_soft_shadow(surface, ribbon, 0, dy=6)
    pygame.draw.rect(surface, Theme.RIBBON_FILL, ribbon)
    highlight = pygame.Rect(ribbon.x, ribbon.y, ribbon.w, 12)
    pygame.draw.rect(surface, Theme.RIBBON_LIGHT, highlight)
    pygame.draw.line(surface, Theme.RIBBON_DARK, (ribbon.left, ribbon.bottom - 3), (ribbon.right, ribbon.bottom - 3), 3)

    font = fonts.get(34, bold=True)
    text_surf = font.render(text, True, Theme.TEXT_LIGHT)
    outline = font.render(text, True, Theme.OUTLINE_DARK)
    tx, ty = text_surf.get_rect(center=ribbon.center).topleft
    for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        surface.blit(outline, (tx + ox, ty + oy))
    surface.blit(text_surf, (tx, ty))

    if close_button:
        size = 40
        close_rect = pygame.Rect(ribbon.right - size - 14, ribbon.centery - size // 2, size, size)
        draw_icon_button(surface, close_rect, "×", Theme.BTN_RED, Theme.BTN_RED_DARK, fonts)
        return close_rect
    return None


# ============================================================
# Buttons
# ============================================================
@dataclass
class UIButton:
    rect: pygame.Rect
    label: str
    fill: Color
    depth: Color
    text_color: Color = Theme.TEXT_DARK
    enabled: bool = True

    def hit(self, pos) -> bool:
        return self.enabled and self.rect.collidepoint(pos)

    def draw(self, surface: pygame.Surface, fonts: FontBook, hovered: bool = False):
        draw_main_button(surface, self.rect, self.label, self.fill, self.depth, fonts, hovered, self.text_color, self.enabled)


@dataclass
class UIIconButton:
    rect: pygame.Rect
    icon: str
    fill: Color = Theme.BTN_ORANGE
    depth: Color = Theme.BTN_ORANGE_DARK
    text_color: Color = Theme.TEXT_LIGHT
    enabled: bool = True

    def hit(self, pos) -> bool:
        return self.enabled and self.rect.collidepoint(pos)

    def draw(self, surface: pygame.Surface, fonts: FontBook, hovered: bool = False):
        draw_icon_button(surface, self.rect, self.icon, self.fill, self.depth, fonts, hovered, self.text_color, self.enabled)


def draw_main_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    fill: Color,
    depth: Color,
    fonts: FontBook,
    hovered: bool = False,
    text_color: Color = Theme.TEXT_DARK,
    enabled: bool = True,
):
    base_fill = fill if enabled else darken(Theme.BTN_CREAM, 10)
    base_depth = depth if enabled else darken(Theme.BTN_CREAM_DARK, 10)
    top_fill = lighten(base_fill, 10) if hovered and enabled else base_fill

    # base / lower strip
    base_rect = rect.move(0, 7)
    pygame.draw.rect(surface, base_depth, base_rect, border_radius=Theme.BUTTON_RADIUS)

    # main body
    pygame.draw.rect(surface, top_fill, rect, border_radius=Theme.BUTTON_RADIUS)
    pygame.draw.rect(surface, lighten(top_fill, 18), (rect.x + 6, rect.y + 5, rect.w - 12, 12), border_radius=10)
    pygame.draw.rect(surface, Theme.PANEL_BORDER, rect, width=2, border_radius=Theme.BUTTON_RADIUS)

    font = fonts.get(max(22, int(rect.h * 0.45)), bold=True)
    shadow = font.render(label, True, Theme.OUTLINE_DARK)
    text = font.render(label, True, text_color if enabled else Theme.TEXT_SOFT)
    tr = text.get_rect(center=(rect.centerx, rect.centery + 1))
    surface.blit(shadow, shadow.get_rect(center=(tr.centerx + 1, tr.centery + 2)))
    surface.blit(text, tr)


def draw_icon_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    icon: str,
    fill: Color,
    depth: Color,
    fonts: FontBook,
    hovered: bool = False,
    text_color: Color = Theme.TEXT_LIGHT,
    enabled: bool = True,
):
    base_fill = fill if enabled else Theme.BTN_CREAM_DARK
    base_depth = depth if enabled else darken(Theme.BTN_CREAM_DARK, 24)
    top_fill = lighten(base_fill, 10) if hovered and enabled else base_fill

    base_rect = rect.move(0, 5)
    pygame.draw.ellipse(surface, base_depth, base_rect)
    pygame.draw.ellipse(surface, top_fill, rect)
    inner = rect.inflate(-8, -8)
    pygame.draw.ellipse(surface, lighten(top_fill, 14), inner, width=2)
    pygame.draw.ellipse(surface, Theme.PANEL_BORDER, rect, width=2)

    font = fonts.get(max(20, int(min(rect.w, rect.h) * 0.52)), bold=True)
    shadow = font.render(icon, True, Theme.OUTLINE_DARK)
    text = font.render(icon, True, text_color)
    surface.blit(shadow, shadow.get_rect(center=(rect.centerx + 1, rect.centery + 2)))
    surface.blit(text, text.get_rect(center=rect.center))


# ============================================================
# Cards / badges / HUD
# ============================================================
def draw_badge(surface: pygame.Surface, rect: pygame.Rect, label: str, value: str, fonts: FontBook):
    pygame.draw.rect(surface, Theme.BADGE_FILL, rect, border_radius=rect.h // 2)
    pygame.draw.rect(surface, Theme.BADGE_BORDER, rect, width=2, border_radius=rect.h // 2)

    icon_rect = pygame.Rect(rect.x - rect.h // 3, rect.y - 4, rect.h + 8, rect.h + 8)
    draw_icon_button(surface, icon_rect, label, Theme.BTN_ORANGE, Theme.BTN_ORANGE_DARK, fonts)

    font = fonts.get(max(18, int(rect.h * 0.44)), bold=True)
    shadow = font.render(str(value), True, Theme.OUTLINE_DARK)
    text = font.render(str(value), True, Theme.TEXT_LIGHT)
    center = (rect.x + rect.w * 0.55, rect.centery)
    surface.blit(shadow, shadow.get_rect(center=(center[0] + 1, center[1] + 1)))
    surface.blit(text, text.get_rect(center=center))


def draw_instruction_card(
    surface: pygame.Surface,
    rect: pygame.Rect,
    text: str,
    fonts: FontBook,
    icon_button: Optional[UIIconButton] = None,
):
    draw_soft_shadow(surface, rect, Theme.SMALL_RADIUS, dy=5)
    pygame.draw.rect(surface, Theme.BTN_CREAM, rect, border_radius=Theme.SMALL_RADIUS)
    pygame.draw.rect(surface, Theme.PANEL_BORDER, rect, width=2, border_radius=Theme.SMALL_RADIUS)

    title_font = fonts.get(22, bold=True)
    body_font = fonts.get(26, bold=True)

    title = title_font.render("Instruction", True, Theme.TEXT_SOFT)
    surface.blit(title, (rect.x + 16, rect.y + 10))

    body_rect = pygame.Rect(rect.x + 16, rect.y + 36, rect.w - 32, rect.h - 46)
    if icon_button is not None:
        body_rect.w -= 58

    lines = wrap_text(text, body_font, body_rect.w)
    y = body_rect.y + max(0, (body_rect.h - len(lines) * body_font.get_linesize()) // 2 - 4)
    for line in lines[:3]:
        surf = body_font.render(line, True, Theme.TEXT_DARK)
        surface.blit(surf, (body_rect.x, y))
        y += body_font.get_linesize() + 2

    if icon_button is not None:
        icon_button.rect = pygame.Rect(rect.right - 48, rect.bottom - 48, 38, 38)
        icon_button.draw(surface, fonts)


def draw_progress_stars(surface: pygame.Surface, center: Tuple[int, int], count: int, total: int, fonts: FontBook):
    spacing = 74
    start_x = center[0] - ((total - 1) * spacing) // 2
    for i in range(total):
        color = Theme.BTN_ORANGE if i < count else (64, 83, 162)
        color_dark = Theme.BTN_ORANGE_DARK if i < count else (46, 58, 119)
        rect = pygame.Rect(start_x + i * spacing - 26, center[1] - 26, 52, 52)
        draw_star(surface, rect.center, 24, 12, color, color_dark)


def draw_feedback_pill(surface: pygame.Surface, rect: pygame.Rect, text: str, kind: str, fonts: FontBook):
    if kind == "success":
        fill = lighten(Theme.SUCCESS, 38)
        border = Theme.SUCCESS
    elif kind == "error":
        fill = lighten(Theme.ERROR, 42)
        border = Theme.ERROR
    else:
        fill = lighten(Theme.INFO, 42)
        border = Theme.INFO

    draw_soft_shadow(surface, rect, rect.h // 2, dy=4)
    pygame.draw.rect(surface, fill, rect, border_radius=rect.h // 2)
    pygame.draw.rect(surface, border, rect, width=3, border_radius=rect.h // 2)

    font = fonts.get(max(22, int(rect.h * 0.4)), bold=True)
    txt = font.render(text, True, Theme.TEXT_DARK)
    surface.blit(txt, txt.get_rect(center=rect.center))


def draw_top_bar(
    surface: pygame.Surface,
    title: str,
    fonts: FontBook,
    menu_btn: UIButton,
    right_buttons: Sequence[UIIconButton] = (),
    badge: Optional[Tuple[str, str, pygame.Rect]] = None,
):
    title_rect = pygame.Rect(surface.get_width() // 2 - 180, 24, 360, 56)
    draw_ribbon_title(surface, title, title_rect.inflate(0, 0), fonts, close_button=False)

    menu_btn.draw(surface, fonts)
    for btn in right_buttons:
        btn.draw(surface, fonts)

    if badge is not None:
        label, value, rect = badge
        draw_badge(surface, rect, label, value, fonts)


# ============================================================
# Shapes
# ============================================================
def draw_star(surface: pygame.Surface, center: Tuple[int, int], outer_r: int, inner_r: int, fill: Color, depth: Color):
    cx, cy = center
    pts = []
    shadow_pts = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = outer_r if i % 2 == 0 else inner_r
        x = cx + math.cos(angle) * r
        y = cy + math.sin(angle) * r
        pts.append((x, y))
        shadow_pts.append((x, y + 4))
    pygame.draw.polygon(surface, depth, shadow_pts)
    pygame.draw.polygon(surface, fill, pts)
    pygame.draw.polygon(surface, darken(fill, 28), pts, width=2)


# ============================================================
# Text wrapping
# ============================================================
def wrap_text(text: str, font: pygame.font.Font, max_width: int):
    words = str(text).split()
    lines = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if font.size(trial)[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ============================================================
# Ready-made layout helpers
# ============================================================
def build_vertical_menu_buttons(panel_rect: pygame.Rect):
    btn_w = int(panel_rect.w * 0.62)
    btn_h = 64
    x = panel_rect.centerx - btn_w // 2
    y0 = panel_rect.y + 130
    gap = 24
    return [
        pygame.Rect(x, y0 + i * (btn_h + gap), btn_w, btn_h)
        for i in range(4)
    ]


def build_right_icon_row(x_right: int, y: int, count: int, size: int = 48, gap: int = 12):
    rects = []
    cur_x = x_right - count * size - (count - 1) * gap
    for _ in range(count):
        rects.append(pygame.Rect(cur_x, y, size, size))
        cur_x += size + gap
    return rects


# ============================================================
# Example screen renderer
# ============================================================
def demo_menu_screen(surface: pygame.Surface, fonts: FontBook):
    draw_background(surface)

    panel = pygame.Rect(80, 22, 560, 630)
    draw_panel(surface, panel)
    draw_ribbon_title(surface, "Game UI Kit", panel, fonts, close_button=True)

    rects = build_vertical_menu_buttons(panel)
    buttons = [
        UIButton(rects[0], "Play!", Theme.BTN_YELLOW, Theme.BTN_YELLOW_DARK),
        UIButton(rects[1], "Settings", Theme.BTN_BLUE, Theme.BTN_BLUE_DARK),
        UIButton(rects[2], "Shop", Theme.BTN_GREEN, Theme.BTN_GREEN_DARK),
        UIButton(rects[3], "Credits", Theme.BTN_CREAM, Theme.BTN_CREAM_DARK),
    ]
    for btn in buttons:
        btn.draw(surface, fonts)

    draw_badge(surface, pygame.Rect(870, 40, 140, 44), "★", "130", fonts)
    draw_badge(surface, pygame.Rect(870, 98, 140, 44), "❤", "9", fonts)
    draw_badge(surface, pygame.Rect(870, 156, 140, 44), "⚡", "3999", fonts)

    icons = [
        UIIconButton(pygame.Rect(840 + i * 58, 236, 42, 42), icon)
        for i, icon in enumerate(("+", "⏸", "▶", "?", "♪", "🔊"))
    ]
    for ic in icons:
        ic.draw(surface, fonts)

    draw_progress_stars(surface, (1000, 420), 2, 3, fonts)
    draw_star(surface, (1000, 540), 34, 17, Theme.BTN_ORANGE, Theme.BTN_ORANGE_DARK)


# ============================================================
# Quick integration notes
# ------------------------------------------------------------
# 1. In your game file:
#       from game_ui_style import *
#       fonts = FontBook()
#
# 2. At the start of every draw loop:
#       draw_background(canvas)
#
# 3. Replace plain draw_button(...) with UIButton(...).draw(...)
#
# 4. Replace instruction rectangles with draw_instruction_card(...)
#
# 5. Use draw_panel + draw_ribbon_title for launcher/start/result screens.
# ============================================================
