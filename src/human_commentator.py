"""Hinglish Broadcaster Commentary Engine for Cricket Live Streams.

Takes all ball-by-ball text and match state as input from CREX/match feed,
and delivers dynamic, energetic Hinglish commentary (mix of Hindi + English)
in authentic Indian TV broadcast style (like Aakash Chopra / JioCinema / Star Sports).

Powered by Gemini AI (with intelligent, high-speed local fallback) for real-time
sub-second delivery.
"""
import os
import re
import json
import logging
import asyncio
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

logger = logging.getLogger("HumanCommentator")


class HumanCommentator:
    """Delivers live cricket broadcast commentary in vibrant Hinglish,
    using all ball text and context as input."""

    GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"

    # Authentic Hindi broadcast terms for fallback / replacements
    HINDI_CRICKET_TERMS = [
        (r'\bscores are levelled\b', 'स्कोर बराबर हो चुका है'),
        (r'\bscores level\b', 'स्कोर बराबर'),
        (r'\bshort and around off\b', 'ऑफ स्टंप के बाहर शॉर्ट पिच गेंद'),
        (r'\bshort of a length\b', 'शॉर्ट ऑफ लेंथ गेंद'),
        (r'\bgood length\b', 'गुड लेंथ पर टप्पा खाती गेंद'),
        (r'\boutside off\b', 'ऑफ स्टंप के बाहर'),
        (r'\bon the pads\b', 'पैड्स पर आती हुई गेंद'),
        (r'\byorker\b', 'सटीक यॉर्कर'),
        (r'\bbouncer\b', 'तीखा बाउंसर'),
        (r'\bslower ball\b', 'गति में परिवर्तन, धीमी गेंद'),
        (r'\bclean bowled\b', 'क्लीन बोल्ड, गिल्लियां हवा में'),
        (r'\bbowled him\b', 'क्लीन बोल्ड'),
        (r'\bcaught behind\b', 'विकेटकीपर के हाथों में कैच'),
        (r'\braces away\b', 'गोली की रफ़्तार से सीमा रेखा के पार'),
        (r'\btracer bullet\b', 'ट्रेसर बुलेट की तरह गोली की रफ़्तार से'),
        (r'\bcover drive\b', 'लाजवाब कवर ड्राइव'),
        (r'\bpull shot\b', 'शानदार पुल शॉट'),
        (r'\bslog sweep\b', 'दमदार स्लॉग स्वीप'),
        (r'\bstraight down the ground\b', 'सीधे बल्ले से बॉलर के सिर के ऊपर से'),
        (r'\bbottom part of the bat\b', 'बल्ले के निचले हिस्से से लगी गेंद'),
        (r'\bmiddle of the bat\b', 'बल्ले के बीचों-बीच से'),
        (r'\btickled fine\b', 'हल्के हाथों से फाइन लेग की तरफ मोड़ा'),
        (r'\bdrifts into the pads\b', 'पैड्स पर टकराई'),
        (r'\bhuge appeal\b', 'जोरदार अपील'),
        (r'\bnot out\b', 'नॉट आउट करार दिया'),
        (r'\bsingle taken\b', 'आसानी से एक रन पूरा किया'),
        (r'\btwo runs\b', 'तेजी से दौड़कर दो रन बटोरे'),
        (r'\bno run\b', 'कोई रन नहीं'),
        (r'\bdot ball\b', 'डॉट गेंद'),
        (r'\bfour runs\b', 'चार रन'),
        (r'\bsix runs\b', 'छह रन'),
        (r'\bboundary\b', 'शानदार चौका'),
        (r'\bmaximum\b', 'गगनचुंबी छक्का'),
    ]

    def __init__(self):
        self.default_gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    @classmethod
    def apply_hindi_terms(cls, text: str) -> str:
        """Applies authentic Hindi cricket terminology replacements."""
        res = text
        for pattern, repl in cls.HINDI_CRICKET_TERMS:
            res = re.sub(pattern, repl, res, flags=re.IGNORECASE)
        return res

    @classmethod
    def detect_event_type(cls, text: str, runs: str = "") -> str:
        """Accurately detects cricket event without false positives like 'mid-wicket'."""
        r = str(runs).strip()
        t = re.sub(r'\bmid-?wicket\b', '', text.lower())

        if r.upper() == "W" or re.search(r'\b(out|bowled|caught|lbw|run out|stumped|dismissed|timber)\b', t):
            return "wicket"
        if r == "6" or re.search(r'\b(six|maximum|out of the ground|into the stands)\b', t):
            return "six"
        if r == "4" or re.search(r'\b(four|boundary|races away|tracer bullet)\b', t):
            return "four"
        if re.search(r'\b(scores are levelled|scores level|thriller|nail.?biter|last over drama)\b', t):
            return "milestone"
        if r in ("WD", "WIDE") or re.search(r'\b(wide ball|wide)\b', t):
            return "wide"
        if r in ("NB", "NO BALL") or re.search(r'\b(no ball|free hit)\b', t):
            return "noball"
        if r == "0" or re.search(r'\b(no run|dot ball|beaten|play and miss|defended|leaves alone)\b', t):
            return "dot"
        return "rotation"

    def generate_local_hinglish(self, ball_info: Dict[str, Any], event: str) -> str:
        """High-speed local fallback engine that produces energetic Hinglish commentary
        taking all ball text into account."""
        bowler = ball_info.get("bowler") or "Bowler"
        batter = ball_info.get("striker") or "Batter"
        bowler_short = bowler.split()[-1] if bowler else "Bowler"
        batter_short = batter.split()[-1] if batter else "Batter"

        commentary = str(ball_info.get("commentary") or "").lower()
        runs = str(ball_info.get("runs", "")).strip()

        # Check for specific shot / ball variations
        if event == "wicket":
            if "bowled" in commentary or "timber" in commentary:
                return f"{bowler_short} ki raftaar aur stumps hawa mein! {batter_short} clean bowled, kya zabardast delivery thi!"
            elif "caught" in commentary or "catch" in commentary:
                return f"Gend hawa mein, fielder niche aur aasan catch! {batter_short} ka bada wicket yahan girta hua!"
            elif "lbw" in commentary or "pads" in commentary:
                return f"Pads par lagi ball, zordaar appeal aur umpire ki ungli uthi! {batter_short} ko jana hoga wapas!"
            elif "run out" in commentary:
                return f"Direct hit aur batsman crease se bahar! Kya chust fielding, {batter_short} run out ho gaye!"
            return f"Bada jhatka! {bowler_short} ne {batter_short} ko pavilion ka raasta dikha diya hai, huge breakthrough!"

        elif event == "six":
            if "pull" in commentary or "hook" in commentary:
                return f"Short ball aur {batter_short} ka damdaar pull shot! Gend seedha boundary ke paar, 6 run!"
            elif "cover" in commentary or "straight" in commentary:
                return f"Kya timing hai! {batter_short} ne lofted shot khela aur ball direct stands mein, shaandaar six!"
            return f"Utha kar mara hai {batter_short} ne! Gend seedha darshakon ke beech, behtareen six lagaya yahan!"

        elif event == "four":
            if "cover drive" in commentary:
                return f"Textbook cover drive! {batter_short} ne khoobsurat timing dikhayi aur gend bullet ki tarah boundary paar, 4 run!"
            elif "cut" in commentary or "point" in commentary:
                return f"Point ke bagal se gap dhoondha {batter_short} ne, fielder helpless aur yeh mila ek aur shaandaar chauka!"
            elif "sweep" in commentary:
                return f"Fine sweep shot {batter_short} dwara! Ball tezi se fine leg boundary ke paar, chaar run!"
            return f"Khoobsurat shot! {batter_short} ne gap nikaala aur ball goli ki speed se boundary ke paar, 4 run!"

        elif event == "dot":
            if "yorker" in commentary:
                return f"{bowler_short} ki pin-point yorker! {batter_short} ke paas koi jawab nahi tha, dot ball."
            elif "bouncer" in commentary or "short" in commentary:
                return f"Tez bouncer {bowler_short} dwara, {batter_short} ne duck kiya, koi run nahi milega."
            elif "beaten" in commentary:
                return f"Lajawab delivery {bowler_short} ki! {batter_short} poori tarah se beat hue, dot ball."
            return f"Achhi line aur length, {batter_short} ne defend kiya aur koi run lene ka mauka nahi mila."

        elif event == "wide":
            return f"Direction se bhatke {bowler_short}, leg stump ke bahar aur umpire ne isse wide ball karaar diya."

        elif event == "noball":
            return f"Overstepping yahan {bowler_short} dwara, no-ball ka signal aur ab batsman ko milegi free-hit!"

        else:
            # 1 or 2 runs rotation
            if runs == "2":
                return f"Gap mein push kiya aur tezi se bhaag kar do run poore kiye, behtareen running between the wickets."
            return f"Halke haathon se push kiya aur aasaani se strike rotate kiya ek run ke saath."

    async def generate_gemini_hinglish(self, ball_info: Dict[str, Any], api_key: str) -> Optional[str]:
        """Calls Gemini API with full ball text and context to generate vibrant Hinglish commentary."""
        import aiohttp

        over = ball_info.get("over", "")
        bowler = ball_info.get("bowler", "Bowler")
        striker = ball_info.get("striker", "Batter")
        runs = ball_info.get("runs", "")
        commentary = ball_info.get("commentary", "")
        matchup = ball_info.get("matchup", "")
        batting_team = ball_info.get("batting_team", "")
        score = f"{ball_info.get('total_runs', '')}/{ball_info.get('total_wickets', '')}" if ball_info.get('total_runs') else ""
        target = ball_info.get("target", "")

        context_parts = []
        if over:
            context_parts.append(f"Over: {over}")
        if matchup:
            context_parts.append(f"Matchup: {matchup}")
        elif bowler or striker:
            context_parts.append(f"Bowler: {bowler}, Batter: {striker}")
        if runs:
            context_parts.append(f"Runs on ball: {runs}")
        if score:
            context_parts.append(f"Score: {score} ({batting_team})")
        if target:
            context_parts.append(f"Target: {target}")
        if commentary:
            context_parts.append(f"Source commentary text: {commentary}")

        context_str = "\n".join(f"- {p}" for p in context_parts)

        prompt = f"""You are a top-tier Indian cricket live TV broadcaster (in the energetic, engaging style of Aakash Chopra, Jatin Sapru, or JioCinema/Star Sports).
Convert the following cricket ball details into a single short, punchy, exciting Hinglish live commentary line (1 to 2 sentences max).

Guidelines:
1. Deliver in natural Hinglish (Hindi + English blend written in Roman/English script, e.g. "Bumrah ki raftaar aur stumps hawa mein!").
2. DO NOT just repeat the raw text. Make it fresh, enthusiastic, and conversational for live audio broadcast.
3. Keep it under 25 words so the live voice synthesis is fast and real-time.
4. Output ONLY the Hinglish commentary line, no quotes, no markdown, no conversational filler.

Ball Details:
{context_str}"""

        url = f"{self.GEMINI_ENDPOINT}?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.8,
                "topP": 0.95,
                "maxOutputTokens": 60
            }
        }

        try:
            timeout = aiohttp.ClientTimeout(total=4.5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                line = parts[0].get("text", "").strip()
                                line = line.strip('"\'*`')
                                if line:
                                    return line
                    else:
                        err_text = await resp.text()
                        logger.warning(f"Gemini API returned status {resp.status}: {err_text[:120]}")
        except Exception as e:
            logger.warning(f"Gemini Hinglish generation timeout/error ({e}), using local engine.")

        return None

    async def humanize_async(
        self,
        raw_text: str,
        ball_info: Optional[Dict[str, Any]] = None,
        lang: str = "hinglish",
        gemini_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Asynchronously processes all ball text into dynamic Hinglish commentary
        powered by Gemini AI, with high-speed local fallback."""
        ball_info = ball_info or {}
        raw_text_clean = re.sub(r'<[^>]+>', '', raw_text).strip()

        # Check studio / breaks / non-ball events
        over_tag = str(ball_info.get("over", "")).lower()
        is_studio = (
            bool(ball_info.get("is_studio"))
            or over_tag in ["pre-match", "result", "summary", "preview", "post-match", "stumps", "break", "update"]
            or any(k in raw_text_clean.lower() for k in [
                "welcome", "won by", "scores are", "stumps", "innings break",
                "lunch break", "tea break", "rain delay", "match update",
                "match situation", "toss", "concludes", "goodbye", "live build-up",
                "match wrap", "play update", "stand at", "at the crease"
            ])
        )

        if is_studio:
            if "stumps" in raw_text_clean.lower() or over_tag == "stumps":
                badge = "⏸️ STUMPS"
                spoken = "Aaj ke din ka khel samapt ho chuka hai, stumps call kar diya gaya hai."
            elif any(w in raw_text_clean.lower() for w in ["break", "lunch", "tea", "rain"]) or over_tag == "break":
                badge = "☕ BREAK"
                spoken = "Match mein break ho chuka hai, thodi der mein dobara live judenge."
            elif "won by" in raw_text_clean.lower() or over_tag == "result":
                badge = "🏆 RESULT"
                spoken = f"Match ka nateeja aa chuka hai! {raw_text_clean}"
            elif "toss" in raw_text_clean.lower() or over_tag in ["pre-match", "preview"]:
                badge = "⚡ PREVIEW"
                spoken = "Toss ka samay ho chuka hai aur match ka preview shuru ho gaya hai!"
            else:
                badge = "🎙️ STUDIO"
                spoken = raw_text_clean

            return {
                "spoken_text": spoken,
                "event": "studio",
                "badge": badge,
                "rate": "+3%",
                "pitch": "+1Hz",
                "emotion": "calm",
                "bowler": ball_info.get("bowler", ""),
                "batter": ball_info.get("striker", "")
            }

        # --- Real ball delivery ---
        bowler = ball_info.get("bowler") or "Bowler"
        batter = ball_info.get("striker") or "Batter"
        bowler_short = bowler.split()[-1] if bowler else "Bowler"
        batter_short = batter.split()[-1] if batter else "Batter"

        commentary_text = str(ball_info.get("commentary") or "").strip() or raw_text_clean
        runs = str(ball_info.get("runs", "")).strip()

        # Detect event type for audio modulation and badge
        event = self.detect_event_type(commentary_text, runs)

        if event == "wicket":
            rate, pitch, badge, emotion = "+9%", "+4Hz", "⚡ WICKET", "high_energy"
        elif event == "six":
            rate, pitch, badge, emotion = "+8%", "+3Hz", "🔥 MAXIMUM", "high_energy"
        elif event == "four":
            rate, pitch, badge, emotion = "+6%", "+2Hz", "🎯 BOUNDARY", "medium_energy"
        elif event == "milestone":
            rate, pitch, badge, emotion = "+7%", "+3Hz", "💥 THRILLER", "high_energy"
        elif event == "dot":
            rate, pitch, badge, emotion = "+1%", "+0Hz", "🛡️ DOT BALL", "calm"
        else:
            rate, pitch, badge, emotion = "+3%", "+1Hz", "🏏 ROTATION", "normal"

        # Determine Hinglish Commentary
        # Default behavior: Deliver in lively Hinglish taking all ball text as input!
        spoken = ""
        key = gemini_api_key or self.default_gemini_key or os.environ.get("GEMINI_API_KEY", "").strip()

        if lang in ("hinglish", "hi", "en", ""):
            if key:
                ai_line = await self.generate_gemini_hinglish(ball_info, key)
                if ai_line:
                    spoken = ai_line

            # If Gemini was not used or failed, use local Hinglish generator
            if not spoken:
                spoken = self.generate_local_hinglish(ball_info, event)

        return {
            "spoken_text": spoken,
            "event": event,
            "badge": badge,
            "rate": rate,
            "pitch": pitch,
            "emotion": emotion,
            "bowler": bowler_short,
            "batter": batter_short
        }

    def humanize(
        self,
        raw_text: str,
        ball_info: Optional[Dict[str, Any]] = None,
        lang: str = "hinglish",
        gemini_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Synchronous wrapper for humanize_async."""
        ball_info = ball_info or {}
        commentary_text = str(ball_info.get("commentary") or "").strip() or re.sub(r'<[^>]+>', '', raw_text).strip()
        runs = str(ball_info.get("runs", "")).strip()
        event = self.detect_event_type(commentary_text, runs)

        # In synchronous context, use the local Hinglish generator
        spoken = self.generate_local_hinglish(ball_info, event)

        bowler = ball_info.get("bowler") or "Bowler"
        batter = ball_info.get("striker") or "Batter"
        bowler_short = bowler.split()[-1] if bowler else "Bowler"
        batter_short = batter.split()[-1] if batter else "Batter"

        if event == "wicket":
            rate, pitch, badge, emotion = "+9%", "+4Hz", "⚡ WICKET", "high_energy"
        elif event == "six":
            rate, pitch, badge, emotion = "+8%", "+3Hz", "🔥 MAXIMUM", "high_energy"
        elif event == "four":
            rate, pitch, badge, emotion = "+6%", "+2Hz", "🎯 BOUNDARY", "medium_energy"
        elif event == "milestone":
            rate, pitch, badge, emotion = "+7%", "+3Hz", "💥 THRILLER", "high_energy"
        elif event == "dot":
            rate, pitch, badge, emotion = "+1%", "+0Hz", "🛡️ DOT BALL", "calm"
        else:
            rate, pitch, badge, emotion = "+3%", "+1Hz", "🏏 ROTATION", "normal"

        return {
            "spoken_text": spoken,
            "event": event,
            "badge": badge,
            "rate": rate,
            "pitch": pitch,
            "emotion": emotion,
            "bowler": bowler_short,
            "batter": batter_short
        }


# Global singleton
commentator = HumanCommentator()
