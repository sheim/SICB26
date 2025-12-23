const state = {
  day: "",
  eventsAll: [],
  layout: {
    room_order_by_day: {},
    hidden_event_ids_by_day: {},
    misc_rooms_by_day: {},
    display_options: {},
    title_max_length: 60,
  },
  roomOrder: [],
};

const slotMinutes = 15;
const DEFAULT_DISPLAY_OPTIONS = {
  show_session: true,
  show_talk_title: true,
  show_time: true,
  show_room: true,
};
const DEFAULT_TITLE_MAX_LENGTH = 60;

const elements = {
  daySelect: document.getElementById("daySelect"),
  tableContainer: document.getElementById("tableContainer"),
  status: document.getElementById("status"),
  saveBtn: document.getElementById("saveBtn"),
  resetBtn: document.getElementById("resetBtn"),
  hiddenList: document.getElementById("hiddenList"),
  showSession: document.getElementById("showSession"),
  showTalkTitle: document.getElementById("showTalkTitle"),
  showTime: document.getElementById("showTime"),
  showRoom: document.getElementById("showRoom"),
  titleMaxLength: document.getElementById("titleMaxLength"),
};

function setStatus(message) {
  elements.status.textContent = message;
}

function minutesToLabel(totalMinutes) {
  const hour = Math.floor(totalMinutes / 60);
  const minute = totalMinutes % 60;
  const ampm = hour < 12 ? "AM" : "PM";
  const displayHour = hour % 12 === 0 ? 12 : hour % 12;
  return `${displayHour}:${String(minute).padStart(2, "0")} ${ampm}`;
}

function truncateText(text, maxLength) {
  if (!text) return "";
  if (!maxLength || maxLength <= 0 || text.length <= maxLength) {
    return text;
  }
  const suffix = "...";
  if (maxLength <= suffix.length) {
    return text.slice(0, maxLength);
  }
  const trimmed = text.slice(0, maxLength - suffix.length).trimEnd();
  if (!trimmed) {
    return text.slice(0, maxLength);
  }
  return `${trimmed}${suffix}`;
}

function normalizeLayout(layout) {
  const normalized = layout ? { ...layout } : {};
  normalized.room_order_by_day = normalized.room_order_by_day || {};
  normalized.hidden_event_ids_by_day = normalized.hidden_event_ids_by_day || {};
  normalized.misc_rooms_by_day = normalized.misc_rooms_by_day || {};

  const display = { ...DEFAULT_DISPLAY_OPTIONS };
  if (normalized.display_options) {
    Object.keys(display).forEach((key) => {
      if (typeof normalized.display_options[key] === "boolean") {
        display[key] = normalized.display_options[key];
      }
    });
  }
  normalized.display_options = display;

  const rawLength = Number(normalized.title_max_length);
  normalized.title_max_length = Number.isFinite(rawLength)
    ? Math.max(0, Math.floor(rawLength))
    : DEFAULT_TITLE_MAX_LENGTH;

  return normalized;
}

function getDisplayOptions() {
  return {
    ...DEFAULT_DISPLAY_OPTIONS,
    ...(state.layout.display_options || {}),
  };
}

function setDisplayOption(key, value) {
  const display = getDisplayOptions();
  display[key] = value;
  state.layout.display_options = display;
}

function getTitleMaxLength() {
  const value = Number(state.layout.title_max_length);
  if (!Number.isFinite(value)) return DEFAULT_TITLE_MAX_LENGTH;
  return Math.max(0, Math.floor(value));
}

function setTitleMaxLength(value) {
  state.layout.title_max_length = Math.max(0, Math.floor(value));
}

function syncDisplayControls() {
  const display = getDisplayOptions();
  elements.showSession.checked = display.show_session;
  elements.showTalkTitle.checked = display.show_talk_title;
  elements.showTime.checked = display.show_time;
  elements.showRoom.checked = display.show_room;
  elements.titleMaxLength.value = getTitleMaxLength();
}

function getHiddenSet() {
  const hidden = state.layout.hidden_event_ids_by_day[state.day] || [];
  return new Set(hidden.map((id) => Number(id)));
}

function setHiddenSet(ids) {
  state.layout.hidden_event_ids_by_day[state.day] = Array.from(ids);
}

function getMiscSet() {
  const misc = state.layout.misc_rooms_by_day[state.day] || [];
  return new Set(misc);
}

function setMiscSet(rooms) {
  state.layout.misc_rooms_by_day[state.day] = Array.from(rooms);
}

