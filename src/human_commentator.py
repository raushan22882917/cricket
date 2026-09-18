"""Human Broadcaster Commentary Engine for Cricket Live Streams.

Converts raw scraped ball-by-ball text or webhook payloads into television-quality
color commentary in English (Ravi Shastri / Ian Bishop style) and Hindi (Aakash Chopra / Vivek Razdan style).
Prevents robotic verbatim reading by injecting emotional cadence, natural breath pauses,
and authentic cricket broadcast terminology.
"""
import re
import json
import random
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger("HumanCommentator")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PLAYERS_FILE = DATA_DIR / "players.json"
HERITAGE_FILE = DATA_DIR / "heritage.json"


class HumanCommentator:
    """Intelligent commentary reformatter that turns plain text into authentic human broadcasts."""

    # Real Hindi cricket broadcast terms (preventing literal dictionary translation)
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

    ENGLISH_WICKET_HOOKS = [
        "OH GONE! What an absolute ripper of a delivery!",
        "BOWLED HIM! Knocked the castle over in breathtaking fashion!",
        "IN THE AIR... AND TAKEN! A massive, massive breakthrough for the bowling side!",
        "EDGED AND GONE! The finger goes up and that is the end of a big innings!",
        "OUT! Timber! You miss, I hit — fast bowling at its absolute finest!"
    ]

    ENGLISH_SIX_HOOKS = [
        "HIGH, HANDSOME, AND INTO THE STANDS! What an enormous hit!",
        "BOOM! Dispatched into the second tier with sheer disdain!",
        "STAND AND DELIVER! That ball has left the stadium, colossal six!",
        "SWEET AS A NUT! Pure timing, straight out of the screws for a maximum!"
    ]

    ENGLISH_FOUR_HOOKS = [
        "CRACKING SHOT! Pierces the infield and races away like a tracer bullet to the fence!",
        "MAGNIFICENT TIMING! Leans into the drive and that is four written all over it!",
        "DELICATE TOUCH! Guided expertly past third man with soft hands, boundary!",
        "PULLED WITH AUTHORITY! That was asking to be hit and got the royal treatment!"
    ]

    ENGLISH_DOT_HOOKS = [
        "Beaten all ends up! Superb seam presentation, asking serious questions outside off.",
        "Solid defense right under the eyes, giving absolutely nothing away.",
        "Play and a miss! Through to the keeper, tension ratcheting up here.",
        "Tight, disciplined line. That's pure gold in the context of this game."
    ]

    ENGLISH_ROTATION_HOOKS = [
        "Pushed into the gap, calls early, and they hustle through for a sharp single.",
        "Worked off the hips into the leg side, comfortable single to turn the strike over.",
        "Soft hands towards mid-wicket, excellent communication and running between the wickets.",
        "Tapped gently into the cover region, sensible cricket to keep the scoreboard ticking."
    ]

    HINDI_WICKET_HOOKS = [
        "ओहोहो! क्लीन बोल्ड! गिल्लियां हवा में नाचती हुई, बहुत बड़ा झटका यहाँ पर!",
        "हवा में गेंद... और फील्डर नीचे, कोई गलती नहीं! शानदार कैच और पवेलियन का रास्ता दिखाया!",
        "अरे वाह, क्या गेंद थी! बल्लेबाज के पास कोई जवाब नहीं, सीधा स्टंप्स पर जा टकराई!",
        "बड़ा विकेट! दबाव काम कर गया, और एक अहम साझेदारी का अंत!"
    ]

    HINDI_SIX_HOOKS = [
        "वाह भाई वाह! क्या टाइमिंग, क्या पावर! गेंद जा गिरी सीधे स्टैंड्स में, गगनचुंबी छक्का!",
        "गेंद हवा में, और दर्शकों के बीच! इसे कहते हैं अधिकार भरा शॉट, छह रन!",
        "खोल के रख दिया धागा! बल्ले के बीचों-बीच से निकली गेंद, लंबा छक्का!"
    ]

    HINDI_FOUR_HOOKS = [
        "खूबसूरत टाइमिंग! नज़ाकत भरा शॉट और गेंद गोली की रफ़्तार से सीमा रेखा के पार, चार रन!",
        "गैप में ढकेला, फील्डर के पास कोई मौका नहीं! दर्शनीय चौका!",
        "नजाकत और ताकत का बेहतरीन संगम, गेंद सीधे बाउंड्री के पार चार रनों के लिए!"
    ]

    HINDI_DOT_HOOKS = [
        "सटीक लाइन और लेंथ, बल्लेबाज पूरी तरह से चकमा खा गए, कोई रन नहीं.",
        "शानदार वापसी गेंदबाज की, बल्लेबाज को क्रीज पर बिल्कुल बांध कर रखा.",
        "बेहतरीन गेंदबाजी, डॉट गेंद के साथ दबाव और ज्यादा बढ़ता हुआ."
    ]

    HINDI_ROTATION_HOOKS = [
        "हल्के हाथों से खेला, खाली जगह में गेंद और आसानी से एक रन पूरा किया, स्ट्राइक बदली.",
        "गैप में ढकेला, तेजी से भागे और सुरक्षित क्रीज में पहुंचे, एक रन.",
        "सूझबूझ भरी बल्लेबाजी, सिंगल्स के साथ स्कोरबोर्ड को लगातार चलायमान रखते हुए."
    ]

    def __init__(self):
        self.players = self._load_json(PLAYERS_FILE)
        self.heritage = self._load_json(HERITAGE_FILE)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {path}: {e}")
        return {}

    @classmethod
    def clean_raw_crex(cls, text: str) -> Tuple[str, str, str]:
        """Extracts bowler, batter, and core commentary action from raw CREX string."""
        bowler = ""
        batter = ""
        clean = text

        # Strip 'Over 10.4: ' or '10.4'
        m_over = re.search(r'Over\s*([0-9\.]+)\s*:?\s*', clean, re.IGNORECASE)
        if m_over:
            clean = clean[m_over.end():].strip()

        # Match 'Bowler to Batter'
        m_matchup = re.match(r'([A-Za-z\s]+)\s+to\s+([A-Za-z\s]+)[\.\,\:\-]\s*', clean, re.IGNORECASE)
        if m_matchup:
            bowler = m_matchup.group(1).strip()
            batter = m_matchup.group(2).strip()
            clean = clean[m_matchup.end():].strip()

        # Remove repetitive uppercase headers like 'SCORES ARE LEVELLED!'
        clean = re.sub(r'^\s*([A-Z\s]{4,})\s*!\s*', r'\1. ', clean)
        return bowler, batter, clean.strip()

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
        """Turns raw event text into broadcaster-level human speech."""
        ball_info = ball_info or {}
        raw_bowler, raw_batter, core_commentary = self.clean_raw_crex(raw_text)

        bowler = ball_info.get("bowler") or raw_bowler or "The bowler"
        batter = ball_info.get("striker") or raw_batter or "The batter"
        runs = ball_info.get("runs", "")

        # Use last names for natural broadcast rhythm (e.g. "Pat Cummins" -> "Cummins")
        bowler_short = bowler.split()[-1] if bowler else "Bowler"
        batter_short = batter.split()[-1] if batter else "Batter"

        event = self.detect_event_type(core_commentary + " " + raw_text, runs)

        # Check player database for signature highlights
        p_striker = self.players.get(batter, {})
        p_bowler = self.players.get(bowler, {})
        striker_signature = p_striker.get("signature_shot", "")
        bowler_specialty = p_bowler.get("specialty", "")

        # Dynamic TTS Modulation (Pitch, Rate, Emotion Badge)
        if event == "wicket":
            rate, pitch = "+9%", "+4Hz"
            badge = "⚡ WICKET"
            emotion = "high_energy"
        elif event == "six":
            rate, pitch = "+8%", "+3Hz"
            badge = "🔥 MAXIMUM"
            emotion = "high_energy"
        elif event == "four":
            rate, pitch = "+6%", "+2Hz"
            badge = "🎯 BOUNDARY"
            emotion = "medium_energy"
        elif event == "milestone":
            rate, pitch = "+7%", "+3Hz"
            badge = "💥 THRILLER"
            emotion = "high_energy"
        elif event == "dot":
            rate, pitch = "+1%", "+0Hz"
            badge = "🛡️ DOT BALL"
            emotion = "calm"
        else:
            rate, pitch = "+3%", "+1Hz"
            badge = "🏏 ROTATION"
            emotion = "normal"

        if lang == "hi":
            # --- HINDI HUMAN COMMENTARY (Aakash Chopra / Vivek Razdan style) ---
            specialty_hi = "घातक यॉर्कर" if "yorker" in bowler_specialty.lower() else "शानदार स्विंग" if "swing" in bowler_specialty.lower() else "कसी हुई गेंदबाजी"
            shot_hi = "कवर ड्राइव" if "cover" in striker_signature.lower() else "पुल शॉट" if "pull" in striker_signature.lower() else "हवाई शॉट"

            if event == "wicket":
                hook = random.choice(self.HINDI_WICKET_HOOKS)
                if bowler_specialty:
                    spoken = f"{hook} {bowler_short} की {specialty_hi}, और {batter_short} को पवेलियन लौटना ही होगा!"
                else:
                    spoken = f"{hook} {bowler_short} की घातक गेंदबाजी, {batter_short} पूरी तरह चकमा खा गए!"
            elif event == "six":
                hook = random.choice(self.HINDI_SIX_HOOKS)
                if striker_signature:
                    spoken = f"{hook} {batter_short} का वो ट्रेडमार्क {shot_hi}, गेंद को भेजा सीधे हवाई यात्रा पर!"
                else:
                    spoken = f"{hook} {batter_short} ने गेंद को भेजा सीधे हवाई यात्रा पर, क्या गजब का शॉट!"
            elif event == "four":
                hook = random.choice(self.HINDI_FOUR_HOOKS)
                spoken = f"{hook} {batter_short} के बल्ले से निकला ये दिलकश चौका, फील्डर मूकदर्शक बने रहे!"
            elif event == "milestone":
                spoken = f"सांसें थाम देने वाला रोमांच! स्कोर यहाँ बराबर हो चुके हैं दोस्तों, {bowler_short} और {batter_short} के बीच कांटे की टक्कर!"
            elif event == "dot":
                hook = random.choice(self.HINDI_DOT_HOOKS)
                spoken = f"{bowler_short} अपने रन-अप से आए... {hook}"
            else:
                hook = random.choice(self.HINDI_ROTATION_HOOKS)
                spoken = f"{bowler_short} की ये गेंद... {batter_short} ने {hook}"

            # If core commentary has specific dramatic highlights, adapt into authentic Hindi
            if "scores are levelled" in core_commentary.lower():
                spoken = f"स्कोर बराबर हो चुका है दोस्तों! {batter_short} ने गेंद को मिड-विकेट की दिशा में मोड़ा, तेजी से एक रन निकाला, और मुकाबला टाई हो चुका है!"
        else:
            # --- ENGLISH HUMAN COMMENTARY (Ravi Shastri / Ian Bishop style) ---
            if event == "wicket":
                hook = random.choice(self.ENGLISH_WICKET_HOOKS)
                if bowler_specialty:
                    spoken = f"{hook} That is {bowler_short}'s signature {bowler_specialty} doing the damage under extreme pressure!"
                else:
                    spoken = f"{hook} {bowler_short} strikes with sheer venom, and {batter_short} has to make the long walk back!"
            elif event == "six":
                hook = random.choice(self.ENGLISH_SIX_HOOKS)
                if striker_signature:
                    spoken = f"{hook} That trademark {striker_signature} from {batter_short}, launching it into the stratosphere!"
                else:
                    spoken = f"{hook} {batter_short} steps out and sends that soaring deep into the crowd!"
            elif event == "four":
                hook = random.choice(self.ENGLISH_FOUR_HOOKS)
                spoken = f"{hook} Brilliant placement from {batter_short}, finding the fence with surgical precision!"
            elif event == "milestone":
                spoken = f"THE SCORES ARE LEVEL! High drama here at the ground — {batter_short} tucks it into the deep, and this game is right on the edge!"
            elif event == "dot":
                hook = random.choice(self.ENGLISH_DOT_HOOKS)
                spoken = f"{bowler_short} steams in... {hook}"
            else:
                hook = random.choice(self.ENGLISH_ROTATION_HOOKS)
                spoken = f"{bowler_short} into the attack... {batter_short} {hook}"

            if "scores are levelled" in core_commentary.lower():
                spoken = f"AND THE SCORES ARE TIED! Pushed through mid-wicket for a frantic single, and what an unbelievable climax we have here!"

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
