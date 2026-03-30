const state = {
  runId: null,
  pipeline: null,
  runs: [],
  nodes: {},
  events: [],
  selectedNodeId: null,
  selectedArtifact: "output.txt",
  artifactCache: new Map(),
  eventSource: null,
  validationPipeline: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function setBanner(message, kind = "success") {
  const banner = document.getElementById("banner");
  if (!message) {
    banner.className = "banner hidden";
    banner.textContent = "";
    return;
  }
  banner.className = `banner ${kind}`;
  banner.textContent = message;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatDuration(run) {
  if (!run?.started_at || !run?.finished_at) return "-";
  return `${Math.max(0, Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000))}s`;
}

function currentRun() {
  return state.runs.find((run) => run.id === state.runId) || null;
}

function topoLevels(nodes) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const indegree = Object.fromEntries(nodes.map((node) => [node.id, 0]));
  const outgoing = Object.fromEntries(nodes.map((node) => [node.id, []]));
  const levels = {};

  nodes.forEach((node) => {
    for (const dependency of node.depends_on || []) {
      if (!nodeIds.has(dependency)) continue;
      indegree[node.id] += 1;
      outgoing[dependency].push(node.id);
    }
  });

  const queue = nodes.filter((node) => indegree[node.id] === 0).map((node) => node.id);
  while (queue.length) {
    const id = queue.shift();
    levels[id] = levels[id] ?? 0;
    for (const next of outgoing[id]) {
      levels[next] = Math.max(levels[next] ?? 0, levels[id] + 1);
      indegree[next] -= 1;
      if (indegree[next] === 0) queue.push(next);
    }
  }

  nodes.forEach((node) => {
    if (levels[node.id] !== undefined) return;
    const dependencyLevels = (node.depends_on || []).map((dependency) => levels[dependency] ?? 0);
    levels[node.id] = dependencyLevels.length ? Math.max(...dependencyLevels) + 1 : 0;
  });

  return levels;
}

const graphViewState = {
  cleanup: null,
  layoutSignature: null,
  positions: {},
  zoom: 1,
};

const GRAPH_STATUS_COLORS = {
  pending: "#8b949e",
  queued: "#8b949e",
  skipped: "#8b949e",
  running: "#d29922",
  retrying: "#d29922",
  completed: "#3fb950",
  failed: "#f85149",
  cancelled: "#f85149",
};

function graphLayoutSignature(nodes) {
  return JSON.stringify(nodes.map((node) => ({
    id: node.id,
    depends_on: node.depends_on || [],
    on_failure_restart: node.on_failure_restart || [],
  })));
}

function graphStatusColor(status) {
  return GRAPH_STATUS_COLORS[status] || GRAPH_STATUS_COLORS.pending;
}

function truncateGraphLabel(value, maxLength) {
  const text = String(value ?? "");
  return text.length > maxLength ? `${text.slice(0, Math.max(0, maxLength - 3))}...` : text;
}

function graphLayout(nodes) {
  const levels = topoLevels(nodes);
  const groups = {};
  let maxLevel = 0;

  nodes.forEach((node) => {
    const level = levels[node.id] || 0;
    groups[level] ||= [];
    groups[level].push(node);
    maxLevel = Math.max(maxLevel, level);
  });

  const nodeWidth = 220;
  const nodeHeight = 104;
  const levelGap = 156;
  const rowGap = 56;
  const margin = { top: 48, right: 72, bottom: 48, left: 48 };
  const maxGroupSize = Math.max(1, ...Object.values(groups).map((group) => group.length));
  const sceneWidth = Math.max(860, margin.left + (maxLevel + 1) * nodeWidth + maxLevel * levelGap + margin.right);
  const sceneHeight = Math.max(560, margin.top + maxGroupSize * nodeHeight + Math.max(0, maxGroupSize - 1) * rowGap + margin.bottom);
  const positions = {};

  Object.entries(groups).forEach(([levelText, group]) => {
    const level = Number(levelText);
    const columnHeight = group.length * nodeHeight + Math.max(0, group.length - 1) * rowGap;
    const startY = margin.top + Math.max(0, (sceneHeight - margin.top - margin.bottom - columnHeight) / 2);
    group.forEach((node, index) => {
      positions[node.id] = {
        x: margin.left + level * (nodeWidth + levelGap),
        y: startY + index * (nodeHeight + rowGap),
      };
    });
  });

  return { nodeWidth, nodeHeight, sceneWidth, sceneHeight, positions };
}

function updateTopMetrics() {
  document.getElementById("metric-total").textContent = state.runs.length;
  document.getElementById("metric-queued").textContent = state.runs.filter((run) => run.status === "queued").length;
  document.getElementById("metric-running").textContent = state.runs.filter((run) => ["running", "cancelling"].includes(run.status)).length;
}

function filteredRuns() {
  const query = document.getElementById("run-search").value.trim().toLowerCase();
  if (!query) return state.runs;
  return state.runs.filter((run) =>
    run.id.toLowerCase().includes(query) ||
    run.pipeline.name.toLowerCase().includes(query) ||
    run.status.toLowerCase().includes(query)
  );
}

function renderRuns() {
  const container = document.getElementById("runs");
  const runs = filteredRuns();
  if (!runs.length) {
    container.innerHTML = '<div class="small">No runs yet.</div>';
    return;
  }
  container.innerHTML = runs.map((run) => `
    <div class="run-item ${run.id === state.runId ? "active" : ""}">
      <h3>${escapeHtml(run.pipeline.name)}</h3>
      <div class="small mono">${run.id}</div>
      <div class="small">Status: ${escapeHtml(run.status)} · Started: ${escapeHtml(formatDate(run.started_at || run.created_at))}</div>
      <div class="small">Duration: ${escapeHtml(formatDuration(run))}</div>
      <div class="button-row" style="margin-top:0.65rem">
        <button data-open-run="${run.id}">Open</button>
      </div>
    </div>
  `).join("");

  container.querySelectorAll("button[data-open-run]").forEach((button) => {
    button.onclick = async () => {
      await openRun(button.dataset.openRun);
    };
  });
}

function renderGraph(pipelineNodes = null, nodeStatusMap = null) {
  const container = document.getElementById("graph");
  if (graphViewState.cleanup) {
    graphViewState.cleanup();
    graphViewState.cleanup = null;
  }

  container.style.padding = "0";
  container.innerHTML = "";

  const pipeline = state.pipeline || state.validationPipeline;
  const nodes = pipelineNodes || pipeline?.nodes || [];
  const nodeMap = nodeStatusMap || state.nodes;
  if (!nodes.length) {
    container.innerHTML = '<p class="small" style="padding:1rem">Validate or run a pipeline to render the DAG.</p>';
    return;
  }

  const layout = graphLayout(nodes);
  const signature = graphLayoutSignature(nodes);
  if (graphViewState.layoutSignature !== signature) {
    graphViewState.layoutSignature = signature;
    graphViewState.positions = {};
    graphViewState.zoom = 1;
    container.scrollLeft = 0;
    container.scrollTop = 0;
  }

  nodes.forEach((node) => {
    graphViewState.positions[node.id] ||= { ...layout.positions[node.id] };
  });
  Object.keys(graphViewState.positions).forEach((nodeId) => {
    if (!nodes.some((node) => node.id === nodeId)) delete graphViewState.positions[nodeId];
  });

  const ns = "http://www.w3.org/2000/svg";
  const rootStyles = getComputedStyle(document.documentElement);
  const primaryColor = rootStyles.getPropertyValue("--primary").trim() || "#38bdf8";
  const borderColor = rootStyles.getPropertyValue("--border").trim() || "#334155";
  const panelColor = rootStyles.getPropertyValue("--panel").trim() || "#111827";
  const textColor = rootStyles.getPropertyValue("--text").trim() || "#e5e7eb";
  const mutedColor = rootStyles.getPropertyValue("--muted").trim() || "#94a3b8";
  const badgeFill = "rgba(56, 189, 248, 0.14)";
  const badgeStroke = "rgba(56, 189, 248, 0.45)";
  const svg = document.createElementNS(ns, "svg");

  svg.setAttribute("viewBox", `0 0 ${layout.sceneWidth} ${layout.sceneHeight}`);
  svg.setAttribute("width", String(layout.sceneWidth * graphViewState.zoom));
  svg.setAttribute("height", String(layout.sceneHeight * graphViewState.zoom));
  svg.style.display = "block";
  svg.style.userSelect = "none";
  svg.style.webkitUserSelect = "none";
  svg.style.touchAction = "none";
  container.appendChild(svg);

  const defs = document.createElementNS(ns, "defs");
  const createMarker = (id, color) => {
    const marker = document.createElementNS(ns, "marker");
    marker.setAttribute("id", id);
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", "9");
    marker.setAttribute("refY", "5");
    marker.setAttribute("markerWidth", "8");
    marker.setAttribute("markerHeight", "8");
    marker.setAttribute("markerUnits", "strokeWidth");
    marker.setAttribute("orient", "auto");
    const arrow = document.createElementNS(ns, "path");
    arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
    arrow.setAttribute("fill", color);
    marker.appendChild(arrow);
    return marker;
  };
  defs.appendChild(createMarker("graph-arrow", borderColor));
  defs.appendChild(createMarker("graph-arrow-cycle", "#f85149"));
  svg.appendChild(defs);

  const background = document.createElementNS(ns, "rect");
  background.setAttribute("x", "0");
  background.setAttribute("y", "0");
  background.setAttribute("width", String(layout.sceneWidth));
  background.setAttribute("height", String(layout.sceneHeight));
  background.setAttribute("fill", "transparent");
  svg.appendChild(background);

  const edgesLayer = document.createElementNS(ns, "g");
  const nodesLayer = document.createElementNS(ns, "g");
  svg.appendChild(edgesLayer);
  svg.appendChild(nodesLayer);

  const nodeRefs = {};
  const edgeRefs = [];

  function scenePoint(event) {
    const rect = svg.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * layout.sceneWidth,
      y: ((event.clientY - rect.top) / rect.height) * layout.sceneHeight,
    };
  }

  function nodeBounds(nodeId) {
    const position = graphViewState.positions[nodeId] || layout.positions[nodeId];
    return {
      x: position.x,
      y: position.y,
      width: layout.nodeWidth,
      height: layout.nodeHeight,
    };
  }

  function forwardPath(fromId, toId) {
    const from = nodeBounds(fromId);
    const to = nodeBounds(toId);
    const startX = from.x + from.width;
    const startY = from.y + from.height / 2;
    const endX = to.x;
    const endY = to.y + to.height / 2;
    const direction = endX >= startX ? 1 : -1;
    const curve = Math.max(52, Math.abs(endX - startX) * 0.45);
    return `M ${startX} ${startY} C ${startX + direction * curve} ${startY}, ${endX - direction * curve} ${endY}, ${endX} ${endY}`;
  }

  function cyclePath(fromId, toId) {
    const from = nodeBounds(fromId);
    const to = nodeBounds(toId);
    const startX = from.x;
    const startY = from.y + from.height / 2;
    const endX = to.x + to.width;
    const endY = to.y + to.height / 2;
    const horizontalLift = Math.max(92, Math.abs(startX - endX) * 0.3);
    const verticalLift = Math.max(96, Math.abs(startY - endY) * 0.45 + 36);
    const controlY = Math.min(startY, endY) - verticalLift;
    return `M ${startX} ${startY} C ${startX - horizontalLift} ${controlY}, ${endX + horizontalLift} ${controlY}, ${endX} ${endY}`;
  }

  function updateNodePosition(nodeId) {
    const ref = nodeRefs[nodeId];
    const position = graphViewState.positions[nodeId];
    if (!ref || !position) return;
    ref.setAttribute("transform", `translate(${position.x} ${position.y})`);
  }

  function updateEdges(changedNodeId = null) {
    edgeRefs.forEach((edge) => {
      if (changedNodeId && edge.fromId !== changedNodeId && edge.toId !== changedNodeId) return;
      edge.path.setAttribute("d", edge.kind === "cycle" ? cyclePath(edge.fromId, edge.toId) : forwardPath(edge.fromId, edge.toId));
    });
  }

  function findNodeGroup(target) {
    let current = target;
    while (current && current !== svg) {
      if (current.dataset?.nodeId) return current;
      current = current.parentNode;
    }
    return null;
  }

  nodes.forEach((node) => {
    for (const dependency of node.depends_on || []) {
      if (!graphViewState.positions[dependency] || !graphViewState.positions[node.id]) continue;
      const edge = document.createElementNS(ns, "path");
      edge.setAttribute("fill", "none");
      edge.setAttribute("stroke", borderColor);
      edge.setAttribute("stroke-width", "2");
      edge.setAttribute("stroke-linecap", "round");
      edge.setAttribute("stroke-linejoin", "round");
      edge.setAttribute("marker-end", "url(#graph-arrow)");
      edgesLayer.appendChild(edge);
      edgeRefs.push({ fromId: dependency, toId: node.id, kind: "dependency", path: edge });
    }
  });

  nodes.forEach((node) => {
    for (const restartTarget of node.on_failure_restart || []) {
      if (!graphViewState.positions[restartTarget] || !graphViewState.positions[node.id]) continue;
      const edge = document.createElementNS(ns, "path");
      edge.setAttribute("fill", "none");
      edge.setAttribute("stroke", "#f85149");
      edge.setAttribute("stroke-width", "2");
      edge.setAttribute("stroke-dasharray", "8 6");
      edge.setAttribute("stroke-linecap", "round");
      edge.setAttribute("stroke-linejoin", "round");
      edge.setAttribute("marker-end", "url(#graph-arrow-cycle)");
      edgesLayer.appendChild(edge);
      edgeRefs.push({ fromId: node.id, toId: restartTarget, kind: "cycle", path: edge });
    }
  });

  updateEdges();

  let dragState = null;
  let suppressClick = false;

  nodes.forEach((node) => {
    const result = nodeMap[node.id] || { status: "pending" };
    const status = result.status || "pending";
    const statusColor = graphStatusColor(status);
    const badgeLabel = truncateGraphLabel(node.agent || "agent", 14);
    const badgeWidth = Math.max(64, badgeLabel.length * 7 + 24);
    const group = document.createElementNS(ns, "g");
    group.dataset.nodeId = node.id;
    group.style.cursor = "grab";

    const selection = document.createElementNS(ns, "rect");
    selection.setAttribute("x", "-4");
    selection.setAttribute("y", "-4");
    selection.setAttribute("width", String(layout.nodeWidth + 8));
    selection.setAttribute("height", String(layout.nodeHeight + 8));
    selection.setAttribute("rx", "20");
    selection.setAttribute("fill", "none");
    selection.setAttribute("stroke", primaryColor);
    selection.setAttribute("stroke-width", "2.5");
    selection.setAttribute("opacity", state.selectedNodeId === node.id ? "1" : "0");
    group.appendChild(selection);

    const card = document.createElementNS(ns, "rect");
    card.setAttribute("x", "0");
    card.setAttribute("y", "0");
    card.setAttribute("width", String(layout.nodeWidth));
    card.setAttribute("height", String(layout.nodeHeight));
    card.setAttribute("rx", "16");
    card.setAttribute("fill", panelColor);
    card.setAttribute("fill-opacity", "0.94");
    card.setAttribute("stroke", statusColor);
    card.setAttribute("stroke-width", "2.5");
    group.appendChild(card);

    const title = document.createElementNS(ns, "text");
    title.setAttribute("x", "16");
    title.setAttribute("y", "32");
    title.setAttribute("fill", textColor);
    title.setAttribute("font-size", "14");
    title.setAttribute("font-weight", "600");
    title.setAttribute("font-family", "Inter, ui-sans-serif, system-ui, sans-serif");
    title.textContent = truncateGraphLabel(node.id, 24);
    group.appendChild(title);

    const statusText = document.createElementNS(ns, "text");
    statusText.setAttribute("x", String(layout.nodeWidth - 16));
    statusText.setAttribute("y", "32");
    statusText.setAttribute("fill", statusColor);
    statusText.setAttribute("font-size", "11");
    statusText.setAttribute("font-weight", "700");
    statusText.setAttribute("text-anchor", "end");
    statusText.setAttribute("font-family", "Inter, ui-sans-serif, system-ui, sans-serif");
    statusText.textContent = truncateGraphLabel(status.toUpperCase(), 12);
    group.appendChild(statusText);

    const subtitle = document.createElementNS(ns, "text");
    subtitle.setAttribute("x", "16");
    subtitle.setAttribute("y", "58");
    subtitle.setAttribute("fill", mutedColor);
    subtitle.setAttribute("font-size", "11");
    subtitle.setAttribute("font-family", "Inter, ui-sans-serif, system-ui, sans-serif");
    subtitle.textContent = `Attempts ${(result.current_attempt || 0)}/${(node.retries || 0) + 1}`;
    group.appendChild(subtitle);

    const badge = document.createElementNS(ns, "rect");
    badge.setAttribute("x", "16");
    badge.setAttribute("y", "72");
    badge.setAttribute("width", String(badgeWidth));
    badge.setAttribute("height", "22");
    badge.setAttribute("rx", "11");
    badge.setAttribute("fill", badgeFill);
    badge.setAttribute("stroke", badgeStroke);
    badge.setAttribute("stroke-width", "1");
    group.appendChild(badge);

    const badgeText = document.createElementNS(ns, "text");
    badgeText.setAttribute("x", String(16 + badgeWidth / 2));
    badgeText.setAttribute("y", "87");
    badgeText.setAttribute("fill", primaryColor);
    badgeText.setAttribute("font-size", "11");
    badgeText.setAttribute("font-weight", "600");
    badgeText.setAttribute("text-anchor", "middle");
    badgeText.setAttribute("font-family", "Inter, ui-sans-serif, system-ui, sans-serif");
    badgeText.textContent = badgeLabel;
    group.appendChild(badgeText);

    nodeRefs[node.id] = group;
    updateNodePosition(node.id);

    group.addEventListener("click", () => {
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      state.selectedNodeId = node.id;
      renderGraph();
      renderDetail();
    });

    nodesLayer.appendChild(group);
  });

  function stopDragging() {
    if (!dragState) return;
    svg.style.cursor = "default";
    if (nodeRefs[dragState.nodeId]) nodeRefs[dragState.nodeId].style.cursor = "grab";
    suppressClick = dragState.moved;
    if (dragState.moved) {
      window.setTimeout(() => {
        suppressClick = false;
      }, 0);
    }
    dragState = null;
  }

  function handleMouseDown(event) {
    if (event.button !== 0) return;
    const nodeGroup = findNodeGroup(event.target);
    if (!nodeGroup) return;
    const nodeId = nodeGroup.dataset.nodeId;
    if (!graphViewState.positions[nodeId]) return;
    const point = scenePoint(event);
    nodesLayer.appendChild(nodeGroup);
    dragState = {
      nodeId,
      startX: point.x,
      startY: point.y,
      originX: graphViewState.positions[nodeId].x,
      originY: graphViewState.positions[nodeId].y,
      moved: false,
    };
    svg.style.cursor = "grabbing";
    nodeGroup.style.cursor = "grabbing";
    event.preventDefault();
  }

  function handleMouseMove(event) {
    if (!dragState) return;
    const point = scenePoint(event);
    const dx = point.x - dragState.startX;
    const dy = point.y - dragState.startY;
    dragState.moved ||= Math.abs(dx) > 2 || Math.abs(dy) > 2;
    graphViewState.positions[dragState.nodeId] = {
      x: Math.max(24, Math.min(layout.sceneWidth - layout.nodeWidth - 24, dragState.originX + dx)),
      y: Math.max(24, Math.min(layout.sceneHeight - layout.nodeHeight - 24, dragState.originY + dy)),
    };
    updateNodePosition(dragState.nodeId);
    updateEdges(dragState.nodeId);
  }

  function handleMouseUp() {
    stopDragging();
  }

  function handleWheel(event) {
    event.preventDefault();
    const nextZoom = Math.max(0.6, Math.min(2.4, graphViewState.zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12)));
    if (nextZoom === graphViewState.zoom) return;
    const containerRect = container.getBoundingClientRect();
    const offsetX = event.clientX - containerRect.left + container.scrollLeft;
    const offsetY = event.clientY - containerRect.top + container.scrollTop;
    const logicalX = offsetX / graphViewState.zoom;
    const logicalY = offsetY / graphViewState.zoom;
    graphViewState.zoom = nextZoom;
    svg.setAttribute("width", String(layout.sceneWidth * graphViewState.zoom));
    svg.setAttribute("height", String(layout.sceneHeight * graphViewState.zoom));
    container.scrollLeft = Math.max(0, logicalX * graphViewState.zoom - (event.clientX - containerRect.left));
    container.scrollTop = Math.max(0, logicalY * graphViewState.zoom - (event.clientY - containerRect.top));
  }

  svg.addEventListener("mousedown", handleMouseDown);
  svg.addEventListener("wheel", handleWheel, { passive: false });
  window.addEventListener("mousemove", handleMouseMove);
  window.addEventListener("mouseup", handleMouseUp);

  graphViewState.cleanup = () => {
    svg.removeEventListener("mousedown", handleMouseDown);
    svg.removeEventListener("wheel", handleWheel);
    window.removeEventListener("mousemove", handleMouseMove);
    window.removeEventListener("mouseup", handleMouseUp);
  };
}

