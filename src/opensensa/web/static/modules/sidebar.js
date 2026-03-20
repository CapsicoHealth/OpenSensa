/* ===========================================================================
 * Copyright (C) 2025 CapsicoHealth Inc. — Apache-2.0
 * =========================================================================== */
// @ts-check

/**
 * Sidebar — Self-contained widget for listing and selecting agents,
 * with collapse/expand behaviour.
 *
 * Usage:
 *   import { Sidebar } from './sidebar.js';
 *   const sidebar = new Sidebar(document.getElementById('sidebar-container'));
 *   sidebar.loadAgents([{ name: 'router', description: 'Routes tasks', model: 'gpt-4o' }]);
 *   sidebar.on('agentSelected', ({ name }) => console.log('selected', name));
 *   sidebar.on('editRequested', ({ name }) => console.log('edit', name));
 *
 * Required CSS: css/sidebar.css  (+ css/tokens.css or custom token values)
 * External JS dependencies: NONE
 */

/**
 * @typedef {Object} SidebarAgent
 * @property {string}   name
 * @property {string}   description
 * @property {string}   model
 * @property {string[]} [tools]
 * @property {string[]} [sub_agents]
 * @property {string[]} [context_headers]
 */

/**
 * @typedef {Object} SidebarAgentInternal
 * @property {SidebarAgent} data
 * @property {HTMLElement}  el
 */

export class Sidebar {
    /** @type {HTMLElement} */  _container;
    /** @type {HTMLElement} */  _sidebarEl;
    /** @type {HTMLElement} */  _listEl;
    /** @type {HTMLElement} */  _refreshBtn;
    /** @type {Map<string, SidebarAgentInternal>} */ _agents = new Map();
    /** @type {string|null} */ _selected = null;
    /** @type {Record<string, Function[]>} */ _handlers = {};
    /** @type {Array<[EventTarget, string, EventListener]>} */ _listeners = [];

    /**
     * @param {HTMLElement} containerEl
     */
    constructor(containerEl) {
        this._container = containerEl;

        this._container.innerHTML = `
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
        <div class="sidebar-list" data-ref="sidebar-list"></div>`;

        this._sidebarEl = this._container;
        this._listEl = /** @type {HTMLElement} */ (this._container.querySelector('[data-ref="sidebar-list"]'));
        this._refreshBtn = /** @type {HTMLElement} */ (this._container.querySelector('[data-ref="btn-refresh-agents"]'));

        // Refresh button
        this._on(this._refreshBtn, "click", async () => {
            this._refreshBtn.classList.add("spinning");
            this._emit("refreshRequested", {});
            setTimeout(() => this._refreshBtn.classList.remove("spinning"), 400);
        });

        // Collapse/expand click on header area
        this._on(this._sidebarEl, "click", (/** @type {MouseEvent} */ e) => {
            if (!this._sidebarEl.classList.contains("collapsed")) return;
            if (/** @type {HTMLElement} */ (e.target).closest(".sidebar-agent")) return;
            this._sidebarEl.classList.toggle("expanded");
        });

        // Close expanded sidebar when clicking outside
        this._on(document, "click", (/** @type {MouseEvent} */ e) => {
            if (!this._sidebarEl.classList.contains("expanded")) return;
            if (!this._sidebarEl.contains(/** @type {Node} */ (e.target))) {
                this._sidebarEl.classList.remove("expanded");
            }
        });
    }

    /* ─── Public API ─────────────────────────────────────── */

    /**
     * Populate the sidebar from a list of agents.
     * Preserves existing entries that are still in the new list.
     * @param {SidebarAgent[]} agentList
     */
    loadAgents(agentList) {
        const incoming = new Set(agentList.map(a => a.name));
        const existing = new Set(this._agents.keys());

        // Remove agents that are no longer present
        for (const name of existing) {
            if (!incoming.has(name)) {
                const entry = this._agents.get(name);
                if (entry?.el) entry.el.remove();
                this._agents.delete(name);
            }
        }

        // Add new agents
        for (const a of agentList) {
            if (this._agents.has(a.name)) continue;

            const el = this._createEntry(a);
            this._listEl.appendChild(el);
            this._agents.set(a.name, { data: a, el });
        }
    }

    /**
     * Programmatically select an agent by name.
     * @param {string} name
     */
    selectAgent(name) {
        if (!this._agents.has(name)) return;
        this._selected = name;
        this._sidebarEl.classList.add("collapsed");
        this._sidebarEl.classList.remove("expanded");

        for (const [n, entry] of this._agents) {
            entry.el.classList.toggle("active", n === name);
        }

        this._emit("agentSelected", { name, agent: this._agents.get(name)?.data });
    }

    /**
     * Highlight an agent as currently being delegated to.
     * @param {string} name
     * @param {boolean} active
     */
    highlightDelegating(name, active) {
        const entry = this._agents.get(name);
        if (entry?.el) entry.el.classList.toggle("delegating", active);
    }

    /** Collapse the sidebar to icon-only mode. */
    collapse() { this._sidebarEl.classList.add("collapsed"); this._sidebarEl.classList.remove("expanded"); }

    /** Expand the sidebar. */
    expand() { this._sidebarEl.classList.remove("collapsed"); }

    /** @returns {string|null} */
    get selected() { return this._selected; }

    /** @returns {SidebarAgent|undefined} */
    getAgent(/** @type {string} */ name) { return this._agents.get(name)?.data; }

    /** @returns {string[]} */
    get agentNames() { return [...this._agents.keys()]; }

    /** @returns {boolean} */
    get hasAgents() { return this._agents.size > 0; }

    /** Reset sidebar — clears all entries + selection. */
    clear() {
        for (const entry of this._agents.values()) entry.el.remove();
        this._agents.clear();
        this._selected = null;
        this._sidebarEl.classList.remove("collapsed");
    }

    /** Remove an agent by name. */
    removeAgent(/** @type {string} */ name) {
        const entry = this._agents.get(name);
        if (entry?.el) entry.el.remove();
        this._agents.delete(name);
        if (this._selected === name) this._selected = null;
    }

    /** Destroy the widget. */
    destroy() {
        for (const [el, evt, fn] of this._listeners) el.removeEventListener(evt, fn);
        this._listeners.length = 0;
        this._container.innerHTML = "";
        this._agents.clear();
        this._handlers = {};
    }

    /**
     * Register an event handler.
     * Events: 'agentSelected', 'editRequested', 'addRequested', 'refreshRequested'
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
     * @param {SidebarAgent} agent
     * @returns {HTMLElement}
     */
    _createEntry(agent) {
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
            this.selectAgent(agent.name);
        });

        const editBtn = el.querySelector(".sidebar-agent-edit");
        editBtn?.addEventListener("click", (e) => {
            e.stopPropagation();
            this._emit("editRequested", { name: agent.name });
        });

        return el;
    }
}
