// Cricket AI Live Broadcaster - Frontend Client
(function () {
  let ws = null;
  let isAudioMuted = false;
  const audioPlayer = document.getElementById("liveAudio");

  // DOM Elements
  const btnStart = document.getElementById("btnStart");
  const btnStop = document.getElementById("btnStop");
  const btnAudioToggle = document.getElementById("btnAudioToggle");
  const audioIcon = document.getElementById("audioIcon");
  const audioText = document.getElementById("audioText");
  const statusBadge = document.getElementById("statusBadge");
  const statusText = document.getElementById("statusText");
  const wsBadge = document.getElementById("wsBadge");
  const wsText = document.getElementById("wsText");

  const matchTitle = document.getElementById("matchTitle");
  const matchVenue = document.getElementById("matchVenue");
  const battingTeam = document.getElementById("battingTeam");
  const teamScore = document.getElementById("teamScore");
  const oversCount = document.getElementById("oversCount");
  const crrBadge = document.getElementById("crrBadge");
  const oppScore = document.getElementById("oppScore");
  const strikerName = document.getElementById("strikerName");
  const strikerFigures = document.getElementById("strikerFigures");
  const strikerMeta = document.getElementById("strikerMeta");
  const nonStrikerName = document.getElementById("nonStrikerName");
  const nonStrikerFigures = document.getElementById("nonStrikerFigures");
  const nonStrikerMeta = document.getElementById("nonStrikerMeta");
  const bowlerName = document.getElementById("bowlerName");
  const bowlerFigures = document.getElementById("bowlerFigures");
  const bowlerEcon = document.getElementById("bowlerEcon");
  const partnershipText = document.getElementById("partnershipText");
  const lastWktText = document.getElementById("lastWktText");
  const thisOverContainer = document.getElementById("thisOverContainer");
  const alertBanner = document.getElementById("alertBanner");


  const onAirBadge = document.getElementById("onAirBadge");
  const onAirText = document.getElementById("onAirText");
  const waveform = document.getElementById("waveform");
  const speakingText = document.getElementById("speakingText");
  const playerStateText = document.getElementById("playerStateText");

  const feedList = document.getElementById("feedList");
  const feedCount = document.getElementById("feedCount");
  const archiveList = document.getElementById("archiveList");
  const archiveCount = document.getElementById("archiveCount");

  let totalBalls = 0;
  let totalArchives = 0;

  // 1. WebSocket Connection
  function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      wsBadge.className = "badge-conn connected";
      wsText.textContent = "LIVE CONNECTED";
    };

    ws.onclose = () => {
      wsBadge.className = "badge-conn disconnected";
      wsText.textContent = "DISCONNECTED";
      setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
      ws.close();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error("Error parsing WS message:", e);
      }
    };
  }

  // 2. Dispatch WebSocket Message
  function handleMessage(msg) {
    switch (msg.type) {
      case "status":
        updateEngineStatus(msg.data);
        break;

      case "match_state":
        updateScoreboard(msg.data);
        break;

      case "commentary":
        handleCommentary(msg.data);
        break;

      case "recording_ready":
        addArchiveItem(msg.data);
        break;

      case "feed_item":
        addFeedItem(msg.data);
        break;
    }
  }

  function updateEngineStatus(data) {
    if (data.is_running) {
      statusBadge.className = "badge-status streaming";
      statusText.textContent = "STREAMING LIVE";
      btnStart.disabled = true;
      btnStop.disabled = false;
    } else {
      statusBadge.className = "badge-status idle";
      statusText.textContent = "IDLE";
      btnStart.disabled = false;
      btnStop.disabled = true;
      setTalkingState(false);
    }
  }

  function updateScoreboard(data) {
    if (data.title) matchTitle.textContent = data.title;
    if (data.venue) matchVenue.textContent = data.venue;
    if (data.batting_team) battingTeam.textContent = data.batting_team;
    if (data.total_runs !== undefined && data.total_wickets !== undefined) {
      teamScore.textContent = `${data.total_runs}/${data.total_wickets}`;
    }
    if (data.overs) oversCount.textContent = `OVERS: ${data.overs}`;
    if (data.crr && crrBadge) crrBadge.textContent = `CRR: ${data.crr}`;
    if (data.team2_score && oppScore) oppScore.textContent = data.team2_score;

    if (data.striker) strikerName.textContent = data.striker;
    if (data.striker_runs !== undefined) strikerFigures.textContent = `${data.striker_runs} (${data.striker_balls || 0})`;
    if (strikerMeta) {
      strikerMeta.textContent = `4s: ${data.striker_fours ?? 0} • 6s: ${data.striker_sixes ?? 0} • SR: ${data.striker_sr || '0.00'}`;
    }

    if (data.non_striker) nonStrikerName.textContent = data.non_striker;
    if (data.non_striker_runs !== undefined) nonStrikerFigures.textContent = `${data.non_striker_runs} (${data.non_striker_balls || 0})`;
    if (nonStrikerMeta) {
      nonStrikerMeta.textContent = `4s: ${data.non_striker_fours ?? 0} • 6s: ${data.non_striker_sixes ?? 0} • SR: ${data.non_striker_sr || '0.00'}`;
    }

    if (data.bowler) bowlerName.textContent = data.bowler;
    if (data.bowler_figures) bowlerFigures.textContent = data.bowler_figures;
    if (bowlerEcon) bowlerEcon.textContent = `Econ: ${data.bowler_econ || '0.00'}`;

    if (partnershipText && data.partnership) partnershipText.textContent = `${data.partnership} runs`;
    if (lastWktText && data.last_wicket) lastWktText.textContent = data.last_wicket;

    // Render this over ball bubbles
    if (thisOverContainer && data.this_over_balls && Array.isArray(data.this_over_balls)) {
      thisOverContainer.innerHTML = "";
      data.this_over_balls.forEach((b) => {
        const bubble = document.createElement("span");
        let cls = "ball-bubble";
        if (b === "4") cls += " four";
        else if (b === "6") cls += " six";
        else if (b.toUpperCase().includes("W")) cls += " wicket";
        bubble.className = cls;
        bubble.textContent = b;
        thisOverContainer.appendChild(bubble);
      });
    }

    const bannerText = data.alert || data.status || "";
    if (bannerText) {
      alertBanner.textContent = bannerText;
      alertBanner.classList.remove("hidden");
    } else {
      alertBanner.classList.add("hidden");
    }
  }


  function handleCommentary(data) {
    speakingText.textContent = `"${data.text}"`;
    setTalkingState(true, data.badge);

    // If an audio file URL is provided, play it
    if (data.audio_url && !isAudioMuted) {
      audioPlayer.src = data.audio_url;
      audioPlayer.play().catch((e) => {
        console.warn("Auto-play prevented by browser policy (interact with page first):", e);
        playerStateText.textContent = "Click Mute/Unmute to enable audio playback";
      });
      playerStateText.textContent = `Broadcasting: ${data.badge || '🎙️ Live Voice'} (${data.duration ? data.duration.toFixed(1) + 's' : ''})`;
    }

    // Reset talking state after duration
    const durMs = (data.duration || 4.0) * 1000;
    setTimeout(() => {
      setTalkingState(false);
    }, durMs);
  }

  function setTalkingState(isTalking, badge = null) {
    if (isTalking) {
      onAirBadge.className = "on-air-badge active";
      onAirText.textContent = badge ? `${badge} • ON AIR` : "ON AIR (COMMENTATOR)";
      waveform.className = "waveform active";
    } else {
      onAirBadge.className = "on-air-badge";
      onAirText.textContent = "STUDIO READY";
      waveform.className = "waveform";
    }
  }

  function addFeedItem(item) {
    const empty = feedList.querySelector(".feed-empty");
    if (empty) empty.remove();

    totalBalls++;
    feedCount.textContent = `${totalBalls} Balls`;

    const el = document.createElement("div");
    el.className = "feed-item";

    let badgeClass = "feed-runs-badge";
    if (item.runs === "4") badgeClass += " four";
    else if (item.runs === "6") badgeClass += " six";
    else if (String(item.runs).toUpperCase().includes("W")) badgeClass += " wicket";

    const eventBadgeHtml = item.badge ? `<span class="feed-event-badge">${item.badge}</span>` : "";

    el.innerHTML = `
      <div class="feed-item-top">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="feed-over-badge">OVER ${item.over}</span>
          ${eventBadgeHtml}
        </div>
        <span class="${badgeClass}">${item.runs} RUN${item.runs === "1" ? "" : "S"}</span>
      </div>
      <div class="feed-matchup">${item.matchup || ""}</div>
      <div class="feed-commentary">${item.commentary}</div>
    `;

    feedList.prepend(el);
  }


  function addArchiveItem(item) {
    const empty = archiveList.querySelector(".feed-empty");
    if (empty) empty.remove();

    totalArchives++;
    archiveCount.textContent = `${totalArchives} Clips`;

    const el = document.createElement("div");
    el.className = "archive-item";
    el.innerHTML = `
      <div class="archive-info">
        <span class="archive-title">${item.title || "Commentary Voice Clip"}</span>
        <span class="archive-time">${item.time || new Date().toLocaleTimeString()} • ${item.duration ? item.duration.toFixed(1) + "s" : ""}</span>
      </div>
      <div class="archive-actions">
        <button class="btn-play-sm" onclick="window.playClip('${item.url}')">▶ Play</button>
        <a class="btn-dl-sm" href="${item.url}" download="${item.filename || 'commentary.mp3'}">⬇ MP3</a>
      </div>
    `;

    archiveList.prepend(el);
  }

  window.playClip = function (url) {
    audioPlayer.src = url;
    audioPlayer.play();
  };

  // 3. User Controls
  btnStart.addEventListener("click", async () => {
    const url = document.getElementById("matchUrl").value.trim();
    const lang = document.getElementById("langSelect").value;
    const key = document.getElementById("streamKey").value.trim();

    if (!url) {
      alert("Please provide a valid match link!");
      return;
    }

    btnStart.disabled = true;
    statusText.textContent = "STARTING...";

    try {
      const resp = await fetch("/api/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, lang, stream_key: key }),
      });
      const res = await resp.json();
      if (!res.ok) {
        alert("Error starting stream: " + (res.error || "Unknown error"));
        btnStart.disabled = false;
      }
    } catch (e) {
      alert("Failed to connect to server: " + e);
      btnStart.disabled = false;
    }
  });

  btnStop.addEventListener("click", async () => {
    btnStop.disabled = true;
    try {
      await fetch("/api/stop", { method: "POST" });
    } catch (e) {
      console.error(e);
    }
  });

  btnAudioToggle.addEventListener("click", () => {
    isAudioMuted = !isAudioMuted;
    if (isAudioMuted) {
      audioPlayer.muted = true;
      audioIcon.textContent = "🔇";
      audioText.textContent = "Unmute Audio";
      playerStateText.textContent = "Audio muted by user";
    } else {
      audioPlayer.muted = false;
      audioIcon.textContent = "🔊";
      audioText.textContent = "Mute Audio";
      playerStateText.textContent = "Live audio streaming enabled";
      audioPlayer.play().catch(() => {});
    }
  });

  // 4. Initial Fetch
  async function loadInitialData() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      updateEngineStatus(data);
      if (data.match_state) updateScoreboard(data.match_state);

      const recRes = await fetch("/api/recordings");
      const recs = await recRes.json();
      if (Array.isArray(recs)) {
        recs.forEach(addArchiveItem);
      }
    } catch (e) {
      console.log("Could not load initial data:", e);
    }
  }

  // Run
  connectWebSocket();
  loadInitialData();
})();