function renderRunMeta() {
  const run = currentRun();
  document.getElementById("run-status").textContent = run?.status || "idle";
  document.getElementById("run-meta").textContent = run
    ? `${run.pipeline.name} · created ${formatDate(run.created_at)} · duration ${formatDuration(run)}`
    : state.validationPipeline
      ? `Validated DAG: ${state.validationPipeline.name}`
      : "No run selected";
}

function upsertAttempt(nodeState, attemptNumber, patch) {
  if (!attemptNumber) return;
  nodeState.attempts ||= [];
  let attempt = nodeState.attempts.find((item) => item.number === attemptNumber);
  if (!attempt) {
    attempt = { number: attemptNumber };
    nodeState.attempts.push(attempt);
    nodeState.attempts.sort((left, right) => left.number - right.number);
  }
  Object.assign(attempt, patch);
}

async function fetchArtifact(nodeId, name) {
  if (!state.runId || !nodeId) return "";
  const cacheKey = `${state.runId}:${nodeId}:${name}`;
  if (state.artifactCache.has(cacheKey)) return state.artifactCache.get(cacheKey);
  const content = await api(`/api/runs/${state.runId}/artifacts/${nodeId}/${name}`);
  state.artifactCache.set(cacheKey, content);
  return content;
}

async function renderDetail() {
  const detail = document.getElementById("detail");
  const selected = state.selectedNodeId && state.nodes[state.selectedNodeId];
  document.getElementById("selected-node").textContent = state.selectedNodeId || "None selected";
  if (!selected || !state.selectedNodeId) {
    detail.innerHTML = '<p class="small">Select a node to inspect its output, attempts, artifacts, and parsed timeline.</p>';
    return;
  }

  let artifactText = "";
  try {
    artifactText = await fetchArtifact(state.selectedNodeId, state.selectedArtifact);
  } catch {
    artifactText = selected.output || "";
  }

  const attemptRows = (selected.attempts || []).map((attempt) => `
    <div class="summary-card">
      <div><strong>Attempt ${attempt.number}</strong></div>
      <div class="small">Status: ${escapeHtml(attempt.status)} · Exit: ${escapeHtml(String(attempt.exit_code ?? "-"))}</div>
      <div class="small">Started: ${escapeHtml(formatDate(attempt.started_at))}</div>
      <div class="small">Finished: ${escapeHtml(formatDate(attempt.finished_at))}</div>
    </div>
  `).join("");

  const events = state.events.filter((event) => event.node_id === state.selectedNodeId).slice(-25).reverse();
  detail.innerHTML = `
    <div class="summary-grid">
      <div class="summary-card"><div class="small">Status</div><strong>${escapeHtml(selected.status || "pending")}</strong></div>
      <div class="summary-card"><div class="small">Current attempt</div><strong>${escapeHtml(String(selected.current_attempt || 0))}</strong></div>
      <div class="summary-card"><div class="small">Exit code</div><strong>${escapeHtml(String(selected.exit_code ?? "-"))}</strong></div>
      <div class="summary-card"><div class="small">Success</div><strong>${escapeHtml(String(selected.success ?? "-"))}</strong></div>
    </div>
    <div class="trace-item">
      <h4>Attempts</h4>
      <div class="summary-grid">${attemptRows || '<div class="small">No attempts yet.</div>'}</div>
    </div>
    <div class="trace-item">
      <h4>Artifact: ${escapeHtml(state.selectedArtifact)}</h4>
      <div class="output-box">${escapeHtml(artifactText)}</div>
    </div>
    <div class="trace-item">
      <h4>Success checks</h4>
      <div class="output-box">${escapeHtml((selected.success_details || []).join("\n"))}</div>
    </div>
    <div class="trace-item">
      <h4>Recent events</h4>
      ${events.map((event) => `
        <div class="summary-card">
          <div><strong>${escapeHtml(event.type)}</strong></div>
          <div class="small">${escapeHtml(formatDate(event.timestamp))}</div>
          <div class="output-box">${escapeHtml(JSON.stringify(event.data || {}, null, 2))}</div>
        </div>
      `).join("") || '<div class="small">No node-specific events yet.</div>'}
    </div>
  `;
}

