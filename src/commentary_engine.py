"""Color Commentary NLP Engine for Cricket Broadcast.

Generates broadcast-grade color commentary referencing player statistics,
tactical analysis, game situations, and cricket heritage with low latency.
"""
import json
import logging
import random
from pathlib import Path
from typing import Dict, Any, Optional

import config

logger = logging.getLogger("CommentaryEngine")

COLOR_COMMENTATOR_SYSTEM_PROMPT = """You are an elite international cricket color commentator (in the style of Ravi Shastri, Nasser Hussain, and Ricky Ponting).
The viewers ALREADY have the visual scoreboard and play-by-play description.
YOUR ROLE IS STRICTLY COLOR COMMENTARY:
1. Provide psychological analysis, tactical insights, bowler seam/length analysis, or player statistics.
2. Reference the current player's career strengths, signature shots, or historical cricket moments whenever relevant.
3. Keep it punchy, rhythmic, and broadcaster-ready: EXACTLY 1 to 2 sentences (15 to 25 words maximum).
4. Never describe what just physically happened in plain terms; explain WHY it matters, what the bowler intended, or how the batter outthought the field.
"""

class CommentaryEngine:
    def __init__(self, mode: str = "auto", gemini_api_key: Optional[str] = None):
        self.mode = mode
        self.gemini_api_key = gemini_api_key or config.GEMINI_API_KEY
        self.players = self._load_json(config.PLAYERS_FILE)
        self.heritage = self._load_json(config.HERITAGE_FILE)
        self.gemini_client = None

        if self.gemini_api_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=self.gemini_api_key)
                logger.info("Gemini client initialized for real-time color commentary.")
            except Exception as e:
                logger.warning(f"Could not initialize Gemini client: {e}. Falling back to offline narrative engine.")

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {path}: {e}")
        return {}

    async def generate_commentary(self, summary: Dict[str, Any]) -> str:
        """Generates color commentary for the current ball event."""
        # Check if online mode is preferred and available
        if (self.mode in ("gemini", "auto")) and self.gemini_client:
            try:
                return await self._generate_gemini_commentary(summary)
            except Exception as e:
                logger.warning(f"Gemini generation error ({e}), falling back to offline narrative engine.")

        return self._generate_offline_commentary(summary)

    async def _generate_gemini_commentary(self, summary: Dict[str, Any]) -> str:
        striker = summary.get("striker", "Batter")
        bowler = summary.get("bowler", "Bowler")
        striker_data = self.players.get(striker, {})
        bowler_data = self.players.get(bowler, {})

        context_payload = {
            "striker": striker,
            "striker_score": f"{summary.get('striker_runs')} off {summary.get('striker_balls')} balls (SR: {summary.get('striker_sr')})",
            "striker_nuggets": striker_data.get("nuggets", []),
            "bowler": bowler,
            "bowler_figures": f"{summary.get('bowler_wickets')}/{summary.get('bowler_runs')} in {summary.get('bowler_overs')} ov",
            "bowler_profile": bowler_data.get("tactical_profile", ""),
            "match_situation": f"Score: {summary.get('total_runs')}/{summary.get('total_wickets')} in {summary.get('overs_str')} ov.",
            "target": summary.get("target"),
            "runs_needed": summary.get("runs_needed"),
            "balls_remaining": summary.get("balls_remaining"),
            "crr": summary.get("crr"),
            "rrr": summary.get("rrr"),
            "last_event": summary.get("last_event_text"),
            "milestone": summary.get("milestone"),
            "venue": summary.get("venue")
        }

        user_prompt = f"Match Data: {json.dumps(context_payload)}\nGenerate the 1-2 sentence color commentary broadcast voiceover line now:"

        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config={
                    "system_instruction": COLOR_COMMENTATOR_SYSTEM_PROMPT,
                    "temperature": 0.7,
                    "max_output_tokens": 80
                }
            )
        )
        text = response.text.strip().replace('"', '')
        return text

    def _generate_offline_commentary(self, summary: Dict[str, Any]) -> str:
        """High-speed heuristic narrative color commentary generator."""
        striker = summary.get("striker", "The batter")
        bowler = summary.get("bowler", "The bowler")
        striker_runs = summary.get("striker_runs", 0)
        striker_balls = summary.get("striker_balls", 0)
        striker_sr = summary.get("striker_sr", 0.0)
        is_wicket = summary.get("is_wicket", False)
        is_boundary = summary.get("is_boundary", False)
        b_type = summary.get("boundary_type")
        runs_needed = summary.get("runs_needed", 0)
        balls_rem = summary.get("balls_remaining", 0)
        rrr = summary.get("rrr", 0.0)
        venue = summary.get("venue", "the stadium")

        p_striker = self.players.get(striker, {})
        p_bowler = self.players.get(bowler, {})
        nuggets_striker = p_striker.get("nuggets", [])
        nuggets_bowler = p_bowler.get("nuggets", [])

        # 1. Milestone / 50 or Century
        if striker_runs == 50 and summary.get("last_ball_runs", 0) in (1, 2, 4):
            if nuggets_striker:
                return f"That brings up a masterclass half-century for {striker}! {random.choice(nuggets_striker)}"
            return f"Magnificent fifty for {striker}. He is controlling the tempo of this chase with utter precision."

        # 2. Wicket situation
        if is_wicket:
            dismissed = summary.get("dismissed_player", striker)
            if p_bowler.get("specialty"):
                return f"Massive breakthrough for {bowler}! That is his trademark {p_bowler['specialty']} delivering gold under extreme pressure."
            return f"What a twist in the tale! Australia strike just when India looked to be running away with the contest."

        # 3. Six hit
        if is_boundary and b_type == 6:
            if p_striker.get("signature_shot"):
                return f"High, handsome, and into the stands! That signature bat swing from {striker} striking at {striker_sr} today."
            if nuggets_striker:
                return f"Pure authority from {striker}! {random.choice(nuggets_striker)}"
            return f"That is sheer class under pressure. You simply cannot miss your radar in the death overs against a batter in this mood."

        # 4. Four hit
        if is_boundary and b_type == 4:
            if runs_needed <= 0 and summary.get("is_chase"):
                return f"What a breathtaking finish here at {venue}! {striker} seals an unforgettable run chase under the lights."
            if nuggets_striker:
                return f"Exquisite timing from {striker}! Remember, in high-pressure chases, his calm temperament is second to none."
            return f"Beaten for sheer timing! The field was up on the off-side, and {striker} pierced the gap with surgical precision."

        # 5. Tight dot ball
        if summary.get("last_ball_runs", 0) == 0:
            if nuggets_bowler:
                return f"Ice in his veins from {bowler}. {random.choice(nuggets_bowler)}"
            return f"Dot ball gold! When the required rate is touching {rrr}, every ball without a run is a mini-victory for the bowling side."

        # 6. Singles / Twos / General Rotation
        if summary.get("last_ball_runs", 0) == 2:
            return f"Terrific hustle between the wickets by {striker}. Turning ones into twos is the hallmark of great white-ball chasers."

        # Default contextual commentary
        if runs_needed > 0 and balls_rem > 0:
            return f"India need {runs_needed} off {balls_rem} balls. The field is spread, but {striker} knows a boundary is just around the corner."

        return f"Tremendous atmosphere here at {venue}. The tactical chess match between bat and ball is reaching boiling point."
