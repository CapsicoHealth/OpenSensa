/* ===========================================================================
 * Copyright (C) 2025 CapsicoHealth Inc. — Apache-2.0
 * =========================================================================== */
// @ts-check

/**
 * DelegationTree — Self-contained widget for rendering an agent-delegation
 * execution tree with tool-chip activity indicators.
 *
 * Usage:
 *   import { DelegationTree } from './delegation-tree.js';
 *   const tree = new DelegationTree(document.getElementById('my-tree'));
 *   tree.startDelegation({ id: '1', fromAgent: 'Router', toAgent: 'Search', message: 'find docs' });
 *   tree.startTool({ delegationId: '1', nodeId: 't1', toolName: 'web_search' });
 *   tree.endTool({ delegationId: '1', nodeId: 't1', toolName: 'web_search', durationMs: 340 });
 *   tree.endDelegation({ id: '1', response: 'Found 3 results.' });
 *   tree.destroy();
 *
 * Required CSS: css/delegation-tree.css  (+ css/tokens.css or custom token values)
 * External JS dependencies: NONE (optionally pass `marked` in options for
 *   markdown rendering of delegation responses; falls back to textContent).
 */

/**
 * @typedef {Object} DelegationTreeOptions
 * @property {any}    [marked]  — marked.js instance for rendering markdown responses
 * @property {string} [hintText] — text shown when tree is empty
 */

/**
 * @typedef {Object} DelegationNodeState
 * @property {string}               id
 * @property {string}               from
 * @property {string}               to
 * @property {HTMLElement}          nodeEl
 * @property {HTMLElement}          messagesEl
 * @property {HTMLElement}          activityEl
 * @property {string}               response
 * @property {HTMLElement|null}     thinkingEl
 * @property {Map<string,HTMLElement>} activeTools
 * @property {DelegationNodeState[]} children
 */

export class DelegationTree {
    /** @type {HTMLElement} */                 _container;
    /** @type {HTMLElement} */                 _treeEl;
    /** @type {HTMLElement} */                 _hintEl;
    /** @type {Map<string, DelegationNodeState>} */ _active = new Map();
    /** @type {Record<string, Function[]>} */ _handlers = {};
    /** @type {any} */                        _marked;

    /**
     * @param {HTMLElement} containerEl — the element to render inside
     * @param {DelegationTreeOptions} [options]
     */
    constructor(containerEl, options = {}) {
        this._container = containerEl;
        this._marked = options.marked || null;

        // Build own DOM
        const hintText = options.hintText || "Delegations appear here when agents hand off tasks";
        this._container.innerHTML = `
            <div class="tree-panel-header">
                <span class="tree-panel-title">Delegation Tree</span>
                <span class="tree-panel-hint">${hintText}</span>
            </div>
            <div class="delegation-tree"></div>`;

        this._hintEl = /** @type {HTMLElement} */ (this._container.querySelector(".tree-panel-hint"));
        this._treeEl = /** @type {HTMLElement} */ (this._container.querySelector(".delegation-tree"));
    }

    /* ─── Public API ─────────────────────────────────────── */

    /**
     * Create a new delegation node.
     * @param {{ id: string, fromAgent: string, toAgent: string, message?: string, parentId?: string }} opts
     * @returns {DelegationNodeState}
     */
    startDelegation({ id, fromAgent, toAgent, message = "", parentId }) {
        let parentContainer = this._treeEl;
        if (parentId) {
            const parent = this._active.get(parentId);
            if (parent) parentContainer = this._getChildContainer(parent);
        } else {
            // find parent by matching `toAgent === del.to` pattern (same as legacy)
            for (const del of this._active.values()) {
                if (del.to === fromAgent) {
                    parentContainer = this._getChildContainer(del);
                    break;
                }
            }
        }

        const node = document.createElement("div");
        node.className = "delegation-node";
        node.dataset.nodeId = id;

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

        const msgsEl = /** @type {HTMLElement} */ (node.querySelector(".delegation-card-messages"));
        const activityEl = /** @type {HTMLElement} */ (node.querySelector(".delegation-card-activity"));

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

        /** @type {DelegationNodeState} */
        const state = {
            id, from: fromAgent, to: toAgent,
            nodeEl: node, messagesEl: msgsEl, activityEl,
            response: "", thinkingEl, activeTools: new Map(), children: [],
        };
        this._active.set(id, state);
        this._updateHint();

        this._emit("delegationStart", { id, fromAgent, toAgent });

        setTimeout(() => node.scrollIntoView({ behavior: "smooth", block: "nearest" }), 100);
        return state;
    }