function applyEvent(event) {
  state.events.push(event);
  if (event.type === "run_queued") {
    const run = currentRun();
    if (run) run.status = "queued";
  }
  if (event.type === "run_started") {
    const run = currentRun();
    if (run) run.status = "running";
  }
  if (event.type === "run_cancelling") {
    const run = currentRun();
    if (run) run.status = "cancelling";
  }
  if (event.node_id && !state.nodes[event.node_id]) {
    state.nodes[event.node_id] = { node_id: event.node_id, trace_events: [], attempts: [], status: "pending", current_attempt: 0 };
  }
  if (event.type === "node_started" && event.node_id) {
    state.nodes[event.node_id].status = "running";
  }
  if (event.type === "node_retrying" && event.node_id) {
    state.nodes[event.node_id].status = "retrying";
    state.nodes[event.node_id].current_attempt = event.data.attempt || state.nodes[event.node_id].current_attempt;
    upsertAttempt(state.nodes[event.node_id], event.data.attempt, { status: "retrying" });
  }
  if (event.type === "node_trace" && event.node_id) {
    state.nodes[event.node_id].trace_events ||= [];
    state.nodes[event.node_id].trace_events.push(event.data.trace);
    const attempt = event.data.trace?.attempt;
    if (attempt) state.nodes[event.node_id].current_attempt = attempt;
  }
  if (["node_completed", "node_failed", "node_cancelled"].includes(event.type) && event.node_id) {
    const status = event.type === "node_completed" ? "completed" : event.type === "node_failed" ? "failed" : "cancelled";
    Object.assign(state.nodes[event.node_id], {
      status,
      exit_code: event.data.exit_code,
      success: event.data.success,
      output: event.data.output,
      final_response: event.data.final_response,
      success_details: event.data.success_details,
      current_attempt: event.data.attempt || state.nodes[event.node_id].current_attempt,
    });
    upsertAttempt(state.nodes[event.node_id], event.data.attempt, {
      status,
      exit_code: event.data.exit_code,
      output: event.data.output,
      success: event.data.success,
    });
  }
  if (event.type === "node_skipped" && event.node_id) {
    state.nodes[event.node_id].status = "skipped";
  }
  if (event.type === "run_completed") {
    const run = currentRun();
    if (run) run.status = event.data.status;
  }
  renderRunMeta();
  renderRuns();
  renderGraph();
  renderDetail();
}