function defaultRoomOrder(events) {
  const counts = {};
  for (const event of events) {
    const room = event.room || "TBD";
    counts[room] = (counts[room] || 0) + 1;
  }
  return Object.keys(counts).sort((a, b) => {
    const countDiff = counts[b] - counts[a];
    if (countDiff !== 0) return countDiff;
    return a.localeCompare(b);
  });
}

function applyRoomOrderOverride(defaultRooms) {
  const override = state.layout.room_order_by_day[state.day] || [];
  const seen = new Set();
  const ordered = [];
  for (const room of override) {
    if (defaultRooms.includes(room) && !seen.has(room)) {
      ordered.push(room);
      seen.add(room);
    }
  }
  for (const room of defaultRooms) {
    if (!seen.has(room)) {
      ordered.push(room);
      seen.add(room);
    }
  }
  return ordered;
}

function intervalsOverlap(left, right) {
  return left.start_min < right.end_min && right.start_min < left.end_min;
}

function resolveRoomConflicts(events) {
  const resolved = [];
  const sorted = [...events].sort(
    (a, b) => a.start_min - b.start_min || a.end_min - b.end_min
  );

  for (const event of sorted) {
    const conflicts = resolved.filter((existing) =>
      intervalsOverlap(event, existing)
    );
    if (conflicts.length === 0) {
      resolved.push(event);
      continue;
    }
    const duration = event.end_min - event.start_min;
    const longerThanAll = conflicts.every(
      (existing) => duration > (existing.end_min - existing.start_min)
    );
    if (longerThanAll) {
      conflicts.forEach((conflict) => {
        const idx = resolved.indexOf(conflict);
        if (idx >= 0) resolved.splice(idx, 1);
      });
      resolved.push(event);
    }
  }
  return resolved;
}

function assignMiscLanes(events) {
  const sorted = [...events].sort(
    (a, b) => a.start_min - b.start_min || a.end_min - b.end_min
  );
  const lanes = [];
  for (const event of sorted) {
    let placed = false;
    for (const lane of lanes) {
      const last = lane[lane.length - 1];
      if (event.start_min >= last.end_min) {
        lane.push(event);
        placed = true;
        break;
      }
    }
    if (!placed) {
      lanes.push([event]);
    }
  }
  return lanes;
}

function buildMatrix(events) {
  if (!events.length) {
    return null;
  }
  events.forEach((event) => {
    delete event._misc_source_room;
  });
  const miscSet = getMiscSet();
  const normalEvents = events.filter(
    (event) => !miscSet.has(event.room || "TBD")
  );
  const defaultRooms = defaultRoomOrder(normalEvents);
  const normalRooms = applyRoomOrderOverride(defaultRooms);
  state.roomOrder = normalRooms;

  const eventsByRoom = {};
  const miscByRoom = {};
  for (const room of normalRooms) {
    eventsByRoom[room] = [];
  }
  for (const event of events) {
    const room = event.room || "TBD";
    if (miscSet.has(room)) {
      if (!miscByRoom[room]) {
        miscByRoom[room] = [];
      }
      miscByRoom[room].push(event);
    } else {
      if (!eventsByRoom[room]) {
        eventsByRoom[room] = [];
        normalRooms.push(room);
      }
      eventsByRoom[room].push(event);
    }
  }

  for (const room of normalRooms) {
    eventsByRoom[room] = resolveRoomConflicts(eventsByRoom[room]);
  }

  const miscEvents = [];
  Object.keys(miscByRoom).forEach((room) => {
    const resolved = resolveRoomConflicts(miscByRoom[room]);
    resolved.forEach((event) => {
      event._misc_source_room = room;
      miscEvents.push(event);
    });
  });

  const miscLanes = assignMiscLanes(miscEvents);
  const miscColumns = [];
  miscLanes.forEach((lane, idx) => {
    const label = idx === 0 ? "Misc" : `Misc ${idx + 1}`;
    miscColumns.push(label);
    eventsByRoom[label] = lane;
  });

  const rooms = [...normalRooms, ...miscColumns];
  const allEvents = rooms.flatMap((room) => eventsByRoom[room] || []);
  const dayStart =
    Math.floor(Math.min(...allEvents.map((event) => event.start_min)) / slotMinutes) *
    slotMinutes;
  const dayEndRaw = Math.max(...allEvents.map((event) => event.end_min));
  const dayEnd = Math.ceil(dayEndRaw / slotMinutes) * slotMinutes;
  const timeSlots = [];
  for (let m = dayStart; m < dayEnd; m += slotMinutes) {
    timeSlots.push(m);
  }

  const roomStarts = {};
  const roomSkips = {};
  for (const room of rooms) {
    roomStarts[room] = {};
    roomSkips[room] = new Set();
    for (const event of eventsByRoom[room] || []) {
      const duration = Math.max(1, event.end_min - event.start_min);
      const rowSpan = Math.max(1, Math.ceil(duration / slotMinutes));
      event._rowspan = rowSpan;
      const start = event.start_min;
      roomStarts[room][start] = event;
      for (let offset = 1; offset < rowSpan; offset++) {
        roomSkips[room].add(start + offset * slotMinutes);
      }
    }
  }

  return {
    rooms,
    normalRooms,
    miscColumns,
    timeSlots,
    roomStarts,
    roomSkips,
  };
}

