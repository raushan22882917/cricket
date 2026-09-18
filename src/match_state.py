"""Match state management and cricket statistical calculations."""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

@dataclass
class PlayerInnings:
    name: str
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0

    @property
    def strike_rate(self) -> float:
        if self.balls == 0:
            return 0.0
        return round((self.runs / self.balls) * 100.0, 1)

@dataclass
class BowlerFigures:
    name: str
    overs: float = 0.0
    maidens: int = 0
    runs: int = 0
    wickets: int = 0

    @property
    def economy(self) -> float:
        completed_overs = int(self.overs)
        balls = round((self.overs - completed_overs) * 10)
        total_overs = completed_overs + (balls / 6.0)
        if total_overs <= 0:
            return 0.0
        return round(self.runs / total_overs, 2)

@dataclass
class BallEvent:
    match_id: str
    match_title: str
    venue: str
    innings: int
    batting_team: str
    bowling_team: str
    target: Optional[int]
    over: int
    ball: int
    runs: int
    extras: int = 0
    is_boundary: bool = False
    boundary_type: Optional[int] = None
    is_wicket: bool = False
    dismissal_type: Optional[str] = None
    dismissed_player: Optional[str] = None
    striker: str = ""
    striker_runs: int = 0
    striker_balls: int = 0
    striker_fours: int = 0
    striker_sixes: int = 0
    non_striker: str = ""
    non_striker_runs: int = 0
    non_striker_balls: int = 0
    non_striker_fours: int = 0
    non_striker_sixes: int = 0
    bowler: str = ""
    bowler_overs: float = 0.0
    bowler_runs: int = 0
    bowler_wickets: int = 0
    total_runs: int = 0
    total_wickets: int = 0
    play_by_play: str = ""
    speed_kph: Optional[float] = None
    pitch_zone: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BallEvent":
        return cls(
            match_id=data.get("match_id", "LIVE_MATCH"),
            match_title=data.get("match_title", "Live Cricket Broadcast"),
            venue=data.get("venue", "International Stadium"),
            innings=data.get("innings", 1),
            batting_team=data.get("batting_team", "BAT"),
            bowling_team=data.get("bowling_team", "BOWL"),
            target=data.get("target"),
            over=data.get("over", 0),
            ball=data.get("ball", 1),
            runs=data.get("runs", 0),
            extras=data.get("extras", 0),
            is_boundary=data.get("is_boundary", False),
            boundary_type=data.get("boundary_type"),
            is_wicket=data.get("is_wicket", False),
            dismissal_type=data.get("dismissal_type"),
            dismissed_player=data.get("dismissed_player"),
            striker=data.get("striker", "Striker"),
            striker_runs=data.get("striker_runs", 0),
            striker_balls=data.get("striker_balls", 0),
            striker_fours=data.get("striker_fours", 0),
            striker_sixes=data.get("striker_sixes", 0),
            non_striker=data.get("non_striker", "Non-Striker"),
            non_striker_runs=data.get("non_striker_runs", 0),
            non_striker_balls=data.get("non_striker_balls", 0),
            non_striker_fours=data.get("non_striker_fours", 0),
            non_striker_sixes=data.get("non_striker_sixes", 0),
            bowler=data.get("bowler", "Bowler"),
            bowler_overs=data.get("bowler_overs", 0.0),
            bowler_runs=data.get("bowler_runs", 0),
            bowler_wickets=data.get("bowler_wickets", 0),
            total_runs=data.get("total_runs", 0),
            total_wickets=data.get("total_wickets", 0),
            play_by_play=data.get("play_by_play", ""),
            speed_kph=data.get("speed_kph"),
            pitch_zone=data.get("pitch_zone")
        )

