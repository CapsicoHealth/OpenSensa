/* ===========================================================================
 * Copyright (C) 2025 CapsicoHealth Inc. — Apache-2.0
 * =========================================================================== */
// @ts-check

/**
 * ChatPanel — Self-contained chat widget with SSE streaming, tool chips,
 * thinking dots, context-header inputs, and message history.
 *
 * Usage:
 *   import { ChatPanel } from './chat-panel.js';
 *   const chat = new ChatPanel(document.getElementById('chat-container'), {
 *       baseUrl: '',
 *       marked: window.marked,
 *       hljs: window.hljs,
 *   });
 *   chat.setAgent({ name: 'my-agent', model: 'gpt-4o', contextHeaders: ['X-Doc-URL'] });
 *   chat.on('sseEvent', evt => console.log(evt));
 *   chat.on('editRequested', name => console.log('edit', name));
 *
 * Required CSS: css/chat.css  (+ css/tokens.css or custom token values)
 * External JS dependencies: marked.js (optional), highlight.js (optional)
 */

/**
 * @typedef {Object} ChatPanelOptions
 * @property {string}  [baseUrl=""]
 * @property {string}  [storagePrefix="opensensa"]
 * @property {any}     [marked]  — marked.js instance
 * @property {any}     [hljs]    — highlight.js instance
 */

/**
 * @typedef {Object} ChatAgentConfig
 * @property {string}   name
 * @property {string}   model
 * @property {string[]} [contextHeaders]
 */

/** @typedef {{ role: string, content: string }} ChatMessage */

const CHAT_TEMPLATE = `
<div class="empty-state" data-ref="empty-state">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="56" height="56">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
    <p>Select an agent to start chatting</p>
    <span>Or create a new agent with the button above</span>
</div>

<div class="chat-panel hidden" data-ref="chat-panel">
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
</div>`;

export class ChatPanel {
    /** @type {HTMLElement} */ _container;
    /** @type {string} */     _baseUrl;
    /** @type {string} */     _storagePrefix;
    /** @type {any} */        _marked;
    /** @type {any} */        _hljs;

    // DOM refs
    /** @type {HTMLElement} */      _emptyState;
    /** @type {HTMLElement} */      _chatPanel;
    /** @type {HTMLElement} */      _chatHeader;
    /** @type {HTMLElement} */      _chatAgentName;
    /** @type {HTMLElement} */      _chatAgentModel;
    /** @type {HTMLElement} */      _chatMessages;
    /** @type {HTMLElement} */      _chatMessagesInner;
    /** @type {HTMLElement} */      _chatActivity;
    /** @type {HTMLElement} */      _contextHeadersBar;
    /** @type {HTMLInputElement} */ _chatInput;
    /** @type {HTMLElement} */      _chatSendBtn;

    // State
    /** @type {string|null} */                 _agentName = null;
    /** @type {ChatMessage[]} */               _messages = [];
    /** @type {boolean} */                     _isSending = false;
    /** @type {HTMLElement|null} */             _thinkingEl = null;
    /** @type {Map<string, HTMLElement>} */     _activeTools = new Map();
    /** @type {HTMLElement|null} */             _streamingEl = null;
    /** @type {string} */                      _streamingText = "";
    /** @type {string[]} */                    _contextHeaders = [];
    /** @type {Record<string, Function[]>} */  _handlers = {};
    /** @type {Array<[EventTarget, string, EventListener]>} */ _listeners = [];

