#!/usr/bin/env python3
"""
🏏 All-in-One Cricket AI Streaming Engine (URL -> Scrape -> AI Commentary -> Hindi/English TTS -> YouTube Live)

Usage:
  # 1. English commentary preview from CREX link:
  python cricket_streamer.py "https://crex.com/cricket-live-score/pak-w-vs-tha-w-2nd-qtr-final-womens-asian-games-t20-2026-match-updates-13Q0"

  # 2. Hindi commentary preview (free translator + Hindi neural voice):
  python cricket_streamer.py "https://crex.com/..." --lang hi

  # 3. Stream directly to YouTube Live:
  python cricket_streamer.py "https://crex.com/..." --lang hi --mode youtube --key "xxxx-xxxx-xxxx-xxxx"
"""
import os
import re
import sys
import html
import time
import json
import queue
import tempfile
import asyncio
import logging
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import edge_tts
import aiohttp
from bs4 import BeautifulSoup
from pydub import AudioSegment
from pydub.effects import normalize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.human_commentator import commentator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("CricketStreamer")



class FreeTranslator:
    """100% Free Translation to Hindi with zero API keys."""
    def __init__(self):
        self._translator = None

    def _get_translator(self):
        if self._translator is None:
            try:
                from deep_translator import MyMemoryTranslator
                self._translator = MyMemoryTranslator(source="en-US", target="hi-IN")
            except Exception as e:
                logger.warning(f"Could not initialize MyMemoryTranslator: {e}")
        return self._translator

    def translate_to_hindi(self, text: str) -> str:
        # Check if already Devanagari/Hindi
        if re.search(r'[\u0900-\u097F]', text):
            return text

        clean = re.sub(r'<[^>]+>', '', text).strip()
        if not clean:
            return ""

        tr = self._get_translator()
        if tr:
            try:
                # Translate in concise chunks
                translated = tr.translate(clean[:300])
                if translated and len(translated) > 5:
                    return translated
            except Exception as e:
                logger.warning(f"Free translation notice: {e}, using original text.")

        return clean