function connectStream(runId) {
  if (state.eventSource) state.eventSource.close();
  state.eventSource = new EventSource(`/api/runs/${runId}/stream`);
  state.eventSource.onmessage = (message) => applyEvent(JSON.parse(message.data));
  state.eventSource.onerror = () => {
    if (state.eventSource) state.eventSource.close();
  };
}

async function refreshRuns() {
  state.runs = await api("/api/runs");
  updateTopMetrics();
  renderRuns();
  renderRunMeta();
}

async function openRun(runId) {
  const run = await api(`/api/runs/${runId}`);
  state.runId = run.id;
  state.pipeline = run.pipeline;
  state.nodes = run.nodes;
  state.selectedNodeId = state.selectedNodeId || state.pipeline.nodes?.[0]?.id || null;
  state.events = await api(`/api/runs/${runId}/events`);
  state.artifactCache.clear();
  renderRunMeta();
  renderRuns();
  renderGraph();
  await renderDetail();
  connectStream(run.id);
}

function pipelinePayload() {
  const pipelineText = document.getElementById("pipeline-input").value;
  const baseDir = document.getElementById("pipeline-base-dir").value.trim();
  return baseDir ? { pipeline_text: pipelineText, base_dir: baseDir } : { pipeline_text: pipelineText };
}

