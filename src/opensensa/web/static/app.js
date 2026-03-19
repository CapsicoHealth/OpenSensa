/* ===========================================================================
 * Copyright (C) 2025 CapsicoHealth Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 * =========================================================================== */

// @ts-check
/* ── OpenSensa · ES6 Module — mount(rootEl, options) ───────── */

/**
 * @typedef {Object} OpenSensaOptions
 * @property {string}  [baseUrl=""]               — API base URL prefix (e.g. "https://my-server.com")
 * @property {string}  [storagePrefix="opensensa"]   — localStorage key prefix (for multi-instance)
 * @property {any}     [marked]                    — marked.js instance (falls back to window.marked)
 * @property {any}     [hljs]                      — highlight.js instance (falls back to window.hljs)
 */

/**
 * @typedef {{
 *   name: string, description: string, model: string,
 *   tools: string[], sub_agents: string[],
 *   context_headers: string[],
 *   sidebarEl: HTMLElement|null,
 *   sessionId: string|null,
 *   messages: Array<{role:string, content:string}>,
 *   isSending: boolean,
 *   activeTools: Map<string, HTMLElement>,
 *   thinkingEl: HTMLElement|null,
 * }} AgentState
 *
 * @typedef {{
 *   id: string, from: string, to: string,
 *   nodeEl: HTMLElement|null,
 *   messagesEl: HTMLElement|null,
 *   activityEl: HTMLElement|null,
 *   response: string,
 *   thinkingEl: HTMLElement|null,
 *   activeTools: Map<string, HTMLElement>,
 *   children: DelegationState[],
 * }} DelegationState
 */

/* ════════════════════════════════════════════════════════════
   HTML Template (injected into rootEl)
   ════════════════════════════════════════════════════════════ */
const TEMPLATE = `
<!-- Toolbar -->
<div class="toolbar">
    <div class="toolbar-section">
        <div class="logo">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                stroke-linejoin="round" width="22" height="22">
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
            </svg>
            OpenSensa
        </div>
    </div>
    <div class="toolbar-section toolbar-right">
        <button class="tool-btn tool-btn-accent" data-ref="btn-add-agent">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New Agent
        </button>
    </div>
</div>

<!-- Main Layout -->
<div class="app-layout">
    <!-- Left Sidebar -->
    <aside class="sidebar">
        <div class="sidebar-header">
            <span class="sidebar-title">Agents</span>
            <button class="sidebar-refresh-btn" data-ref="btn-refresh-agents" title="Refresh agent list">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14">
                    <polyline points="23 4 23 10 17 10" />
                    <polyline points="1 20 1 14 7 14" />
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10" />
                    <path d="M20.49 15a9 9 0 0 1-14.85 3.36L1 14" />
                </svg>
            </button>
        </div>
        <div class="sidebar-list" data-ref="sidebar-list"></div>
    </aside>

    <!-- Centre: Chat -->
    <main class="main-area">
        <div class="empty-state" data-ref="empty-state">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="56" height="56">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
            <p>Select an agent to start chatting</p>
            <span>Or create a new agent with the button above</span>
        </div>

        <div class="chat-panel hidden" data-ref="primary-chat">
            <div class="chat-header" data-ref="chat-header">
                <div class="chat-header-left">
                    <div class="chat-status-dot"></div>
                    <span class="chat-agent-name" data-ref="chat-agent-name"></span>
                    <span class="chat-agent-model" data-ref="chat-agent-model"></span>
                </div>
                <div class="chat-header-right">
                    <button class="icon-btn" data-ref="btn-edit-agent" title="Edit agent">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="chat-messages" data-ref="chat-messages">
                <div class="chat-messages-inner" data-ref="chat-messages-inner"></div>
            </div>
            <div class="chat-activity" data-ref="chat-activity"></div>
            <div class="context-headers-bar hidden" data-ref="context-headers-bar"></div>
            <div class="chat-input-area">
                <input type="text" class="chat-input" data-ref="chat-input" placeholder="Type a message…" />
                <button class="chat-send-btn" data-ref="chat-send-btn" title="Send">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round">
                        <line x1="22" y1="2" x2="11" y2="13" />
                        <polygon points="22 2 15 22 11 13 2 9 22 2" />
                    </svg>
                </button>
            </div>
        </div>
    </main>

    <!-- Link arrow -->
    <div class="tree-link-arrow" data-ref="tree-link-arrow">
        <svg viewBox="0 0 28 60" fill="none" width="28" height="60">
            <path d="M4 0 v24 Q4 30 10 30 h8 Q22 30 22 36 v24" stroke="var(--accent-light)" stroke-width="2" fill="none"/>
            <circle cx="22" cy="58" r="3" fill="var(--accent)"/>
        </svg>
    </div>

    <!-- Right: Delegation Tree -->
    <aside class="tree-panel">
        <div class="tree-panel-header">
            <span class="tree-panel-title">Delegation Tree</span>
            <span class="tree-panel-hint" data-ref="tree-panel-hint">Delegations appear here when agents hand off tasks</span>
        </div>
        <div class="delegation-tree" data-ref="delegation-tree"></div>
    </aside>
</div>

<!-- Agent CRUD Modal -->
<div class="modal-overlay hidden" data-ref="modal-overlay">
    <div class="modal">
        <div class="modal-header">
            <h2 data-ref="modal-title">Manage Agents</h2>
            <button class="modal-close" data-ref="modal-close">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>
        </div>
        <div class="modal-body">
            <form data-ref="agent-form">
                <div class="form-group">
                    <label>Name</label>
                    <input type="text" data-ref="af-name" required placeholder="my-agent" />
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <input type="text" data-ref="af-desc" placeholder="A helpful assistant" />
                </div>
                <div class="form-group">
                    <label>System Prompt</label>
                    <textarea data-ref="af-prompt" required placeholder="You are a helpful assistant that…"></textarea>
                </div>
                <div class="form-group">
                    <label>Model</label>
                    <input type="text" data-ref="af-model" placeholder="gpt-4o" />
                </div>
                <div class="form-group">
                    <label>Tools <span class="form-hint">(comma-separated)</span></label>
                    <input type="text" data-ref="af-tools" placeholder="web_search, calculator" />
                </div>
                <div class="form-group">
                    <label>Sub-agents <span class="form-hint">(comma-separated)</span></label>
                    <input type="text" data-ref="af-subs" placeholder="agent-a, agent-b" />
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-ghost" data-ref="af-cancel">Cancel</button>
                    <button type="button" class="btn btn-danger hidden" data-ref="af-delete">Delete</button>
                    <button type="submit" class="btn btn-primary" data-ref="af-submit">Create</button>
                </div>
            </form>
        </div>
    </div>
</div>`;