class MatchState:
    """Maintains running match state and produces context summaries."""
    def __init__(self):
        self.latest_event: Optional[BallEvent] = None
        self.event_history: List[BallEvent] = []
        self.recent_balls: List[str] = [] # e.g. ['4', '1', 'W', '6']

    def update(self, event: BallEvent) -> Dict[str, Any]:
        self.latest_event = event
        self.event_history.append(event)
        
        # Track recent ball badge
        badge = str(event.runs)
        if event.is_wicket:
            badge = "W"
        elif event.is_boundary and event.boundary_type == 6:
            badge = "6"
        elif event.is_boundary and event.boundary_type == 4:
            badge = "4"
        elif event.runs == 0 and not event.is_wicket:
            badge = "•"
        self.recent_balls.append(badge)
        if len(self.recent_balls) > 8:
            self.recent_balls.pop(0)

        return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        if not self.latest_event:
            return {}
        ev = self.latest_event
        
        # Calculate total balls bowled in innings
        completed_overs = ev.over
        current_ball = ev.ball
        balls_bowled = (completed_overs * 6) + (current_ball - 1)
        overs_float = completed_overs + ((current_ball) / 10.0)
        overs_decimal = completed_overs + ((current_ball) / 6.0)

        # Current Run Rate
        crr = round(ev.total_runs / overs_decimal, 2) if overs_decimal > 0 else 0.0

        # Required Run Rate
        rrr = 0.0
        runs_needed = 0
        balls_remaining = 0
        is_chase = ev.target is not None and ev.target > 0
        if is_chase:
            runs_needed = max(0, ev.target - ev.total_runs)
            # Assuming 20-over match default unless over > 20
            max_overs = 20 if ev.over < 20 else 50
            total_match_balls = max_overs * 6
            balls_remaining = max(0, total_match_balls - (completed_overs * 6 + current_ball))
            if balls_remaining > 0:
                rrr = round((runs_needed / balls_remaining) * 6.0, 2)

        # Milestones / special situations
        milestone = None
        if ev.striker_runs in (50, 100):
            milestone = f"{ev.striker} {ev.striker_runs} Milestone"
        elif ev.striker_runs >= 48 and ev.striker_runs < 50:
            milestone = f"{ev.striker} nearing 50"

        # Match phase
        if ev.over < 6:
            phase = "Powerplay"
        elif ev.over >= 16:
            phase = "Death Overs"
        else:
            phase = "Middle Overs"

        return {
            "match_title": ev.match_title,
            "venue": ev.venue,
            "batting_team": ev.batting_team,
            "bowling_team": ev.bowling_team,
            "total_runs": ev.total_runs,
            "total_wickets": ev.total_wickets,
            "over": ev.over,
            "ball": ev.ball,
            "overs_str": f"{ev.over}.{ev.ball}",
            "target": ev.target,
            "runs_needed": runs_needed,
            "balls_remaining": balls_remaining,
            "crr": crr,
            "rrr": rrr,
            "is_chase": is_chase,
            "phase": phase,
            "striker": ev.striker,
            "striker_runs": ev.striker_runs,
            "striker_balls": ev.striker_balls,
            "striker_fours": ev.striker_fours,
            "striker_sixes": ev.striker_sixes,
            "striker_sr": round((ev.striker_runs / ev.striker_balls) * 100, 1) if ev.striker_balls > 0 else 0.0,
            "non_striker": ev.non_striker,
            "non_striker_runs": ev.non_striker_runs,
            "non_striker_balls": ev.non_striker_balls,
            "bowler": ev.bowler,
            "bowler_overs": ev.bowler_overs,
            "bowler_runs": ev.bowler_runs,
            "bowler_wickets": ev.bowler_wickets,
            "bowler_economy": round(ev.bowler_runs / max(1.0, ev.bowler_overs), 2),
            "last_event_text": ev.play_by_play,
            "last_ball_runs": ev.runs,
            "is_boundary": ev.is_boundary,
            "boundary_type": ev.boundary_type,
            "is_wicket": ev.is_wicket,
            "dismissed_player": ev.dismissed_player,
            "milestone": milestone,
            "speed_kph": ev.speed_kph,
            "recent_balls": list(self.recent_balls)
        }