class CrexParser:
    """Scrapes match details and commentary paragraphs line-by-line from CREX.

    CREX renders ball-by-ball commentary server-side in the language selected
    via its `content-lang` cookie (e.g. 'hi' for native Hindi commentary written
    by CREX itself, not machine-translated). Passing the same code we broadcast
    in gets the exact source-site text in that language.
    """
    def __init__(self, url: str, lang: str = "en"):
        self.url = url.strip()
        self.lang = lang

    async def fetch_html_async(self, session: Optional[aiohttp.ClientSession] = None) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": f"content-lang={self.lang}"
        }
        try:
            if session and not session.closed:
                async with session.get(self.url, headers=headers, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=4.5)) as resp:
                    if resp.status == 404 or str(resp.url).endswith("/404"):
                        raise ValueError(f"Match URL returned 404 (Not Found): {self.url}")
                    if resp.status == 200:
                        text = await resp.text()
                        if "<title>404" in text or "Page Not Found" in text:
                            raise ValueError(f"Match URL not found on CREX (404 Page): {self.url}")
                        return text
                    raise ValueError(f"CREX server returned HTTP {resp.status}")
            else:
                timeout = aiohttp.ClientTimeout(total=4.5)
                async with aiohttp.ClientSession(timeout=timeout) as s:
                    async with s.get(self.url, headers=headers, allow_redirects=True) as resp:
                        if resp.status == 404 or str(resp.url).endswith("/404"):
                            raise ValueError(f"Match URL returned 404 (Not Found): {self.url}")
                        if resp.status == 200:
                            text = await resp.text()
                            if "<title>404" in text or "Page Not Found" in text:
                                raise ValueError(f"Match URL not found on CREX (404 Page): {self.url}")
                            return text
                        raise ValueError(f"CREX server returned HTTP {resp.status}")
        except ValueError:
            raise
        except Exception as e:
            logger.debug(f"Async fetch error ({e}), falling back to curl")
        return await asyncio.to_thread(self.fetch_html)

    def fetch_html(self) -> str:
        try:
            cmd = [
                "curl", "-s", "-L", "--max-redirs", "3",
                "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Accept-Language: en-US,en;q=0.9",
                "-H", f"Cookie: content-lang={self.lang}",
                self.url
            ]
            output = subprocess.check_output(cmd, timeout=12).decode("utf-8", errors="ignore")
            if "<title>404" in output or "Page Not Found" in output or "Redirecting to /404" in output:
                raise ValueError(f"Match URL does not exist on CREX (404 Not Found): {self.url}")
            return output
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching URL: {e}")
            raise ValueError(f"Network error while connecting to CREX: {e}")

    def parse(self, html_text: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Match Title & Venue
        title = soup.title.get_text() if soup.title else "Live Cricket Match"
        clean_title = title.split(",")[0].replace("🏆", "").strip()

        # Parse JSON state if present
        data_store = {}
        for s in html_text.split("<script"):
            if "stats.crickapi.com" in s:
                try:
                    body = s.split(">", 1)[1].split("</script>")[0].strip()
                    clean_json = html.unescape(body.replace("&q;", '"').replace("&a;", "&").replace("&s;", "'"))
                    data_store = json.loads(clean_json)
                    break
                except Exception:
                    pass

        venue = "International Stadium"
        for k, v in data_store.items():
            if "getMatchMetaData" in k and isinstance(v, list) and len(v) > 0:
                venue = v[0].get("v", venue)
                break

        full_text = soup.get_text(" | ", strip=True)

        # Extract team names from URL slug if available as fallback
        # e.g. /cricket-live-score/aus-vs-zim-2nd-odi-... or pak-w-vs-tha-w-...
        slug_match = re.search(r'/cricket-live-score/([a-zA-Z0-9\-]+?)-vs-([a-zA-Z0-9\-]+?)-', self.url)
        url_team1 = slug_match.group(1).upper() if slug_match else ""
        url_team2 = slug_match.group(2).upper() if slug_match else ""

        batting_team = url_team1 or "TEAM 1"
        bowling_team = url_team2 or "TEAM 2"
        total_runs = 0
        total_wickets = 0
        overs_str = "0.0"

        # 2. Multi-Strategy Dynamic Scorecard Extraction (No hardcoded score defaults)
        # Strategy A: Extract from page Title (e.g. "ZIM 66-2 (16.4) (Innocent Kaia 7(17)) ...")
        m_title = re.search(r'\b([A-Za-z\-]{2,7})\s+(\d+)[-/](\d+)\s*\(([0-9\.]+)\)', title)
        if m_title:
            batting_team = m_title.group(1).strip()
            total_runs = int(m_title.group(2))
            total_wickets = int(m_title.group(3))
            overs_str = m_title.group(4).strip()
        else:
            # Strategy B: Extract from live-score-card div
            score_card = soup.find("div", class_=lambda x: x and "live-score-card" in x)
            if score_card:
                sc_text = score_card.get_text(" ", strip=True)
                score_match = re.search(r'\b([A-Za-z\-]{2,7})\s*(\d+)[-/](\d+)\s*\(([0-9\.]+)\)', sc_text)
                if score_match:
                    batting_team = score_match.group(1).strip()
                    total_runs = int(score_match.group(2))
                    total_wickets = int(score_match.group(3))
                    overs_str = score_match.group(4).strip()

            # Strategy C: Extract pipe-delimited score from full_text
            if total_runs == 0 and total_wickets == 0:
                m_pipe = re.search(r'\b([A-Za-z\-]{2,7})\s*\|\s*(\d+)[-/](\d+)\s*\|\s*\(([0-9\.]+)\)', full_text)
                if m_pipe:
                    batting_team = m_pipe.group(1).strip()
                    total_runs = int(m_pipe.group(2))
                    total_wickets = int(m_pipe.group(3))
                    overs_str = m_pipe.group(4).strip()

            # Strategy D: Extract standard score from full_text
            if total_runs == 0 and total_wickets == 0:
                m_std = re.search(r'\b([A-Za-z\-]{2,7})\s+(\d+)[-/](\d+)\s*\(([0-9\.]+)\)', full_text)
                if m_std:
                    batting_team = m_std.group(1).strip()
                    total_runs = int(m_std.group(2))
                    total_wickets = int(m_std.group(3))
                    overs_str = m_std.group(4).strip()

        # Update bowling team based on match url teams
        if url_team1 and url_team2:
            if batting_team.upper() == url_team1.upper():
                bowling_team = url_team2
            elif batting_team.upper() == url_team2.upper():
                bowling_team = url_team1

        # Current Run Rate (CRR) - computed early so available for all commentary strategies
        overs_float = float(overs_str) if overs_str and overs_str.replace('.', '', 1).isdigit() else 0.0
        c_ov = int(overs_float)
        b_rem = int(round((overs_float - c_ov) * 10))
        tot_balls = c_ov * 6 + b_rem
        crr = f"{round((total_runs / (tot_balls / 6.0)), 2):.2f}" if tot_balls > 0 else "0.00"

        # 3. Batsmen and Bowler (Dynamic with neutral fallbacks)
        striker = "Batter 1"
        striker_runs = 0
        striker_balls = 0
        non_striker = "Batter 2"
        non_striker_runs = 0
        non_striker_balls = 0
        bowler = "Bowler"
        bowler_wickets = 0
        bowler_runs = 0
        bowler_overs = 0.0

        over_idx = full_text.find("OVER ")
        section = full_text[over_idx:over_idx + 250] if over_idx != -1 else full_text

        batter_matches = re.findall(r'([A-Za-zऀ-ॿ\s\-]+?)\s*\|\s*(\d+)\((\d+)\)', section)
        if len(batter_matches) >= 1:
            striker = batter_matches[0][0].strip()
            striker_runs = int(batter_matches[0][1])
            striker_balls = int(batter_matches[0][2])
        if len(batter_matches) >= 2:
            non_striker = batter_matches[1][0].strip()
            non_striker_runs = int(batter_matches[1][1])
            non_striker_balls = int(batter_matches[1][2])

        bowler_matches = re.findall(r'([A-Za-zऀ-ॿ\s\-]+?)\s*\|\s*(\d+)-(\d+)\(([0-9\.]+)\)', section)
        if bowler_matches:
            bowler = bowler_matches[0][0].strip()
            bowler_wickets = int(bowler_matches[0][1])
            bowler_runs = int(bowler_matches[0][2])
            bowler_overs = float(bowler_matches[0][3])

        # 4. Extract structured ball-by-ball commentary using exact CREX classes
        balls_data = []
        for over_span in soup.find_all("span", class_=lambda x: x and "cm-b-over" in x):
            parent = over_span.find_parent("div", class_=lambda x: x and "cm-b-roundcard" in x) or over_span.find_parent("div")
            c1_span = parent.find("span", class_=lambda x: x and "cm-b-comment-c1" in x) if parent else None
            ball_span = parent.find("span", class_=lambda x: x and "cm-b-ballupdate" in x) if parent else None
            c2_span = parent.find("span", class_=lambda x: x and "cm-b-comment-c2" in x) if parent else None

            over_str = over_span.get_text(strip=True)
            matchup_str = c1_span.get_text(strip=True) if c1_span else ""
            runs_str = ball_span.get_text(strip=True) if ball_span else "0"
            commentary_str = c2_span.get_text(" ", strip=True) if c2_span else ""
            commentary_clean = re.sub(r'\s+', ' ', commentary_str).strip()

            if commentary_clean:
                full_spoken_line = f"Over {over_str}: {matchup_str}. {commentary_clean}" if matchup_str else f"Over {over_str}. {commentary_clean}"
                balls_data.append({
                    "over": over_str,
                    "matchup": matchup_str,
                    "runs": runs_str,
                    "commentary": commentary_clean,
                    "spoken_line": full_spoken_line
                })

        # Strategy 4B: Extract from embedded getBallFeeds JSON if HTML classes are missing
        if not balls_data:
            for k, v in data_store.items():
                if "getBallFeeds" in k and isinstance(v, list):
                    for item in v:
                        # Case 1: Structured ball object with 'b' (runs/event), 'o' (over), 'c1' (matchup), 'c2' (description)
                        if item.get("type") == "b" or ("b" in item and "o" in item):
                            o_val = str(item.get("o", "Live")).strip()
                            r_val = str(item.get("b", "0")).strip().upper()
                            m_val = str(item.get("c1", "") or "").strip()
                            c2_raw = str(item.get("c2", "") or "").strip()
                            c2_clean = re.sub(r'\s+', ' ', html.unescape(c2_raw)).strip()

                            if c2_clean:
                                comm_val = c2_clean
                            elif r_val == "W":
                                comm_val = f"Wicket! {m_val}" if m_val else "Wicket down!"
                            elif r_val == "4":
                                comm_val = "Boundary! Cracking shot races away to the fence for four."
                            elif r_val == "6":
                                comm_val = "Maximum! Struck cleanly into the stands for a huge six."
                            elif r_val == "0":
                                comm_val = "Good delivery, defended with care, no run."
                            else:
                                comm_val = f"{r_val} run{'s' if r_val != '1' else ''} taken off the delivery."

                            spoken = f"Over {o_val}: {m_val}. {comm_val}" if m_val else f"Over {o_val}: {comm_val}"
                            balls_data.append({
                                "over": o_val,
                                "matchup": m_val,
                                "runs": r_val,
                                "commentary": comm_val,
                                "spoken_line": spoken
                            })
                            continue

                        # Case 2: Legacy/Text ball format with 'c' string
                        raw_c = item.get("c", "")
                        if not raw_c:
                            continue
                        clean_c = html.unescape(raw_c.replace("&l;", "<").replace("&g;", ">").replace("&q;", '"').replace("&a;", "&"))
                        clean_c = re.sub(r'<[^>]+>', '', clean_c).strip()
                        if len(clean_c) < 10:
                            continue

                        # Check for over pattern in commentary
                        m_over = re.search(r'(?:Over\s*|^\s*)(\d+\.\d+)\s*:?\s*([^:\n\r0-9]+?)(?:\s+(\d+|W|4|6|0))?\s*[:\-\.]?\s+(.+)', clean_c)
                        if m_over:
                            o_val = m_over.group(1)
                            m_val = m_over.group(2).strip()
                            r_val = m_over.group(3) or "0"
                            comm_val = m_over.group(4).strip()
                            balls_data.append({
                                "over": o_val,
                                "matchup": m_val,
                                "runs": r_val,
                                "commentary": comm_val,
                                "spoken_line": f"Over {o_val}: {m_val}. {comm_val}"
                            })
                        else:
                            on = item.get("on", -1)
                            over_label = f"{on//6}.{on%6 + 1}" if isinstance(on, int) and on > 0 else "Live"
                            balls_data.append({
                                "over": over_label,
                                "matchup": f"{bowler} to {striker}" if bowler and striker else "",
                                "runs": "0",
                                "commentary": clean_c,
                                "spoken_line": clean_c
                            })

        cards = soup.find_all("div", class_=lambda x: x and "cm-b-roundcard" in x)
        paragraphs = []
        for b in reversed(balls_data):
            paragraphs.append(b["spoken_line"])

        for c in reversed(cards):
            txt = c.get_text(" ", strip=True)
            txt = re.sub(r'\s+', ' ', txt)
            txt = re.sub(r'^\d+:\d+\s*[AP]M\s*IST,\s*\d+:\d+\s*[AP]M\s*Local Time:\s*', '', txt)
            if txt and len(txt) > 20 and not any(txt[:25] in p for p in paragraphs):
                paragraphs.append(txt)

        # Strategy 4C: If balls_data is still empty, parse paragraphs
        if not balls_data and paragraphs:
            for p in paragraphs:
                m_p = re.search(r'(?:Over\s*|^\s*)(\d+\.\d+)\s*:?\s*([^:\n\r0-9]+?)(?:\s+(\d+|W|4|6|0))?\s*[:\-\.]?\s+(.+)', p)
                if m_p:
                    balls_data.append({
                        "over": m_p.group(1),
                        "matchup": m_p.group(2).strip(),
                        "runs": m_p.group(3) or "0",
                        "commentary": m_p.group(4).strip(),
                        "spoken_line": p
                    })
                elif len(p) > 25:
                    balls_data.append({
                        "over": "Live",
                        "matchup": f"{bowler} to {striker}",
                        "runs": "0",
                        "commentary": p,
                        "spoken_line": p
                    })

        # Match status / alert banner
        m_status = re.search(r"(?:\|\s*)([A-Za-z\s]+won by [0-9\sA-Za-z🏆]+|SCORES ARE LEVELLED|[A-Za-z\s]+beat [0-9\sA-Za-z🏆]+|Need \d+ runs? in \d+ balls?|Innings Break|Match drawn|Stumps|Rain delay)", full_text, re.IGNORECASE)
        match_status = m_status.group(1).strip() if m_status else ""

        # Strategy 4D: Situational Broadcast Fallback if no commentary is present (Live, Result, or Upcoming)
        if not balls_data:
            if match_status and any(w in match_status.lower() for w in ["won by", "beat", "scores are", "drawn"]):
                situational_comm = f"Match summary from {venue}: {clean_title}. {batting_team} finished with {total_runs} for {total_wickets} in {overs_str} overs. {match_status}."
                over_label = "Result"
                matchup_label = f"{batting_team} vs {bowling_team}"
            elif total_runs == 0 and total_wickets == 0 and overs_str == "0.0":
                situational_comm = f"Welcome to our live cricket studio from {venue}! Today {batting_team} take on {bowling_team} in an exciting contest. The pitch is ready and anticipation is high. Stay tuned as action gets underway shortly!"
                over_label = "Pre-Match"
                matchup_label = f"{batting_team} vs {bowling_team}"
            else:
                situational_comm = f"Live action from {venue}. {batting_team} are {total_runs} for {total_wickets} in {overs_str} overs with a current run rate of {crr}. {striker} is on {striker_runs} runs and {non_striker} on {non_striker_runs}."
                over_label = overs_str if overs_str != "0.0" else "Live"
                matchup_label = f"{bowler} to {striker}"

            balls_data.append({
                "over": over_label,
                "matchup": matchup_label,
                "runs": "0",
                "commentary": situational_comm,
                "spoken_line": situational_comm
            })

        if not paragraphs:
            paragraphs = [b["spoken_line"] for b in balls_data]

        # Batters detailed statistics (4s, 6s, Strike Rate)
        b_matches = re.findall(r"([A-Za-z\u0900-\u097F\s\-]+?)\s*\|\s*(\d+)\s*\|\s*\((\d+)\)\s*\|\s*4s:\s*\|\s*(\d+)\s*\|\s*6s:\s*\|\s*(\d+)\s*\|\s*SR:\s*\|\s*([0-9\.]+)", full_text)
        striker_fours = int(b_matches[0][3]) if len(b_matches) >= 1 else 0
        striker_sixes = int(b_matches[0][4]) if len(b_matches) >= 1 else 0
        striker_sr = b_matches[0][5] if len(b_matches) >= 1 else "0.0"

        non_striker_fours = int(b_matches[1][3]) if len(b_matches) >= 2 else 0
        non_striker_sixes = int(b_matches[1][4]) if len(b_matches) >= 2 else 0
        non_striker_sr = b_matches[1][5] if len(b_matches) >= 2 else "0.0"

        # Bowler economy
        b_econ_match = re.search(r"([A-Za-zऀ-ॿ\s\-]+?)\s*\|\s*(\d+-\d+)\s*\|\s*\(([0-9\.]+)\)\s*\|\s*Econ:\s*\|\s*([0-9\.]+)", full_text)
        bowler_econ = b_econ_match.group(4) if b_econ_match else "0.00"

        # Partnership & Last Wicket
        m_pship = re.search(r"P\x27?ship\s*:\s*\|\s*([0-9\(\)]+)", full_text)
        partnership = m_pship.group(1) if m_pship else ""

        m_lastw = re.search(r"Last Wkt\s*:\s*\|\s*([A-Za-zऀ-ॿ\s\-]+?)\s*\|\s*([0-9\(\)]+)", full_text)
        last_wicket = f"{m_lastw.group(1).strip()} {m_lastw.group(2).strip()}" if m_lastw else ""

        # Current / recent over ball bubbles
        m_overs = re.findall(r"Over\s*(\d+)\s*\|\s*([0-9\sWwB\|\+\.]+?)\s*\|\s*=\s*(\d+)", full_text)
        this_over_balls = [x.strip() for x in m_overs[-1][1].split("|")] if m_overs else []

        # Opponent score (find opponent team score, excluding active batting team and player names)
        team2_score = ""
        # Exclude historical 'Team Form / Last 5 matches' table from score extraction
        scorecard_text = full_text.split("Team Form")[0].split("Last 5 matches")[0].split("Recent Form")[0]

        # Only extract opponent score if match has actual play or valid scorecard
        is_upcoming_game = (total_runs == 0 and total_wickets == 0 and overs_str == "0.0" and not balls_data)
        if not is_upcoming_game:
            opp_target = None
            if url_team1 and url_team2:
                opp_target = url_team2 if batting_team.upper() == url_team1.upper() else url_team1

            if opp_target:
                m_target = re.search(rf"\b({opp_target})\s*\|\s*(?:\(([0-9\.]+)\)\s*\|\s*)?(\d+[-/]\d+)(?:\s*\|\s*\(([0-9\.]+)\))?", scorecard_text, re.IGNORECASE)
                if m_target:
                    ov = m_target.group(2) or m_target.group(4) or ""
                    team2_score = f"{m_target.group(1).upper()} {m_target.group(3)} ({ov} ov)" if ov else f"{m_target.group(1).upper()} {m_target.group(3)}"
                else:
                    m_target_std = re.search(rf"\b({opp_target})\s+(\d+[-/]\d+)\s*\(([0-9\.]+)(?:\s*ov)?\)", scorecard_text, re.IGNORECASE)
                    if m_target_std:
                        team2_score = f"{m_target_std.group(1).upper()} {m_target_std.group(2)} ({m_target_std.group(3)} ov)"

            if not team2_score:
                opp_candidates = re.findall(r"\b([A-Za-z\-]{2,7})\s*\|\s*(?:\(([0-9\.]+)\)\s*\|\s*)?(\d+[-/]\d+)(?:\s*\|\s*\(([0-9\.]+)\))?", scorecard_text)
                for cand in opp_candidates:
                    c_team = cand[0].strip()
                    if c_team.upper() != batting_team.upper() and c_team.upper() not in ["LIVE", "OVER", "CRR", "ECON", "TOTAL", bowler.upper()]:
                        ov = cand[1] or cand[3] or ""
                        sc = cand[2]
                        team2_score = f"{c_team} {sc} ({ov} ov)" if ov else f"{c_team} {sc}"
                        break

            if not team2_score:
                opp_std = re.findall(r"\b([A-Za-z\-]{2,7})\s+(\d+[-/]\d+)\s*\(([0-9\.]+)(?:\s*ov)?\)", scorecard_text)
                for cand in opp_std:
                    c_team = cand[0].strip()
                    if c_team.upper() != batting_team.upper() and c_team.upper() not in ["LIVE", "OVER", "CRR", "ECON", "TOTAL", bowler.upper()]:
                        team2_score = f"{c_team} {cand[1]} ({cand[2]} ov)"
                        break

        # Current Run Rate (CRR)
        overs_float = float(overs_str) if overs_str and overs_str.replace('.', '', 1).isdigit() else 0.0
        c_ov = int(overs_float)
        b_rem = int(round((overs_float - c_ov) * 10))
        tot_balls = c_ov * 6 + b_rem
        crr = f"{round((total_runs / (tot_balls / 6.0)), 2):.2f}" if tot_balls > 0 else "0.00"

        return {
            "title": clean_title,
            "venue": venue,
            "status": match_status,
            "batting_team": batting_team,
            "bowling_team": bowling_team,
            "total_runs": total_runs,
            "total_wickets": total_wickets,
            "overs": overs_str,
            "crr": crr,
            "team2_score": team2_score,
            "striker": striker,
            "striker_runs": striker_runs,
            "striker_balls": striker_balls,
            "striker_fours": striker_fours,
            "striker_sixes": striker_sixes,
            "striker_sr": striker_sr,
            "non_striker": non_striker,
            "non_striker_runs": non_striker_runs,
            "non_striker_balls": non_striker_balls,
            "non_striker_fours": non_striker_fours,
            "non_striker_sixes": non_striker_sixes,
            "non_striker_sr": non_striker_sr,
            "bowler": bowler,
            "bowler_figures": f"{bowler_wickets}-{bowler_runs} ({bowler_overs} ov)",
            "bowler_econ": bowler_econ,
            "partnership": partnership,
            "last_wicket": last_wicket,
            "this_over_balls": this_over_balls,
            "paragraphs": paragraphs,
            "balls": balls_data
        }


def get_live_matches() -> List[Dict[str, str]]:
    """Scrapes crex.com to discover live, recent/completed, and upcoming matches."""
    sources = [
        "https://crex.com/",
        "https://crex.com/cricket-live-score",
        "https://crex.com/fixtures/match-list"
    ]
    matches = []
    seen_urls = set()

    for src_url in sources:
        try:
            cmd = [
                "curl", "-s", "-L", "--max-redirs", "3",
                "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Accept-Language: en-US,en;q=0.9",
                src_url
            ]
            html_content = subprocess.check_output(cmd, timeout=8).decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html_content, "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/cricket-live-score/" in href and "-match-updates-" in href:
                    full_url = f"https://crex.com{href}" if href.startswith("/") else href
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    raw_text = a.get_text(" ", strip=True)
                    raw_text = re.sub(r'\s+', ' ', raw_text)
                    slug_part = href.split("/cricket-live-score/")[-1].split("-match-updates-")[0]
                    formatted_slug = slug_part.replace("-", " ").title()

                    raw_lower = raw_text.lower()
                    if any(w in raw_lower for w in ["won by", "beat", "scores level", "drawn", "concluded"]):
                        status_tag = "🏁 [RESULT]"
                        priority = 2
                    elif any(w in raw_lower for w in [" am", " pm", "tomorrow", "today", "starts at", "toss at", "upcoming"]):
                        status_tag = "📅 [UPCOMING]"
                        priority = 3
                    elif any(w in raw_lower for w in ["need", "crr", "opt to", "trail by", "lead by"]) or re.search(r'\b(?:ov|overs)\b', raw_lower) or re.search(r'\b\d+[-/]\d+\b', raw_text):
                        status_tag = "🔴 [LIVE]"
                        priority = 1
                    else:
                        status_tag = "🏏 [MATCH]"
                        priority = 4

                    clean_title = raw_text if raw_text and len(raw_text) > 5 else formatted_slug
                    if len(clean_title) > 65:
                        clean_title = clean_title[:62] + "..."

                    matches.append({
                        "title": f"{status_tag} {clean_title}",
                        "url": full_url,
                        "slug": slug_part,
                        "priority": priority
                    })
        except Exception as e:
            logger.warning(f"Error fetching live matches list from {src_url}: {e}")

    # Sort with LIVE matches first, then completed RESULTS, then UPCOMING matches
    matches.sort(key=lambda x: x.get("priority", 99))
    return matches[:45]


def resolve_match_url(user_input: str, force_fuzzy: bool = False) -> tuple[str, Optional[str]]:
    """Smart Match Resolver: Maps any URL (CREX, Cricbuzz, Cricinfo, partial slug, or team query)
    to a valid, live CREX match updates feed."""
    raw = user_input.strip()
    if not raw:
        return raw, None

    # 1. Direct valid CREX link with match ID (unless force_fuzzy requested because link returned 404)
    if not force_fuzzy and "crex.com/cricket-live-score/" in raw and "-match-updates-" in raw:
        return raw, None

    # 2. Extract match ID if present in any CREX URL (e.g. /social/...-11FL or -11FL)
    if not force_fuzzy:
        crex_id_match = re.search(r'-([a-zA-Z0-9]{3,6})$', raw.rstrip('/'))
        if "crex.com" in raw and crex_id_match:
            mid = crex_id_match.group(1)
            # Exclude 4-digit years like 2022, 2026
            if not re.match(r'^(?:19|20)\d{2}$', mid):
                slug_match = re.search(r'([a-zA-Z0-9\-]+?)-[a-zA-Z0-9]{3,6}$', raw.rstrip('/'))
                if slug_match:
                    slug_base = slug_match.group(1).split("/")[-1]
                    slug_base = re.sub(r'-(?:match-updates|live-score|scorecard|info)$', '', slug_base)
                    reconstructed = f"https://crex.com/cricket-live-score/{slug_base}-match-updates-{mid}"
                    return reconstructed, "Auto-reconstructed CREX Live Feed URL"

    # 3. Fuzzy match against current CREX live fixtures
    cleaned = re.sub(r'https?://[^\s/]+', '', raw)
    stop_words = {
        'https', 'http', 'com', 'www', 'cricket', 'live', 'score', 'scores', 'match', 'updates',
        'series', 'vs', 'v', '1st', '2nd', '3rd', '4th', '5th', 't20', 'odi', 'test', '2024',
        '2025', '2026', '2027', 'women', 'womens'
    }
    tokens = [t.lower() for t in re.findall(r'[a-zA-Z0-9]+', cleaned) if t.lower() not in stop_words]

    try:
        live_list = get_live_matches()
        best_match = None
        best_score = 0

        for m in live_list:
            m_text = (m.get('slug', '') + " " + m.get('title', '')).lower()
            m_tokens = set(re.findall(r'[a-zA-Z0-9]+', m_text))

            score = 0
            for t in tokens:
                if t in m_tokens:
                    score += 4 if len(t) >= 3 else 1
                elif any(t in mt for mt in m_tokens if len(t) >= 3):
                    score += 2

            if score > best_score:
                best_score = score
                best_match = m

        if best_match and best_score >= 3:
            title_preview = best_match.get('title', '')
            if len(title_preview) > 40:
                title_preview = title_preview[:37] + "..."
            return best_match['url'], f"Auto-resolved to live match: {title_preview}"
    except Exception as e:
        logger.debug(f"Smart resolver fuzzy match failed: {e}")

    return raw, None


class FastTTS:
    """Broadcaster neural voice generator with English & Hindi support."""
    def __init__(self, language: str = "en", voice: Optional[str] = None):
        self.language = language
        if voice:
            self.voice = voice
        elif language == "hi":
            # Native, energetic Hindi sports broadcaster
            self.voice = "hi-IN-MadhurNeural"
        else:
            # English broadcaster
            self.voice = "en-IN-PrabhatNeural"

    async def speak(self, text: str, rate: Optional[str] = None, pitch: Optional[str] = None) -> bytes:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        words = clean_text.split()
        if len(words) > 40:
            clean_text = " ".join(words[:40]) + "..."

        target_rate = rate or ("+7%" if self.language == "hi" else "+6%")
        target_pitch = pitch or "+1Hz"

        comm = edge_tts.Communicate(clean_text, self.voice, rate=target_rate, pitch=target_pitch)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])

        if not buf:
            return b""

        import io
        seg = AudioSegment.from_file(io.BytesIO(buf), format="mp3")
        seg = seg.set_frame_rate(44100).set_channels(2).set_sample_width(2)
        # Studio presence boost & broadcast normalization
        seg = normalize(seg) + 1.5
        return seg.raw_data

    async def speak_mp3(self, text: str, rate: Optional[str] = None, pitch: Optional[str] = None) -> bytes:
        """Direct ultra-fast MP3 generation with zero format conversion overhead."""
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        words = clean_text.split()
        if len(words) > 35:
            clean_text = " ".join(words[:35]) + "..."

        target_rate = rate or ("+10%" if self.language == "hi" else "+8%")
        target_pitch = pitch or "+1Hz"

        comm = edge_tts.Communicate(clean_text, self.voice, rate=target_rate, pitch=target_pitch)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)