    /**
     * Complete a delegation node.
     * @param {{ id: string, response?: string }} opts
     */
    endDelegation({ id, response }) {
        const del = this._active.get(id);
        if (!del) return;

        if (response != null) del.response = response;

        if (del.thinkingEl) { del.thinkingEl.remove(); del.thinkingEl = null; }

        if (del.response && del.messagesEl) {
            const msgDiv = document.createElement("div");
            msgDiv.className = "chat-msg agent";
            msgDiv.style.fontSize = "12px";
            msgDiv.style.maxWidth = "95%";
            if (this._marked) {
                msgDiv.innerHTML = this._marked.parse(del.response);
            } else {
                msgDiv.textContent = del.response;
            }
            del.messagesEl.appendChild(msgDiv);
        }

        const card = del.nodeEl.querySelector(".delegation-card");
        if (card) { card.classList.remove("active"); card.classList.add("completed"); }

        const arrow = del.nodeEl.querySelector(".delegation-connector-arrow");
        if (arrow) {
            arrow.innerHTML = `
                <circle cx="7" cy="7" r="5" fill="var(--success-bg)" stroke="var(--success)" stroke-width="1.5"/>
                <path d="M4.5 7l2 2 3-3.5" stroke="var(--success)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`;
        }

        this._emit("delegationEnd", { id, toAgent: del.to });
        this._active.delete(id);
        this._updateHint();
    }

    /**
     * Show a running tool chip inside a delegation card.
     * @param {{ delegationId: string, nodeId: string, toolName: string }} opts
     */
    startTool({ delegationId, nodeId, toolName }) {
        const del = this._active.get(delegationId);
        if (!del) return;
        this._showToolChip(nodeId, toolName, "running", undefined, del.activityEl, del.activeTools);
    }

    /**
     * Complete a tool chip inside a delegation card.
     * @param {{ delegationId: string, nodeId: string, toolName: string, durationMs?: number }} opts
     */
    endTool({ delegationId, nodeId, toolName, durationMs }) {
        const del = this._active.get(delegationId);
        if (!del) return;
        this._showToolChip(nodeId, toolName, "complete", durationMs, del.activityEl, del.activeTools);
    }

    /** End all active delegations (e.g. on turn_complete or turn_error). */
    endAll() {
        for (const [id] of this._active) this.endDelegation({ id });
    }

    /** Clear the tree completely. */
    clear() {
        this._treeEl.innerHTML = "";
        this._active.clear();
        this._updateHint();
    }

    /**
     * Get the DelegationNodeState for a delegation by ID.
     * @param {string} id
     * @returns {DelegationNodeState|undefined}
     */
    get(id) { return this._active.get(id); }

    /** @returns {boolean} */
    get hasActive() { return this._active.size > 0; }

    /** Clean up DOM and internal state. */
    destroy() {
        this._container.innerHTML = "";
        this._active.clear();
        this._handlers = {};
    }

    /**
     * Register an event handler.
     * Events: 'delegationStart', 'delegationEnd'
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

    _updateHint() {
        const hasDelegations = this._treeEl.children.length > 0;
        this._hintEl.style.display = hasDelegations ? "none" : "block";
    }

    /**
     * @param {DelegationNodeState} parentDel
     * @returns {HTMLElement}
     */
    _getChildContainer(parentDel) {
        let nested = /** @type {HTMLElement|null} */ (parentDel.nodeEl.querySelector(".delegation-nested"));
        if (!nested) {
            nested = document.createElement("div");
            nested.className = "delegation-nested delegation-tree";
            parentDel.nodeEl.appendChild(nested);
        }
        return nested;
    }

    /**
     * @param {string} nodeId
     * @param {string} toolName
     * @param {string} status
     * @param {number|undefined} durationMs
     * @param {HTMLElement} area
     * @param {Map<string, HTMLElement>} toolMap
     */
    _showToolChip(nodeId, toolName, status, durationMs, area, toolMap) {
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
            setTimeout(() => toolMap.delete(nodeId), 2000);
        } else if (status === "failed") {
            chip.className = "tool-chip failed";
            chip.innerHTML = `<span class="tool-chip-icon">✗</span><span>${toolName}</span>`;
            toolMap.delete(nodeId);
        }
    }
}
