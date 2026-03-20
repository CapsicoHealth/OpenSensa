/* ===========================================================================
 * Copyright (C) 2025 CapsicoHealth Inc. — Apache-2.0
 * =========================================================================== */
// @ts-check

/**
 * API client — thin convenience wrapper around fetch for OpenSensa REST endpoints.
 *
 * Not a dependency for any widget. Only the orchestrator (app.js) uses this to
 * wire widget events to server calls.
 *
 * Usage:
 *   import { createApi } from './api.js';
 *   const api = createApi('https://my-server.com');
 *   const agents = await api.fetchAgents();
 */

/**
 * @typedef {Object} OpenSensaApi
 * @property {() => Promise<any[]>} fetchAgents
 * @property {(name: string) => Promise<any>} fetchAgent
 * @property {(body: any) => Promise<any>} createAgent
 * @property {(name: string, body: any) => Promise<any>} updateAgent
 * @property {(name: string) => Promise<any>} deleteAgent
 */

/**
 * Create an API client bound to a base URL.
 * @param {string} [baseUrl=""]
 * @returns {OpenSensaApi}
 */
export function createApi(baseUrl = "") {
    const base = baseUrl.replace(/\/+$/, "");

    /** @param {string} path @param {RequestInit} [opts] */
    const request = (path, opts = {}) =>
        fetch(base + path, { headers: { "Content-Type": "application/json" }, ...opts });

    return {
        async fetchAgents() {
            const res = await request("/api/agents");
            return res.json();
        },

        async fetchAgent(name) {
            const res = await request(`/api/agents/${name}`);
            return res.json();
        },

        async createAgent(body) {
            const res = await request("/api/agents", {
                method: "POST",
                body: JSON.stringify(body),
            });
            return res.json();
        },

        async updateAgent(name, body) {
            const res = await request(`/api/agents/${name}`, {
                method: "PUT",
                body: JSON.stringify(body),
            });
            return res.json();
        },

        async deleteAgent(name) {
            const res = await request(`/api/agents/${name}`, { method: "DELETE" });
            return res.json();
        },
    };
}