class FastOverlayRenderer:
    """Renders 720p 30fps TV cricket broadcast graphics supporting Devanagari (Hindi) & English."""
    def __init__(self, width: int = 1280, height: int = 720):
        self.width = width
        self.height = height
        self.frame = 0
        self.font_large = self._load_font(26, bold=True)
        self.font_medium = self._load_font(18, bold=True)
        self.font_small = self._load_font(14, bold=False)

    def _load_font(self, size: int, bold: bool = False):
        # Prioritize Kohinoor for clean Devanagari & Latin rendering on macOS
        fonts = [
            "/System/Library/Fonts/Kohinoor.ttc",
            "/System/Library/Fonts/SFProText-Bold.otf" if bold else "/System/Library/Fonts/SFProText-Regular.otf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/Library/Fonts/Arial.ttf"
        ]
        for f in fonts:
            try: return ImageFont.truetype(f, size)
            except Exception: pass
        return ImageFont.load_default()

    def render(self, state: Dict[str, Any], subtitle: str, is_speaking: bool, alert_text: Optional[str] = None) -> bytes:
        self.frame += 1
        img = Image.new("RGB", (self.width, self.height), (15, 23, 42))
        draw = ImageDraw.Draw(img)

        # 1. Stadium Turf Background Gradient
        for y in range(0, self.height, 4):
            ratio = y / self.height
            draw.rectangle([0, y, self.width, y + 4], fill=(int(12 + ratio * 8), int(20 + ratio * 32), int(48 + ratio * 20)))

        # 2. Header Bar
        draw.rectangle([0, 0, self.width, 48], fill=(9, 14, 26))
        draw.line([0, 48, self.width, 48], fill=(35, 65, 115), width=2)
        # LIVE badge
        pulse = (np.sin(self.frame * 0.15) + 1.0) * 0.5
        draw.rounded_rectangle([25, 10, 95, 38], radius=6, fill=(int(200 + pulse * 55), 25, 25))
        draw.text((40, 15), "LIVE", fill=(255, 255, 255), font=self.font_medium)
        # Title
        draw.text((115, 15), f"{state['title'].upper()} • {state['venue']}", fill=(240, 240, 245), font=self.font_medium)

        # 3. Center Pitch Visualizer
        cx, cy = self.width // 2, 230
        draw.rounded_rectangle([cx - 150, cy - 100, cx + 150, cy + 100], radius=10, fill=(18, 28, 48), outline=(35, 60, 100), width=2)
        draw.rectangle([cx - 40, cy - 85, cx + 40, cy + 85], fill=(160, 140, 100))
        draw.line([cx - 40, cy - 55, cx + 40, cy - 55], fill=(255, 255, 255), width=2)
        draw.line([cx - 40, cy + 55, cx + 40, cy + 55], fill=(255, 255, 255), width=2)

        # Event Alert Banner (if any)
        if alert_text:
            draw.rectangle([0, 150, self.width, 215], fill=(210, 40, 40))
            draw.text((cx - 160, 162), alert_text, fill=(255, 255, 255), font=self.font_large)

        # 4. Commentary Bar
        c_y = self.height - 180
        draw.rectangle([0, c_y, self.width, c_y + 52], fill=(12, 18, 32))
        draw.line([0, c_y, self.width, c_y], fill=(30, 55, 95), width=1)
        # Mic badge
        if is_speaking:
            draw.rounded_rectangle([25, c_y + 10, 185, c_y + 42], radius=6, fill=(18, 130, 60))
            draw.text((35, c_y + 16), "🎙️ ON AIR (AI)", fill=(255, 255, 255), font=self.font_small)
        else:
            draw.rounded_rectangle([25, c_y + 10, 185, c_y + 42], radius=6, fill=(40, 55, 80))
            draw.text((35, c_y + 16), "🎙️ COLOR BOOTH", fill=(180, 200, 220), font=self.font_small)

        # Commentary Subtitle
        display_sub = subtitle[:95] + "..." if len(subtitle) > 95 else subtitle
        draw.text((205, c_y + 17), display_sub, fill=(245, 245, 250), font=self.font_medium)

        # 5. Lower Third Scorecard
        s_y = self.height - 120
        draw.rectangle([0, s_y, self.width, self.height], fill=(9, 14, 26))
        draw.line([0, s_y, self.width, s_y], fill=(40, 80, 150), width=3)

        # Left Score Pill
        draw.rectangle([0, s_y, 260, self.height], fill=(16, 38, 76))
        draw.text((25, s_y + 14), f"{state['batting_team']}", fill=(255, 215, 0), font=self.font_large)
        draw.text((125, s_y + 14), f"{state['total_runs']}/{state['total_wickets']}", fill=(255, 255, 255), font=self.font_large)
        draw.text((25, s_y + 58), f"OV: {state['overs']} • CRR: {state.get('crr', '0.00')}", fill=(200, 220, 240), font=self.font_medium)
        if state.get("team2_score"):
            draw.text((25, s_y + 84), f"vs {state['team2_score']}", fill=(140, 180, 220), font=self.font_small)

        # Middle Batsmen
        s_meta = f"4s:{state.get('striker_fours', 0)} 6s:{state.get('striker_sixes', 0)}"
        draw.text((280, s_y + 16), f"▶ {state['striker']}", fill=(255, 255, 255), font=self.font_medium)
        draw.text((475, s_y + 16), f"{state['striker_runs']} ({state['striker_balls']})", fill=(255, 215, 0), font=self.font_medium)
        draw.text((545, s_y + 18), s_meta, fill=(150, 180, 210), font=self.font_small)

        ns_meta = f"4s:{state.get('non_striker_fours', 0)} 6s:{state.get('non_striker_sixes', 0)}"
        draw.text((280, s_y + 50), f"   {state['non_striker']}", fill=(200, 210, 230), font=self.font_medium)
        draw.text((475, s_y + 50), f"{state['non_striker_runs']} ({state['non_striker_balls']})", fill=(200, 210, 230), font=self.font_medium)
        draw.text((545, s_y + 52), ns_meta, fill=(130, 160, 190), font=self.font_small)

        # Partnership row
        pship_str = f"P'SHIP: {state.get('partnership', '')}  |  LAST WKT: {state.get('last_wicket', '')}"
        draw.text((280, s_y + 84), pship_str, fill=(140, 170, 210), font=self.font_small)

        # Right Bowler
        bx = self.width - 340
        draw.line([bx - 15, s_y + 10, bx - 15, self.height - 10], fill=(30, 50, 80), width=1)
        draw.text((bx, s_y + 14), "BOWLING", fill=(140, 170, 210), font=self.font_small)
        draw.text((bx, s_y + 36), f"{state['bowler']}", fill=(255, 255, 255), font=self.font_medium)
        draw.text((bx, s_y + 64), f"{state['bowler_figures']}", fill=(255, 215, 0), font=self.font_medium)
        draw.text((bx + 160, s_y + 66), f"Econ: {state.get('bowler_econ', '0.00')}", fill=(160, 190, 220), font=self.font_small)


        return img.tobytes()


