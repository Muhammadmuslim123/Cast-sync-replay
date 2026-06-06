/**
 * Time-synced multi-stream asciinema player with global timeline scrubbing.
 */

(function () {
  const gridEl = document.getElementById("grid");
  const btnPlay = document.getElementById("btn-play");
  const btnPause = document.getElementById("btn-pause");
  const btnRestart = document.getElementById("btn-restart");
  const btnBack10 = document.getElementById("btn-back-10");
  const btnFwd10 = document.getElementById("btn-fwd-10");
  const speedInput = document.getElementById("speed");
  const speedLabel = document.getElementById("speed-label");
  const syncClock = document.getElementById("sync-clock");
  const timeline = document.getElementById("timeline");
  const timelineEnd = document.getElementById("timeline-end");

  let streams = [];
  let grid = { rows: 1, cols: 1, split: "grid" };
  let slots = [];

  let speed = 1;
  let running = false;
  let scrubbing = false;
  let syncTime = 0;
  let maxSyncTime = 0;
  let lastFrame = null;
  let rafId = null;

  function formatTime(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  function updateClock() {
    syncClock.textContent = formatTime(syncTime);
    if (!scrubbing) {
      timeline.value = String(syncTime);
    }
  }

  function computeMaxSyncTime() {
    let max = 0;
    slots.forEach((slot) => {
      if (!slot.player) return;
      const dur = slot.player.getDuration();
      if (dur != null) {
        max = Math.max(max, slot.delay + dur);
      }
    });
    maxSyncTime = max || 60;
    timeline.max = String(maxSyncTime);
    timeline.disabled = maxSyncTime <= 0;
    timelineEnd.textContent = formatTime(maxSyncTime);
  }

  function scrollMountToBottom(mount) {
    requestAnimationFrame(() => {
      mount.scrollTop = mount.scrollHeight;
    });
  }

  function seekSlot(slot, localTime, shouldPlay) {
    if (!slot.player) return Promise.resolve();

    const t = Math.max(0, localTime);
    if (t <= 0 && syncTime < slot.delay) {
      slot.started = false;
      return slot.player.seek(0).then(() => {
        slot.player.pause();
      });
    }

    slot.started = true;
    return slot.player.seek(t).then(() => {
      if (shouldPlay) {
        return slot.player.play();
      }
      slot.player.pause();
    });
  }

  function seekAll(globalTime, shouldPlay) {
    syncTime = Math.max(0, Math.min(globalTime, maxSyncTime));
    updateClock();

    const jobs = slots.map((slot) => {
      const local = syncTime - slot.delay;
      return seekSlot(slot, local, shouldPlay && local >= 0);
    });
    return Promise.all(jobs);
  }

  function buildGrid() {
    gridEl.className = grid.split === "stacked" ? "stacked" : "";
    gridEl.style.gridTemplateRows = `repeat(${grid.rows}, minmax(0, 1fr))`;
    gridEl.style.gridTemplateColumns = `repeat(${grid.cols}, minmax(0, 1fr))`;
    gridEl.innerHTML = "";

    slots = streams.map((stream) => {
      const cell = document.createElement("section");
      cell.className = "stream-cell";
      const rowSpan = stream.row_span || 1;
      const colSpan = stream.col_span || 1;
      cell.style.gridRow = `${stream.row + 1} / span ${rowSpan}`;
      cell.style.gridColumn = `${stream.col + 1} / span ${colSpan}`;

      const label = document.createElement("div");
      label.className = "stream-label";
      const delayNote =
        stream.delay > 0
          ? ` <span class="delay">(+${stream.delay}s)</span>`
          : "";
      const primaryNote = stream.is_primary
        ? '<span class="primary">primary</span>'
        : "";
      label.innerHTML = `${stream.name}${delayNote}${primaryNote}`;

      const mount = document.createElement("div");
      mount.className = "player-mount";
      mount.id = `player-${stream.id}`;

      cell.appendChild(label);
      cell.appendChild(mount);
      gridEl.appendChild(cell);

      if (typeof AsciinemaPlayer === "undefined") {
        mount.innerHTML =
          '<p class="player-error">asciinema-player failed to load (check network / CDN)</p>';
        return { player: null, started: false, mount, delay: stream.delay };
      }

      const fontPx = stream.font_size || 14;
      const player = AsciinemaPlayer.create(stream.url, mount, {
        autoPlay: false,
        preload: true,
        speed: speed,
        cols: stream.width,
        rows: stream.height,
        fit: false,
        terminalFontSize: `${fontPx}px`,
        controls: false,
        theme: "asciinema",
        idleTimeLimit: 2,
      });

      player.addEventListener("playing", () => computeMaxSyncTime());

      return { player, started: false, mount, delay: stream.delay };
    });

    // Durations load async after preload
    setTimeout(computeMaxSyncTime, 800);
    setTimeout(computeMaxSyncTime, 2500);
  }

  function disposePlayers() {
    slots.forEach((slot) => {
      try {
        if (slot.player) slot.player.dispose();
      } catch (_) {
        /* ignore */
      }
    });
    slots = [];
  }

  function showCastErrors(bad) {
    if (bad.length === 0) return;
    const names = bad.map((b) => `${b.stream.name} (${b.status})`).join(", ");
    gridEl.insertAdjacentHTML(
      "afterbegin",
      `<div class="banner-error">Some recordings could not be loaded: ${names}. ` +
        `Stop the server (Ctrl+C) and run <code>cast-sync-here</code> again.</div>`
    );
  }

  async function validateCasts() {
    const checks = await Promise.all(
      streams.map(async (s) => {
        const res = await fetch(s.url, { method: "HEAD" });
        return { stream: s, ok: res.ok, status: res.status };
      })
    );
    return checks.filter((c) => !c.ok);
  }

  function tick(now) {
    if (lastFrame !== null && running) {
      const delta = (now - lastFrame) / 1000;
      syncTime += delta * speed;
      if (syncTime > maxSyncTime) syncTime = maxSyncTime;
      updateClock();

      slots.forEach((slot) => {
        const local = syncTime - slot.delay;
        if (!slot.started && local >= 0) {
          slot.started = true;
          if (slot.player) {
            slot.player.play().catch((err) => console.error("play failed", err));
          }
        }
        if (slot.started && running) {
          scrollMountToBottom(slot.mount);
        }
      });
    }
    lastFrame = now;
    if (running) {
      rafId = requestAnimationFrame(tick);
    }
  }

  function startSync() {
    if (running) return;
    running = true;
    lastFrame = null;
    seekAll(syncTime, true);
    rafId = requestAnimationFrame(tick);
  }

  function pauseSync() {
    running = false;
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
    slots.forEach((slot) => {
      if (slot.player) slot.player.pause();
    });
  }

  function restartSync() {
    pauseSync();
    syncTime = 0;
    updateClock();
    disposePlayers();
    buildGrid();
    seekAll(0, false);
  }

  function nudge(seconds) {
    pauseSync();
    seekAll(syncTime + seconds, false);
  }

  function onSpeedChange() {
    const newSpeed = parseFloat(speedInput.value);
    speedLabel.textContent = `${newSpeed}×`;
    speed = newSpeed;
    slots.forEach((slot) => {
      if (!slot.player) return;
      // Recreate is heavy; player speed is set at create — update via dispose only if needed.
      // asciinema v3 has no runtime setSpeed; pause and note in UI.
    });
    speedLabel.title =
      newSpeed !== 1
        ? "Speed applies to sync clock. Per-player speed is set at load — restart to apply."
        : "";
  }

  btnPlay.addEventListener("click", startSync);
  btnPause.addEventListener("click", pauseSync);
  btnRestart.addEventListener("click", restartSync);
  btnBack10.addEventListener("click", () => nudge(-10));
  btnFwd10.addEventListener("click", () => nudge(10));
  speedInput.addEventListener("input", onSpeedChange);

  timeline.addEventListener("pointerdown", () => {
    scrubbing = true;
    pauseSync();
  });
  timeline.addEventListener("input", () => {
    seekAll(parseFloat(timeline.value), false);
  });
  timeline.addEventListener("pointerup", () => {
    scrubbing = false;
  });

  window.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea")) return;
    if (e.code === "Space") {
      e.preventDefault();
      running ? pauseSync() : startSync();
    } else if (e.code === "ArrowLeft") {
      nudge(e.shiftKey ? -30 : -10);
    } else if (e.code === "ArrowRight") {
      nudge(e.shiftKey ? 30 : 10);
    }
  });

  window.addEventListener("beforeunload", () => {
    pauseSync();
    disposePlayers();
  });

  fetch("/api/config")
    .then((r) => r.json())
    .then(async (config) => {
      streams = config.streams;
      grid = config.grid;
      const bad = await validateCasts();
      buildGrid();
      showCastErrors(bad);
      updateClock();
      // Start paused so user can scrub/copy before playing
      seekAll(0, false);
    })
    .catch((err) => {
      gridEl.innerHTML = `<p style="padding:1rem;color:#f85149">Failed to load config: ${err}</p>`;
    });
})();
