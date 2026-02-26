

(() => {
    "use strict";

    const API_BASE = window.location.origin;
    const POLL_INTERVAL = 2000;

    // ── DOM Refs ────────────────────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const dom = {
        connectionStatus: $("#connectionStatus"),
        routeCard: $("#routeCard"),
        routeIcon: $("#routeIcon"),
        routeLabel: $("#routeLabel"),
        routeReason: $("#routeReason"),
        pingValue: $("#pingValue"),
        pingBar: $("#pingBar"),
        batteryValue: $("#batteryValue"),
        batteryBar: $("#batteryBar"),
        batteryUnit: $("#batteryUnit"),
        ramValue: $("#ramValue"),
        ramBar: $("#ramBar"),
        // Sparklines (#5)
        pingSpark: $("#pingSpark"),
        batterySpark: $("#batterySpark"),
        ramSpark: $("#ramSpark"),
        // Cost (#4)
        costSaved: $("#costSaved"),
        edgePercent: $("#edgePercent"),
        totalRequests: $("#totalRequests"),
        projectedSavings: $("#projectedSavings"),
        // Latency chart (#2)
        latencyChart: $("#latencyChart"),
        // Route toggle (#1)
        toggleAuto: $("#toggleAuto"),
        toggleCloud: $("#toggleCloud"),
        toggleEdge: $("#toggleEdge"),
        // Chat
        chatContainer: $("#chatContainer"),
        chatInput: $("#chatInput"),
        sendTextBtn: $("#sendTextBtn"),
        // Vision
        dropzone: $("#dropzone"),
        imageInput: $("#imageInput"),
        browseBtn: $("#browseBtn"),
        cameraBtn: $("#cameraBtn"),
        visionUpload: $("#visionUpload"),
        visionResults: $("#visionResults"),
        previewImage: $("#previewImage"),
        detectionCanvas: $("#detectionCanvas"),
        detectionList: $("#detectionList"),
        detectionCount: $("#detectionCount"),
        newImageBtn: $("#newImageBtn"),
        cameraVideo: $("#cameraVideo"),
        // Tabs
        tabText: $("#tabText"),
        tabVision: $("#tabVision"),
        panelText: $("#panelText"),
        panelVision: $("#panelVision"),
        // Logs
        logList: $("#logList"),
        clearLogsBtn: $("#clearLogsBtn"),
        // Loading
        loadingOverlay: $("#loadingOverlay"),
        loadingText: $("#loadingText"),
        // Toasts
        toastContainer: $("#toastContainer"),
    };

    // ── State ───────────────────────────────────────────────────────────────
    let currentRoute = null;
    let isProcessing = false;
    let welcomeVisible = true;
    let pollTimer = null;
    let currentForceRoute = "auto";

    // Sparkline history buffers (#5) — last 20 readings
    const pingHistory = [];
    const batteryHistory = [];
    const ramHistory = [];
    const MAX_SPARKLINE_POINTS = 20;

    // ── Toast Notifications ─────────────────────────────────────────────────
    function showToast(message, type = "success", duration = 3000) {
        const toast = document.createElement("div");
        toast.className = `toast toast--${type}`;
        toast.innerHTML = message;
        dom.toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.classList.add("toast-out");
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // ── Force Route Override (#1) ───────────────────────────────────────────
    async function setForceRoute(route) {
        try {
            const res = await fetch(`${API_BASE}/v1/force-route?route=${route}`, {
                method: "POST",
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            currentForceRoute = route;

            // Update toggle UI
            $$(".route-toggle").forEach((btn) => btn.classList.remove("route-toggle--active"));
            $(`[data-route="${route}"]`).classList.add("route-toggle--active");

            const labels = { auto: "AUTO", cloud: "☁️ CLOUD", edge: "🖥️ EDGE" };
            showToast(`Route override: <strong>${labels[route]}</strong>`, route === "auto" ? "success" : route);

            // Immediately re-poll telemetry
            pollTelemetry();
        } catch (err) {
            showToast(`Failed to set route: ${err.message}`, "edge");
        }
    }

    // ── Telemetry Polling ───────────────────────────────────────────────────
    async function pollTelemetry() {
        try {
            const res = await fetch(`${API_BASE}/v1/telemetry`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            updateTelemetryUI(data.telemetry, data.routing);
            updateConnectionStatus(true);
        } catch (err) {
            console.warn("Telemetry poll failed:", err);
            updateConnectionStatus(false);
        }

        // Also poll stats
        pollStats();
    }

    async function pollStats() {
        try {
            const res = await fetch(`${API_BASE}/v1/stats`);
            if (!res.ok) return;
            const data = await res.json();
            updateCostWidget(data);
            updateLatencyChart(data.latency_history);
        } catch (err) {
            // silent
        }
    }

    function updateConnectionStatus(connected) {
        const dot = dom.connectionStatus.querySelector(".status-dot");
        const label = dom.connectionStatus.querySelector("span:last-child");
        dot.className = `status-dot status-dot--${connected ? "online" : "offline"}`;
        label.textContent = connected ? "Connected" : "Disconnected";
    }

    function updateTelemetryUI(telemetry, routing) {
        // ── Ping ──
        if (telemetry.is_online && telemetry.ping_ms !== null) {
            const ping = Math.round(telemetry.ping_ms);
            dom.pingValue.textContent = ping;
            const pingPct = Math.min(ping / 200 * 100, 100);
            dom.pingBar.style.width = pingPct + "%";

            let pingStatus = "good";
            if (ping > 150) pingStatus = "bad";
            else if (ping > 50) pingStatus = "warn";
            dom.pingValue.className = `telemetry-card__value status--${pingStatus}`;
            dom.pingBar.className = `telemetry-card__bar-fill status--${pingStatus}`;

            // Sparkline (#5)
            pushSparkline(pingHistory, ping);
            drawSparkline(dom.pingSpark, pingHistory, 0, 200, pingStatus);
        } else {
            dom.pingValue.textContent = "OFFLINE";
            dom.pingValue.className = "telemetry-card__value status--bad";
            dom.pingBar.style.width = "100%";
            dom.pingBar.className = "telemetry-card__bar-fill status--bad";
            pushSparkline(pingHistory, 200);
            drawSparkline(dom.pingSpark, pingHistory, 0, 200, "bad");
        }

        // ── Battery ──
        if (telemetry.battery_percent !== null) {
            const batt = Math.round(telemetry.battery_percent);
            dom.batteryValue.textContent = batt;
            dom.batteryBar.style.width = batt + "%";
            dom.batteryUnit.textContent = telemetry.battery_plugged ? "% ⚡" : "%";

            let battStatus = "good";
            if (batt < 20) battStatus = "bad";
            else if (batt < 50) battStatus = "warn";
            dom.batteryValue.className = `telemetry-card__value status--${battStatus}`;
            dom.batteryBar.className = `telemetry-card__bar-fill status--${battStatus}`;

            pushSparkline(batteryHistory, batt);
            drawSparkline(dom.batterySpark, batteryHistory, 0, 100, battStatus);
        } else {
            dom.batteryValue.textContent = "N/A";
            dom.batteryValue.className = "telemetry-card__value";
        }

        // ── RAM ──
        const ramAvail = telemetry.ram_available_gb;
        const ramTotal = telemetry.ram_total_gb;
        dom.ramValue.textContent = ramAvail.toFixed(1);
        const ramPct = (ramAvail / ramTotal) * 100;
        dom.ramBar.style.width = ramPct + "%";

        let ramStatus = "good";
        if (ramPct < 15) ramStatus = "bad";
        else if (ramPct < 30) ramStatus = "warn";
        dom.ramValue.className = `telemetry-card__value status--${ramStatus}`;
        dom.ramBar.className = `telemetry-card__bar-fill status--${ramStatus}`;

        pushSparkline(ramHistory, ramAvail);
        drawSparkline(dom.ramSpark, ramHistory, 0, ramTotal, ramStatus);

        // ── Route Indicator ──
        updateRouteIndicator(routing.target, routing.reasoning);
    }

    function updateRouteIndicator(target, reasoning) {
        const isCloud = target === "cloud";
        const prevRoute = currentRoute;
        currentRoute = target;

        dom.routeCard.className = `card route-card route--${target}`;
        dom.routeIcon.textContent = isCloud ? "☁️" : "🖥️";
        dom.routeLabel.textContent = isCloud ? "CLOUD" : "EDGE";
        dom.routeReason.textContent = reasoning;

        if (prevRoute !== null && prevRoute !== target) {
            dom.routeCard.style.animation = "none";
            dom.routeCard.offsetHeight;
            dom.routeCard.style.animation = "routeChange 0.6s ease-out";
            showToast(
                `Route switched: <strong>${isCloud ? "☁️ CLOUD" : "🖥️ EDGE"}</strong>`,
                isCloud ? "cloud" : "edge"
            );
        }
    }

    // ── Sparkline Drawing (#5) ──────────────────────────────────────────────
    function pushSparkline(arr, val) {
        arr.push(val);
        if (arr.length > MAX_SPARKLINE_POINTS) arr.shift();
    }

    function drawSparkline(canvas, data, min, max, status) {
        if (!canvas || data.length < 2) return;

        const ctx = canvas.getContext("2d");
        const w = canvas.width;
        const h = canvas.height;
        const padding = 2;

        ctx.clearRect(0, 0, w, h);

        const range = max - min || 1;
        const stepX = (w - padding * 2) / (MAX_SPARKLINE_POINTS - 1);

        const colors = {
            good: "#10b981",
            warn: "#f59e0b",
            bad: "#ef4444",
        };

        const color = colors[status] || "#6366f1";

        // Draw filled area
        ctx.beginPath();
        ctx.moveTo(padding, h - padding);

        data.forEach((val, i) => {
            const x = padding + i * stepX;
            const y = h - padding - ((val - min) / range) * (h - padding * 2);
            if (i === 0) ctx.lineTo(x, y);
            else ctx.lineTo(x, y);
        });

        ctx.lineTo(padding + (data.length - 1) * stepX, h - padding);
        ctx.closePath();

        const gradient = ctx.createLinearGradient(0, 0, 0, h);
        gradient.addColorStop(0, color + "40");
        gradient.addColorStop(1, color + "05");
        ctx.fillStyle = gradient;
        ctx.fill();

        // Draw line
        ctx.beginPath();
        data.forEach((val, i) => {
            const x = padding + i * stepX;
            const y = h - padding - ((val - min) / range) * (h - padding * 2);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });

        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.lineJoin = "round";
        ctx.stroke();
    }

    // ── Cost Estimation Widget (#4) ─────────────────────────────────────────
    function updateCostWidget(stats) {
        dom.costSaved.textContent = `$${stats.total_cost_saved_usd.toFixed(4)}`;
        dom.totalRequests.textContent = stats.total_requests;

        const edgePct = stats.total_requests > 0
            ? Math.round((stats.edge_requests / stats.total_requests) * 100)
            : 0;
        dom.edgePercent.textContent = `${edgePct}%`;

        // Project daily savings: if we've saved X over N requests, project to 10K
        if (stats.total_requests > 0) {
            const perRequest = stats.total_cost_saved_usd / stats.total_requests;
            const daily = perRequest * 10000;
            dom.projectedSavings.textContent = `$${daily.toFixed(2)}`;
        }
    }

    // ── Latency Comparison Chart (#2) ───────────────────────────────────────
    function updateLatencyChart(history) {
        if (!history || history.length === 0) return;

        const canvas = dom.latencyChart;
        const ctx = canvas.getContext("2d");
        const dpr = window.devicePixelRatio || 1;

        // High-DPI support
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        const w = rect.width;
        const h = rect.height;
        const padding = { top: 10, right: 10, bottom: 25, left: 40 };
        const plotW = w - padding.left - padding.right;
        const plotH = h - padding.top - padding.bottom;

        ctx.clearRect(0, 0, w, h);

        // Take last 20 entries
        const entries = history.slice(-20);
        if (entries.length === 0) return;

        const maxLatency = Math.max(...entries.map((e) => e.latency_ms), 100);
        const barWidth = Math.max(8, (plotW / entries.length) - 4);

        // Grid lines
        ctx.strokeStyle = "rgba(255,255,255,0.05)";
        ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const y = padding.top + (plotH / 4) * i;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(w - padding.right, y);
            ctx.stroke();

            // Label
            const val = Math.round(maxLatency - (maxLatency / 4) * i);
            ctx.fillStyle = "rgba(255,255,255,0.3)";
            ctx.font = "10px 'JetBrains Mono', monospace";
            ctx.textAlign = "right";
            ctx.fillText(`${val}`, padding.left - 5, y + 4);
        }

        // Bars
        entries.forEach((entry, i) => {
            const x = padding.left + (plotW / entries.length) * i + (plotW / entries.length - barWidth) / 2;
            const barH = (entry.latency_ms / maxLatency) * plotH;
            const y = padding.top + plotH - barH;

            const isCloud = entry.route === "cloud";
            const color = isCloud ? "#6366f1" : "#f59e0b";

            // Bar with rounded top
            ctx.fillStyle = color;
            ctx.beginPath();
            const r = Math.min(3, barWidth / 2);
            ctx.moveTo(x, y + barH);
            ctx.lineTo(x, y + r);
            ctx.quadraticCurveTo(x, y, x + r, y);
            ctx.lineTo(x + barWidth - r, y);
            ctx.quadraticCurveTo(x + barWidth, y, x + barWidth, y + r);
            ctx.lineTo(x + barWidth, y + barH);
            ctx.closePath();
            ctx.fill();

            // Glow
            ctx.shadowColor = color;
            ctx.shadowBlur = 4;
            ctx.fill();
            ctx.shadowBlur = 0;

            // Latency number label on top
            if (entries.length <= 15) {
                ctx.fillStyle = "rgba(255,255,255,0.5)";
                ctx.font = "9px 'JetBrains Mono', monospace";
                ctx.textAlign = "center";
                ctx.fillText(`${Math.round(entry.latency_ms)}`, x + barWidth / 2, y - 3);
            }
        });

        // "ms" label
        ctx.fillStyle = "rgba(255,255,255,0.2)";
        ctx.font = "9px Inter, sans-serif";
        ctx.textAlign = "left";
        ctx.fillText("ms", padding.left - 5, padding.top - 2);
    }

    // ── SSE Streaming Text (#3) ─────────────────────────────────────────────
    async function sendTextRequestStreaming() {
        const prompt = dom.chatInput.value.trim();
        if (!prompt || isProcessing) return;

        isProcessing = true;
        dom.sendTextBtn.disabled = true;
        dom.chatInput.value = "";

        // Remove welcome
        if (welcomeVisible) {
            const welcome = dom.chatContainer.querySelector(".chat-welcome");
            if (welcome) welcome.remove();
            welcomeVisible = false;
        }

        // Add user message
        appendChatMessage(prompt, "user");

        // Create AI message placeholder for streaming
        const aiMsg = document.createElement("div");
        aiMsg.className = "chat-msg chat-msg--ai chat-msg--streaming";
        const textEl = document.createElement("div");
        textEl.className = "chat-msg__text";
        textEl.textContent = "";
        aiMsg.appendChild(textEl);
        dom.chatContainer.appendChild(aiMsg);
        dom.chatContainer.scrollTop = dom.chatContainer.scrollHeight;

        let route = null;
        let latencyMs = 0;
        let fullText = "";

        try {
            const res = await fetch(`${API_BASE}/v1/stream`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    type: "text",
                    payload: prompt,
                    force_route: currentForceRoute === "auto" ? null : currentForceRoute,
                }),
            });

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                // Parse SSE events
                const lines = buffer.split("\n");
                buffer = lines.pop(); // keep incomplete line

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    try {
                        const event = JSON.parse(line.slice(6));

                        if (event.type === "route") {
                            route = event.route;
                        } else if (event.type === "token") {
                            fullText += event.content;
                            textEl.innerHTML = renderMarkdown(fullText);
                            dom.chatContainer.scrollTop = dom.chatContainer.scrollHeight;
                        } else if (event.type === "done") {
                            latencyMs = event.latency_ms;
                            route = event.route;

                            // Finalize message
                            aiMsg.classList.remove("chat-msg--streaming");
                            const meta = document.createElement("div");
                            meta.className = "chat-msg__meta";
                            meta.innerHTML = `
                                <span class="chat-msg__route route--${route}">
                                    ${route === "cloud" ? "☁️" : "🖥️"} ${route}
                                </span>
                                <span>${Math.round(latencyMs)}ms</span>
                                ${event.cost_saved_usd > 0 ? `<span>💰 saved $${event.cost_saved_usd.toFixed(4)}</span>` : ""}
                            `;
                            aiMsg.appendChild(meta);

                            // Add to log
                            addLogEntry({
                                route,
                                type: "text",
                                result: fullText,
                                latency_ms: latencyMs,
                            });

                            // Refresh stats
                            pollStats();
                        } else if (event.type === "error") {
                            textEl.textContent = "Error: " + event.message;
                            aiMsg.classList.remove("chat-msg--streaming");
                        }
                    } catch (e) {
                        // not valid JSON, skip
                    }
                }
            }
        } catch (err) {
            textEl.textContent = "Network error: " + err.message;
            aiMsg.classList.remove("chat-msg--streaming");
        }

        isProcessing = false;
        dom.sendTextBtn.disabled = false;
        dom.chatContainer.scrollTop = dom.chatContainer.scrollHeight;
    }

    function appendChatMessage(text, role, route, latencyMs) {
        const msg = document.createElement("div");
        msg.className = `chat-msg chat-msg--${role}`;

        const displayHtml = role === "ai" ? renderMarkdown(text) : escapeHtml(text);
        let html = `<div class="chat-msg__text">${displayHtml}</div>`;

        if (role === "ai" && route) {
            html += `
                <div class="chat-msg__meta">
                    <span class="chat-msg__route route--${route}">
                        ${route === "cloud" ? "☁️" : "🖥️"} ${route}
                    </span>
                    <span>${latencyMs?.toFixed(0)}ms</span>
                </div>`;
        }

        msg.innerHTML = html;
        dom.chatContainer.appendChild(msg);
        dom.chatContainer.scrollTop = dom.chatContainer.scrollHeight;
    }

    // ── Vision Inference ────────────────────────────────────────────────────
    async function processImage(base64Data) {
        if (isProcessing) return;
        isProcessing = true;

        dom.visionUpload.style.display = "none";
        dom.visionResults.style.display = "grid";
        dom.previewImage.src = base64Data;
        dom.detectionList.innerHTML = "";
        dom.detectionCount.textContent = "Analyzing…";

        showLoading("Routing vision request…");

        try {
            const res = await fetch(`${API_BASE}/v1/process`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    type: "vision",
                    payload: base64Data,
                    force_route: currentForceRoute === "auto" ? null : currentForceRoute,
                }),
            });

            const data = await res.json();
            hideLoading();

            if (data.success) {
                displayDetections(data.result);
                addLogEntry(data);
                if (data.cost_saved_usd > 0) {
                    showToast(`💰 Saved $${data.cost_saved_usd.toFixed(4)} on vision request`, "success");
                }
                pollStats();
            } else {
                dom.detectionCount.textContent = "Error";
                dom.detectionList.innerHTML = `<div class="log-empty">${data.detail || "Detection failed"}</div>`;
            }
        } catch (err) {
            hideLoading();
            dom.detectionCount.textContent = "Error";
            dom.detectionList.innerHTML = `<div class="log-empty">Network error: ${err.message}</div>`;
        }

        isProcessing = false;
    }

    function displayDetections(detections) {
        const count = Array.isArray(detections) ? detections.length : 0;
        dom.detectionCount.textContent = `${count} object${count !== 1 ? "s" : ""}`;
        dom.detectionList.innerHTML = "";

        if (!Array.isArray(detections) || count === 0) {
            dom.detectionList.innerHTML = '<div class="log-empty">No objects detected</div>';
            return;
        }

        detections.forEach((det) => {
            const item = document.createElement("div");
            item.className = "detection-item";
            item.innerHTML = `
                <span class="detection-item__label">${escapeHtml(det.label)}</span>
                <span class="detection-item__conf">${(det.confidence * 100).toFixed(1)}%</span>
            `;
            dom.detectionList.appendChild(item);
        });
    }

    function drawBoundingBoxes(detections) {
        const img = dom.previewImage;
        const canvas = dom.detectionCanvas;

        const draw = () => {
            const rect = img.getBoundingClientRect();
            canvas.width = rect.width;
            canvas.height = rect.height;
            canvas.style.width = rect.width + "px";
            canvas.style.height = rect.height + "px";

            const ctx = canvas.getContext("2d");
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            const colors = [
                "#6366f1", "#06b6d4", "#10b981", "#f59e0b",
                "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6",
            ];

            detections.forEach((det, i) => {
                if (!det.bbox || det.bbox.length < 4) return;

                const [x1, y1, x2, y2] = det.bbox;
                const bx = x1 * canvas.width;
                const by = y1 * canvas.height;
                const bw = (x2 - x1) * canvas.width;
                const bh = (y2 - y1) * canvas.height;
                const color = colors[i % colors.length];

                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.strokeRect(bx, by, bw, bh);

                const label = `${det.label} ${(det.confidence * 100).toFixed(0)}%`;
                ctx.font = "bold 12px Inter, sans-serif";
                const metrics = ctx.measureText(label);
                const labelH = 18;

                ctx.fillStyle = color;
                ctx.fillRect(bx, by - labelH, metrics.width + 8, labelH);
                ctx.fillStyle = "#fff";
                ctx.fillText(label, bx + 4, by - 5);
            });
        };

        if (img.complete) setTimeout(draw, 100);
        else img.onload = () => setTimeout(draw, 100);
    }

    // ── Activity Log ────────────────────────────────────────────────────────
    function addLogEntry(data) {
        const empty = dom.logList.querySelector(".log-empty");
        if (empty) empty.remove();

        const entry = document.createElement("div");
        const isCloud = data.route === "cloud";
        entry.className = `log-entry ${isCloud ? "" : "log--edge"}`;

        const preview = typeof data.result === "string"
            ? data.result.substring(0, 50)
            : `${Array.isArray(data.result) ? data.result.length : 0} detection(s)`;

        const time = new Date().toLocaleTimeString();

        entry.innerHTML = `
            <span class="log-entry__badge badge--${data.route}">
                ${isCloud ? "☁️" : "🖥️"}
            </span>
            <div class="log-entry__content">
                <div class="log-entry__preview">${escapeHtml(preview)}</div>
                <div class="log-entry__meta">
                    <span>${data.type}</span>
                    <span>•</span>
                    <span>${data.latency_ms?.toFixed(0)}ms</span>
                    <span>•</span>
                    <span>${time}</span>
                </div>
            </div>
        `;

        dom.logList.prepend(entry);
    }

    // ── Tabs ────────────────────────────────────────────────────────────────
    function switchTab(tab) {
        $$(".tab").forEach((t) => t.classList.remove("tab--active"));
        $$(".panel").forEach((p) => p.classList.remove("panel--active"));

        if (tab === "text") {
            dom.tabText.classList.add("tab--active");
            dom.panelText.classList.add("panel--active");
        } else {
            dom.tabVision.classList.add("tab--active");
            dom.panelVision.classList.add("panel--active");
        }
    }

    // ── Loading ─────────────────────────────────────────────────────────────
    function showLoading(text = "Processing…") {
        dom.loadingText.textContent = text;
        dom.loadingOverlay.style.display = "flex";
    }

    function hideLoading() { dom.loadingOverlay.style.display = "none"; }

    // ── Helpers ─────────────────────────────────────────────────────────────
    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function renderMarkdown(text) {
        // Lightweight markdown-to-HTML converter for chat responses
        let html = escapeHtml(text);

        // Code blocks (```...```)
        html = html.replace(/```(\w*)?\n([\s\S]*?)```/g, (_, lang, code) => {
            return `<pre class="md-code-block"><code>${code.trim()}</code></pre>`;
        });

        // Inline code (`...`)
        html = html.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>');

        // Bold (**...**)
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // Italic (*...*)
        html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');

        // Headers (### ... , ## ... , # ...)
        html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
        html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>');
        html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>');

        // Unordered lists (- item or * item)
        html = html.replace(/^[\-\*] (.+)$/gm, '<li class="md-li">$1</li>');
        html = html.replace(/((?:<li class="md-li">.*<\/li>\n?)+)/g, '<ul class="md-ul">$1</ul>');

        // Ordered lists (1. item)
        html = html.replace(/^\d+\.\s(.+)$/gm, '<li class="md-oli">$1</li>');
        html = html.replace(/((?:<li class="md-oli">.*<\/li>\n?)+)/g, '<ol class="md-ol">$1</ol>');

        // Paragraphs — convert double newlines to paragraph breaks
        html = html.replace(/\n\n/g, '</p><p class="md-p">');
        // Single newlines to <br> (outside of lists/pre)
        html = html.replace(/(?<!<\/li>|<\/ul>|<\/ol>|<\/pre>|<\/h[234]>|<\/p>)\n(?!<)/g, '<br>');

        return html;
    }

    function fileToBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    function autoResize(textarea) {
        textarea.style.height = "auto";
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + "px";
    }

    // ── Event Listeners ─────────────────────────────────────────────────────

    // Route toggle (#1)
    dom.toggleAuto.addEventListener("click", () => setForceRoute("auto"));
    dom.toggleCloud.addEventListener("click", () => setForceRoute("cloud"));
    dom.toggleEdge.addEventListener("click", () => setForceRoute("edge"));

    // Tabs
    dom.tabText.addEventListener("click", () => switchTab("text"));
    dom.tabVision.addEventListener("click", () => switchTab("vision"));

    // Text input — now uses SSE streaming (#3)
    dom.sendTextBtn.addEventListener("click", sendTextRequestStreaming);
    dom.chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendTextRequestStreaming();
        }
    });
    dom.chatInput.addEventListener("input", () => autoResize(dom.chatInput));

    // Image upload
    dom.dropzone.addEventListener("click", () => dom.imageInput.click());
    dom.browseBtn.addEventListener("click", () => dom.imageInput.click());

    dom.imageInput.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const b64 = await fileToBase64(file);
        processImage(b64);
    });

    // Drag & drop
    dom.dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dom.dropzone.classList.add("dragover");
    });
    dom.dropzone.addEventListener("dragleave", () => dom.dropzone.classList.remove("dragover"));
    dom.dropzone.addEventListener("drop", async (e) => {
        e.preventDefault();
        dom.dropzone.classList.remove("dragover");
        const file = e.dataTransfer.files[0];
        if (!file || !file.type.startsWith("image/")) return;
        const b64 = await fileToBase64(file);
        processImage(b64);
    });

    // Camera
    dom.cameraBtn.addEventListener("click", async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: true });
            dom.cameraVideo.srcObject = stream;
            dom.cameraVideo.style.display = "block";
            dom.cameraVideo.play();

            setTimeout(() => {
                const canvas = document.createElement("canvas");
                canvas.width = dom.cameraVideo.videoWidth;
                canvas.height = dom.cameraVideo.videoHeight;
                canvas.getContext("2d").drawImage(dom.cameraVideo, 0, 0);
                const b64 = canvas.toDataURL("image/jpeg", 0.9);
                stream.getTracks().forEach((t) => t.stop());
                dom.cameraVideo.style.display = "none";
                processImage(b64);
            }, 1500);
        } catch (err) {
            showToast("Camera access denied: " + err.message, "edge");
        }
    });

    // New image
    dom.newImageBtn.addEventListener("click", () => {
        dom.visionResults.style.display = "none";
        dom.visionUpload.style.display = "flex";
        dom.imageInput.value = "";
    });

    // Clear logs
    dom.clearLogsBtn.addEventListener("click", () => {
        dom.logList.innerHTML = '<div class="log-empty">No requests yet.</div>';
    });

    // ── Route change animation ──────────────────────────────────────────────
    const style = document.createElement("style");
    style.textContent = `
        @keyframes routeChange {
            0% { transform: scale(1); }
            30% { transform: scale(1.03); }
            60% { transform: scale(0.98); }
            100% { transform: scale(1); }
        }
    `;
    document.head.appendChild(style);

    // ── Start ───────────────────────────────────────────────────────────────
    pollTelemetry();
    pollTimer = setInterval(pollTelemetry, POLL_INTERVAL);

    console.log("🚀 OmniRoute v2 dashboard initialized");
})();