function renderHiddenList(hiddenSet) {
  elements.hiddenList.innerHTML = "";
  const hiddenIds = Array.from(hiddenSet);
  if (!hiddenIds.length) {
    const item = document.createElement("li");
    item.textContent = "No hidden items yet.";
    elements.hiddenList.appendChild(item);
    return;
  }
  const byId = {};
  for (const event of state.eventsAll) {
    byId[event.id] = event;
  }
  for (const id of hiddenIds) {
    const event = byId[id];
    const li = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = event
      ? `${truncateText(event.title, getTitleMaxLength())} (${event.room || "TBD"})`
      : `Event ${id}`;
    const button = document.createElement("button");
    button.textContent = "Restore";
    button.addEventListener("click", () => {
      hiddenSet.delete(id);
      setHiddenSet(hiddenSet);
      render();
    });
    li.appendChild(label);
    li.appendChild(button);
    elements.hiddenList.appendChild(li);
  }
}

function render() {
  const hiddenSet = getHiddenSet();
  const events = state.eventsAll.filter(
    (event) => !hiddenSet.has(event.id)
  );
  const matrix = buildMatrix(events);
  elements.tableContainer.innerHTML = "";

  if (!matrix) {
    elements.tableContainer.textContent = "No events available.";
    renderHiddenList(hiddenSet);
    return;
  }

  const display = getDisplayOptions();
  const titleMaxLength = getTitleMaxLength();

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const timeHeader = document.createElement("th");
  timeHeader.textContent = "Time";
  timeHeader.className = "time-col";
  headRow.appendChild(timeHeader);

  matrix.normalRooms.forEach((room) => {
    const th = document.createElement("th");
    const wrapper = document.createElement("div");
    wrapper.className = "room-header";

    const label = document.createElement("span");
    label.textContent = room;
    wrapper.appendChild(label);

    const miscButton = document.createElement("button");
    miscButton.textContent = "To misc";
    miscButton.className = "mini";
    miscButton.addEventListener("click", () => {
      const miscSet = getMiscSet();
      miscSet.add(room);
      setMiscSet(miscSet);
      render();
    });
    wrapper.appendChild(miscButton);

    th.appendChild(wrapper);
    th.setAttribute("draggable", "true");
    th.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", room);
      th.classList.add("dragging");
    });
    th.addEventListener("dragend", () => {
      th.classList.remove("dragging");
    });
    th.addEventListener("dragover", (event) => {
      event.preventDefault();
    });
    th.addEventListener("drop", (event) => {
      event.preventDefault();
      const from = event.dataTransfer.getData("text/plain");
      const to = room;
      reorderRooms(from, to);
    });
    headRow.appendChild(th);
  });

  matrix.miscColumns.forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    th.className = "misc-header";
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  matrix.timeSlots.forEach((slot) => {
    const row = document.createElement("tr");
    const timeCell = document.createElement("td");
    timeCell.textContent = minutesToLabel(slot);
    timeCell.className = "time-col";
    row.appendChild(timeCell);

    matrix.rooms.forEach((room) => {
      if (matrix.roomSkips[room].has(slot)) {
        return;
      }
      const startEvent = matrix.roomStarts[room][slot];
      if (startEvent) {
        const cell = document.createElement("td");
        cell.className = "event-cell";
        cell.setAttribute("rowspan", startEvent._rowspan);
        const miscRoom = startEvent._misc_source_room;

        const rawTitle = startEvent.title || "(Untitled)";
        const title = document.createElement("div");
        title.className = "event-title";
        title.textContent = truncateText(rawTitle, titleMaxLength);
        cell.appendChild(title);

        const details = [];
        if (
          display.show_session &&
          startEvent.session &&
          startEvent.session !== rawTitle
        ) {
          details.push(truncateText(startEvent.session, titleMaxLength));
        }
        if (
          display.show_talk_title &&
          startEvent.talk_title &&
          startEvent.talk_title !== rawTitle &&
          !details.includes(startEvent.talk_title)
        ) {
          details.push(truncateText(startEvent.talk_title, titleMaxLength));
        }
        if (display.show_time) {
          details.push(`${startEvent.start_time} - ${startEvent.end_time}`);
        }
        details.forEach((detail) => {
          const detailEl = document.createElement("div");
          detailEl.className = "event-detail";
          detailEl.textContent = detail;
          cell.appendChild(detailEl);
        });

        if (miscRoom && display.show_room) {
          const roomTag = document.createElement("div");
          roomTag.className = "event-room";
          roomTag.textContent = `Room: ${miscRoom}`;
          cell.appendChild(roomTag);
        }

        const actions = document.createElement("div");
        actions.className = "event-actions";
        const hideButton = document.createElement("button");
        hideButton.textContent = "Hide";
        hideButton.addEventListener("click", () => {
          hiddenSet.add(startEvent.id);
          setHiddenSet(hiddenSet);
          render();
        });
        actions.appendChild(hideButton);
        if (miscRoom) {
          const restoreButton = document.createElement("button");
          restoreButton.textContent = "Restore room";
          restoreButton.addEventListener("click", () => {
            const miscSet = getMiscSet();
            miscSet.delete(miscRoom);
            setMiscSet(miscSet);
            render();
          });
          actions.appendChild(restoreButton);
        }
        cell.appendChild(actions);

        row.appendChild(cell);
      } else {
        const cell = document.createElement("td");
        cell.className = "empty";
        row.appendChild(cell);
      }
    });
    tbody.appendChild(row);
  });
  table.appendChild(tbody);
  elements.tableContainer.appendChild(table);
  renderHiddenList(hiddenSet);
}

