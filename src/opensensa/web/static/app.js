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
/* ── OpenSensa · ES6 Orchestrator — mount(rootEl, options) ─ */

/**
 * Thin orchestrator that wires self-contained widget modules together.
 * Each widget (Sidebar, ChatPanel, DelegationTree, AgentModal) is a
 * standalone class that owns its own DOM, state, and lifecycle.
 *
 * Individual widgets can be extracted and used independently — see each
 * module's JSDoc header for standalone usage instructions.
 */

import { Sidebar } from "./modules/sidebar.js";
import { ChatPanel } from "./modules/chat-panel.js";
import { DelegationTree } from "./modules/delegation-tree.js";
import { AgentModal } from "./modules/agent-modal.js";
import { createApi } from "./modules/api.js";

/**
 * @typedef {Object} OpenSensaOptions
 * @property {string}  [baseUrl=""]               — API base URL prefix
 * @property {string}  [storagePrefix="opensensa"] — localStorage key prefix
 * @property {any}     [marked]                    — marked.js instance
 * @property {any}     [hljs]                      — highlight.js instance
 */

/* ════════════════════════════════════════════════════════════
   Layout skeleton (toolbar + 3-column flex container)
   ════════════════════════════════════════════════════════════ */
const LAYOUT = `
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
    <aside class="sidebar" data-ref="sidebar-container"></aside>
    <main class="main-area" data-ref="chat-container"></main>
    <div class="tree-link-arrow" data-ref="tree-link-arrow">
        <svg viewBox="0 0 28 60" fill="none" width="28" height="60">
            <path d="M4 0 v24 Q4 30 10 30 h8 Q22 30 22 36 v24" stroke="var(--accent-light)" stroke-width="2" fill="none"/>
            <circle cx="22" cy="58" r="3" fill="var(--accent)"/>
        </svg>
    </div>
    <aside class="tree-panel" data-ref="tree-container"></aside>
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

    // ── Inject layout skeleton ───────────────────────────────
    rootEl.classList.add("root");
    rootEl.innerHTML = LAYOUT;

    const ref = (/** @type {string} */ n) =>
        /** @type {HTMLElement} */(rootEl.querySelector(`[data-ref="${n}"]`));

    // ── Instantiate widgets ──────────────────────────────────
    const api = createApi(baseUrl);
    const sidebar = new Sidebar(ref("sidebar-container"));
    const chat = new ChatPanel(ref("chat-container"), { baseUrl, storagePrefix, marked, hljs });
    const tree = new DelegationTree(ref("tree-container"), { marked });
    const modal = new AgentModal(rootEl);

    const treeLinkArrow = ref("tree-link-arrow");

    // Per-agent state (message history) stored in orchestrator
    /** @type {Map<string, { messages: Array<{role:string,content:string}>, contextHeaders: string[] }>} */
    const agentState = new Map();

    // ── Helpers ──────────────────────────────────────────────
    function updateTreeArrow() {
        treeLinkArrow.classList.toggle("visible", tree.hasActive);
    }

    async function loadAndShowAgents() {
        try {
            const agentList = await api.fetchAgents();
            if (!Array.isArray(agentList) || agentList.length === 0) {
                chat.showEmpty();
                return;
            }
            sidebar.loadAgents(agentList);
            // Store context_headers per agent
            for (const a of agentList) {
                if (!agentState.has(a.name)) {
                    agentState.set(a.name, { messages: [], contextHeaders: a.context_headers || [] });
                }
            }
        } catch (err) {
            console.error("opensensa loadAgents:", err);
        }
    }

    // ── Wire sidebar events ──────────────────────────────────
    sidebar.on("agentSelected", (/** @type {{name: string, agent: any}} */ { name, agent }) => {
        const state = agentState.get(name);
        chat.setAgent(
            { name, model: agent?.model || "", contextHeaders: state?.contextHeaders || agent?.context_headers || [] },
            state ? { messages: state.messages } : undefined,
        );
        tree.clear();
        updateTreeArrow();
    });

    sidebar.on("editRequested", async (/** @type {{name: string}} */ { name }) => {
        try {
            const data = await api.fetchAgent(name);
            modal.openEdit(data);
        } catch { modal.openEdit({ name }); }
    });

    sidebar.on("refreshRequested", async () => {
        sidebar.clear();
        chat.showEmpty();
        tree.clear();
        agentState.clear();
        updateTreeArrow();
        await loadAndShowAgents();
    });

    // ── Wire chat events ─────────────────────────────────────
    chat.on("editRequested", async (/** @type {string} */ name) => {
        try {
            const data = await api.fetchAgent(name);
            modal.openEdit(data);
        } catch { modal.openEdit({ name }); }
    });

    // SSE event routing — delegation and tool events go to the tree widget
    chat.on("sseEvent", (/** @type {any} */ evt) => {
        switch (evt.event) {
            case "turn_complete":
            case "turn_error":
                tree.endAll();
                updateTreeArrow();
                // Save messages back to orchestrator state
                if (chat.agentName) {
                    const s = agentState.get(chat.agentName);
                    if (s) s.messages = chat.getState().messages;
                }
                break;

            case "tool_start":
                // Tool chips for direct (non-delegation) tools are handled
                // inside chat-panel.js _handleA2AEvent already
                break;

            case "tool_end":
                break;

            case "delegation_start":
                tree.startDelegation({
                    id: evt.node_id,
                    fromAgent: evt.from_agent || sidebar.selected || "",
                    toAgent: evt.to_agent,
                    message: evt.message || "",
                });
                updateTreeArrow();
                break;

            case "delegation_end":
                tree.endDelegation({ id: evt.node_id, response: evt.response || "" });
                updateTreeArrow();
                break;

            default: break;
        }
    });

    // ── Wire delegation tree events ──────────────────────────
    tree.on("delegationStart", (/** @type {{toAgent: string}} */ { toAgent }) => {
        sidebar.highlightDelegating(toAgent, true);
    });

    tree.on("delegationEnd", (/** @type {{toAgent: string}} */ { toAgent }) => {
        sidebar.highlightDelegating(toAgent, false);
    });

    // ── Wire modal events ────────────────────────────────────
    modal.on("submitted", async (/** @type {{payload: any, isEdit: boolean, name: string|null}} */ { payload, isEdit, name }) => {
        try {
            if (isEdit && name) await api.updateAgent(name, payload);
            else await api.createAgent(payload);
            modal.close();
            // Reload agents
            sidebar.clear();
            chat.showEmpty();
            tree.clear();
            agentState.clear();
            updateTreeArrow();
            await loadAndShowAgents();
        } catch (err) { alert("Failed: " + /** @type {Error} */ (err).message); }
    });

    modal.on("deleted", async (/** @type {{name: string}} */ { name }) => {
        try {
            await api.deleteAgent(name);
            modal.close();
            sidebar.removeAgent(name);
            agentState.delete(name);
            if (sidebar.selected === name || chat.agentName === name) {
                const remaining = sidebar.agentNames;
                if (remaining.length > 0) sidebar.selectAgent(remaining[0]);
                else { chat.showEmpty(); sidebar.expand(); }
            }
        } catch (err) { alert("Failed: " + /** @type {Error} */ (err).message); }
    });

    // ── Toolbar "New Agent" button ───────────────────────────
    ref("btn-add-agent").addEventListener("click", () => modal.openCreate());

    // ── Init ─────────────────────────────────────────────────
    loadAndShowAgents();

    // ── Destroy — cleanup for unmount ────────────────────────
    return {
        destroy() {
            sidebar.destroy();
            chat.destroy();
            tree.destroy();
            modal.destroy();
            rootEl.classList.remove("root");
            rootEl.innerHTML = "";
        },
    };
}
