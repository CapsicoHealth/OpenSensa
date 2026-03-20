/* ===========================================================================
 * Copyright (C) 2025 CapsicoHealth Inc. — Apache-2.0
 * =========================================================================== */
// @ts-check

/**
 * AgentModal — Self-contained CRUD modal for creating/editing/deleting agents.
 *
 * The modal does NOT call APIs itself — it emits events ('submitted', 'deleted')
 * so the parent orchestrator can handle HTTP calls. This makes it fully reusable
 * in any context.
 *
 * Usage:
 *   import { AgentModal } from './agent-modal.js';
 *   const modal = new AgentModal(document.getElementById('modal-host'));
 *   modal.on('submitted', payload => fetch('/api/agents', { body: JSON.stringify(payload) }));
 *   modal.on('deleted', ({ name }) => fetch(`/api/agents/${name}`, { method: 'DELETE' }));
 *   modal.openCreate();
 *   modal.openEdit({ name: 'my-agent', description: 'Helper', ... });
 *
 * Required CSS: css/modal.css  (+ css/tokens.css or custom token values)
 * External JS dependencies: NONE
 */

/**
 * @typedef {Object} AgentFormData
 * @property {string}   name
 * @property {string}   description
 * @property {string}   system_prompt
 * @property {string}   model
 * @property {string[]} tools
 * @property {string[]} sub_agents
 */

const MODAL_TEMPLATE = `
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
</div>`;

export class AgentModal {
    /** @type {HTMLElement} */          _overlay;
    /** @type {HTMLElement} */          _title;
    /** @type {HTMLFormElement} */      _form;
    /** @type {HTMLInputElement} */     _afName;
    /** @type {HTMLInputElement} */     _afDesc;
    /** @type {HTMLTextAreaElement} */  _afPrompt;
    /** @type {HTMLInputElement} */     _afModel;
    /** @type {HTMLInputElement} */     _afTools;
    /** @type {HTMLInputElement} */     _afSubs;
    /** @type {HTMLElement} */          _afSubmit;
    /** @type {HTMLElement} */          _afDelete;

    /** @type {string|null} */                 _editingAgent = null;
    /** @type {Record<string, Function[]>} */  _handlers = {};
    /** @type {Array<[EventTarget, string, EventListener]>} */ _listeners = [];

    /**
     * @param {HTMLElement} containerEl — overlay will be appended inside this element
     */
    constructor(containerEl) {
        this._overlay = document.createElement("div");
        this._overlay.className = "modal-overlay hidden";
        this._overlay.innerHTML = MODAL_TEMPLATE;
        containerEl.appendChild(this._overlay);

        const ref = (/** @type {string} */ n) => /** @type {HTMLElement} */(this._overlay.querySelector(`[data-ref="${n}"]`));
        this._title = ref("modal-title");
        this._form = /** @type {HTMLFormElement} */ (ref("agent-form"));
        this._afName = /** @type {HTMLInputElement} */ (ref("af-name"));
        this._afDesc = /** @type {HTMLInputElement} */ (ref("af-desc"));
        this._afPrompt = /** @type {HTMLTextAreaElement} */ (ref("af-prompt"));
        this._afModel = /** @type {HTMLInputElement} */ (ref("af-model"));
        this._afTools = /** @type {HTMLInputElement} */ (ref("af-tools"));
        this._afSubs = /** @type {HTMLInputElement} */ (ref("af-subs"));
        this._afSubmit = ref("af-submit");
        this._afDelete = ref("af-delete");

        // Event bindings
        this._on(ref("modal-close"), "click", () => this.close());
        this._on(this._overlay, "click", (/** @type {MouseEvent} */ e) => {
            if (e.target === this._overlay) this.close();
        });
        this._on(ref("af-cancel"), "click", () => this.close());
        this._on(this._form, "submit", (/** @type {Event} */ e) => this._onSubmit(e));
        this._on(this._afDelete, "click", () => this._onDelete());
    }

    /* ─── Public API ─────────────────────────────────────── */

    /** Open the modal in "Create" mode with a blank form. */
    openCreate() {
        this._editingAgent = null;
        this._form.reset();
        this._afName.disabled = false;
        this._afSubmit.textContent = "Create";
        this._afDelete.classList.add("hidden");
        this._title.textContent = "New Agent";
        this._overlay.classList.remove("hidden");
    }

    /**
     * Open the modal in "Edit" mode with pre-filled data.
     * @param {{ name: string, description?: string, system_prompt?: string, model?: string, tools?: string[], sub_agents?: string[] }} agentData
     */
    openEdit(agentData) {
        this._editingAgent = agentData.name;
        this._afName.disabled = true;
        this._afSubmit.textContent = "Save";
        this._afDelete.classList.remove("hidden");
        this._title.textContent = `Edit ${agentData.name}`;
        this._overlay.classList.remove("hidden");

        this._afName.value = agentData.name;
        this._afDesc.value = agentData.description || "";
        this._afPrompt.value = agentData.system_prompt || "";
        this._afModel.value = agentData.model || "";
        this._afTools.value = (agentData.tools || []).join(", ");
        this._afSubs.value = (agentData.sub_agents || []).join(", ");
    }

    /** Close the modal. */
    close() {
        this._overlay.classList.add("hidden");
        this._emit("closed", {});
    }

    /** @returns {boolean} */
    get isOpen() { return !this._overlay.classList.contains("hidden"); }

    /** @returns {string|null} — the name of the agent being edited, or null if creating */
    get editingAgent() { return this._editingAgent; }

    /** Destroy the widget. */
    destroy() {
        for (const [el, evt, fn] of this._listeners) el.removeEventListener(evt, fn);
        this._listeners.length = 0;
        this._overlay.remove();
        this._handlers = {};
    }

    /**
     * Register an event handler.
     * Events: 'submitted', 'deleted', 'closed'
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

    /** @param {Event} e */
    _onSubmit(e) {
        e.preventDefault();
        /** @type {AgentFormData} */
        const payload = {
            name: this._afName.value.trim(),
            description: this._afDesc.value.trim() || "Agent",
            system_prompt: this._afPrompt.value.trim(),
            model: this._afModel.value.trim() || "${default}",
            tools: this._afTools.value ? this._afTools.value.split(",").map(s => s.trim()).filter(Boolean) : [],
            sub_agents: this._afSubs.value ? this._afSubs.value.split(",").map(s => s.trim()).filter(Boolean) : [],
        };
        this._emit("submitted", { payload, isEdit: !!this._editingAgent, name: this._editingAgent });
    }

    _onDelete() {
        if (!this._editingAgent) return;
        if (!confirm(`Delete agent "${this._editingAgent}"?`)) return;
        this._emit("deleted", { name: this._editingAgent });
    }
}
