/**
 * Event-by-event multi-stream asciinema review.
 *
 * Each pane is an xterm.js terminal, so cursor movement, redraws, clears, and
 * prompt editing render like a terminal instead of raw text. The global player
 * merges all cast output events chronologically and skips idle waits.
 */

(function () {
  const gridEl = document.getElementById("grid");
  const btnPlay = document.getElementById("btn-play");
  const btnPause = document.getElementById("btn-pause");
  const btnRestart = document.getElementById("btn-restart");
  const btnBack10 = document.getElementById("btn-back-10");
  const btnFwd10 = document.getElementById("btn-fwd-10");
  const btnEnd = document.getElementById("btn-end");
  const speedInput = document.getElementById("speed");
  const speedLabel = document.getElementById("speed-label");
  const syncClock = document.getElementById("sync-clock");
  const timeline = document.getElementById("timeline");
  const timelineEnd = document.getElementById("timeline-end");
  const sessionRow = document.getElementById("session-row");
  const sessionSelect = document.getElementById("session-select");
  const sessionSummary = document.getElementById("session-summary");

  const params = new URLSearchParams(window.location.search);
  const focusStreamId = params.has("stream") ? Number(params.get("stream")) : null;

  let allStreams = [];
  let sessions = [];
  let streams = [];
  let slots = [];
  let globalEvents = [];
  let running = false;
  let scrubbing = false;
  let playRate = 12;
  let globalStep = 0;
  let frameCarry = 0;
  let lastFrame = null;
  let rafId = null;

  function formatCount(value) {
    return `${Math.max(0, Math.floor(value))}`;
  }

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (ch) => {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function resetDelays(selectedStreams) {
    return selectedStreams
      .slice()
      .sort((a, b) => a.timestamp - b.timestamp)
      .map((stream, index) => ({ ...stream, is_primary: index === 0 }));
  }

  function updateGlobalUi() {
    syncClock.textContent = formatCount(globalStep);
    if (!scrubbing) timeline.value = String(globalStep);
    slots.forEach(updateSlotUi);
  }

  function updateSlotUi(slot) {
    slot.localClock.textContent = formatCount(slot.index);
    if (!slot.localScrubbing) slot.localTimeline.value = String(slot.index);
  }

  function buildGrid() {
    pauseReview();
    disposeSlots();
    gridEl.innerHTML = "";
    globalEvents = [];
    globalStep = 0;
    slots = streams.map((stream) => buildSlot(stream));
    Promise.all(slots.map(loadEvents)).then(() => {
      buildGlobalEvents();
      seekGlobal(0);
    });
  }

  function buildSlot(stream) {
    const cell = document.createElement("section");
    cell.className = focusStreamId === stream.id ? "stream-cell focused" : "stream-cell";

    const label = document.createElement("div");
    label.className = "stream-label";

    const title = document.createElement("div");
    title.className = "stream-title";
    title.innerHTML = `${escapeHtml(stream.name)}${
      stream.is_primary ? ' <span class="primary">primary</span>' : ""
    }`;

    const actions = document.createElement("div");
    actions.className = "pane-actions";
    actions.appendChild(
      createButton("Expand", "Expand this pane in the current page", () => {
        cell.classList.toggle("expanded");
        requestAnimationFrame(() => resizeTerminal(slot));
      })
    );
    actions.appendChild(
      createButton("New Tab", "Open this recording in a focused tab", () => {
        window.open(`/?stream=${stream.id}`, "_blank", "noopener");
      })
    );
    actions.appendChild(
      createButton("Pane End", "Jump this recording to its end", () => {
        seekSlot(slot, slot.events.length);
      })
    );

    label.appendChild(title);
    label.appendChild(actions);

    const localTimeline = document.createElement("div");
    localTimeline.className = "pane-timeline";
    const localClock = document.createElement("span");
    localClock.className = "pane-clock";
    localClock.textContent = "0";
    const localRange = document.createElement("input");
    localRange.type = "range";
    localRange.min = "0";
    localRange.max = "0";
    localRange.step = "1";
    localRange.value = "0";
    localRange.disabled = true;
    const localEnd = document.createElement("span");
    localEnd.className = "pane-clock";
    localEnd.textContent = "0";
    localTimeline.appendChild(localClock);
    localTimeline.appendChild(localRange);
    localTimeline.appendChild(localEnd);

    const output = document.createElement("div");
    output.className = "player-mount xterm-mount";
    output.textContent = "Loading recording...";

    cell.appendChild(label);
    cell.appendChild(localTimeline);
    cell.appendChild(output);
    gridEl.appendChild(cell);

    const slot = {
      stream,
      cell,
      output,
      term: null,
      events: [],
      index: 0,
      localScrubbing: false,
      localTimeline: localRange,
      localClock,
      localEnd,
      resizeObserver: null,
    };

    localRange.addEventListener("pointerdown", () => {
      slot.localScrubbing = true;
      pauseReview();
    });
    localRange.addEventListener("input", () => {
      seekSlot(slot, Number(localRange.value));
    });
    localRange.addEventListener("pointerup", () => {
      slot.localScrubbing = false;
    });

    setupTerminal(slot);
    return slot;
  }

  function createButton(text, title, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "pane-button";
    button.textContent = text;
    button.title = title;
    button.addEventListener("click", onClick);
    return button;
  }

  function setupTerminal(slot) {
    slot.output.textContent = "";
    if (typeof Terminal === "undefined") {
      slot.output.textContent = "xterm.js failed to load.";
      return;
    }

    slot.term = new Terminal({
      cols: slot.stream.width || 120,
      rows: slot.stream.height || 30,
      scrollback: 100000,
      convertEol: false,
      cursorBlink: false,
      disableStdin: true,
      allowProposedApi: false,
      fontSize: 13,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
      theme: {
        background: "#0d1117",
        foreground: "#e6edf3",
        cursor: "#e6edf3",
        selectionBackground: "#264f78",
      },
    });
    slot.term.open(slot.output);
    slot.resizeObserver = new ResizeObserver(() => resizeTerminal(slot));
    slot.resizeObserver.observe(slot.output);
    requestAnimationFrame(() => resizeTerminal(slot));
  }

  function resizeTerminal(slot) {
    if (!slot.term || !slot.output.clientWidth || !slot.output.clientHeight) return;
    const charW = 7.8;
    const charH = 17.5;
    const cols = Math.max(40, Math.floor((slot.output.clientWidth - 16) / charW));
    const rows = Math.max(10, Math.floor((slot.output.clientHeight - 16) / charH));
    if (cols !== slot.term.cols || rows !== slot.term.rows) {
      slot.term.resize(cols, rows);
      rerenderSlot(slot, slot.index);
    }
  }

  async function loadEvents(slot) {
    try {
      const res = await fetch(slot.stream.url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const lines = (await res.text()).split(/\r?\n/).filter(Boolean);
      slot.events = lines
        .slice(1)
        .map((line) => {
          try {
            const event = JSON.parse(line);
            if (event[1] !== "o") return null;
            return { time: Number(event[0]), text: event[2] || "" };
          } catch (_) {
            return null;
          }
        })
        .filter(Boolean);

      slot.localTimeline.max = String(slot.events.length);
      slot.localTimeline.disabled = slot.events.length === 0;
      slot.localEnd.textContent = formatCount(slot.events.length);
      rerenderSlot(slot, 0);
    } catch (err) {
      if (slot.term) slot.term.write(`Recording failed to load: ${err}`);
      else slot.output.textContent = `Recording failed to load: ${err}`;
      slot.events = [];
    }
  }

  function buildGlobalEvents() {
    globalEvents = [];
    slots.forEach((slot, slotIndex) => {
      slot.events.forEach((event, eventIndex) => {
        globalEvents.push({
          at: slot.stream.timestamp + event.time,
          slotIndex,
          eventIndex,
        });
      });
    });
    globalEvents.sort((a, b) => a.at - b.at || a.slotIndex - b.slotIndex || a.eventIndex - b.eventIndex);
    timeline.max = String(globalEvents.length);
    timeline.disabled = globalEvents.length === 0;
    timelineEnd.textContent = formatCount(globalEvents.length);
    updateGlobalUi();
  }

  function seekGlobal(step) {
    globalStep = Math.max(0, Math.min(step, globalEvents.length));
    const counts = new Array(slots.length).fill(0);
    for (let i = 0; i < globalStep; i += 1) {
      const event = globalEvents[i];
      counts[event.slotIndex] = Math.max(counts[event.slotIndex], event.eventIndex + 1);
    }
    slots.forEach((slot, index) => renderSlot(slot, counts[index]));
    updateGlobalUi();
  }

  function seekSlot(slot, index) {
    pauseReview();
    renderSlot(slot, index);
    updateGlobalFromSlots();
  }

  function updateGlobalFromSlots() {
    let count = 0;
    for (const event of globalEvents) {
      if (slots[event.slotIndex].index > event.eventIndex) count += 1;
    }
    globalStep = count;
    updateGlobalUi();
  }

  function renderSlot(slot, index) {
    const next = Math.max(0, Math.min(index, slot.events.length));
    if (!slot.term) {
      slot.index = next;
      return;
    }

    if (next < slot.index) {
      rerenderSlot(slot, next);
      return;
    }

    let chunk = "";
    while (slot.index < next) {
      chunk += slot.events[slot.index].text;
      slot.index += 1;
    }
    if (chunk) slot.term.write(chunk);
    updateSlotUi(slot);
  }

  function rerenderSlot(slot, index) {
    if (!slot.term) {
      slot.index = index;
      updateSlotUi(slot);
      return;
    }
    slot.term.reset();
    slot.term.clear();
    slot.index = 0;
    renderSlot(slot, index);
  }

  function stepForward(amount) {
    pauseReview();
    seekGlobal(globalStep + amount);
  }

  function playTick(now) {
    if (lastFrame !== null && running) {
      const delta = (now - lastFrame) / 1000;
      frameCarry += delta * playRate;
      const steps = Math.floor(frameCarry);
      if (steps > 0) {
        frameCarry -= steps;
        seekGlobal(globalStep + steps);
      }
      if (globalStep >= globalEvents.length) pauseReview();
    }
    lastFrame = now;
    if (running) rafId = requestAnimationFrame(playTick);
  }

  function startReview() {
    if (running) return;
    running = true;
    lastFrame = null;
    frameCarry = 0;
    rafId = requestAnimationFrame(playTick);
  }

  function pauseReview() {
    running = false;
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  function restartReview() {
    pauseReview();
    seekGlobal(0);
  }

  function jumpEnd() {
    pauseReview();
    seekGlobal(globalEvents.length);
  }

  function onSpeedChange() {
    const multiplier = Number(speedInput.value);
    playRate = Math.max(1, Math.round(multiplier * 12));
    speedLabel.textContent = `${playRate}/s`;
    speedLabel.title = "Terminal output events per second. Idle waits are skipped.";
  }

  function renderSessionPicker() {
    if (focusStreamId !== null || sessions.length <= 1) {
      sessionRow.hidden = true;
      return;
    }
    sessionRow.hidden = false;
    sessionSelect.innerHTML = "";
    sessions.forEach((session) => {
      const option = document.createElement("option");
      option.value = String(session.id);
      option.textContent = `${session.label} (${session.count} recordings)`;
      sessionSelect.appendChild(option);
    });
  }

  async function selectSession(sessionId) {
    pauseReview();
    const session = sessions.find((s) => s.id === Number(sessionId)) || sessions[0];
    const ids = new Set(session.stream_ids);
    streams = resetDelays(allStreams.filter((stream) => ids.has(stream.id)));
    sessionSummary.textContent = `${streams.length} recordings loaded`;
    buildGrid();
  }

  async function selectFocusedStream(streamId) {
    const stream = allStreams.find((s) => s.id === streamId) || allStreams[0];
    streams = resetDelays([stream]);
    buildGrid();
  }

  function disposeSlots() {
    slots.forEach((slot) => {
      if (slot.resizeObserver) slot.resizeObserver.disconnect();
      if (slot.term) slot.term.dispose();
    });
    slots = [];
  }

  btnPlay.addEventListener("click", startReview);
  btnPause.addEventListener("click", pauseReview);
  btnRestart.addEventListener("click", restartReview);
  btnBack10.addEventListener("click", () => stepForward(-10));
  btnFwd10.addEventListener("click", () => stepForward(10));
  btnEnd.addEventListener("click", jumpEnd);
  speedInput.addEventListener("input", onSpeedChange);
  sessionSelect.addEventListener("change", () => selectSession(sessionSelect.value));

  timeline.addEventListener("pointerdown", () => {
    scrubbing = true;
    pauseReview();
  });
  timeline.addEventListener("input", () => {
    seekGlobal(Number(timeline.value));
  });
  timeline.addEventListener("pointerup", () => {
    scrubbing = false;
  });

  window.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select, button")) return;
    if (e.code === "Space") {
      e.preventDefault();
      running ? pauseReview() : startReview();
    } else if (e.code === "ArrowLeft") {
      stepForward(e.shiftKey ? -50 : -10);
    } else if (e.code === "ArrowRight") {
      stepForward(e.shiftKey ? 50 : 10);
    } else if (e.code === "End") {
      jumpEnd();
    }
  });

  window.addEventListener("beforeunload", () => {
    pauseReview();
    disposeSlots();
  });

  onSpeedChange();

  fetch("/api/config")
    .then((r) => r.json())
    .then(async (config) => {
      allStreams = config.streams;
      sessions =
        config.sessions && config.sessions.length
          ? config.sessions
          : [{ id: 0, stream_ids: allStreams.map((s) => s.id), count: allStreams.length }];
      renderSessionPicker();
      if (focusStreamId !== null) {
        await selectFocusedStream(focusStreamId);
      } else {
        await selectSession(sessions[0].id);
      }
    })
    .catch((err) => {
      gridEl.innerHTML = `<p style="padding:1rem;color:#f85149">Failed to load config: ${err}</p>`;
    });
})();