/* ════════════════════════════════════════════════════════════
   mount() — public entry point
   ════════════════════════════════════════════════════════════ */

/**
 * Mount the OpenSensa Agent Chat UI into a container element.
 *
 * @param {HTMLElement} rootEl — the container element (any div)
 * @param {OpenSensaOptions} [options={}]
 * @returns {{ destroy: () => void }}
 */
export default function mount(rootEl, options = {}) {
    const baseUrl = (options.baseUrl || "").replace(/\/+$/, "");
    const storagePrefix = options.storagePrefix || "opensensa";
    const marked = options.marked || /** @type {any} */ (window)["marked"];
    const hljs = options.hljs || /** @type {any} */ (window)["hljs"];

    // ── Inject HTML ──────────────────────────────────────────
    rootEl.classList.add("root");
    rootEl.innerHTML = TEMPLATE;

    // ── Scoped query helper ──────────────────────────────────
    const $ = (/** @type {string} */ s, /** @type {ParentNode} */ p = rootEl) => p.querySelector(s);
    const ref = (/** @type {string} */ name) => /** @type {HTMLElement} */($(`[data-ref="${name}"]`));

    // ── DOM Refs ─────────────────────────────────────────────
    const sidebarList = ref("sidebar-list");
    const sidebar = /** @type {HTMLElement} */ ($(".sidebar"));
    const emptyState = ref("empty-state");
    const primaryChat = ref("primary-chat");
    const chatHeader = ref("chat-header");
    const chatAgentName = ref("chat-agent-name");
    const chatAgentModel = ref("chat-agent-model");
    const chatMessages = ref("chat-messages");
    const chatMessagesInner = ref("chat-messages-inner");
    const chatActivity = ref("chat-activity");
    const contextHeadersBar = ref("context-headers-bar");
    const chatInput = /** @type {HTMLInputElement} */ (ref("chat-input"));
    const chatSendBtn = ref("chat-send-btn");
    const treePanelHint = ref("tree-panel-hint");
    const treeLinkArrow = ref("tree-link-arrow");
    const delegationTree = ref("delegation-tree");
    const modalOverlay = ref("modal-overlay");
    const modalTitle = ref("modal-title");
    const agentForm = /** @type {HTMLFormElement} */ (ref("agent-form"));
    const afName = /** @type {HTMLInputElement} */ (ref("af-name"));
    const afDesc = /** @type {HTMLInputElement} */ (ref("af-desc"));
    const afPrompt = /** @type {HTMLTextAreaElement} */ (ref("af-prompt"));
    const afModel = /** @type {HTMLInputElement} */ (ref("af-model"));
    const afTools = /** @type {HTMLInputElement} */ (ref("af-tools"));
    const afSubs = /** @type {HTMLInputElement} */ (ref("af-subs"));
    const afSubmit = ref("af-submit");
    const afDelete = ref("af-delete");
    const afCancel = ref("af-cancel");

    // ── State ────────────────────────────────────────────────
    /** @type {Map<string, AgentState>} */
    const agents = new Map();
    /** @type {string|null} */
    let selectedAgent = null;
    /** @type {Map<string, DelegationState>} */
    const activeDelegations = new Map();
    /** @type {string|null} */
    let editingAgent = null;
    let destroyed = false;

    // ── Helpers ──────────────────────────────────────────────
    const api = (/** @type {string} */ path, /** @type {RequestInit} */ opts = {}) =>
        fetch(baseUrl + path, { headers: { "Content-Type": "application/json" }, ...opts });

    marked.setOptions({
        highlight: (/** @type {string} */ code, /** @type {string} */ lang) => {
            if (lang && hljs.getLanguage(lang)) return hljs.highlight(code, { language: lang }).value;
            return hljs.highlightAuto(code).value;
        },
        breaks: true,
    });

    // ── Namespaced localStorage ──────────────────────────────
    function storageGet(/** @type {string} */ key) {
        try { return localStorage.getItem(`${storagePrefix}-${key}`); } catch { return null; }
    }
    function storageSet(/** @type {string} */ key, /** @type {string} */ val) {
        try { localStorage.setItem(`${storagePrefix}-${key}`, val); } catch { }
    }

    /* ════════════════════════════════════════════════════════════
       SIDEBAR — Load & Select Agents
       ════════════════════════════════════════════════════════════ */

    function createSidebarEntry(/** @type {{name:string, description:string, model:string}} */ agent) {
        const el = document.createElement("div");
        el.className = "sidebar-agent";
        el.dataset.agent = agent.name;
        el.innerHTML = `
            <div class="sidebar-agent-dot"></div>
            <div class="sidebar-agent-info">
                <span class="sidebar-agent-name">${agent.name}</span>
                <span class="sidebar-agent-desc">${agent.description || "Agent"}</span>
            </div>
            <button class="sidebar-agent-edit" title="Edit">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
            </button>`;

        el.addEventListener("click", (e) => {
            if (/** @type {HTMLElement} */ (e.target).closest(".sidebar-agent-edit")) return;
            selectAgent(agent.name);
        });

        const editBtn = $(".sidebar-agent-edit", el);
        editBtn?.addEventListener("click", (e) => {
            e.stopPropagation();
            openEditModal(agent.name);
        });

        return el;
    }

    async function loadAgents() {
        if (destroyed) return;
        try {
            const res = await api("/api/agents");
            const agentList = await res.json();
            console.log("[opensensa] loadAgents response:", agentList.map((/** @type {any} */ a) => ({ name: a.name, context_headers: a.context_headers })));

            if (!Array.isArray(agentList) || agentList.length === 0) {
                emptyState.classList.remove("hidden");
                primaryChat.classList.add("hidden");
                return;
            }

            const existing = new Set(agents.keys());

            agentList.forEach((/** @type {any} */ a) => {
                if (agents.has(a.name)) { existing.delete(a.name); return; }

                const sidebarEl = createSidebarEntry(a);
                sidebarList.appendChild(sidebarEl);

                /** @type {AgentState} */
                const state = {
                    name: a.name,
                    description: a.description || "",
                    model: a.model || "",
                    tools: a.tools || [],
                    sub_agents: a.sub_agents || [],
                    context_headers: a.context_headers || [],
                    sidebarEl,
                    sessionId: null,
                    messages: [],
                    isSending: false,
                    activeTools: new Map(),
                    thinkingEl: null,
                };
                agents.set(a.name, state);
            });

            for (const gone of existing) {
                const s = agents.get(gone);
                if (s?.sidebarEl) s.sidebarEl.remove();
                agents.delete(gone);
            }

            // No agent selected by default — user clicks to choose
        } catch (err) {
            console.error("opensensa loadAgents:", err);
        }
    }

    function selectAgent(/** @type {string} */ name) {
        const agent = agents.get(name);
        if (!agent) return;

        sidebar.classList.add("collapsed");
        sidebar.classList.remove("expanded");

        selectedAgent = name;
        storageSet("selected", name);

        for (const a of agents.values()) a.sidebarEl?.classList.toggle("active", a.name === name);

        emptyState.classList.add("hidden");
        primaryChat.classList.remove("hidden");

        primaryChat.classList.remove("panel-enter");
        void primaryChat.offsetWidth;
        primaryChat.classList.add("panel-enter");

        chatAgentName.textContent = name;
        chatAgentModel.textContent = agent.model || "default";

        chatMessagesInner.innerHTML = "";
        for (const msg of agent.messages) appendMessageToEl(chatMessagesInner, msg.role, msg.content);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        chatActivity.innerHTML = "";
        delegationTree.innerHTML = "";
        updateTreePanelVisibility();

        chatInput.placeholder = `Ask ${name}…`;
        renderContextHeaders(agent);
        chatInput.focus();
    }

    function updateTreePanelVisibility() {
        const hasDelegations = delegationTree.children.length > 0;
        treeLinkArrow.classList.toggle("visible", hasDelegations);
        treePanelHint.style.display = hasDelegations ? "none" : "block";
    }

    /* ════════════════════════════════════════════════════════════
       CHAT — Messages + Sending
       ════════════════════════════════════════════════════════════ */

    function appendMessageToEl(/** @type {HTMLElement} */ container, /** @type {string} */ role, /** @type {string} */ content) {
        const div = document.createElement("div");
        if (role === "user") {
            div.className = "chat-msg user";
            div.textContent = content;
        } else if (role === "agent") {
            div.className = "chat-msg agent";
            div.innerHTML = marked.parse(content);
        } else if (role === "error") {
            div.className = "chat-msg error-msg";
            div.textContent = content;
        } else {
            div.className = "chat-msg system-msg";
            div.textContent = content;
        }
        container.appendChild(div);
    }

    function addMessage(/** @type {string} */ role, /** @type {string} */ content) {
        if (!selectedAgent) return;
        const agent = agents.get(selectedAgent);
        if (!agent) return;
        agent.messages.push({ role, content });
        appendMessageToEl(chatMessagesInner, role, content);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function showThinking() {
        if (!selectedAgent) return;
        const agent = agents.get(selectedAgent);
        if (!agent || agent.thinkingEl) return;
        const el = document.createElement("div");
        el.className = "chat-thinking";
        el.innerHTML = "<span></span><span></span><span></span>";
        chatMessagesInner.appendChild(el);
        agent.thinkingEl = el;
        const dot = $(".chat-status-dot", chatHeader);
        if (dot) dot.classList.add("thinking");
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function hideThinking() {
        if (!selectedAgent) return;
        const agent = agents.get(selectedAgent);
        if (!agent) return;
        if (agent.thinkingEl) { agent.thinkingEl.remove(); agent.thinkingEl = null; }
        const dot = $(".chat-status-dot", chatHeader);
        if (dot) dot.classList.remove("thinking");
    }

    async function ensureSession(/** @type {AgentState} */ agent) {
        if (agent.sessionId) return agent.sessionId;
        const res = await api("/api/chat/sessions", {
            method: "POST", body: JSON.stringify({ agent_name: agent.name }),
        });
        const data = await res.json();
        agent.sessionId = data.session_id;
        return agent.sessionId;
    }

    /* ── Context-header inputs (e.g. X-Document-URL for healthbuddy) ── */

    /**
     * Render input fields above the chat input for each declared context_header.
     * @param {AgentState} agent
     */
    function renderContextHeaders(agent) {
        contextHeadersBar.innerHTML = "";
        const keys = agent.context_headers || [];
        console.log("[opensensa] renderContextHeaders", agent.name, "keys:", keys);
        if (!keys.length) {
            contextHeadersBar.classList.add("hidden");
            return;
        }
        contextHeadersBar.classList.remove("hidden");
        for (const headerName of keys) {
            const label = headerName.replace(/^X-/i, "").replace(/-/g, " ");
            const wrapper = document.createElement("div");
            wrapper.className = "ctx-header-field";
            wrapper.innerHTML = `<label class="ctx-header-label">${label}</label>`;
            const input = document.createElement("input");
            input.type = "text";
            input.className = "ctx-header-input";
            input.placeholder = headerName;
            input.dataset.headerName = headerName;
            // Restore from localStorage if previously set
            const stored = storageGet(`ctx:${agent.name}:${headerName}`);
            if (stored) input.value = stored;
            input.addEventListener("change", () => {
                storageSet(`ctx:${agent.name}:${headerName}`, input.value);
            });
            wrapper.appendChild(input);
            contextHeadersBar.appendChild(wrapper);
        }
    }

    /**
     * Read current context-header input values and return as a headers object.
     * @returns {Record<string, string>}
     */
    function getContextHeaderValues() {
        /** @type {Record<string, string>} */
        const headers = {};
        contextHeadersBar.querySelectorAll("input.ctx-header-input").forEach((/** @type {HTMLInputElement} */ el) => {
            const name = el.dataset.headerName;
            if (name && el.value.trim()) headers[name] = el.value.trim();
        });
        console.log("[opensensa] getContextHeaderValues →", headers);
        return headers;
    }

    async function sendMessage() {
        if (!selectedAgent) return;
        const agent = agents.get(selectedAgent);
        if (!agent || agent.isSending) return;
        const text = chatInput.value.trim();
        if (!text) return;

        agent.isSending = true;
        chatInput.value = "";
        addMessage("user", text);

        try {
            const sid = await ensureSession(agent);
            showThinking();

            // Collect context headers from the UI inputs (e.g. X-Document-URL)
            const extraHeaders = getContextHeaderValues();
            const allHeaders = { "Content-Type": "application/json", ...extraHeaders };
            console.log("[opensensa] sendMessage fetch headers:", allHeaders);

            const res = await fetch(baseUrl + `/api/chat/sessions/${sid}/messages`, {
                method: "POST",
                headers: allHeaders,
                body: JSON.stringify({ message: text }),
            });

            const reader = res.body?.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            if (reader) {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split("\n");
                    buffer = lines.pop() || "";
                    for (const line of lines) {
                        if (!line.startsWith("data: ")) continue;
                        const raw = line.slice(6);
                        if (raw === "[DONE]") continue;
                        try { handleSSEEvent(JSON.parse(raw)); } catch { }
                    }
                }
            }
        } catch (err) {
            hideThinking();
            addMessage("error", "Network error: " + /** @type {Error} */ (err).message);
        }

        agent.isSending = false;
        hideThinking();
        clearToolChips();
    }

    /* ════════════════════════════════════════════════════════════
       TOOL CHIPS
       ════════════════════════════════════════════════════════════ */

    function showToolChip(/** @type {string} */ nodeId, /** @type {string} */ toolName, /** @type {string} */ status, /** @type {number|undefined} */ durationMs, /** @type {HTMLElement|null} */ targetEl, /** @type {Map<string, HTMLElement>|null} */ targetMap) {
        const area = targetEl || chatActivity;
        const toolMap = targetMap || agents.get(selectedAgent || "")?.activeTools;
        if (!area || !toolMap) return;

        let chip = toolMap.get(nodeId);
        if (!chip) {
            chip = document.createElement("div");
            chip.className = "tool-chip running";
            chip.innerHTML = `<span class="tool-chip-icon">🔧</span><span>${toolName}</span><span class="spinner"></span>`;
            area.appendChild(chip);
            toolMap.set(nodeId, chip);
        }

        if (status === "complete" || status === "completed") {
            chip.className = "tool-chip complete";
            const ms = durationMs != null ? ` · ${durationMs}ms` : "";
            chip.innerHTML = `<span class="tool-chip-icon">✓</span><span>${toolName}${ms}</span>`;
            setTimeout(() => { toolMap.delete(nodeId); }, 2000);
        } else if (status === "failed") {
            chip.className = "tool-chip failed";
            chip.innerHTML = `<span class="tool-chip-icon">✗</span><span>${toolName}</span>`;
            toolMap.delete(nodeId);
        }
    }

    function clearToolChips() {
        if (!selectedAgent) return;
        const agent = agents.get(selectedAgent);
        if (agent) agent.activeTools.clear();
        setTimeout(() => { chatActivity.innerHTML = ""; }, 2000);
    }

    /* ════════════════════════════════════════════════════════════
       DELEGATION TREE
       ════════════════════════════════════════════════════════════ */

    function createDelegationNode(/** @type {string} */ nodeId, /** @type {string} */ fromAgent, /** @type {string} */ toAgent, /** @type {string} */ message, /** @type {HTMLElement} */ parentContainer) {
        const node = document.createElement("div");
        node.className = "delegation-node";
        node.dataset.nodeId = nodeId;

        node.innerHTML = `
            <svg class="delegation-connector-arrow" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="5" fill="var(--accent-bg)" stroke="var(--accent)" stroke-width="1.5"/>
                <path d="M5 7h4M7 5v4" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <div class="delegation-card active">
                <div class="delegation-card-header">
                    <div class="delegation-card-dot"></div>
                    <span class="delegation-card-name">${toAgent}</span>
                    <span class="delegation-card-from">from ${fromAgent}</span>
                </div>
                <div class="delegation-card-messages"></div>
                <div class="delegation-card-activity"></div>
            </div>`;

        parentContainer.appendChild(node);

        const msgsEl = /** @type {HTMLElement} */ ($(".delegation-card-messages", node));
        const activityEl = /** @type {HTMLElement} */ ($(".delegation-card-activity", node));

        if (message) {
            const label = document.createElement("div");
            label.className = "delegation-from-label";
            label.textContent = `↗ Query from ${fromAgent}`;
            msgsEl.appendChild(label);

            const msgDiv = document.createElement("div");
            msgDiv.className = "chat-msg user";
            msgDiv.style.fontSize = "12px";
            msgDiv.style.maxWidth = "95%";
            msgDiv.textContent = message;
            msgsEl.appendChild(msgDiv);
        }

        const thinkingEl = document.createElement("div");
        thinkingEl.className = "chat-thinking";
        thinkingEl.innerHTML = "<span></span><span></span><span></span>";
        msgsEl.appendChild(thinkingEl);

        /** @type {DelegationState} */
        const state = {
            id: nodeId, from: fromAgent, to: toAgent,
            nodeEl: node, messagesEl: msgsEl, activityEl,
            response: "", thinkingEl, activeTools: new Map(), children: [],
        };
        activeDelegations.set(nodeId, state);

        const targetAgent = agents.get(toAgent);
        if (targetAgent?.sidebarEl) targetAgent.sidebarEl.classList.add("delegating");

        updateTreePanelVisibility();
        setTimeout(() => { node.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, 100);
        return state;
    }

    function endDelegationNode(/** @type {string} */ nodeId) {
        const del = activeDelegations.get(nodeId);
        if (!del) return;

        if (del.thinkingEl) { del.thinkingEl.remove(); del.thinkingEl = null; }

        if (del.response && del.messagesEl) {
            const msgDiv = document.createElement("div");
            msgDiv.className = "chat-msg agent";
            msgDiv.style.fontSize = "12px";
            msgDiv.style.maxWidth = "95%";
            msgDiv.innerHTML = marked.parse(del.response);
            del.messagesEl.appendChild(msgDiv);
        }

        const card = del.nodeEl ? $(".delegation-card", del.nodeEl) : null;
        if (card) { card.classList.remove("active"); card.classList.add("completed"); }

        const arrow = del.nodeEl ? $(".delegation-connector-arrow", del.nodeEl) : null;
        if (arrow) {
            arrow.innerHTML = `
                <circle cx="7" cy="7" r="5" fill="var(--success-bg)" stroke="var(--success)" stroke-width="1.5"/>
                <path d="M4.5 7l2 2 3-3.5" stroke="var(--success)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`;
        }

        const targetAgent = agents.get(del.to);
        if (targetAgent?.sidebarEl) targetAgent.sidebarEl.classList.remove("delegating");

        activeDelegations.delete(nodeId);
        updateTreePanelVisibility();
    }

    function getDelegationChildContainer(/** @type {DelegationState} */ parentDel) {
        if (!parentDel.nodeEl) return delegationTree;
        let nested = /** @type {HTMLElement|null} */ ($(".delegation-nested", parentDel.nodeEl));
        if (!nested) {
            nested = document.createElement("div");
            nested.className = "delegation-nested delegation-tree";
            parentDel.nodeEl.appendChild(nested);
        }
        return nested;
    }

    /* ════════════════════════════════════════════════════════════
       SSE EVENT ROUTER
       ════════════════════════════════════════════════════════════ */

    function findInTree(/** @type {any[]} */ tree, /** @type {string} */ nodeId, /** @type {any[]} */ ancestors = []) {
        for (const n of tree) {
            if (n.id === nodeId) return { node: n, ancestors };
            if (n.children?.length) {
                const r = findInTree(n.children, nodeId, [...ancestors, n]);
                if (r) return r;
            }
        }
        return null;
    }

    function getDelegationForEvent(/** @type {any[]} */ tree, /** @type {string} */ nodeId) {
        if (!nodeId || !tree) return null;
        const r = findInTree(tree, nodeId);
        if (!r) return null;
        for (const anc of r.ancestors) {
            if (anc.kind === "delegation") {
                const del = activeDelegations.get(anc.id);
                if (del) return del;
            }
        }
        return null;
    }

    function handleSSEEvent(/** @type {any} */ evt) {
        const event = evt.event;
        switch (event) {
            case "turn_complete":
                hideThinking();
                if (evt.response) addMessage("agent", evt.response);
                for (const [nid] of activeDelegations) endDelegationNode(nid);
                break;

            case "turn_error":
                hideThinking();
                addMessage("error", evt.error || "Unknown error");
                for (const [nid] of activeDelegations) endDelegationNode(nid);
                break;

            case "tool_start": {
                const del = getDelegationForEvent(evt.tree, evt.node_id);
                if (del) showToolChip(evt.node_id, evt.tool || "tool", "running", undefined, del.activityEl, del.activeTools);
                else showToolChip(evt.node_id, evt.tool || "tool", "running", undefined, null, null);
                break;
            }

            case "tool_end": {
                const del = getDelegationForEvent(evt.tree, evt.node_id);
                if (del) showToolChip(evt.node_id, evt.tool || "tool", "complete", evt.duration_ms, del.activityEl, del.activeTools);
                else showToolChip(evt.node_id, evt.tool || "tool", "complete", evt.duration_ms, null, null);
                break;
            }

            case "delegation_start": {
                const fromAgent = evt.from_agent || selectedAgent || "";
                const toAgent = evt.to_agent;
                let parentContainer = delegationTree;
                for (const del of activeDelegations.values()) {
                    if (del.to === fromAgent) { parentContainer = getDelegationChildContainer(del); break; }
                }
                createDelegationNode(evt.node_id, fromAgent, toAgent, evt.message || "", parentContainer);
                break;
            }

            case "delegation_end": {
                const del = activeDelegations.get(evt.node_id);
                if (del) del.response = evt.response || "";
                endDelegationNode(evt.node_id);
                break;
            }

            case "llm_start": {
                const del = getDelegationForEvent(evt.tree, evt.node_id);
                if (!del) showThinking();
                break;
            }

            case "llm_end": {
                const del = getDelegationForEvent(evt.tree, evt.node_id);
                if (!del) hideThinking();
                break;
            }

            default: break;
        }
    }

    /* ════════════════════════════════════════════════════════════
       AGENT CRUD MODAL
       ════════════════════════════════════════════════════════════ */

    function openCreateModal() {
        editingAgent = null;
        agentForm.reset();
        afName.disabled = false;
        afSubmit.textContent = "Create";
        afDelete.classList.add("hidden");
        modalTitle.textContent = "New Agent";
        modalOverlay.classList.remove("hidden");
    }

    async function openEditModal(/** @type {string} */ name) {
        editingAgent = name;
        afName.disabled = true;
        afSubmit.textContent = "Save";
        afDelete.classList.remove("hidden");
        modalTitle.textContent = `Edit ${name}`;
        modalOverlay.classList.remove("hidden");
        try {
            const res = await api(`/api/agents/${name}`);
            const data = await res.json();
            afName.value = name;
            afDesc.value = data.description || "";
            afPrompt.value = data.system_prompt || "";
            afModel.value = data.model || "";
            afTools.value = (data.tools || []).join(", ");
            afSubs.value = (data.sub_agents || []).join(", ");
        } catch { agentForm.reset(); afName.value = name; }
    }

    function closeModal() { modalOverlay.classList.add("hidden"); }

    async function submitAgent(/** @type {Event} */ e) {
        e.preventDefault();
        const payload = {
            name: afName.value.trim(),
            description: afDesc.value.trim() || "Agent",
            system_prompt: afPrompt.value.trim(),
            model: afModel.value.trim() || "${default}",
            tools: afTools.value ? afTools.value.split(",").map(s => s.trim()).filter(Boolean) : [],
            sub_agents: afSubs.value ? afSubs.value.split(",").map(s => s.trim()).filter(Boolean) : [],
        };
        try {
            if (editingAgent) await api(`/api/agents/${editingAgent}`, { method: "PUT", body: JSON.stringify(payload) });
            else await api("/api/agents", { method: "POST", body: JSON.stringify(payload) });
            closeModal();
            await reloadAgents();
        } catch (err) { alert("Failed: " + /** @type {Error} */ (err).message); }
    }

    async function deleteCurrentAgent() {
        if (!editingAgent || !confirm(`Delete agent "${editingAgent}"?`)) return;
        try {
            await api(`/api/agents/${editingAgent}`, { method: "DELETE" });
            closeModal();
            const agent = agents.get(editingAgent);
            if (agent?.sidebarEl) agent.sidebarEl.remove();
            agents.delete(editingAgent);
            if (editingAgent === selectedAgent) {
                selectedAgent = null;
                if (agents.size > 0) selectAgent(/** @type {string} */(agents.keys().next().value));
                else { emptyState.classList.remove("hidden"); primaryChat.classList.add("hidden"); sidebar.classList.remove("collapsed"); }
            }
        } catch (err) { alert("Failed: " + /** @type {Error} */ (err).message); }
    }

    async function reloadAgents() {
        for (const a of agents.values()) { if (a.sidebarEl) a.sidebarEl.remove(); }
        agents.clear();
        selectedAgent = null;
        sidebar.classList.remove("collapsed");
        emptyState.classList.remove("hidden");
        primaryChat.classList.add("hidden");
        activeDelegations.clear();
        delegationTree.innerHTML = "";
        chatMessagesInner.innerHTML = "";
        chatActivity.innerHTML = "";
        updateTreePanelVisibility();
        await loadAgents();
    }

    /* ════════════════════════════════════════════════════════════
       EVENT BINDINGS (tracked for cleanup)
       ════════════════════════════════════════════════════════════ */
    /** @type {Array<[EventTarget, string, EventListener]>} */
    const listeners = [];

    function on(/** @type {EventTarget} */ el, /** @type {string} */ evt, /** @type {EventListener} */ fn) {
        el.addEventListener(evt, fn);
        listeners.push([el, evt, fn]);
    }

    on(chatInput, "keydown", (e) => {
        if (/** @type {KeyboardEvent} */ (e).key === "Enter" && !/** @type {KeyboardEvent} */ (e).shiftKey) {
            e.preventDefault(); sendMessage();
        }
    });
    on(chatSendBtn, "click", () => sendMessage());
    on(ref("btn-edit-agent"), "click", () => { if (selectedAgent) openEditModal(selectedAgent); });
    on(ref("btn-add-agent"), "click", openCreateModal);
    on(ref("btn-refresh-agents"), "click", async () => {
        const btn = ref("btn-refresh-agents");
        btn.classList.add("spinning");
        try { await reloadAgents(); } finally { setTimeout(() => btn.classList.remove("spinning"), 400); }
    });
    on(sidebar, "click", (e) => {
        if (!sidebar.classList.contains("collapsed")) return;
        if (/** @type {HTMLElement} */ (e.target).closest(".sidebar-agent")) return;
        sidebar.classList.toggle("expanded");
    });
    on(document, "click", (e) => {
        if (!sidebar.classList.contains("expanded")) return;
        if (!sidebar.contains(/** @type {Node} */(e.target))) {
            sidebar.classList.remove("expanded");
        }
    });
    on(ref("modal-close"), "click", closeModal);
    on(modalOverlay, "click", (e) => { if (e.target === modalOverlay) closeModal(); });
    on(afCancel, "click", closeModal);
    on(agentForm, "submit", submitAgent);
    on(afDelete, "click", deleteCurrentAgent);

    /* ════════════════════════════════════════════════════════════
       INIT
       ════════════════════════════════════════════════════════════ */
    loadAgents();

    /* ════════════════════════════════════════════════════════════
       DESTROY — cleanup for unmount
       ════════════════════════════════════════════════════════════ */
    return {
        destroy() {
            destroyed = true;
            for (const [el, evt, fn] of listeners) el.removeEventListener(evt, fn);
            listeners.length = 0;
            rootEl.classList.remove("root");
            rootEl.innerHTML = "";
        },
    };
}