async function validatePipeline() {
  const response = await api("/api/runs/validate", { method: "POST", body: JSON.stringify(pipelinePayload()) });
  state.validationPipeline = response.pipeline;
  state.pipeline = null;
  state.nodes = {};
  state.runId = null;
  state.events = [];
  state.selectedNodeId = response.pipeline.nodes?.[0]?.id || null;
  renderRunMeta();
  renderGraph();
  await renderDetail();
  setBanner(`Pipeline validated: ${response.pipeline.name}`, "success");
}

async function runPipeline() {
  const run = await api("/api/runs", { method: "POST", body: JSON.stringify(pipelinePayload()) });
  state.validationPipeline = null;
  await refreshRuns();
  await openRun(run.id);
  setBanner(`Run queued: ${run.id}`, "success");
}

async function cancelRun() {
  if (!state.runId) return;
  await api(`/api/runs/${state.runId}/cancel`, { method: "POST" });
  setBanner(`Cancellation requested for ${state.runId}`, "success");
  await openRun(state.runId);
}

async function rerunRun() {
  if (!state.runId) return;
  const rerun = await api(`/api/runs/${state.runId}/rerun`, { method: "POST" });
  await refreshRuns();
  await openRun(rerun.id);
  setBanner(`Rerun queued: ${rerun.id}`, "success");
}

for (const button of document.querySelectorAll(".artifact-button")) {
  button.onclick = async () => {
    state.selectedArtifact = button.dataset.artifact;
    await renderDetail();
  };
}

document.getElementById("load-example").onclick = async () => {
  const data = await api("/api/examples/default");
  document.getElementById("pipeline-input").value = data.example;
  document.getElementById("pipeline-base-dir").value = data.base_dir || "";
  setBanner(null);
};

document.getElementById("validate-pipeline").onclick = () => validatePipeline().catch((error) => setBanner(error.message, "error"));
document.getElementById("run-pipeline").onclick = () => runPipeline().catch((error) => setBanner(error.message, "error"));
document.getElementById("cancel-run").onclick = () => cancelRun().catch((error) => setBanner(error.message, "error"));
document.getElementById("rerun-run").onclick = () => rerunRun().catch((error) => setBanner(error.message, "error"));
document.getElementById("refresh-runs").onclick = () => refreshRuns().catch((error) => setBanner(error.message, "error"));
document.getElementById("run-search").oninput = renderRuns;

refreshRuns()
  .then(async () => {
    if (state.runs[0]) await openRun(state.runs[0].id);
  })
  .catch((error) => setBanner(error.message, "error"));
