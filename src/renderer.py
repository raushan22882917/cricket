"""Broadcast Scoreboard and Visual Graphics Renderer.

Produces television-grade 720p/1080p frames at 30 fps with lower-third scorecards,
batsman/bowler statistics, event alert banners, ball tracker badges,
and live commentator indicators.
"""
import math
import time
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

import config

class BroadcastRenderer:
    def __init__(self, width: int = config.VIDEO_WIDTH, height: int = config.VIDEO_HEIGHT):
        self.width = width
        self.height = height
        self.frame_count = 0

        # Attempt to load clean TrueType fonts or fallback to default
        self.font_large = self._load_font(28, bold=True)
        self.font_medium = self._load_font(20, bold=True)
        self.font_regular = self._load_font(16, bold=False)
        self.font_small = self._load_font(13, bold=False)
        self.font_banner = self._load_font(42, bold=True)

        # Event alert display timer
        self.active_alert: Optional[str] = None
        self.alert_color = (255, 75, 75)
        self.alert_expiry_frame = 0

        # Latest commentary subtitle
        self.commentary_text = "Broadcast system initialized. Live match feed connected."
        self.is_talking = False

    def _load_font(self, size: int, bold: bool = False):
        system_fonts = [
            "/System/Library/Fonts/SFProText-Bold.otf" if bold else "/System/Library/Fonts/SFProText-Regular.otf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf"
        ]
        for path in system_fonts:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def trigger_event_alert(self, text: str, color=(255, 200, 0), duration_frames: int = 75):
        """Triggers a 2.5 second animated banner across the screen."""
        self.active_alert = text
        self.alert_color = color
        self.alert_expiry_frame = self.frame_count + duration_frames

    def set_commentary(self, text: str, is_talking: bool = True):
        self.commentary_text = text
        self.is_talking = is_talking

    def render_frame(self, state_summary: Dict[str, Any]) -> bytes:
        """
        Renders a single frame and returns raw RGB24 bytes.
        """
        self.frame_count += 1
        img = Image.new("RGB", (self.width, self.height), color=(15, 23, 42))
        draw = ImageDraw.Draw(img)

        # 1. Background: Stadium night gradient with subtle lighting
        self._draw_stadium_background(draw)

        # 2. Main Broadcast Header (Top bar)
        self._draw_header(draw, state_summary)

        # 3. Dynamic Pitch / Match Center Infographic (Center)
        self._draw_match_infographic(draw, state_summary)

        # 4. Animated Event Banner (If active: FOUR, SIX, WICKET)
        self._draw_event_banner(draw)

        # 5. Commentator Subtitle & Status Box (Above lower third)
        self._draw_commentary_bar(draw)

        # 6. Television Lower-Third Scorecard (Bottom)
        self._draw_lower_third(draw, state_summary)

        return img.tobytes()

    def _draw_stadium_background(self, draw: ImageDraw.ImageDraw):
        # Deep navy blue to stadium turf gradient
        for y in range(0, self.height, 4):
            ratio = y / self.height
            r = int(12 + ratio * 8)
            g = int(20 + ratio * 28)
            b = int(45 + ratio * 25)
            draw.rectangle([0, y, self.width, y + 4], fill=(r, g, b))

        # Stadium lights shimmer at top left and top right
        shimmer = (math.sin(self.frame_count * 0.05) + 1.0) * 0.5
        glow_alpha = int(40 + shimmer * 30)
        draw.ellipse([40, 20, 260, 100], fill=(20, 45, 80))
        draw.ellipse([self.width - 260, 20, self.width - 40, 100], fill=(20, 45, 80))

    def _draw_header(self, draw: ImageDraw.ImageDraw, state: Dict[str, Any]):
        # Sleek top glass bar
        draw.rectangle([0, 0, self.width, 50], fill=(10, 16, 30))
        draw.line([0, 50, self.width, 50], fill=(45, 85, 145), width=2)

        # Live Badge
        pulse = (math.sin(self.frame_count * 0.15) + 1.0) * 0.5
        red_val = int(200 + pulse * 55)
        draw.rounded_rectangle([25, 12, 95, 38], radius=6, fill=(red_val, 20, 20))
        draw.text((40, 16), "LIVE", fill=(255, 255, 255), font=self.font_medium)

        # Match Title & Venue
        title = state.get("match_title", "Live Cricket Stream")
        venue = state.get("venue", "")
        header_str = f"{title.upper()} • {venue}"
        draw.text((115, 16), header_str, fill=(240, 240, 245), font=self.font_medium)

        # Phase Badge (e.g. DEATH OVERS)
        phase = state.get("phase", "LIVE").upper()
        draw.rounded_rectangle([self.width - 190, 12, self.width - 25, 38], radius=6, fill=(28, 48, 76))
        draw.text((self.width - 175, 17), phase, fill=(255, 215, 0), font=self.font_small)

    def _draw_match_infographic(self, draw: ImageDraw.ImageDraw, state: Dict[str, Any]):
        center_x = self.width // 2
        center_y = 230

        # Stylized 22-yard pitch graphic in the center
        draw.rounded_rectangle([center_x - 160, center_y - 120, center_x + 160, center_y + 110], radius=12, fill=(18, 28, 48), outline=(35, 60, 100), width=2)
        draw.rectangle([center_x - 45, center_y - 100, center_x + 45, center_y + 90], fill=(160, 140, 100)) # Turf pitch
        draw.line([center_x - 45, center_y - 70, center_x + 45, center_y - 70], fill=(255, 255, 255), width=2) # Bowling crease
        draw.line([center_x - 45, center_y + 60, center_x + 45, center_y + 60], fill=(255, 255, 255), width=2) # Batting crease

        # Pitch Radar & Speed tag
        speed = state.get("speed_kph")
        if speed:
            draw.rounded_rectangle([center_x - 60, center_y - 15, center_x + 60, center_y + 15], radius=6, fill=(240, 40, 40))
            draw.text((center_x - 48, center_y - 9), f"{speed} KPH", fill=(255, 255, 255), font=self.font_medium)

        # Chase Equation Center Box
        if state.get("is_chase"):
            needed = state.get("runs_needed", 0)
            balls = state.get("balls_remaining", 0)
            rrr = state.get("rrr", 0.0)
            crr = state.get("crr", 0.0)

            # Equation pill below pitch
            eq_text = f"NEED {needed} RUNS OFF {balls} BALLS  •  RRR: {rrr}  •  CRR: {crr}"
            draw.rounded_rectangle([center_x - 260, center_y + 130, center_x + 260, center_y + 165], radius=8, fill=(22, 38, 65), outline=(255, 215, 0), width=1)
            draw.text((center_x - 230, center_y + 138), eq_text, fill=(255, 230, 120), font=self.font_medium)

    def _draw_event_banner(self, draw: ImageDraw.ImageDraw):
        if self.active_alert and self.frame_count < self.alert_expiry_frame:
            # Banner animation
            banner_y = 150
            banner_h = 70
            draw.rectangle([0, banner_y, self.width, banner_y + banner_h], fill=self.alert_color)
            # Text shadow
            draw.text((self.width // 2 - 148, banner_y + 12), self.active_alert, fill=(0, 0, 0), font=self.font_banner)
            draw.text((self.width // 2 - 150, banner_y + 10), self.active_alert, fill=(255, 255, 255), font=self.font_banner)
        elif self.frame_count >= self.alert_expiry_frame:
            self.active_alert = None

    def _draw_commentary_bar(self, draw: ImageDraw.ImageDraw):
        box_y = self.height - 180
        box_h = 52

        # Semi-transparent glass bar for commentary
        draw.rectangle([0, box_y, self.width, box_y + box_h], fill=(13, 20, 36))
        draw.line([0, box_y, self.width, box_y], fill=(30, 58, 102), width=1)

        # "AI COLOR COMMENTARY" Badge
        if self.is_talking:
            # Animated green mic waveform
            wave_amp = int(abs(math.sin(self.frame_count * 0.3)) * 8)
            draw.rounded_rectangle([25, box_y + 10, 185, box_y + 42], radius=6, fill=(16, 120, 55))
            draw.text((35, box_y + 17), "🎙️ ON AIR (AI)", fill=(255, 255, 255), font=self.font_small)
            # Wave bars
            for b in range(4):
                bx = 150 + b * 6
                bh = 4 + (wave_amp if b % 2 == 0 else 8 - wave_amp)
                draw.line([bx, box_y + 26 - bh, bx, box_y + 26 + bh], fill=(255, 255, 255), width=2)
        else:
            draw.rounded_rectangle([25, box_y + 10, 185, box_y + 42], radius=6, fill=(40, 55, 80))
            draw.text((35, box_y + 17), "🎙️ COLOR BOOTH", fill=(180, 200, 220), font=self.font_small)

        # Commentary subtitle text ticker
        draw.text((200, box_y + 16), self.commentary_text, fill=(245, 245, 250), font=self.font_medium)

    def _draw_lower_third(self, draw: ImageDraw.ImageDraw, state: Dict[str, Any]):
        base_y = self.height - 120
        base_h = 120

        # Dark TV Scorecard Container
        draw.rectangle([0, base_y, self.width, self.height], fill=(9, 14, 26))
        draw.line([0, base_y, self.width, base_y], fill=(40, 80, 150), width=3)

        # Left Score Section (Team Name, Score, Overs)
        team = state.get("batting_team", "BAT")
        runs = state.get("total_runs", 0)
        wickets = state.get("total_wickets", 0)
        overs = state.get("overs_str", "0.0")

        # Blue score pill
        draw.rectangle([0, base_y, 250, self.height], fill=(16, 38, 76))
        draw.text((25, base_y + 15), f"{team}", fill=(255, 215, 0), font=self.font_large)
        draw.text((95, base_y + 12), f"{runs}/{wickets}", fill=(255, 255, 255), font=self.font_large)
        draw.text((25, base_y + 55), f"OVERS: {overs}", fill=(200, 220, 240), font=self.font_medium)
        draw.text((25, base_y + 85), f"TARGET: {state.get('target', '-')}", fill=(160, 180, 210), font=self.font_small)

        # Middle Batsmen Section
        striker = state.get("striker", "Striker")
        s_runs = state.get("striker_runs", 0)
        s_balls = state.get("striker_balls", 0)
        s_4s = state.get("striker_fours", 0)
        s_6s = state.get("striker_sixes", 0)
        s_sr = state.get("striker_sr", 0.0)

        n_striker = state.get("non_striker", "Non-Striker")
        n_runs = state.get("non_striker_runs", 0)
        n_balls = state.get("non_striker_balls", 0)

        col2_x = 275
        # Striker
        draw.text((col2_x, base_y + 18), f"▶ {striker}", fill=(255, 255, 255), font=self.font_medium)
        draw.text((col2_x + 190, base_y + 18), f"{s_runs} ({s_balls})", fill=(255, 215, 0), font=self.font_medium)
        draw.text((col2_x + 270, base_y + 20), f"[4s:{s_4s} 6s:{s_6s} SR:{s_sr}]", fill=(170, 195, 225), font=self.font_small)

        # Non-striker
        draw.text((col2_x, base_y + 52), f"   {n_striker}", fill=(200, 210, 230), font=self.font_medium)
        draw.text((col2_x + 190, base_y + 52), f"{n_runs} ({n_balls})", fill=(200, 210, 230), font=self.font_medium)

        # Recent Over Deliveries Badges
        recents = state.get("recent_balls", [])
        badge_start_x = col2_x
        draw.text((badge_start_x, base_y + 88), "THIS OVER:", fill=(150, 175, 205), font=self.font_small)
        for i, b in enumerate(recents):
            bx = badge_start_x + 95 + (i * 34)
            by = base_y + 82
            # Circle badge color
            color = (35, 55, 85)
            text_color = (255, 255, 255)
            if b == "W":
                color = (220, 30, 30)
            elif b == "6":
                color = (180, 130, 20)
            elif b == "4":
                color = (20, 140, 70)

            draw.ellipse([bx, by, bx + 26, by + 26], fill=color)
            draw.text((bx + 8, by + 5), b, fill=text_color, font=self.font_small)

        # Right Bowler Section
        col3_x = self.width - 340
        draw.line([col3_x - 15, base_y + 10, col3_x - 15, self.height - 10], fill=(30, 50, 80), width=1)

        bowler = state.get("bowler", "Bowler")
        b_ov = state.get("bowler_overs", 0.0)
        b_runs = state.get("bowler_runs", 0)
        b_wkts = state.get("bowler_wickets", 0)
        b_econ = state.get("bowler_economy", 0.0)

        draw.text((col3_x, base_y + 18), "BOWLING", fill=(140, 170, 210), font=self.font_small)
        draw.text((col3_x, base_y + 42), f"{bowler}", fill=(255, 255, 255), font=self.font_medium)
        draw.text((col3_x, base_y + 72), f"{b_wkts}/{b_runs}  ({b_ov} ov)", fill=(255, 215, 0), font=self.font_medium)
        draw.text((col3_x, base_y + 96), f"ECONOMY: {b_econ}", fill=(160, 185, 215), font=self.font_small)
