"""Human Broadcaster Commentary Engine for Cricket Live Streams.

Speaks the exact ball-by-ball commentary text as published on the source site
(CREX) in a human-like broadcast voice — no scripted rewriting of the words.
Only the TTS delivery (rate/pitch/energy) is adapted per event type (wicket,
six, four, dot ball) so the voice sounds alive without altering the wording.
"""
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("HumanCommentator")


class HumanCommentator:
    """Classifies ball events for voice modulation and passes through the
    exact source commentary text to be spoken."""

    # Real Hindi cricket broadcast terms (used only for studio/situational lines
    # that are generated locally, never for the site's own ball commentary).
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
        pass

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
        # Remove fielding positions with 'wicket' to avoid false wicket matches
        t = re.sub(r'\bmid-?wicket\b', '', text.lower())

        if r.upper() == "W" or re.search(r'\b(out|bowled|caught|lbw|run out|stumped|dismissed|timber)\b', t):
            return "wicket"
        if r == "6" or re.search(r'\b(six|maximum|out of the ground|into the stands)\b', t):
            return "six"
        if r == "4" or re.search(r'\b(four|boundary|races away|tracer bullet)\b', t):
            return "four"
        if re.search(r'\b(scores are levelled|scores level|thriller|nail.?biter|last over drama)\b', t):
            return "milestone"
        if r == "0" or re.search(r'\b(no run|dot ball|beaten|play and miss|defended|leaves alone)\b', t):
            return "dot"
        return "rotation"

    def humanize(self, raw_text: str, ball_info: Optional[Dict[str, Any]] = None, lang: str = "en") -> Dict[str, Any]:
        """Classifies the ball event for voice modulation and returns the exact
        source commentary text to be spoken (no rewriting of the words)."""
        ball_info = ball_info or {}
        raw_text_clean = re.sub(r'<[^>]+>', '', raw_text).strip()

        # Check if this is a studio announcement, pre-match preview, post-match summary, or break/stumps
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
            elif any(w in raw_text_clean.lower() for w in ["break", "lunch", "tea", "rain"]) or over_tag == "break":
                badge = "☕ BREAK"
            elif "won by" in raw_text_clean.lower() or over_tag == "result":
                badge = "🏆 RESULT"
            elif "toss" in raw_text_clean.lower() or over_tag in ["pre-match", "preview"]:
                badge = "⚡ PREVIEW"
            else:
                badge = "🎙️ STUDIO"
            rate, pitch = "+3%", "+1Hz"

            if lang == "hi":
                spoken = raw_text_clean
                if not re.search(r'[ऀ-ॿ]', spoken):
                    try:
                        from cricket_streamer import FreeTranslator
                        spoken = FreeTranslator().translate_to_hindi(spoken)
                    except Exception:
                        pass
                spoken = self.apply_hindi_terms(spoken)
            else:
                spoken = raw_text_clean

            return {
                "spoken_text": spoken,
                "event": "studio",
                "badge": badge,
                "rate": rate,
                "pitch": pitch,
                "emotion": "calm",
                "bowler": ball_info.get("bowler", ""),
                "batter": ball_info.get("striker", "")
            }

        # --- Real ball delivery: speak the EXACT commentary published on the source site ---
        bowler = ball_info.get("bowler") or "Bowler"
        batter = ball_info.get("striker") or "Batter"
        bowler_short = bowler.split()[-1] if bowler else "Bowler"
        batter_short = batter.split()[-1] if batter else "Batter"

        matchup = str(ball_info.get("matchup") or "").strip()
        commentary_text = str(ball_info.get("commentary") or "").strip() or raw_text_clean
        runs = ball_info.get("runs", "")

        event = self.detect_event_type(commentary_text, runs)

        # Dynamic TTS Modulation only (Pitch, Rate, Emotion Badge) — wording is untouched
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

        spoken = f"{matchup}. {commentary_text}" if matchup else commentary_text

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