    /**
     * @param {HTMLElement} containerEl
     * @param {ChatPanelOptions} [options]
     */
    constructor(containerEl, options = {}) {
        this._container = containerEl;
        this._baseUrl = (options.baseUrl || "").replace(/\/+$/, "");
        this._storagePrefix = options.storagePrefix || "opensensa";
        this._marked = options.marked || /** @type {any} */ (globalThis)["marked"] || null;
        this._hljs = options.hljs || /** @type {any} */ (globalThis)["hljs"] || null;

        // Configure marked
        if (this._marked && this._hljs) {
            this._marked.setOptions({
                highlight: (/** @type {string} */ code, /** @type {string} */ lang) => {
                    if (lang && this._hljs.getLanguage(lang)) return this._hljs.highlight(code, { language: lang }).value;
                    return this._hljs.highlightAuto(code).value;
                },
                breaks: true,
            });
        }

        this._container.innerHTML = CHAT_TEMPLATE;

        const ref = (/** @type {string} */ n) => /** @type {HTMLElement} */(this._container.querySelector(`[data-ref="${n}"]`));
        this._emptyState = ref("empty-state");
        this._chatPanel = ref("chat-panel");
        this._chatHeader = ref("chat-header");
        this._chatAgentName = ref("chat-agent-name");
        this._chatAgentModel = ref("chat-agent-model");
        this._chatMessages = ref("chat-messages");
        this._chatMessagesInner = ref("chat-messages-inner");
        this._chatActivity = ref("chat-activity");
        this._contextHeadersBar = ref("context-headers-bar");
        this._chatInput = /** @type {HTMLInputElement} */ (ref("chat-input"));
        this._chatSendBtn = ref("chat-send-btn");

        // Bind events
        this._on(this._chatInput, "keydown", (/** @type {KeyboardEvent} */ e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.sendMessage(); }
        });
        this._on(this._chatSendBtn, "click", () => this.sendMessage());
        this._on(ref("btn-edit-agent"), "click", () => {
            if (this._agentName) this._emit("editRequested", this._agentName);
        });
    }

    /* ─── Public API ─────────────────────────────────────── */

    /**
     * Configure the chat for a specific agent. Clears previous state.
     * @param {ChatAgentConfig} agent
     * @param {{ messages?: ChatMessage[] }} [restore] — optional restored state
     */
    setAgent(agent, restore) {
        this._agentName = agent.name;
        this._messages = restore?.messages ? [...restore.messages] : [];
        this._isSending = false;
        this._thinkingEl = null;
        this._activeTools.clear();
        this._streamingEl = null;
        this._streamingText = "";
        this._contextHeaders = agent.contextHeaders || [];

        this._emptyState.classList.add("hidden");
        this._chatPanel.classList.remove("hidden");

        // Trigger enter animation
        this._chatPanel.classList.remove("panel-enter");
        void this._chatPanel.offsetWidth;
        this._chatPanel.classList.add("panel-enter");

        this._chatAgentName.textContent = agent.name;
        this._chatAgentModel.textContent = agent.model || "default";

        // Render existing messages
        this._chatMessagesInner.innerHTML = "";
        for (const msg of this._messages) this._appendMessage(msg.role, msg.content);
        this._chatMessages.scrollTop = this._chatMessages.scrollHeight;

        this._chatActivity.innerHTML = "";
        this._chatInput.placeholder = `Ask ${agent.name}…`;
        this._renderContextHeaders();
        this._chatInput.focus();
    }

    /** Show the empty state (no agent selected). */
    showEmpty() {
        this._agentName = null;
        this._emptyState.classList.remove("hidden");
        this._chatPanel.classList.add("hidden");
    }

    /**
     * Programmatically add a message.
     * @param {string} role
     * @param {string} content
     */
    addMessage(role, content) {
        this._messages.push({ role, content });
        this._appendMessage(role, content);
        this._chatMessages.scrollTop = this._chatMessages.scrollHeight;
    }

    /** Send the current input value (or programmatically provided text). */
    async sendMessage(/** @type {string} */ text) {
        if (!this._agentName || this._isSending) return;
        const msg = text || this._chatInput.value.trim();
        if (!msg) return;

        this._isSending = true;
        this._chatInput.value = "";
        this.addMessage("user", msg);

        try {
            this.showThinking();

            // Build A2A JSON-RPC message/stream request
            const contextHeaders = this._getContextHeaderValues();
            const msgId = crypto.randomUUID();

            // Build history from prior messages for multi-turn
            /** @type {any[]} */
            const history = this._messages.slice(0, -1).map(m => ({
                role: m.role === "agent" ? "agent" : m.role,
                parts: [{ kind: "text", text: m.content }],
            }));

            /** @type {any} */
            const params = {
                message: {
                    role: "user",
                    parts: [{ kind: "text", text: msg }],
                    messageId: msgId,
                },
            };

            // Attach history and context headers as metadata
            /** @type {any} */
            const metadata = {};
            if (history.length > 0) metadata["framework:history"] = history;
            if (Object.keys(contextHeaders).length > 0) metadata["context_headers"] = contextHeaders;
            if (Object.keys(metadata).length > 0) params.metadata = metadata;

            const payload = {
                jsonrpc: "2.0",
                id: crypto.randomUUID(),
                method: "message/stream",
                params,
            };

            const res = await fetch(
                this._baseUrl + `/agents/${this._agentName}/`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json", ...contextHeaders },
                    body: JSON.stringify(payload),
                },
            );

            const reader = res.body?.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            /** @type {number} */
            let toolCalls = 0;
            /** @type {number} */
            let delegations = 0;

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
                        try {
                            const event = JSON.parse(raw);
                            const parsed = this._handleA2AEvent(event);
                            if (parsed) {
                                if (parsed.toolCalls) toolCalls += parsed.toolCalls;
                                if (parsed.delegations) delegations += parsed.delegations;
                                this._emit("sseEvent", parsed);
                            }
                        } catch { /* skip malformed */ }
                    }
                }
            }

            // Finalize the streamed response
            const response = this._streamingText;
            this.hideThinking();
            this._finalizeStreamingMessage();
            if (!response) {
                this.addMessage("agent", "Agent completed with no output.");
            }
            this._emit("sseEvent", {
                event: "turn_complete",
                response,
                stats: { tool_calls: toolCalls, delegations },
            });
        } catch (err) {
            this.hideThinking();
            this.addMessage("error", "Network error: " + /** @type {Error} */ (err).message);
            this._emit("sseEvent", {
                event: "turn_error",
                error: /** @type {Error} */ (err).message,
            });
        }

        this._isSending = false;
        this.hideThinking();
        this._clearToolChips();
    }

    /** Show the thinking indicator. */
    showThinking() {
        if (this._thinkingEl) return;
        const el = document.createElement("div");
        el.className = "chat-thinking";
        el.innerHTML = "<span></span><span></span><span></span>";
        this._chatMessagesInner.appendChild(el);
        this._thinkingEl = el;
        const dot = this._chatHeader.querySelector(".chat-status-dot");
        if (dot) dot.classList.add("thinking");
        this._chatMessages.scrollTop = this._chatMessages.scrollHeight;
    }

    /** Hide the thinking indicator. */
    hideThinking() {
        if (this._thinkingEl) { this._thinkingEl.remove(); this._thinkingEl = null; }
        const dot = this._chatHeader.querySelector(".chat-status-dot");
        if (dot) dot.classList.remove("thinking");
    }

    /**
     * Show a tool chip in the primary chat activity area.
     * @param {string} nodeId
     * @param {string} toolName
     * @param {string} status — 'running' | 'complete' | 'failed'
     * @param {number} [durationMs]
     */
    showToolChip(nodeId, toolName, status, durationMs) {
        let chip = this._activeTools.get(nodeId);
        if (!chip) {
            chip = document.createElement("div");
            chip.className = "tool-chip running";
            chip.innerHTML = `<span class="tool-chip-icon">🔧</span><span>${toolName}</span><span class="spinner"></span>`;
            this._chatActivity.appendChild(chip);
            this._activeTools.set(nodeId, chip);
        }

        if (status === "complete" || status === "completed") {
            chip.className = "tool-chip complete";
            const ms = durationMs != null ? ` · ${durationMs}ms` : "";
            chip.innerHTML = `<span class="tool-chip-icon">✓</span><span>${toolName}${ms}</span>`;
            setTimeout(() => this._activeTools.delete(nodeId), 2000);
        } else if (status === "failed") {
            chip.className = "tool-chip failed";
            chip.innerHTML = `<span class="tool-chip-icon">✗</span><span>${toolName}</span>`;
            this._activeTools.delete(nodeId);
        }
    }

    /** Reset the conversation (clears history). */
    reset() {
        this._messages = [];
        this._chatMessagesInner.innerHTML = "";
        this._chatActivity.innerHTML = "";
        this._activeTools.clear();
        this._streamingEl = null;
        this._streamingText = "";
        this.hideThinking();
    }

    /** @returns {{ messages: ChatMessage[] }} — serialisable state for persistence */
    getState() { return { messages: [...this._messages] }; }

    /** @returns {string|null} */
    get agentName() { return this._agentName; }

    /** Clean up DOM and event listeners. */
    destroy() {
        for (const [el, evt, fn] of this._listeners) el.removeEventListener(evt, fn);
        this._listeners.length = 0;
        this._container.innerHTML = "";
        this._handlers = {};
    }

    /**
     * Register an event handler.
     * Events: 'sseEvent', 'editRequested', 'messageSent'
     * @param {string} event
     * @param {Function} handler
     */
    on(event, handler) {
        (this._handlers[event] ??= []).push(handler);
    }

    /* ─── Private ────────────────────────────────────────── */

    /** @param {string} event @param {any} data */
    _emit(event, data) {
        for (const fn of this._handlers[event] || []) fn(data);
    }

    /** @param {EventTarget} el @param {string} evt @param {EventListener} fn */
    _on(el, evt, fn) {
        el.addEventListener(evt, fn);
        this._listeners.push([el, evt, fn]);
    }

    /**
     * @param {string} role
     * @param {string} content
     */
    _appendMessage(role, content) {
        const div = document.createElement("div");
        if (role === "user") {
            div.className = "chat-msg user";
            div.textContent = content;
        } else if (role === "agent") {
            div.className = "chat-msg agent";
            div.innerHTML = this._marked ? this._marked.parse(content) : content;
        } else if (role === "error") {
            div.className = "chat-msg error-msg";
            div.textContent = content;
        } else {
            div.className = "chat-msg system-msg";
            div.textContent = content;
        }
        this._chatMessagesInner.appendChild(div);
    }

    /**
     * Parse an A2A SSE event (JSON-RPC result) into a normalized event
     * for the delegation tree and chat panel.
     *
     * A2A SSE events have this shape:
     *   { "result": { "kind": "status-update"|"artifact-update", ... } }
     *
     * Returns a normalized event object or null if unhandled.
     *
     * @param {any} event — raw parsed JSON from SSE data line
     * @returns {any|null}
     */
    _handleA2AEvent(event) {
        const result = event?.result;
        if (!result) return null;
        const kind = result.kind;

        if (kind === "status-update") {
            const msg = result.status?.message || {};
            const meta = msg.metadata || {};
            const fwEvent = meta["framework:event"];

            if (fwEvent === "tool_start") {
                const tool = meta["framework:tool"] || "tool";
                const nodeId = `tool:${Date.now()}`;
                const isDelegation = tool === "delegate";
                if (!isDelegation) {
                    this.showToolChip(nodeId, tool, "running");
                }
                return {
                    event: "tool_start",
                    node_id: nodeId,
                    tool,
                    toolCalls: isDelegation ? 0 : 1,
                    delegations: isDelegation ? 1 : 0,
                };
            }

            if (fwEvent === "tool_end") {
                const tool = meta["framework:tool"] || "tool";
                return { event: "tool_end", tool };
            }

            if (fwEvent === "delegation_start") {
                return {
                    event: "delegation_start",
                    node_id: `del:${Date.now()}`,
                    from_agent: meta["framework:from_agent"] || "",
                    to_agent: meta["framework:to_agent"] || "",
                    message: meta["framework:message"] || "",
                };
            }

            if (fwEvent === "delegation_end") {
                return {
                    event: "delegation_end",
                    to_agent: meta["framework:to_agent"] || "",
                    response: meta["framework:response"] || "",
                };
            }

            return null;
        }

        if (kind === "artifact-update") {
            const artifact = result.artifact || {};
            const aname = artifact.name || "";
            // Skip execution-trace artifacts
            if (aname.endsWith("-execution-trace")) return null;
            // Stream text parts into the live message bubble
            for (const part of artifact.parts || []) {
                if (part.kind === "text" && part.text) {
                    this._appendStreamingChunk(part.text);
                }
            }
            return null;
        }

        return null;
    }

    /**
     * Append a text chunk to the in-progress streaming message bubble.
     * Creates the bubble on first call, hides thinking dots.
     * @param {string} chunk
     */
    _appendStreamingChunk(chunk) {
        if (!this._streamingEl) {
            this.hideThinking();
            const div = document.createElement("div");
            div.className = "chat-msg agent streaming";
            this._chatMessagesInner.appendChild(div);
            this._streamingEl = div;
            this._streamingText = "";
        }
        this._streamingText += chunk;
        // Render plain text while streaming (markdown applied on finalize)
        this._streamingEl.textContent = this._streamingText;
        this._chatMessages.scrollTop = this._chatMessages.scrollHeight;
    }

    /**
     * Finalize the streaming message — parse markdown, save to history.
     */
    _finalizeStreamingMessage() {
        if (!this._streamingEl || !this._streamingText) return;
        const text = this._streamingText;
        // Apply markdown rendering
        this._streamingEl.classList.remove("streaming");
        this._streamingEl.innerHTML = this._marked ? this._marked.parse(text) : text;
        // Save to conversation history
        this._messages.push({ role: "agent", content: text });
        this._streamingEl = null;
        this._streamingText = "";
        this._chatMessages.scrollTop = this._chatMessages.scrollHeight;
    }

    _renderContextHeaders() {
        this._contextHeadersBar.innerHTML = "";
        const keys = this._contextHeaders;
        if (!keys.length) {
            this._contextHeadersBar.classList.add("hidden");
            return;
        }
        this._contextHeadersBar.classList.remove("hidden");
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
            const stored = this._storageGet(`ctx:${this._agentName}:${headerName}`);
            if (stored) input.value = stored;
            input.addEventListener("change", () => {
                this._storageSet(`ctx:${this._agentName}:${headerName}`, input.value);
            });
            wrapper.appendChild(input);
            this._contextHeadersBar.appendChild(wrapper);
        }
    }

    /** @returns {Record<string, string>} */
    _getContextHeaderValues() {
        /** @type {Record<string, string>} */
        const headers = {};
        this._contextHeadersBar.querySelectorAll("input.ctx-header-input").forEach((/** @type {HTMLInputElement} */ el) => {
            const name = el.dataset.headerName;
            if (name && el.value.trim()) headers[name] = el.value.trim();
        });
        return headers;
    }

    _clearToolChips() {
        this._activeTools.clear();
        setTimeout(() => { this._chatActivity.innerHTML = ""; }, 2000);
    }

    /** @param {string} key @returns {string|null} */
    _storageGet(key) {
        try { return localStorage.getItem(`${this._storagePrefix}-${key}`); } catch { return null; }
    }

    /** @param {string} key @param {string} val */
    _storageSet(key, val) {
        try { localStorage.setItem(`${this._storagePrefix}-${key}`, val); } catch { }
    }
}
