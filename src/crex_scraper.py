"""CREX (crex.com) Live Match Scraper & Real-Time Stream Feeder.

Scrapes live ball-by-ball updates, live scorecard, batsman/bowler figures,
and commentary directly from any CREX match URL and feeds them directly
into the BroadcastEngine.
"""
import re
import html
import json
import time
import logging
import asyncio
import subprocess
from typing import Dict, Any, Optional, List
from bs4 import BeautifulSoup

from src.match_state import BallEvent

logger = logging.getLogger("CrexScraper")

class CrexScraper:
    def __init__(self, match_url: str):
        self.match_url = match_url.strip()
        self.last_ball_id = None
        self.last_over_ball_str = ""

    def fetch_page_html(self) -> str:
        """Fetches raw page HTML using curl with browser headers."""
        try:
            cmd = [
                "curl", "-s",
                "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Accept-Language: en-US,en;q=0.9",
                self.match_url
            ]
            output = subprocess.check_output(cmd, timeout=10).decode("utf-8", errors="ignore")
            return output
        except Exception as e:
            logger.error(f"Error fetching CREX page: {e}")
            return ""

    def parse_match_data(self, html_content: str) -> Optional[BallEvent]:
        """Extracts live match state and latest ball from CREX HTML."""
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Parse Angular TransferState JSON
        data_store = {}
        for s in html_content.split("<script"):
            if "stats.crickapi.com" in s:
                try:
                    body = s.split(">", 1)[1].split("</script>")[0].strip()
                    clean = html.unescape(body.replace("&q;", '"').replace("&a;", "&").replace("&s;", "'"))
                    data_store = json.loads(clean)
                    break
                except Exception:
                    pass

        # Match metadata
        match_title = "Live Cricket Match"
        venue = "International Cricket Ground"
        team1_name = "Team 1"
        team2_name = "Team 2"

        for k, v in data_store.items():
            if "getMatchMetaData" in k and isinstance(v, list) and len(v) > 0:
                m = v[0]
                team1_name = m.get("team1", "Team 1")
                team2_name = m.get("team2", "Team 2")
                venue = m.get("v", venue)
                match_title = f"{team1_name} vs {team2_name} ({m.get('mn', 'T20')})"
                break

        # If meta not found in JSON, fallback to HTML title
        if match_title == "Live Cricket Match" and soup.title:
            t_text = soup.title.get_text()
            match_title = t_text.split(",")[0]

        # 2. Extract Scoreboard from Live Score Card
        score_card = soup.find("div", class_=lambda x: x and "live-score-card" in x)
        total_runs = 0
        total_wickets = 0
        over = 0
        ball = 1
        batting_team = team1_name[:5].upper()
        bowling_team = team2_name[:5].upper()

        if score_card:
            sc_text = score_card.get_text(" ", strip=True)
            # Example: PAK-W 92-7 (10.4) ... THA-W (11.0) 91-4
            score_match = re.search(r'([A-Za-z\-]+)\s*(\d+)-(\d+)\s*\(([0-9\.]+)\)', sc_text)
            if score_match:
                batting_team = score_match.group(1).strip()
                total_runs = int(score_match.group(2))
                total_wickets = int(score_match.group(3))
                overs_float = float(score_match.group(4))
                over = int(overs_float)
                ball = int(round((overs_float - over) * 10))

        # 3. Extract Active Batsmen and Bowler from page text
        striker = "Batter 1"
        striker_runs = 0
        striker_balls = 0
        striker_fours = 0
        striker_sixes = 0

        non_striker = "Batter 2"
        non_striker_runs = 0
        non_striker_balls = 0

        bowler = "Bowler"
        bowler_overs = 0.0
        bowler_runs = 0
        bowler_wickets = 0

        full_text = soup.get_text(" | ", strip=True)
        # Search specifically within the 'OVER X' current status box
        over_idx = full_text.find("OVER ")
        section = full_text[over_idx:over_idx + 250] if over_idx != -1 else full_text

        batter_matches = re.findall(r'([A-Za-z\s\-]+?)\s*\|\s*(\d+)\((\d+)\)', section)
        if len(batter_matches) >= 1:
            striker = batter_matches[0][0].strip()
            striker_runs = int(batter_matches[0][1])
            striker_balls = int(batter_matches[0][2])
        if len(batter_matches) >= 2:
            non_striker = batter_matches[1][0].strip()
            non_striker_runs = int(batter_matches[1][1])
            non_striker_balls = int(batter_matches[1][2])

        bowler_matches = re.findall(r'([A-Za-z\s\-]+?)\s*\|\s*(\d+)-(\d+)\(([0-9\.]+)\)', section)
        if bowler_matches:
            bowler = bowler_matches[0][0].strip()
            bowler_wickets = int(bowler_matches[0][1])
            bowler_runs = int(bowler_matches[0][2])
            bowler_overs = float(bowler_matches[0][3])

        # 4. Extract Latest Ball Commentary
        play_by_play = "Live action continuing..."
        runs_on_ball = 0
        is_boundary = False
        boundary_type = None
        is_wicket = False

        ball_feeds = []
        for k, v in data_store.items():
            if "getBallFeeds" in k and isinstance(v, list):
                for item in v:
                    if item.get("type") == "b":
                        ball_feeds.append(item)

        if ball_feeds:
            latest_b = ball_feeds[0]
            b_runs_str = str(latest_b.get("b", "0"))
            c1 = latest_b.get("c1", "")
            c2 = html.unescape(latest_b.get("c2", ""))
            clean_c2 = re.sub(r'<[^>]+>', '', c2).strip()

            play_by_play = f"{c1}. {clean_c2}" if c1 else clean_c2
            try:
                runs_on_ball = int(b_runs_str)
                if runs_on_ball == 4:
                    is_boundary = True
                    boundary_type = 4
                elif runs_on_ball == 6:
                    is_boundary = True
                    boundary_type = 6
            except ValueError:
                if "w" in b_runs_str.lower():
                    is_wicket = True

        event = BallEvent(
            match_id="CREX_LIVE_MATCH",
            match_title=match_title,
            venue=venue,
            innings=2,
            batting_team=batting_team,
            bowling_team=bowling_team,
            target=total_runs if total_runs > 0 else None,
            over=over,
            ball=ball,
            runs=runs_on_ball,
            is_boundary=is_boundary,
            boundary_type=boundary_type,
            is_wicket=is_wicket,
            striker=striker,
            striker_runs=striker_runs,
            striker_balls=striker_balls,
            striker_fours=striker_fours,
            striker_sixes=striker_sixes,
            non_striker=non_striker,
            non_striker_runs=non_striker_runs,
            non_striker_balls=non_striker_balls,
            bowler=bowler,
            bowler_overs=bowler_overs,
            bowler_runs=bowler_runs,
            bowler_wickets=bowler_wickets,
            total_runs=total_runs,
            total_wickets=total_wickets,
            play_by_play=play_by_play
        )

        return event

    async def stream_live_from_url(self, on_event_callback, poll_interval_seconds: float = 4.0):
        """Continuously polls the CREX URL, detects score/ball updates, and triggers callbacks."""
        logger.info(f"Starting real-time scraper for CREX URL: {self.match_url}")
        while True:
            try:
                html_text = self.fetch_page_html()
                event = self.parse_match_data(html_text)
                if event:
                    current_tag = f"{event.over}.{event.ball}_{event.total_runs}_{event.total_wickets}"
                    if current_tag != self.last_over_ball_str:
                        self.last_over_ball_str = current_tag
                        logger.info(
                            f"[CREX LIVE] {event.batting_team} {event.total_runs}/{event.total_wickets} "
                            f"(Ov {event.over}.{event.ball}) - {event.striker} facing {event.bowler}"
                        )
                        await on_event_callback(event)
            except Exception as e:
                logger.error(f"Error in CREX polling loop: {e}")

            await asyncio.sleep(poll_interval_seconds)