function reorderRooms(from, to) {
  const order = [...state.roomOrder];
  const fromIndex = order.indexOf(from);
  const toIndex = order.indexOf(to);
  if (fromIndex === -1 || toIndex === -1) return;
  order.splice(fromIndex, 1);
  order.splice(toIndex, 0, from);
  state.layout.room_order_by_day[state.day] = order;
  render();
}

async function saveLayout() {
  setStatus("Saving...");
  const response = await fetch("/api/layout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.layout),
  });
  if (response.ok) {
    setStatus("Saved");
  } else {
    setStatus("Save failed");
  }
}

function resetDay() {
  delete state.layout.room_order_by_day[state.day];
  delete state.layout.hidden_event_ids_by_day[state.day];
  delete state.layout.misc_rooms_by_day[state.day];
  render();
  setStatus("Reset day");
}

async function loadDay(day) {
  state.day = day;
  const response = await fetch(
    `/api/events?day=${encodeURIComponent(day)}`
  );
  const payload = await response.json();
  state.eventsAll = payload.events || [];
  render();
}

async function init() {
  setStatus("Loading...");
  const [daysResponse, layoutResponse] = await Promise.all([
    fetch("/api/days"),
    fetch("/api/layout"),
  ]);
  const daysPayload = await daysResponse.json();
  const layoutPayload = await layoutResponse.json();
  state.layout = normalizeLayout(layoutPayload);
  syncDisplayControls();

  elements.daySelect.innerHTML = "";
  daysPayload.days.forEach((day) => {
    const option = document.createElement("option");
    option.value = day;
    option.textContent = day;
    elements.daySelect.appendChild(option);
  });

  const initialDay = daysPayload.days[0] || "";
  if (initialDay) {
    elements.daySelect.value = initialDay;
    await loadDay(initialDay);
  } else {
    setStatus("No days found");
  }
  setStatus("");
}

function setupDisplayControls() {
  elements.showSession.addEventListener("change", (event) => {
    setDisplayOption("show_session", event.target.checked);
    render();
  });
  elements.showTalkTitle.addEventListener("change", (event) => {
    setDisplayOption("show_talk_title", event.target.checked);
    render();
  });
  elements.showTime.addEventListener("change", (event) => {
    setDisplayOption("show_time", event.target.checked);
    render();
  });
  elements.showRoom.addEventListener("change", (event) => {
    setDisplayOption("show_room", event.target.checked);
    render();
  });
  elements.titleMaxLength.addEventListener("change", (event) => {
    const raw = event.target.value.trim();
    const parsed = raw === "" ? DEFAULT_TITLE_MAX_LENGTH : Number(raw);
    if (!Number.isFinite(parsed)) {
      event.target.value = getTitleMaxLength();
      return;
    }
    setTitleMaxLength(parsed);
    event.target.value = getTitleMaxLength();
    render();
  });
}

elements.daySelect.addEventListener("change", (event) => {
  loadDay(event.target.value);
});
elements.saveBtn.addEventListener("click", saveLayout);
elements.resetBtn.addEventListener("click", resetDay);
setupDisplayControls();

init();