class CricketStreamingEngine:
    """Master streaming orchestrator that reads link paragraphs, translates if needed, and streams live."""
    def __init__(
        self,
        url: str,
        mode: str = "preview",
        stream_key: str = "",
        language: str = "en",
        voice: Optional[str] = None,
        output_file: str = "broadcast_stream.mp4"
    ):
        self.parser = CrexParser(url, lang=language)
        self.mode = mode
        self.stream_key = stream_key
        self.language = language
        self.output_file = output_file
        self.translator = FreeTranslator() if language == "hi" else None
        self.renderer = FastOverlayRenderer()
        self.tts = FastTTS(language=language, voice=voice)

        self.is_running = False
        self.current_subtitle = "Connecting to live match feed..."
        self.is_speaking = False
        self.active_alert = None

        self.audio_queue = queue.Queue()
        self.audio_pipe = os.path.join(tempfile.gettempdir(), f"cricket_live_audio_{os.getpid()}.pipe")

    def _generate_ambience_chunk(self, samples=1470) -> bytes:
        t = np.linspace(0, samples / 44100, samples, endpoint=False)
        hum = 0.08 * np.sin(2 * np.pi * 80 * t) + 0.05 * np.sin(2 * np.pi * 140 * t)
        noise = np.random.normal(0, 0.02, samples)
        mono = (hum + noise).astype(np.float32)
        stereo = np.column_stack((mono, mono))
        int16 = np.clip(stereo * 32767, -32768, 32767).astype(np.int16)
        return int16.tobytes()

    def _audio_writer_thread(self, audio_fd):
        active_voice = None
        voice_offset = 0

        while self.is_running:
            try:
                if active_voice is None:
                    if not self.audio_queue.empty():
                        active_voice = self.audio_queue.get_nowait()
                        voice_offset = 0
                        self.is_speaking = True

                if active_voice is not None:
                    chunk = active_voice[voice_offset:voice_offset + 5880]
                    voice_offset += len(chunk)
                    if len(chunk) < 5880:
                        chunk = chunk + self._generate_ambience_chunk(samples=(5880 - len(chunk)) // 4)
                        active_voice = None
                        self.is_speaking = False
                    os.write(audio_fd, chunk)
                else:
                    os.write(audio_fd, self._generate_ambience_chunk(samples=1470))

                time.sleep(1.0 / 33.0)
            except Exception:
                break

    async def run(self, max_paragraphs: Optional[int] = None):
        logger.info(f"Fetching match data from: {self.parser.url}")
        html_content = self.parser.fetch_html()
        match_data = self.parser.parse(html_content)
        logger.info(f"Match: {match_data['title']} | Score: {match_data['batting_team']} {match_data['total_runs']}/{match_data['total_wickets']}")
        logger.info(f"Loaded {len(match_data['paragraphs'])} commentary lines to broadcast in [{self.language.upper()}].")

        # Setup Audio FIFO
        if os.path.exists(self.audio_pipe):
            os.unlink(self.audio_pipe)
        os.mkfifo(self.audio_pipe)

        # Build FFmpeg command
        cmd = [
            "ffmpeg", "-y", "-loglevel", "warning",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1280x720", "-r", "30", "-i", "pipe:0",
            "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", self.audio_pipe,
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
            "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k", "-g", "60",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100"
        ]

        if self.mode == "youtube" and self.stream_key:
            target = f"rtmp://a.rtmp.youtube.com/live2/{self.stream_key}"
            cmd.extend(["-f", "flv", target])
            logger.info(f"PITCHING DIRECTLY TO YOUTUBE LIVE RTMP (Language: {self.language.upper()})...")
        else:
            cmd.extend(["-f", "mp4", "-movflags", "+frag_keyframe+empty_moov", self.output_file])
            logger.info(f"RECORDING TO LOCAL PREVIEW: {self.output_file}")

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        audio_fd = os.open(self.audio_pipe, os.O_RDWR)
        self.is_running = True

        # Start decoupled audio thread
        audio_thread = threading.Thread(target=self._audio_writer_thread, args=(audio_fd,), daemon=True)
        audio_thread.start()

        # Commentary worker task (Continuous real-time polling)
        async def commentary_worker():
            seen_balls = set()
            first_run = True

            while self.is_running:
                try:
                    html_text = self.parser.fetch_html()
                    fresh_data = self.parser.parse(html_text)
                    match_data.update(fresh_data)

                    raw_balls = fresh_data.get("balls", [])
                    new_events = []

                    # Iterate over balls chronologically
                    for b in reversed(raw_balls):
                        b_key = f"{b.get('over')}_{b.get('runs')}_{b.get('commentary')[:30]}"
                        if b_key not in seen_balls:
                            seen_balls.add(b_key)
                            new_events.append(b)

                    if first_run:
                        first_run = False
                        # On first connect, play the latest 2 balls or max_paragraphs
                        limit = max_paragraphs if max_paragraphs else 2
                        new_events = new_events[-limit:] if len(new_events) >= limit else new_events

                    for b in new_events:
                        if not self.is_running:
                            break

                        human_res = commentator.humanize(
                            b.get("spoken_line") or b.get("commentary", ""),
                            ball_info={**match_data, **b},
                            lang=self.language
                        )
                        spoken_text = human_res["spoken_text"]
                        self.active_alert = human_res["badge"]
                        self.current_subtitle = spoken_text

                        logger.info(f"🎙️ [{human_res['badge']}] Ball {b.get('over')} [{self.language.upper()}]: {spoken_text}")

                        pcm = await self.tts.speak(spoken_text, rate=human_res["rate"], pitch=human_res["pitch"])
                        duration = len(pcm) / (44100 * 4)
                        self.audio_queue.put(pcm)

                        await asyncio.sleep(max(3.0, duration + 1.0))
                        self.active_alert = None

                    if max_paragraphs:
                        # Fixed paragraph test run requested
                        break

                except Exception as e:
                    logger.warning(f"Error during real-time scrape poll: {e}")

                # Poll interval for real-time live cricket feed (4s)
                await asyncio.sleep(4)

            logger.info("Real-time commentary stream cycle finished.")



        c_task = asyncio.create_task(commentary_worker())

        # Video rendering loop at 30 fps
        frame_interval = 1.0 / 30.0
        try:
            while self.is_running and not c_task.done():
                t_frame = time.perf_counter()
                frame_bytes = self.renderer.render(match_data, self.current_subtitle, self.is_speaking, self.active_alert)
                proc.stdin.write(frame_bytes)

                elapsed = time.perf_counter() - t_frame
                sleep_dur = frame_interval - elapsed
                if sleep_dur > 0:
                    await asyncio.sleep(sleep_dur)
                else:
                    await asyncio.sleep(0.001)

        finally:
            self.is_running = False
            try:
                proc.stdin.close()
                proc.wait(timeout=5)
            except Exception:
                pass
            try:
                os.close(audio_fd)
                os.unlink(self.audio_pipe)
            except Exception:
                pass
            logger.info(f"Stream complete! Output saved to: {self.output_file}")


def main():
    parser = argparse.ArgumentParser(description="Cricket AI Link-to-Broadcast Engine")
    parser.add_argument("url", nargs="?", default="https://crex.com/cricket-live-score/pak-w-vs-tha-w-2nd-qtr-final-womens-asian-games-t20-2026-match-updates-13Q0",
                        help="CREX match URL")
    parser.add_argument("--lang", choices=["en", "hi"], default="en",
                        help="Commentary language: 'en' (English) or 'hi' (Hindi)")
    parser.add_argument("--voice", default=None,
                        help="Override TTS voice model (e.g. 'hi-IN-MadhurNeural', 'en-IN-PrabhatNeural')")
    parser.add_argument("--mode", choices=["youtube", "preview"], default="preview",
                        help="Stream mode ('preview' saves MP4, 'youtube' pushes RTMP)")
    parser.add_argument("--key", default=os.getenv("YOUTUBE_STREAM_KEY", ""),
                        help="YouTube Live Stream Key")
    parser.add_argument("--output", default="live_crex_broadcast.mp4",
                        help="Output MP4 filename for preview")
    parser.add_argument("--lines", type=int, default=None,
                        help="Number of commentary lines to stream (default: all)")
    args = parser.parse_args()

    engine = CricketStreamingEngine(
        url=args.url,
        mode=args.mode,
        stream_key=args.key,
        language=args.lang,
        voice=args.voice,
        output_file=args.output
    )
    asyncio.run(engine.run(max_paragraphs=args.lines))

if __name__ == "__main__":
    main()
