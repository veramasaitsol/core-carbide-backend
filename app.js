'use strict';

// =====================
// CONFIG
// =====================
// Prefer the current origin (useful when running locally) and keep fallbacks.
const HOST_BASE = (location.origin || (location.protocol + '//' + location.host)).replace(/\/+$/, '') + '/machinewin_php';
const CONFIG = {
    baseUrls: [
        HOST_BASE,
        'http://localhost/machinewin_php',
        'http://172.67.121.5/machinewin_php',
    ],
    baseUrl: HOST_BASE,
};

const originalFetch = window.fetch.bind(window);

function getApiPath(resource) {
    const urlString = typeof resource === 'string' ? resource : resource.url;
    for (const base of CONFIG.baseUrls) {
        const normalizedBase = base.replace(/\/+$/, '') + '/';
        if (urlString.startsWith(normalizedBase)) {
            return urlString.slice(normalizedBase.length);
        }
    }
    return null;
}

async function fetchWithFallback(resource, init = {}) {
    // If resource is an absolute URL pointing at another host but contains
    // the app base path, rewrite it to the local HOST_BASE so local setups
    // won't keep contacting a remote IP and suffer latency.
    if (typeof resource === 'string') {
        try {
            const u = new URL(resource, location.href);
            if (u.pathname.includes('/machinewin_php') && u.hostname !== location.hostname) {
                const rel = u.pathname.split('/machinewin_php')[1] || '';
                resource = HOST_BASE.replace(/\/+$/, '') + rel + (u.search || '') + (u.hash || '');
            }
        } catch (e) {
            // ignore invalid URLs (relative paths)
        }
    }

    const path = getApiPath(resource);
    if (!path) {
        return originalFetch(resource, init);
    }

    const timeoutMs = typeof init.timeout === 'number' ? init.timeout : 8000;
    let lastError;
    for (const base of CONFIG.baseUrls) {
        const url = base.replace(/\/+$/, '') + '/' + path.replace(/^\/+/, '');
        const controller = new AbortController();
        const sig = controller.signal;
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const mergedInit = {...init, signal: sig };
            const response = await originalFetch(url, mergedInit);
            clearTimeout(timer);
            if (response.ok || response.status < 500) {
                CONFIG.baseUrl = base;
                return response;
            }
            lastError = new Error(`Request failed with status ${response.status}`);
        } catch (error) {
            clearTimeout(timer);
            // convert AbortError to a clearer message
            if (error.name === 'AbortError') lastError = new Error('Request timed out');
            else lastError = error;
        }
    }

    throw lastError || new Error('Request failed for all configured base URLs');
}

window.fetch = fetchWithFallback;

// =====================
// STATE
// =====================
const state = {
    intervals: [],
    theme: localStorage.getItem('theme') || 'light',
    dropdownOpen: false,
    currentPath: '',
    machines: [],
    _reportSubTab: 'oee',
    _dataEntriesSubTab: 'production',
};

// =====================
// THEME MANAGEMENT
// =====================
function initTheme() {
    const theme = state.theme;
    document.documentElement.setAttribute('data-theme', theme);
    updateThemeIcon();
}

function updateThemeIcon() {
    const btn = $('theme-toggle');
    if (!btn) return;
    btn.innerHTML = state.theme === 'dark' ? ICONS.sun : ICONS.moon;
    btn.title = state.theme === 'dark' ? 'Switch to Light Theme' : 'Switch to Dark Theme';
}

function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', state.theme);
    document.documentElement.setAttribute('data-theme', state.theme);
    updateThemeIcon();
}

// =====================
function $(id) { return document.getElementById(id); }

function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
}

function formatDate(d) {
    if (!d) return '-';
    const date = new Date(d);
    return date.toLocaleDateString('en-IN') + ' ' + date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDateInput(date) {
    const d = new Date(date);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function getMachineDisplayName(machine) {
    if (!machine) return 'Machine';
    return machine.oem_name ||
        machine.machine_name ||
        machine.mname ||
        machine.name ||
        machine.vfj_no ||
        (machine.machine_id ? `M${machine.machine_id}` : 'Machine');
}

function todayStart() {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return formatDateInput(d);
}

function todayEnd() {
    const d = new Date();
    d.setHours(23, 59, 59, 999);
    return formatDateInput(d);
}
// FIX #7 — default last 24 hours
function last24hStart() {
    const d = new Date();
    d.setHours(d.getHours() - 24);
    return formatDateInput(d);
}

function nowDatetime() { return formatDateInput(new Date()); }

// Safe array helper — prevents .map is not a function
function toArray(val) {
    if (Array.isArray(val)) return val;
    if (val && typeof val === 'object') {
        // try common wrapper keys
        for (const k of['data', 'records', 'items', 'results', 'list']) {
            if (Array.isArray(val[k])) return val[k];
        }
    }
    return [];
}

// =====================
// PDF EXPORT  (FIX #8)
// =====================
function exportToPDF(title, tableId, extraInfo = '') {
    const table = document.getElementById(tableId);
    if (!table) { showToast('No table found to export', 'error'); return; }
    const win = window.open('', '_blank', 'width=1000,height=700');
    win.document.write(`<!DOCTYPE html><html><head><title>${title}</title>
<style>
  body{font-family:Arial,sans-serif;padding:24px;color:#111;font-size:12px}
  h1{font-size:18px;margin:0 0 4px}
  .meta{color:#555;font-size:11px;margin-bottom:16px}
  table{border-collapse:collapse;width:100%}
  th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}
  th{background:#e8f0fe;font-weight:600}
  tr:nth-child(even){background:#f9f9f9}
  .print-btn{margin-top:16px;padding:8px 20px;background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px}
  @media print{.print-btn{display:none}}
</style></head><body>
<h1>${title}</h1>
<div class="meta">Generated: ${new Date().toLocaleString()}${extraInfo ? ' | ' + extraInfo : ''}</div>
${table.outerHTML}
<br>
<button class="print-btn" onclick="window.print()">&#128438; Print / Save as PDF</button>
</body></html>`);
    win.document.close();
}

// =====================
// TOAST
// =====================
function showToast(msg, type = 'success') {
    const c = $('toast-container');
    if (!c) return;
    const t = el('div', `toast toast-${type}`, msg);
    c.appendChild(t);
    setTimeout(() => t.remove(), 3500);
}

// =====================
// AUTH
// =====================
const auth = {
    getToken: () => localStorage.getItem('token'),
    getUser: () => { try { return JSON.parse(localStorage.getItem('user') || 'null'); } catch { return null; } },
    setAuth: (token, user) => {
        localStorage.setItem('token', token);
        localStorage.setItem('user', JSON.stringify(user));
    },
    clearAuth: () => {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
    },
    isAuthenticated: () => !!localStorage.getItem('token'),
    getRole: () => { const u = auth.getUser(); return u ? u.role : null; },
    getHeaders: () => ({ 'Content-Type': 'application/json', 'Authorization': `Bearer ${auth.getToken()}` }),
};

// =====================
// ROUTER
// =====================
const router = {
    navigate(path) { window.location.hash = '#' + path; },
    getPath() {
        const h = window.location.hash;
        if (!h || h === '#' || h === '#/') return '/';
        return h.slice(1) || '/';
    },
    init() {
        window.addEventListener('hashchange', () => router.route(router.getPath()));
        router.route(router.getPath());
    },
    route(path) {
        state.intervals.forEach(clearInterval);
        state.intervals = [];
        state.currentPath = path;
        if (!auth.isAuthenticated() && path !== '/login') { router.navigate('/login'); return; }
        if (path === '/login') { renderLogin(); return; }
        const role = auth.getRole();
        if (role === 'admin') {
            if (path === '/') { renderAdminRoot(); return; }
            if (path === '/overview') { renderWithMonitoringLayout('overview'); return; }
            if (path === '/machine') { renderWithMonitoringLayout('machine'); return; }
            if (path === '/parameter') { renderWithMonitoringLayout('parameter'); return; }
            if (path === '/machinedetail') { renderWithMonitoringLayout('machinedetail'); return; }
            if (path === '/machinestatus') { renderWithMonitoringLayout('machinestatus'); return; }
            if (path === '/signal') { renderWithMonitoringLayout('signal'); return; }
            if (path === '/alarmmonitoring') { renderWithMonitoringLayout('alarmmonitoring'); return; }
            if (path === '/groupresult') { renderWithResultLayout('groupresult'); return; }
            if (path === '/operationresult') { renderWithResultLayout('operationresult'); return; }
            if (path === '/productionresult') { renderWithResultLayout('productionresult'); return; }
            if (path === '/power') { renderWithResultLayout('power'); return; }
            if (path === '/breakdown') { renderWithResultLayout('breakdown'); return; }
            if (path === '/report') { renderWithDiagLayout('report'); return; }
            if (path === '/dataentries') { renderWithDiagLayout('dataentries'); return; }
            if (path === '/alarm') { renderWithDiagLayout('alarm'); return; }
            if (path === '/setting') { renderWithDiagLayout('setting'); return; }
            if (path === '/user') { renderWithDiagLayout('user'); return; }
            if (path === '/profile') { renderProfile(); return; }
        }
        if (role === 'Operator') {
            if (path === '/Operator') { renderOperatorRoot(); return; }
            if (path === '/Operator/overview') { renderWithOperatorMonitoringLayout('overview'); return; }
            if (path === '/Operator/machine') { renderWithOperatorMonitoringLayout('machine'); return; }
            if (path === '/Operator/parameter') { renderWithOperatorMonitoringLayout('parameter'); return; }
            if (path === '/Operator/machinedetail') { renderWithOperatorMonitoringLayout('machinedetail'); return; }
            if (path === '/Operator/machinestatus') { renderWithOperatorMonitoringLayout('machinestatus'); return; }
            if (path === '/Operator/signal') { renderWithOperatorMonitoringLayout('signal'); return; }
            if (path === '/Operator/alarmmonitoring') { renderWithOperatorMonitoringLayout('alarmmonitoring'); return; }
            if (path === '/Operator/groupresult') { renderWithOperatorResultLayout('groupresult'); return; }
            if (path === '/Operator/operationresult') { renderWithOperatorResultLayout('operationresult'); return; }
            if (path === '/Operator/productionresult') { renderWithOperatorResultLayout('productionresult'); return; }
            if (path === '/Operator/power') { renderWithOperatorResultLayout('power'); return; }
            if (path === '/Operator/breakdown') { renderWithOperatorResultLayout('breakdown'); return; }
            if (path === '/Operator/report') { renderWithOperatorDiagLayout('report'); return; }
            if (path === '/Operator/dataentries') { renderWithOperatorDiagLayout('dataentries'); return; }
            if (path === '/Operator/alarm') { renderWithOperatorDiagLayout('alarm'); return; }
            if (path === '/Operator/setting') { renderWithOperatorDiagLayout('setting'); return; }
            if (path === '/Operator/user') { renderWithOperatorDiagLayout('user'); return; }
            if (path === '/Operator/profile') { renderProfile(); return; }
        }
        router.navigate('/login');
    }
};

// =====================
// SVG ICONS (inline)
// =====================
const ICONS = {
    back: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 8 8 12 12 16"/><line x1="16" y1="12" x2="8" y2="12"/></svg>`,
    profile: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    eye: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
    eyeOff: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`,
    activity: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,
    fileText: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`,
    stethoscope: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4.8 2.3A.3.3 0 1 0 5 2H4a2 2 0 0 0-2 2v5a6 6 0 0 0 6 6v0a6 6 0 0 0 6-6V4a2 2 0 0 0-2-2h-1a.2.2 0 1 0 .3.3"/><path d="M8 15v1a6 6 0 0 0 6 6v0a6 6 0 0 0 6-6v-4"/><circle cx="20" cy="10" r="2"/></svg>`,
    search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
    trash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>`,
    edit: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
    view: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
    warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
    logout: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
    refresh: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
    layout: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
    group: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    monitor: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`,
    signal: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="1" y1="6" x2="1" y2="18"/><line x1="6" y1="3" x2="6" y2="21"/><line x1="11" y1="8" x2="11" y2="16"/><line x1="16" y1="5" x2="16" y2="19"/><line x1="21" y1="10" x2="21" y2="14"/></svg>`,
    alarm: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`,
    layers: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
    zap: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
    trending: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>`,
    database: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>`,
    clock: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    history: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><line x1="12" y1="7" x2="12" y2="12"/><line x1="12" y1="12" x2="15" y2="15"/></svg>`,
    settings: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
    user: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
    cpu: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>`,
    checkCircle: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
    target: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>`,
    trendingUp: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>`,
    sun: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`,
    moon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`,
};

function svgIcon(name, size = 18, color = 'currentColor') {
    const raw = ICONS[name] || '';
    const svg = raw.replace('<svg ', `<svg width="${size}" height="${size}" `);
    return `<span style="display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;color:${color}">${svg}</span>`;
}

// =====================
// CHARTS
// =====================
function createBarChart({ data, width = 700, height = 250, margin = { top: 20, right: 20, bottom: 40, left: 50 } }) {
    const W = width - margin.left - margin.right;
    const H = height - margin.top - margin.bottom;
    const keys = data.keys || [];
    const items = data.items || [];
    const colors = data.colors || ['#22c55e', '#f97316', '#3b82f6', '#9333ea'];
    const maxVal = Math.max(100, ...items.flatMap(item => keys.map(k => item[k] || 0)));
    const barW = Math.max(8, Math.floor(W / ((items.length || 1) * (keys.length + 0.5)) - 2));
    const groupW = barW * keys.length + 8;
    let bars = '',
        xLabels = '',
        yLines = '';
    for (let i = 0; i <= 5; i++) {
        const y = H - (i / 5) * H,
            val = Math.round((i / 5) * maxVal);
        yLines += `<line x1="0" y1="${y.toFixed(1)}" x2="${W}" y2="${y.toFixed(1)}" stroke="#e5e7eb" stroke-dasharray="4,4"/>`;
        yLines += `<text x="-8" y="${(y+4).toFixed(1)}" text-anchor="end" font-size="10" fill="#6b7280">${val}</text>`;
    }
    items.forEach((item, i) => {
        const gx = i * (groupW + 8);
        keys.forEach((k, j) => {
            const val = item[k] || 0,
                bH = Math.max(0, (val / maxVal) * H),
                by = H - bH,
                bx = gx + j * (barW + 2);
            bars += `<rect x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${barW}" height="${bH.toFixed(1)}" fill="${colors[j%colors.length]}" rx="3"><title>${k}: ${val}</title></rect>`;
        });
        xLabels += `<text x="${(gx+groupW/2).toFixed(1)}" y="${H+16}" text-anchor="middle" font-size="10" fill="#6b7280">${item.name||''}</text>`;
    });
    const totalW = items.length * (groupW + 8);
    const svgW = Math.max(totalW + margin.left + margin.right, width);
    const legend = keys.map((k, i) => `<rect x="${i*120}" y="0" width="12" height="12" fill="${colors[i%colors.length]}" rx="2"/><text x="${i*120+16}" y="10" font-size="11" fill="#374151">${k}</text>`).join('');
    return `<div style="overflow-x:auto"><svg width="${svgW}" height="${height+40}" xmlns="http://www.w3.org/2000/svg">
    <g transform="translate(${margin.left},${margin.top})">${yLines}${bars}${xLabels}
      <line x1="0" y1="0" x2="0" y2="${H}" stroke="#d1d5db"/>
      <line x1="0" y1="${H}" x2="${W}" y2="${H}" stroke="#d1d5db"/>
    </g>
    <g transform="translate(${margin.left},${height+10})">${legend}</g>
  </svg></div>`;
}

function createLineChart({ data, labels, width = 700, height = 220, colors = ['#3b82f6', '#22c55e', '#f97316'] }) {
    const margin = { top: 20, right: 20, bottom: 30, left: 50 };
    const W = width - margin.left - margin.right,
        H = height - margin.top - margin.bottom;
    const allVals = data.flatMap(s => s.values || []);
    const maxVal = Math.max(100, ...allVals);
    const n = labels.length;
    const xScale = i => (n > 1) ? (i / (n - 1)) * W : W / 2;
    const yScale = v => H - (v / maxVal) * H;
    let lines = '';
    data.forEach((series, si) => {
        const pts = (series.values || []).map((v, i) => `${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`).join(' ');
        lines += `<polyline points="${pts}" fill="none" stroke="${colors[si%colors.length]}" stroke-width="2"/>`;
        (series.values || []).forEach((v, i) => {
            lines += `<circle cx="${xScale(i).toFixed(1)}" cy="${yScale(v).toFixed(1)}" r="3" fill="${colors[si%colors.length]}"><title>${series.name}: ${v}</title></circle>`;
        });
    });
    let xLabels = '';
    labels.forEach((l, i) => { if (i % Math.ceil(n / 8) === 0) xLabels += `<text x="${xScale(i).toFixed(1)}" y="${H+14}" text-anchor="middle" font-size="9" fill="#6b7280">${l}</text>`; });
    let yLines = '';
    for (let i = 0; i <= 4; i++) {
        const y = H - (i / 4) * H;
        yLines += `<line x1="0" y1="${y.toFixed(1)}" x2="${W}" y2="${y.toFixed(1)}" stroke="#f3f4f6"/><text x="-6" y="${(y+4).toFixed(1)}" text-anchor="end" font-size="9" fill="#9ca3af">${Math.round((i/4)*maxVal)}</text>`;
    }
    const legend = data.map((s, i) => `<rect x="${i*120}" y="0" width="12" height="4" fill="${colors[i%colors.length]}"/><text x="${i*120+16}" y="9" font-size="11" fill="#374151">${s.name}</text>`).join('');
    return `<div style="overflow-x:auto"><svg width="${width}" height="${height+30}" xmlns="http://www.w3.org/2000/svg">
    <g transform="translate(${margin.left},${margin.top})">${yLines}${lines}${xLabels}
      <line x1="0" y1="0" x2="0" y2="${H}" stroke="#e5e7eb"/>
      <line x1="0" y1="${H}" x2="${W}" y2="${H}" stroke="#e5e7eb"/>
    </g>
    <g transform="translate(${margin.left},${height+15})">${legend}</g>
  </svg></div>`;
}

// =====================
// TIME CLOCK
// =====================
function startClock() {
    function updateClock() {
        const e = document.querySelector('.header-center .time-display');
        if (e) e.textContent = formatDate(new Date());
    }
    updateClock();
    const id = setInterval(updateClock, 10000);
    state.intervals.push(id);
}

// =====================
// PROFILE DROPDOWN
// =====================
function initProfileDropdown() {
    const icon = document.querySelector('.profile-icon');
    const dd = document.querySelector('.profile-dropdown');
    if (!icon || !dd) return;
    icon.addEventListener('click', e => {
        e.stopPropagation();
        dd.style.display = dd.style.display === 'block' ? 'none' : 'block';
    });
    document.addEventListener('click', () => { if (dd) dd.style.display = 'none'; });
}

function headerNavBtnActive(path) {
    const monitoring = ['overview', 'machine', 'parameter', 'machinedetail', 'machinestatus', 'signal', 'alarmmonitoring'];
    const result = ['groupresult', 'power', 'productionresult', 'operationresult', 'breakdown'];
    const diag = ['report', 'dataentries', 'alarm', 'setting', 'user'];
    const seg = path.split('/').filter(Boolean).pop() || '';
    if (monitoring.includes(seg)) return 'monitoring';
    if (result.includes(seg)) return 'result';
    if (diag.includes(seg)) return 'diagnosis';
    return '';
}

// =====================
// LAYOUT BUILDERS
// =====================
function renderAppShell(headerHtml, contentHtml, footerHtml = '') {
    $('app').innerHTML = `<div class="app-container">${headerHtml}<div class="main-content" id="page-content">${contentHtml}</div>${footerHtml}</div>`;
    setTimeout(() => {
        const themeBtn = $('theme-toggle');
        if (themeBtn) themeBtn.onclick = toggleTheme;
        initTheme();
        initProfileDropdown();
    }, 50);
}

function buildHeader(isOperator = false) {
    const path = state.currentPath,
        base = isOperator ? '/Operator' : '',
        active = headerNavBtnActive(path);
    const hideNav = (isOperator && path === '/Operator');
    const navHtml = hideNav ? '' : `<div class="header-nav">
    <button class="header-nav-btn ${active==='monitoring'?'active':'inactive'}" onclick="router.navigate('${base}/overview')">${svgIcon('activity',18,'inherit')} Monitoring</button>
    <button class="header-nav-btn ${active==='result'?'active':'inactive'}" onclick="router.navigate('${base}/groupresult')">${svgIcon('fileText',18,'inherit')} Result</button>
    <button class="header-nav-btn ${active==='diagnosis'?'active':'inactive'}" onclick="router.navigate('${base}/report')">${svgIcon('stethoscope',18,'inherit')} Diagnosis &amp; Utility</button>
  </div>`;
    return `<header class="header">
    <div class="header-top">
      <div class="header-left">
        <img src="./assets/CCTPL Logo (2).png" alt="CCTPL Logo" class="header-logo-left"/>
      </div>
      <div class="header-center">
        <div class="title-en">CORE CARBIDE TECH</div>
        
      </div>
      <div class="header-right">
        <button class="theme-toggle" id="theme-toggle" title="Toggle Theme">${ICONS.sun}</button>
        <div class="header-profile">
          <div class="profile-icon">${ICONS.profile}</div>
          <div class="profile-dropdown" style="display:none"><ul>
            <li onclick="router.navigate('${base}/profile')">Profile</li>
            <li onclick="doLogout()">Logout</li>
          </ul></div>
        </div>
      </div>
    </div>${navHtml}
  </header>`;
}

function buildFooter(showScroll = false) {
    const scrollHtml = showScroll ? `</div>` : '';
    return `<footer class="footer">${scrollHtml}<div class="footer-copyright">Engineered By Veramasa</div></footer>`;
}

function doLogout() {
    auth.clearAuth();
    showToast('Logged out successfully', 'info');
    router.navigate('/login');
}

// =====================
// LOGIN PAGE
// =====================
function renderLogin() {
    $('app').innerHTML = `<div class="login-page">
    <img class="login-line-tl" src="./assets/line.png" alt=""/>
    <img class="login-line-br" src="./assets/line2.png" alt=""/>
    <div class="login-form-side">
      <form class="login-form" id="login-form">
        <h2>Login</h2>
        <label>Employee Id</label>
        <input class="login-input" type="text" id="login-user" placeholder="Enter your Employee Id" required/>
        <label>Password</label>
        <div class="password-wrapper">
          <input class="login-input" type="password" id="login-pass" placeholder="Enter Your Password" required/>
          <button type="button" class="eye-toggle" id="eye-toggle" style="width:20px;height:20px">${ICONS.eyeOff}</button>
        </div>
        <button type="submit" class="login-btn">Login</button>
      </form>
    </div>
    <div class="login-right-side">
      <div class="login-right-card">
        <h1>Welcome to CORE CARBIDE TECH</h1>
        <img src="./assets/CCTPL Logo (2).png" alt="CCTPL Logo" class="login-logo"/>
      </div>
    </div>
  </div>`;
    let showPwd = false;
    $('eye-toggle').onclick = () => {
        showPwd = !showPwd;
        $('login-pass').type = showPwd ? 'text' : 'password';
        $('eye-toggle').innerHTML = showPwd ? ICONS.eye : ICONS.eyeOff;
    };
    $('login-form').onsubmit = async(e) => {
        e.preventDefault();
        try {
            const res = await fetch(`${CONFIG.baseUrl}/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: $('login-user').value, password: $('login-pass').value }) });
            if (!res.ok) throw new Error('Invalid credentials');
            const data = await res.json();
            auth.setAuth(data.token, data.user);
            showToast('Login successful!', 'success');
            if (data.user.role === 'admin') router.navigate('/');
            else if (data.user.role === 'Operator') router.navigate('/Operator');
            else router.navigate('/login');
        } catch (err) { showToast(err.message || 'Login failed', 'error'); }
    };
}

// =====================
// ADMIN / OPERATOR ROOT
// =====================
function renderAdminRoot() {
    const header = buildHeader(false);
    const content = `<div class="dashboard-root"><div class="main-boxes-grid">
    <div class="main-box" onclick="router.navigate('/overview')"><div class="main-box-icon">${svgIcon('activity',52,'#2563eb')}</div><h3>Monitoring</h3></div>
    <div class="main-box" onclick="router.navigate('/groupresult')"><div class="main-box-icon">${svgIcon('fileText',52,'#16a34a')}</div><h3>Live Results</h3></div>
    <div class="main-box" onclick="router.navigate('/report')"><div class="main-box-icon">${svgIcon('stethoscope',52,'#ea580c')}</div><h3>Diagnosis &amp; Utility</h3></div>
  </div></div>`;
    renderAppShell(header, content, buildFooter(true));
}

function renderOperatorRoot() {
    const header = buildHeader(true);
    const content = `<div class="dashboard-root"><div class="main-boxes-grid">
    <div class="main-box" onclick="router.navigate('/Operator/overview')"><div class="main-box-icon">${svgIcon('activity',52,'#2563eb')}</div><h3>Monitoring</h3></div>
    <div class="main-box" onclick="router.navigate('/Operator/groupresult')"><div class="main-box-icon">${svgIcon('fileText',52,'#16a34a')}</div><h3>Live Results</h3></div>
    <div class="main-box" onclick="router.navigate('/Operator/report')"><div class="main-box-icon">${svgIcon('stethoscope',52,'#ea580c')}</div><h3>Diagnosis &amp; Utility</h3></div>
  </div></div>`;
    renderAppShell(header, content, buildFooter(false));
}

// =====================
// MONITORING LAYOUT
// =====================
function monitoringTabs(base, activeId) {
    const tabs = [{ id: 'overview', label: 'Overview', icon: 'layout' }, { id: 'machine', label: 'Group Monitoring', icon: 'group' }, { id: 'equipment', label: 'Equipment Monitoring', icon: 'monitor', path: 'parameter' }, { id: 'signal', label: 'Signal Monitoring', icon: 'signal' }, { id: 'alarm', label: 'Alarm Monitoring', icon: 'alarm', path: 'alarmmonitoring' }];
    return tabs.map(t => {
        const pathId = t.path || t.id,
            isActive = (activeId === t.id) || (activeId === 'machinedetail' && t.id === 'equipment') || (activeId === pathId);
        return `<button class="sub-tab ${isActive?'active':''}" onclick="router.navigate('${base}/${pathId}')">${svgIcon(t.icon,16,'inherit')} <span>${t.label}</span></button>`;
    }).join('');
}

function renderWithMonitoringLayout(activeTab) {
    const header = buildHeader(false),
        tabs = monitoringTabs('', activeTab);
    const backBtn = `<button class="back-btn" onclick="router.navigate('/')" title="Back">${ICONS.back}</button>`;
    const subNav = `<div class="sub-tabs-container">${backBtn}<div class="sub-tabs">${tabs}</div></div>`;
    renderAppShell(header, `${subNav}<div id="tab-content" class="page-content" style="padding-top:12px"></div>`, buildFooter(false));
    loadMonitoringContent(activeTab, '');
}

function renderWithOperatorMonitoringLayout(activeTab) {
    const header = buildHeader(true),
        tabs = monitoringTabs('/Operator', activeTab);
    const backBtn = `<button class="back-btn" onclick="router.navigate('/Operator')" title="Back">${ICONS.back}</button>`;
    const subNav = `<div class="sub-tabs-container">${backBtn}<div class="sub-tabs">${tabs}</div></div>`;
    renderAppShell(header, `${subNav}<div id="tab-content" class="page-content" style="padding-top:12px"></div>`, buildFooter(false));
    loadMonitoringContent(activeTab, '/Operator');
}

function loadMonitoringContent(tab, base) {
    const tc = $('tab-content');
    if (!tc) return;
    if (tab === 'overview') loadOverview(tc);
    else if (tab === 'machine') loadMachineDetail(tc, base);
    else if (tab === 'parameter') loadParameter(tc);
    else if (tab === 'machinedetail') loadMachineStats(tc);
    else if (tab === 'machinestatus') loadOverviewMachine(tc);
    else if (tab === 'signal') loadSignal(tc);
    else if (tab === 'alarmmonitoring') loadAlertsPage(tc);
}

// =====================
// RESULT LAYOUT
// =====================
function resultTabs(base, activeId) {
    const tabs = [{ id: 'groupresult', label: 'Group Result', icon: 'layers' }, { id: 'operationresult', label: 'Operation Result', icon: 'database' }, { id: 'productionresult', label: 'Production Result', icon: 'target' }, { id: 'power', label: 'Power Consumption', icon: 'zap' }, { id: 'breakdown', label: 'Breakdown', icon: 'history' }];
    return tabs.map(t => `<button class="sub-tab ${activeId===t.id?'active':''}" onclick="router.navigate('${base}/${t.id}')">${svgIcon(t.icon,16,'inherit')} <span>${t.label}</span></button>`).join('');
}

function renderWithResultLayout(activeTab) {
    const header = buildHeader(false),
        tabs = resultTabs('', activeTab);
    const backBtn = `<button class="back-btn" onclick="router.navigate('/')" title="Back">${ICONS.back}</button>`;
    renderAppShell(header, `<div class="sub-tabs-container">${backBtn}<div class="sub-tabs">${tabs}</div></div><div id="tab-content" class="page-content" style="padding-top:12px"></div>`, buildFooter(false));
    loadResultContent(activeTab);
}

function renderWithOperatorResultLayout(activeTab) {
    const header = buildHeader(true),
        tabs = resultTabs('/Operator', activeTab);
    const backBtn = `<button class="back-btn" onclick="router.navigate('/Operator')" title="Back">${ICONS.back}</button>`;
    renderAppShell(header, `<div class="sub-tabs-container">${backBtn}<div class="sub-tabs">${tabs}</div></div><div id="tab-content" class="page-content" style="padding-top:12px"></div>`, buildFooter(false));
    loadResultContent(activeTab);
}

function loadResultContent(tab) {
    const tc = $('tab-content');
    if (!tc) return;
    if (tab === 'groupresult') loadGroupResult(tc);
    else if (tab === 'operationresult') loadOperatingResult(tc);
    else if (tab === 'productionresult') loadProductionResult(tc);
    else if (tab === 'power') loadPowerConsumption(tc);
    else if (tab === 'breakdown') loadBreakdownResult(tc);
}

// =====================
// DIAGNOSIS LAYOUT
// =====================
function diagTabs(base, activeId) {
    const tabs = [{ id: 'report', label: 'Reports', icon: 'trending' }, { id: 'dataentries', label: 'DataEntries', icon: 'database' }, { id: 'alarm', label: 'Alarm History', icon: 'history' }, { id: 'setting', label: 'Machines', icon: 'settings' }, { id: 'user', label: 'Users', icon: 'user' }];
    return tabs.map(t => `<button class="sub-tab ${activeId===t.id?'active':''}" onclick="router.navigate('${base}/${t.id}')">${svgIcon(t.icon,16,'inherit')} <span>${t.label}</span></button>`).join('');
}

function renderWithDiagLayout(activeTab) {
    const header = buildHeader(false),
        tabs = diagTabs('', activeTab);
    const backBtn = `<button class="back-btn" onclick="router.navigate('/')" title="Back">${ICONS.back}</button>`;
    renderAppShell(header, `<div class="sub-tabs-container">${backBtn}<div class="sub-tabs">${tabs}</div></div><div id="tab-content" class="page-content" style="padding-top:12px"></div>`, buildFooter(false));
    loadDiagContent(activeTab);
}

function renderWithOperatorDiagLayout(activeTab) {
    const header = buildHeader(true),
        tabs = diagTabs('/Operator', activeTab);
    const backBtn = `<button class="back-btn" onclick="router.navigate('/Operator')" title="Back">${ICONS.back}</button>`;
    renderAppShell(header, `<div class="sub-tabs-container">${backBtn}<div class="sub-tabs">${tabs}</div></div><div id="tab-content" class="page-content" style="padding-top:12px"></div>`, buildFooter(false));
    loadDiagContent(activeTab);
}

function loadDiagContent(tab) {
    const tc = $('tab-content');
    if (!tc) return;
    if (tab === 'report') loadReports(tc);
    else if (tab === 'dataentries') loadDataEntries(tc);
    else if (tab === 'alarm') loadAlarmHistory(tc);
    else if (tab === 'setting') loadSetting(tc);
    else if (tab === 'user') loadUsers(tc);
}

// =====================
// OVERVIEW PAGE  (FIX #1 — improved layout)
// =====================
async function loadOverview(container) {
    container.innerHTML = `<div style="color:white;padding:20px">Loading dashboard...</div>`;

    const pct = v => ((v || 0) * 100).toFixed(1);
    const statusColors = {
        RUNNING: { bg: '#22c55e', text: '#166534', light: '#dcfce7' },
        IDLE: { bg: '#eab308', text: '#854d0e', light: '#fef9c3' },
        STOPPED: { bg: '#ef4444', text: '#991b1b', light: '#fee2e2' },
        PAUSED: { bg: '#f97316', text: '#9a3412', light: '#ffedd5' },
        OFFLINE: { bg: '#6b7280', text: '#1f2937', light: '#f3f4f6' },
        MAINTENANCE: { bg: '#3b82f6', text: '#1e40af', light: '#dbeafe' },
        EMERGENCY: { bg: '#b91c1c', text: '#7f1a1a', light: '#fee2e2' }
    };

    const renderDashboard = (fs, machines, liveMachines, alerts) => {
            // Count machines by status
            const statusCounts = {
                RUNNING: 0,
                IDLE: 0,
                STOPPED: 0,
                PAUSED: 0,
                OFFLINE: 0,
                MAINTENANCE: 0,
                EMERGENCY: 0
            };

            liveMachines.forEach(m => {
                const status = (m.machine_state || 'OFFLINE').toUpperCase();
                if (statusCounts[status] !== undefined) {
                    statusCounts[status]++;
                } else {
                    statusCounts.OFFLINE++;
                }
            });

            // Get unique alerts with latest timestamps
            const uniqueAlerts = [];
            const alertMap = new Map();
            alerts.forEach(a => {
                const key = `${a.machine_id}-${a.message || a.code}`;
                if (!alertMap.has(key) || new Date(a.timestamp) > new Date(alertMap.get(key).timestamp)) {
                    alertMap.set(key, a);
                }
            });
            const recentAlerts = Array.from(alertMap.values()).slice(0, 10);

            // Status Cards HTML
            const statusCardsHtml = `
      <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:16px;margin-bottom:24px">
        <div style="background:${statusColors.RUNNING.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.RUNNING}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Running Machines</div>
        </div>
        <div style="background:${statusColors.IDLE.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.IDLE}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Idle Machines</div>
        </div>
        <div style="background:${statusColors.STOPPED.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.STOPPED}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Stopped Machines</div>
        </div>
        <div style="background:${statusColors.PAUSED.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.PAUSED}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Paused Machines</div>
        </div>
        <div style="background:${statusColors.MAINTENANCE.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.MAINTENANCE}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Maintenance</div>
        </div>
        <div style="background:${statusColors.EMERGENCY.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.EMERGENCY}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Emergency</div>
        </div>
        <div style="background:${statusColors.OFFLINE.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.OFFLINE}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Offline Machines</div>
        </div>
      </div>
    `;

            // Alarms & Warnings Section
            const alarmsHtml = `
      <div style="background:#fff;border-radius:12px;padding:20px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.08)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px">
          <span style="font-size:20px">⚠️</span>
          <h3 style="font-size:18px;font-weight:700;color:#111;margin:0">Alarms & Warning</h3>
        </div>
        <div style="max-height:400px;overflow-y:auto">
          ${recentAlerts.length > 0 ? recentAlerts.map(a => {
            const severityColor = a.severity === 'critical' ? '#dc2626' : a.severity === 'warning' ? '#d97706' : '#3b82f6';
            const severityBg = a.severity === 'critical' ? '#fee2e2' : a.severity === 'warning' ? '#fffbeb' : '#eff6ff';
            return `
              <div style="padding:12px;border-bottom:1px solid #f3f4f6;background:${severityBg};border-radius:8px;margin-bottom:8px">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
                  <div style="display:flex;align-items:center;gap:8px">
                    <span style="font-size:14px">⚠️</span>
                    <span style="font-weight:600;color:#374151;font-size:13px">${a.timestamp ? formatDate(a.timestamp) : new Date().toLocaleString()}</span>
                    <span style="font-weight:600;color:${severityColor};font-size:13px">${a.machine_name || 'Machine ' + a.machine_id}</span>
                  </div>
                  <span style="background:${severityColor};color:white;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600">${(a.severity || 'INFO').toUpperCase()}</span>
                </div>
                <div style="color:#6b7280;font-size:13px;margin-left:22px">${a.message || a.code || 'No message'}</div>
              </div>
            `;
          }).join('') : `
            <div style="text-align:center;padding:32px;color:#16a34a">
              <span style="font-size:48px">✅</span>
              <p style="margin-top:8px;font-size:14px">No active alarms or warnings</p>
            </div>
          `}
        </div>
      </div>
    `;
    
    // Machine Wise Production Trends
    const productionItems = machines.map(m => ({
      name: getMachineDisplayName(m),
      parts: m.parts_produced || 0,
      oee: ((m.overall_oee || 0) * 100).toFixed(1)
    })).sort((a, b) => b.parts - a.parts).slice(0, 8);
    
    const maxParts = Math.max(...productionItems.map(p => p.parts), 1);
    
    const productionTrendsHtml = `
      <div style="background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.08)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:20px">
          <span style="font-size:20px">📊</span>
          <h3 style="font-size:18px;font-weight:700;color:#111;margin:0">Machine Wise Production Trends</h3>
        </div>
        <div style="display:flex;flex-direction:column;gap:16px">
          ${productionItems.map(item => `
            <div>
              <div style="display:flex;justify-content:space-between;margin-bottom:6px">
                <span style="font-weight:600;color:#374151;font-size:13px">${item.name}</span>
                <span style="font-weight:600;color:#2563eb;font-size:13px">${item.parts} parts</span>
              </div>
              <div style="background:#e5e7eb;border-radius:8px;height:32px;overflow:hidden;position:relative">
                <div style="background:linear-gradient(90deg, #2563eb, #3b82f6);width:${(item.parts / maxParts) * 100}%;height:100%;border-radius:8px;display:flex;align-items:center;justify-content:flex-end;padding-right:8px">
                  <span style="color:white;font-size:12px;font-weight:600">${item.parts}</span>
                </div>
              </div>
            </div>
          `).join('')}
          ${productionItems.length === 0 ? '<div style="text-align:center;padding:32px;color:#9ca3af">No production data available</div>' : ''}
        </div>
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center">
          <span style="color:#6b7280;font-size:12px">Last updated: ${new Date().toLocaleString()}</span>
          <span style="color:#2563eb;font-size:12px;font-weight:500">Total: ${productionItems.reduce((sum, i) => sum + i.parts, 0)} parts</span>
        </div>
      </div>
    `;
    
    // KPI Cards (OEE, Availability, Performance, Quality)
    const kpiHtml = `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px">
        <div style="background:linear-gradient(135deg, #9333ea, #7e22ce);border-radius:12px;padding:20px;box-shadow:0 4px 12px rgba(0,0,0,.2)">
          <div style="color:rgba(255,255,255,.8);font-size:12px;font-weight:500;margin-bottom:4px">Overall OEE</div>
          <div style="color:#fff;font-size:32px;font-weight:700;margin-bottom:2px">${pct(fs.fleet_overall_oee)}%</div>
          <div style="color:rgba(255,255,255,.6);font-size:11px">Fleet Average</div>
        </div>
        <div style="background:linear-gradient(135deg, #22c55e, #16a34a);border-radius:12px;padding:20px;box-shadow:0 4px 12px rgba(0,0,0,.2)">
          <div style="color:rgba(255,255,255,.8);font-size:12px;font-weight:500;margin-bottom:4px">Availability</div>
          <div style="color:#fff;font-size:32px;font-weight:700;margin-bottom:2px">${pct(fs.fleet_availability)}%</div>
          <div style="color:rgba(255,255,255,.6);font-size:11px">Average</div>
        </div>
        <div style="background:linear-gradient(135deg, #f97316, #ea580c);border-radius:12px;padding:20px;box-shadow:0 4px 12px rgba(0,0,0,.2)">
          <div style="color:rgba(255,255,255,.8);font-size:12px;font-weight:500;margin-bottom:4px">Performance</div>
          <div style="color:#fff;font-size:32px;font-weight:700;margin-bottom:2px">${pct(fs.fleet_performance)}%</div>
          <div style="color:rgba(255,255,255,.6);font-size:11px">Average</div>
        </div>
        <div style="background:linear-gradient(135deg, #3b82f6, #2563eb);border-radius:12px;padding:20px;box-shadow:0 4px 12px rgba(0,0,0,.2)">
          <div style="color:rgba(255,255,255,.8);font-size:12px;font-weight:500;margin-bottom:4px">Quality</div>
          <div style="color:#fff;font-size:32px;font-weight:700;margin-bottom:2px">${pct(fs.fleet_quality)}%</div>
          <div style="color:rgba(255,255,255,.6);font-size:11px">Average</div>
        </div>
      </div>
    `;
    
    container.innerHTML = `
      <div style="padding:0 0 24px 0">
        <h1 style="font-size:24px;font-weight:700;color:#fff;margin:0 0 20px 0">Dashboard Overview</h1>
        ${statusCardsHtml}
        ${kpiHtml}
        <div style="display:grid;grid-template-columns:1fr 1.2fr;gap:24px">
          ${alarmsHtml}
          ${productionTrendsHtml}
        </div>
      </div>
    `;
  };
  
  const doFetch = async () => {
    const today = new Date().toISOString().slice(0, 10);
    // add per-request timeout (ms)
    const to = 8000;
    const requests = [
      { name: 'oee', p: fetch(`${CONFIG.baseUrl}/api/oee/calculate?start_date=${today}&end_date=${today}`, { headers: auth.getHeaders(), timeout: to }) },
      { name: 'live', p: fetch(`${CONFIG.baseUrl}/api/machines/live-status`, { headers: auth.getHeaders(), timeout: to }) },
      { name: 'alerts', p: fetch(`${CONFIG.baseUrl}/api/alerts?limit=50`, { headers: auth.getHeaders(), timeout: to }) },
    ];

    const results = await Promise.all(requests.map(r => r.p.catch(err => ({ __error: err, __name: r.name }))));

    // if any resulted in an error object, throw with details
    for (const res of results) {
      if (res && res.__error) throw new Error(`Failed to fetch ${res.__name}: ${res.__error.message || res.__error}`);
      if (!res || !res.ok) throw new Error(`Request failed: ${res && res.url ? new URL(res.url).pathname : 'unknown'} (status ${res ? res.status : 'no response'})`);
    }

    const [oeeData, liveData, alertData] = await Promise.all(results.map(r => r.json()));
    
    renderDashboard(
      oeeData.fleet_summary || {},
      oeeData.individual_machines || [],
      liveData.machines || [],
      alertData.alerts || alertData.alarms || []
    );
  };
  
  try {
    await doFetch();
    const iv = setInterval(() => doFetch().catch(() => {}), 10000);
    state.intervals.push(iv);
  } catch (e) {
    container.innerHTML = `<div class="error-state">Failed to load dashboard. ${e.message}. Try reloading or check API/server (see console for details).</div>`;
    console.error('Dashboard load error:', e);
  }
}

// =====================
// MACHINE DETAIL — GROUP MONITORING
// FIX #2: navigate to /parameter (Equipment Monitoring) instead of /machinedetail
// =====================
async function loadMachineDetail(container,base) {
  container.innerHTML=`<div class="search-wrapper"><span class="search-icon">${ICONS.search}</span>
    <input class="search-input" id="machine-search" type="text" placeholder="Search machines..." oninput="filterMachines()"/>
  </div>
  <div id="fanuc-section"><div class="section-title fanuc">Fanuc Machines (0)</div><div class="empty-state">Loading...</div></div>
  <div id="siemens-section"><div class="section-title siemens">Siemens Machines (0)</div><div class="empty-state">Loading...</div></div>
  <div class="machine-status-bar" id="status-bar">Loading...</div>`;

  let allMachines=[], liveData={};
  const statusBg={RUNNING:'bg-running',IDLE:'bg-idle',STOPPED:'bg-stopped',PAUSED:'bg-paused',OFFLINE:'bg-offline',MAINTENANCE:'bg-maintenance',EMERGENCY:'bg-emergency'};

  // FIX #2 — navigate to Equipment Monitoring (parameter tab) and pre-select machine
  window.navigateToMachineDetail=(id)=>{
    localStorage.setItem('selectedMachineId', String(id));
    router.navigate(base?`${base}/parameter`:'/parameter');
  };

  function renderMachines() {
    const q=($('machine-search')||{}).value||'';
    const merged=allMachines.map(m=>{const live=liveData[m.id]||{},status=(live.machine_state||'OFFLINE').toUpperCase();return {...m,status,bg:statusBg[status]||'bg-offline',partCount:live.part_count,cycleTime:live.cycle_time};}).filter(m=>!q||m.vfj_no?.toLowerCase().includes(q.toLowerCase())||m.control_details?.toLowerCase().includes(q.toLowerCase()));
    const fanuc=merged.filter(m=>m.control_type?.toLowerCase().includes('fanuc'));
    const siemens=merged.filter(m=>m.control_type?.toLowerCase().includes('siemens'));

    function cardsHtml(list) {
      if(!list.length) return `<div class="empty-state">No machines found</div>`;
      return `<div class="machines-grid">${list.map(m=>`
        <div class="machine-card" onclick="navigateToMachineDetail(${m.id})" style="cursor:pointer">
          <div class="machine-card-header ${m.bg}">
            <div class="ctrl-row">
              <div class="ctrl-name"><span class="ctrl-type">${m.control_type||''}</span><span class="ctrl-detail">- ${m.control_details||''}</span></div>
              <span class="status-badge">${m.status}</span>
            </div>
            <div class="vfj-no">${m.vfj_no||''}</div>
            <div class="oem-name">${m.oem_name||''}</div>
          </div>
          <div class="machine-card-body">
            <div class="machine-card-row"><span>Cycle Time</span><span>${m.cycleTime??'-'}</span></div>
            <div class="machine-card-row"><span>Part Count</span><span class="val">${m.partCount??'-'}</span></div>
          </div>
        </div>`).join('')}</div>`;
    }

    const fs=$('fanuc-section'); if(fs) fs.innerHTML=`<div class="section-title fanuc">Fanuc Machines (${fanuc.length})</div>${cardsHtml(fanuc)}`;
    const ss=$('siemens-section'); if(ss) ss.innerHTML=`<div class="section-title siemens">Siemens Machines (${siemens.length})</div>${cardsHtml(siemens)}`;

    const cnts={running:0,idle:0,stopped:0,paused:0,offline:0};
    merged.forEach(m=>{if(m.status==='RUNNING')cnts.running++;else if(m.status==='IDLE')cnts.idle++;else if(m.status==='STOPPED')cnts.stopped++;else if(m.status==='PAUSED')cnts.paused++;else cnts.offline++;});
    const sb=$('status-bar');
    if(sb) sb.innerHTML=`
      <div class="status-indicator"><div class="status-dot bg-running"></div><span class="status-text">Running: <strong>${cnts.running}</strong></span></div>
      <div class="status-indicator"><div class="status-dot bg-idle"></div><span class="status-text">Idle: <strong>${cnts.idle}</strong></span></div>
      <div class="status-indicator"><div class="status-dot bg-stopped"></div><span class="status-text">Stop: <strong>${cnts.stopped}</strong></span></div>
      <div class="status-indicator"><div class="status-dot bg-paused"></div><span class="status-text">Pause: <strong>${cnts.paused}</strong></span></div>
      <div class="status-indicator"><div class="status-dot bg-offline"></div><span class="status-text">Offline: <strong>${cnts.offline}</strong></span></div>`;
  }

  window.filterMachines=renderMachines;

  try {
    const res=await fetch(`${CONFIG.baseUrl}/machines`,{headers:auth.getHeaders()});
    const data=await res.json();
    allMachines=data.machines||[];
    renderMachines();
  } catch(e) { console.error(e); }

  async function fetchLive() {
    try {
      const res=await fetch(`${CONFIG.baseUrl}/api/machines/live-status`,{headers:auth.getHeaders()});
      const data=await res.json();
      if(data.machines){data.machines.forEach(m=>{liveData[m.machine_id]=m;});renderMachines();}
    } catch(e) {}
  }
  fetchLive();
  const id=setInterval(fetchLive,5000);
  state.intervals.push(id);
}

// =====================
// SIGNAL PAGE
// =====================
async function loadSignal(container) {
  const statusDotColor={RUNNING:'#22c55e',IDLE:'#eab308',STOPPED:'#ef4444',ALARM:'#ef4444',MAINTENANCE:'#3b82f6',EMERGENCY:'#b91c1c',OFFLINE:'#9ca3af'};
  function renderSignalPage(machines,error) {
    if(error){container.innerHTML=`<div style="background:#fff;border-radius:8px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.1)"><h2 style="font-size:18px;font-weight:600;margin:0 0 16px">Machine Status</h2><div style="color:#ef4444;padding:16px;text-align:center">${error}<br><button onclick="loadSignal(document.getElementById('tab-content'))" style="margin-top:12px;padding:6px 16px;background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer">Retry</button></div></div>`;return;}
    container.innerHTML=`<div style="background:#fff;border-radius:8px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.1)">
      <h2 style="font-size:18px;font-weight:600;margin:0 0 16px">Machine Status</h2>
      ${!machines.length?`<p style="color:#6b7280;text-align:center;padding:32px 0">No machines found</p>`:`
      <div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;border:1px solid #d1d5db;background:#fff;font-size:14px">
        <thead><tr style="background:#f9fafb">
          <th style="padding:10px 16px;text-align:left;font-weight:600;color:#374151;border:1px solid #d1d5db">Machine No</th>
          <th style="padding:10px 16px;text-align:left;font-weight:600;color:#374151;border:1px solid #d1d5db">Machine Name</th>
          <th style="padding:10px 16px;text-align:left;font-weight:600;color:#374151;border:1px solid #d1d5db">State</th>
        </tr></thead>
        <tbody>${machines.map((m,i)=>{const st=(m.machine_state||'OFFLINE').toUpperCase(),dot=statusDotColor[st]||'#9ca3af';return `<tr style="border-bottom:1px solid #e5e7eb${i%2===0?'':';background:#f9fafb'}">
          <td style="padding:10px 16px;border:1px solid #d1d5db;color:#374151">${m.vfj_no||'-'}</td>
          <td style="padding:10px 16px;border:1px solid #d1d5db;color:#374151">${getMachineDisplayName(m)}</td>
          <td style="padding:10px 16px;border:1px solid #d1d5db"><div style="display:flex;align-items:center;gap:8px"><span style="width:12px;height:12px;border-radius:50%;background:${dot};flex-shrink:0;display:inline-block"></span><span style="color:#374151;font-weight:500">${st}</span></div></td>
        </tr>`;}).join('')}</tbody>
      </table></div>`}
    </div>`;
  }
  container.innerHTML=`<div style="background:#fff;border-radius:8px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,.1)"><h2 style="font-size:18px;font-weight:600;margin:0 0 16px">Machine Status</h2><p style="color:#6b7280;text-align:center;padding:32px 0">Loading...</p></div>`;
  async function fetchAndRender() {
    try {
      const res=await fetch(`${CONFIG.baseUrl}/api/machines/live-status`,{headers:auth.getHeaders()});
      if(!res.ok) throw new Error(`HTTP ${res.status}`);
      const data=await res.json();
      renderSignalPage(data.machines||[],null);
    } catch(e) { renderSignalPage([],`Error connecting to server: ${e.message}`); }
  }
  fetchAndRender();
  const id=setInterval(fetchAndRender,5000); state.intervals.push(id);
}

// =====================
// ALERTS PAGE
// =====================
async function loadAlertsPage(container) {
  container.innerHTML=`<div style="color:white">Loading alerts...</div>`;
  try {
    const res=await fetch(`${CONFIG.baseUrl}/api/alerts?limit=100`,{headers:auth.getHeaders()});
    const data=await res.json();
    const alerts=data.alerts||data||[];
    const severityBadge=s=>`<span class="badge-severity ${s==='critical'?'badge-critical':s==='warning'?'badge-warning':'badge-info'}">${s||'info'}</span>`;
    container.innerHTML=`<div class="filters-row" style="margin-bottom:16px">
      <h1 class="page-title" style="margin:0">Alarm Monitoring</h1>
      <div class="export-row" style="margin:0;display:flex;gap:8px">
        <button class="export-btn export-csv" onclick="exportAlertsCSV()">CSV</button>
        <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Alarm Monitoring','alerts-table')">PDF</button>
      </div>
    </div>
    <div class="table-wrapper"><table class="data-table" id="alerts-table">
      <thead><tr><th>Time</th><th>Machine</th><th>Type</th><th>Message</th><th>Severity</th><th>Status</th></tr></thead>
      <tbody>${alerts.length?alerts.map(a=>`<tr>
        <td>${formatDate(a.timestamp||a.created_at)}</td><td>${a.machine_id||a.vfj_no||'-'}</td>
        <td>${a.alarm_type||a.type||'-'}</td><td>${a.message||a.description||'-'}</td>
        <td>${severityBadge(a.severity)}</td>
        <td><span style="color:${a.is_active?'#dc2626':'#16a34a'}">${a.is_active?'Active':'Resolved'}</span></td>
      </tr>`).join(''):`<tr><td colspan="6" style="text-align:center;padding:32px;color:#6b7280">No alerts found</td></tr>`}
      </tbody></table></div>`;
    window.exportAlertsCSV=()=>{let csv='Time,Machine,Type,Message,Severity,Status\n';alerts.forEach(a=>{csv+=`"${formatDate(a.timestamp||a.created_at)}","${a.machine_id||'-'}","${a.alarm_type||'-'}","${a.message||'-'}","${a.severity||'-'}","${a.is_active?'Active':'Resolved'}"\n`;});downloadCSV(csv,'alerts.csv');};
  } catch(e) { container.innerHTML=`<div class="error-state">Failed to load alerts. ${e.message}</div>`; }
}

// =====================
// EQUIPMENT MONITORING (Parameter) — UPDATED WITH NEW GAUGE DESIGN
// =====================
async function loadParameter(container) {
  let machines = [];
  let productionEntry = null;
  let machineData = {};
  let selectedId = null;
  let userIsSelecting = false;
  const instanceId = Math.random().toString(36).substr(2, 9);

  const stateColor = {
    RUNNING: '#22c55e', IDLE: '#eab308', ALARM: '#dc2626',
    EMERGENCY: '#dc2626', OFFLINE: '#6b7280', MAINTENANCE: '#3b82f6', STOPPED: '#ef4444'
  };

  function dv(value, st) {
    if (st === 'OFFLINE' || value === null || value === undefined || value === '') return '-';
    return value;
  }

  function boolValue(value) {
    if (value === 1 || value === '1' || value === true || value === 'true') return 'YES';
    if (value === 0 || value === '0' || value === false || value === 'false') return 'NO';
    return value ?? '-';
  }

  // ── ANIMATED HALF-GAUGE SVG ──────────────────────────────────────────────
  function halfGauge(value, maxVal, unit, color = '#22d3ee') {
    const num = parseFloat(value) || 0;
    const pct = Math.min(Math.max(num / (maxVal || 1), 0), 1);
    const angle = -180 + pct * 180; // sweeps from -180° to 0°
    const r = 54, cx = 80, cy = 72;
    const toRad = deg => deg * Math.PI / 180;
    const needleX = cx + r * Math.cos(toRad(angle));
    const needleY = cy + r * Math.sin(toRad(angle));
    const uid = `hg-${instanceId}-${Math.random().toString(36).substr(2,5)}`;

    // Arc path helper
    function arcPath(startDeg, endDeg, radius) {
      const s = { x: cx + radius * Math.cos(toRad(startDeg)), y: cy + radius * Math.sin(toRad(startDeg)) };
      const e = { x: cx + radius * Math.cos(toRad(endDeg)),   y: cy + radius * Math.sin(toRad(endDeg)) };
      const large = (endDeg - startDeg) > 180 ? 1 : 0;
      return `M ${s.x} ${s.y} A ${radius} ${radius} 0 ${large} 1 ${e.x} ${e.y}`;
    }

    return `
      <svg viewBox="0 0 160 85" style="width:100%;max-width:200px;display:block;margin:0 auto;overflow:visible">
        <defs>
          <linearGradient id="${uid}-g" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#1e40af"/>
            <stop offset="50%" stop-color="${color}"/>
            <stop offset="100%" stop-color="#f97316"/>
          </linearGradient>
          <filter id="${uid}-glow">
            <feGaussianBlur stdDeviation="2" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>
        <!-- Track -->
        <path d="${arcPath(-180, 0, r)}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="10" stroke-linecap="round"/>
        <!-- Fill arc -->
        <path d="${arcPath(-180, angle, r)}" fill="none" stroke="url(#${uid}-g)" stroke-width="10" stroke-linecap="round" filter="url(#${uid}-glow)"/>
        <!-- Tick marks -->
        ${[0,1,2,3,4,5,6,7,8,9,10].map(i => {
          const deg = -180 + i * 18;
          const inner = r - 14, outer = r - 8;
          const x1 = cx + inner * Math.cos(toRad(deg)), y1 = cy + inner * Math.sin(toRad(deg));
          const x2 = cx + outer * Math.cos(toRad(deg)), y2 = cy + outer * Math.sin(toRad(deg));
          return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="rgba(255,255,255,0.25)" stroke-width="${i%5===0?1.5:0.8}"/>`;
        }).join('')}
        <!-- Needle -->
        <line x1="${cx}" y1="${cy}" x2="${needleX.toFixed(1)}" y2="${needleY.toFixed(1)}"
          stroke="${color}" stroke-width="2" stroke-linecap="round" filter="url(#${uid}-glow)"/>
        <circle cx="${cx}" cy="${cy}" r="5" fill="${color}" opacity="0.9"/>
        <!-- Center value -->
        <text x="${cx}" y="${cy - 10}" text-anchor="middle" font-size="22" font-weight="700" fill="white"
          style="font-family:monospace">${value === null || value === undefined ? '-' : value}</text>
        <text x="${cx}" y="${cy + 4}" text-anchor="middle" font-size="9" fill="rgba(255,255,255,0.5)">${unit}</text>
      </svg>`;
  }

  function parseAxisPositions(raw) {
    if (!raw || raw === 'None') return [];
    const axes = [];
    String(raw).split(',').forEach(p => {
      const m = p.trim().match(/^([A-Z]+)\s*:\s*(-?[\d.]+)/i);
      if (m) axes.push({ axis: m[1].toUpperCase(), val: m[2] });
    });
    return axes;
  }

  function renderAlarmSection(raw, isAlarm) {
    if (!raw || raw === '0' || raw === 'None' || raw === '[]') {
      return `<div style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);border-radius:8px;padding:10px 14px;color:#22c55e;font-size:13px;font-weight:600">
        ${isAlarm ? '✓ No Alarms' : '✓ No Warnings'}</div>`;
    }
    let items = [];
    try { const p = JSON.parse(raw); items = Array.isArray(p) ? p : [p]; } catch { items = [String(raw)]; }
    items = items.filter(x => x && x !== 'None');
    if (!items.length) return `<div style="background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);border-radius:8px;padding:10px 14px;color:#22c55e;font-size:13px;font-weight:600">${isAlarm ? '✓ No Alarms' : '✓ No Warnings'}</div>`;
    return items.map(item => {
      const str = typeof item === 'object' ? ((item.code ? item.code + ': ' : '') + (item.message || JSON.stringify(item))) : String(item);
      return `<div style="background:rgba(220,38,38,0.15);border:1px solid rgba(220,38,38,0.4);border-radius:8px;padding:10px 14px;color:#fca5a5;font-size:13px">${str}</div>`;
    }).join('');
  }

  // ── CARD BUILDER ─────────────────────────────────────────────────────────
  function card(icon, title, body, accentColor = '#22d3ee') {
    return `
      <div style="background:linear-gradient(135deg, #000000 0%, #111111 100%);
        border:1px solid rgba(255,255,255,0.12);border-radius:16px;padding:18px;
        box-shadow:0 8px 32px rgba(0, 0, 0, 0.4),inset 0 1px 0 rgba(255,255,255,0.05);
        position:relative;overflow:hidden;color:#f8fafc">
        <div style="position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,${accentColor},transparent);opacity:0.6"></div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px">
          <span style="font-size:15px">${icon}</span>
          <span style="font-size:13px;font-weight:700;color:#f8fafc;letter-spacing:0.05em;text-transform:uppercase">${title}</span>
          <div style="margin-left:auto;width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 6px #22c55e;animation:pm-blink 2s ease-in-out infinite"></div>
        </div>
        ${body}
      </div>`;
  }

  function row(label, value, highlight = false, unit = '') {
    const color = highlight ? '#7dd3fc' : '#f8fafc';
    return `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.08)">
        <span style="color:#cbd5e1;font-size:12px">${label}:</span>
        <span style="color:${color};font-weight:600;font-size:13px;font-family:monospace">${value}${unit && value !== '-' ? ` <span style="color:#94a3b8;font-size:10px">${unit}</span>` : ''}</span>
      </div>`;
  }

  function buildColumns() {
    const st = (machineData.machine_state || 'OFFLINE').toUpperCase();
    const axes = parseAxisPositions(machineData.axis_positions);
    const spindleSpeed = dv(machineData.actual_spindle_speed, st);
    const feedRate = dv(machineData.actual_feed_rate, st);

    // Column 1
    const col1 = `
      ${card('📐', 'Relative Axis Positions', `
        <div style="display:flex;flex-direction:column;gap:6px">
          ${axes.length > 0 ? axes.map(a => `
            <div style="display:flex;justify-content:space-between;align-items:center;
              background:rgba(34,211,238,0.06);border:1px solid rgba(34,211,238,0.12);
              border-radius:8px;padding:10px 14px">
              <span style="color:#cbd5e1;font-size:12px;font-weight:600">${a.axis} Axis:</span>
              <span style="color:#f8fafc;font-size:18px;font-weight:700;font-family:monospace">${a.val} <span style="font-size:11px;color:#94a3b8">mm</span></span>
            </div>`).join('')
          : `<div style="color:#94a3b8;text-align:center;padding:20px;font-size:13px">No axis data</div>`}
        </div>`, '#22d3ee')}

      ${card('⚙️', 'Program Status', `
        ${row('Main Program', dv(machineData.main_program_number, st), true)}
        ${row('Executing', dv(machineData.executing_program_number, st), true)}
        ${row('Sequence', dv(machineData.sequence_number, st))}
        ${row('Current Tool', dv(machineData.current_tool_number, st), true)}
        ${row('Tool Offset', dv(machineData.tool_offset_geometry, st))}
        ${row('Wear Offset', dv(machineData.tool_offset_wear, st))}
      `, '#a78bfa')}

      ${card('⏱️', 'Time Tracking', `
        ${row('Cycle Time', dv(machineData.cycle_time, st), true)}
        ${row('Cutting Time', dv(machineData.cutting_time, st))}
        ${row('Operate Time', dv(machineData.operate_time, st))}
        ${row('Power On', dv(machineData.power_on_time, st))}
      `, '#34d399')}`;

    // Column 2 — Spindle + Feed with animated gauges
    const col2 = `
      ${card('⚡', 'Spindle Status', `
        <div style="margin-bottom:12px">
          ${halfGauge(spindleSpeed, 6000, 'RPM', '#22d3ee')}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
          <div style="background:rgba(34,211,238,0.08);border:1px solid rgba(34,211,238,0.2);border-radius:10px;padding:10px;text-align:center">
            <div style="font-size:10px;color:#cbd5e1;margin-bottom:4px">Target</div>
            <div style="font-size:16px;font-weight:700;color:#f8fafc;font-family:monospace">${dv(machineData.set_speed, st)} <span style="font-size:10px;color:#94a3b8">RPM</span></div>
          </div>
          <div style="background:rgba(34,211,238,0.08);border:1px solid rgba(34,211,238,0.2);border-radius:10px;padding:10px;text-align:center">
            <div style="font-size:10px;color:#cbd5e1;margin-bottom:4px">Load</div>
            <div style="font-size:16px;font-weight:700;color:#f8fafc;font-family:monospace">${dv(machineData.spindle_load, st)}${dv(machineData.spindle_load, st) !== '-' ? '%' : ''}</div>
          </div>
        </div>
        ${row('Temperature', dv(machineData.spindle_temperature, st), false, '°C')}
        ${row('Override', dv(machineData.speed_override, st), false, '%')}
      `, '#22d3ee')}

      ${card('🏃', 'Feed Rate', `
        <div style="margin-bottom:12px">
          ${halfGauge(feedRate, 5000, 'mm/min', '#34d399')}
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
          <div style="background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.2);border-radius:10px;padding:10px;text-align:center">
            <div style="font-size:10px;color:#cbd5e1;margin-bottom:4px">Set Feed</div>
            <div style="font-size:14px;font-weight:700;color:#f8fafc;font-family:monospace">${dv(machineData.set_feed_rate, st)} <span style="font-size:9px;color:#94a3b8">mm/min</span></div>
          </div>
          <div style="background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.2);border-radius:10px;padding:10px;text-align:center">
            <div style="font-size:10px;color:#cbd5e1;margin-bottom:4px">Override</div>
            <div style="font-size:14px;font-weight:700;color:#f8fafc;font-family:monospace">${dv(machineData.feed_override, st)}${dv(machineData.feed_override, st) !== '-' ? '%' : ''}</div>
          </div>
        </div>
        ${row('Coolant', dv(machineData.coolant_status, st))}
      `, '#34d399')}

      ${card('🔧', 'Servo Status', `
        ${row('Load', dv(machineData.servo_load, st), true, '%')}
        ${row('Current', dv(machineData.servo_current, st))}
        ${row('Temperature', dv(machineData.servo_temperature, st), false, '°C')}
        ${row('Pulse Coder', dv(machineData.pulse_coder_temps, st))}
      `, '#f97316')}`;

    // Column 3
    const macroRaw = machineData.macro_values;
    const macroLines = macroRaw ? String(macroRaw).split(/\r?\n/).map(l => l.trim()).filter(Boolean) : [];

    const col3 = `
      ${card('⚠️', 'Alerts & Warnings', `
        <div style="margin-bottom:10px">
          <div style="font-size:11px;color:#cbd5e1;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">Machine Alarms</div>
          ${renderAlarmSection(machineData.machine_alarms, true)}
        </div>
        <div>
          <div style="font-size:11px;color:#cbd5e1;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">CNC Warnings</div>
          ${renderAlarmSection(machineData.cnc_warnings, false)}
        </div>
      `, '#f97316')}

      ${card('🖥️', 'System Status', `
        ${row('Machine Mode', dv(machineData.machine_mode, st), true)}
        ${row('Emergency Signal', boolValue(machineData.emergency_signal))}
        ${row('Battery Low Alarm', boolValue(machineData.battery_low_alarm))}
        ${row('Tool Offset Geometry', dv(machineData.tool_offset_geometry, st))}
        ${row('Tool Offset Wear', dv(machineData.tool_offset_wear, st))}
      `, '#a78bfa')}

      ${card('📊', 'Macro Variables', `
        ${macroLines.length > 0
          ? macroLines.map(line => `
              <div style="background:rgba(255,255,255,0.04);border-radius:6px;padding:8px 10px;
                font-family:monospace;font-size:12px;color:#f8fafc;margin-bottom:4px">${line}</div>`).join('')
          : `<div style="color:#94a3b8;font-size:13px;text-align:center;padding:16px">No macro values</div>`}
      `, '#22d3ee')}`;

    return `
      <style>
        @keyframes pm-blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
      </style>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;width:100%;min-width:0;box-sizing:border-box;align-items:start">
        <div style="display:flex;flex-direction:column;gap:16px;min-width:0">${col1}</div>
        <div style="display:flex;flex-direction:column;gap:16px;min-width:0">${col2}</div>
        <div style="display:flex;flex-direction:column;gap:16px;min-width:0">${col3}</div>
      </div>`;
  }

  function patchPage() {
    const st = (machineData.machine_state || 'OFFLINE').toUpperCase();
    const stCol = stateColor[st] || '#6b7280';
    const isEmergency = machineData.emergency_signal === 1;

    const stEl = document.getElementById(`pm-st-${instanceId}`);
    if (stEl) { stEl.textContent = st; stEl.style.color = stCol; stEl.style.borderColor = stCol + '44'; }

    const emEl = document.getElementById(`pm-em-${instanceId}`);
    if (emEl) emEl.style.display = isEmergency ? 'flex' : 'none';

    const target = (productionEntry && productionEntry.product_target != null) ? productionEntry.product_target : null;
    const done   = (productionEntry && productionEntry.production_done != null)
      ? productionEntry.production_done
      : (machineData.original_total_production ?? machineData.total_production ?? machineData.part_count ?? '-');
    const doneEl = document.getElementById(`pm-done-${instanceId}`);
    const tgtEl  = document.getElementById(`pm-tgt-${instanceId}`);
    if (doneEl) doneEl.textContent = done;
    if (tgtEl && target != null) tgtEl.textContent  = target;

    const colsEl = document.getElementById(`pm-cols-${instanceId}`);
    if (colsEl) colsEl.innerHTML = buildColumns();
  }

  function renderPage() {
    if (!machines.length) {
      container.innerHTML = `<div style="background:rgba(255,255,255,0.95);border-radius:12px;padding:24px;text-align:center;color:#6b7280">No machines configured</div>`;
      return;
    }
    const m = machines.find(x => parseInt(x.id) === selectedId) || machines[0];
    if (!selectedId) selectedId = parseInt(m.id, 10);

    const st    = (machineData.machine_state || 'OFFLINE').toUpperCase();
    const stCol = stateColor[st] || '#6b7280';
    const isEmergency = machineData.emergency_signal === 1;
    const target = (productionEntry && productionEntry.product_target != null) ? productionEntry.product_target : null;
    const done   = (productionEntry && productionEntry.production_done != null)
      ? productionEntry.production_done
      : (machineData.original_total_production ?? machineData.total_production ?? machineData.part_count ?? '-');

    container.innerHTML = `
      <style>
        #pm-root-${instanceId} { font-family: 'Segoe UI', system-ui, sans-serif; }
        .pm-header-stat { background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:10px 18px;text-align:center; }
      </style>
      <div id="pm-root-${instanceId}" style="padding:12px 8px;width:100%;box-sizing:border-box;background:transparent">

        <!-- Emergency banner -->
        <div id="pm-em-${instanceId}" style="background:linear-gradient(90deg,#7f1d1d,#dc2626,#7f1d1d);color:white;padding:12px 20px;
          border-radius:10px;margin-bottom:16px;display:${isEmergency ? 'flex' : 'none'};
          align-items:center;justify-content:center;gap:12px;animation:pm-blink 1s infinite">
          <span style="font-size:22px">⚠️</span>
          <span style="font-size:17px;font-weight:800;letter-spacing:0.1em">EMERGENCY STOP ACTIVE</span>
          <span style="font-size:22px">⚠️</span>
        </div>

        <!-- HEADER -->
        <div style="background:linear-gradient(135deg,rgba(15,23,42,0.98),rgba(23,37,84,0.95));
          border:1px solid rgba(148,163,184,0.15);border-radius:16px;padding:16px 20px;
          margin-bottom:16px;box-shadow:0 8px 32px rgba(0,0,0,0.5),inset 0 1px 0 rgba(255,255,255,0.05);
          width:100%;box-sizing:border-box;position:relative;overflow:hidden">
          <div style="position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,#22d3ee,#a78bfa,transparent)"></div>
          <div style="display:grid;grid-template-columns:auto 1fr auto;gap:20px;align-items:center">

            <!-- Left: status + machine select -->
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
              <div style="display:flex;align-items:center;gap:8px;background:rgba(34,197,94,0.1);
                border:1px solid rgba(34,197,94,0.3);border-radius:999px;padding:6px 16px">
                <div style="width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e;animation:pm-blink 2s infinite"></div>
                <span id="pm-st-${instanceId}" style="font-weight:700;font-size:14px;color:${stCol};letter-spacing:0.05em">${st}</span>
              </div>
              <select id="pm-sel-${instanceId}" style="background:rgba(15,23,42,0.9);color:#f8fafc;
                border:1px solid rgba(148,163,184,0.25);border-radius:8px;padding:8px 14px;
                font-size:13px;min-width:240px;cursor:pointer;outline:none">
                ${machines.map(x => `<option value="${x.id}" ${parseInt(x.id) === selectedId ? 'selected' : ''}>
                  ${x.vfj_no ? x.vfj_no + ' — ' : ''}${x.oem_name || 'Machine ' + x.id}
                </option>`).join('')}
              </select>
            </div>

            <!-- Center: machine name -->
            <div style="text-align:center">
              <div style="font-size:11px;color:rgba(148,163,184,0.6);text-transform:uppercase;letter-spacing:0.12em;margin-bottom:4px">Active Machine</div>
              <div style="font-size:20px;font-weight:800;color:#f8fafc;letter-spacing:0.02em">${m.vfj_no || 'Machine ' + m.id}</div>
              <div style="font-size:12px;color:rgba(148,163,184,0.5);margin-top:2px">${m.oem_name || ''}</div>
            </div>

            <!-- Right: production stats -->
            <div style="display:flex;gap:12px;flex-wrap:wrap">
              <div class="pm-header-stat" style="min-width:160px">
                <div style="font-size:10px;color:rgba(147,197,253,0.8);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">Production Done</div>
                <div id="pm-done-${instanceId}" style="font-size:24px;font-weight:800;color:#38bdf8;font-family:monospace">${done}</div>
              </div>
              ${target != null ? `
              <div class="pm-header-stat" style="min-width:160px">
                <div style="font-size:10px;color:rgba(110,231,183,0.8);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">Production Target</div>
                <div id="pm-tgt-${instanceId}" style="font-size:24px;font-weight:800;color:#a7f3d0;font-family:monospace">${target}</div>
              </div>
              ` : ''}
            </div>
          </div>
        </div>

        <!-- DATA COLUMNS -->
        <div id="pm-cols-${instanceId}" style="width:100%;min-width:0;box-sizing:border-box">
          ${buildColumns()}
        </div>
      </div>`;

    // Dropdown listener
    const sel = document.getElementById(`pm-sel-${instanceId}`);
    if (sel) {
      sel.addEventListener('mousedown', () => { userIsSelecting = true; });
      sel.addEventListener('keydown',   () => { userIsSelecting = true; });
      sel.addEventListener('change', async (e) => {
        const newId = parseInt(e.target.value, 10);
        if (!newId || newId === selectedId) { userIsSelecting = false; return; }
        selectedId = newId;
        machineData = {};
        productionEntry = null;
        patchPage();
        await Promise.all([fetchMachineData(), fetchProductionEntry()]);
        patchPage();
        userIsSelecting = false;
      });
      sel.addEventListener('blur', () => { setTimeout(() => { userIsSelecting = false; }, 300); });
    }
  }

  async function fetchMachineData() {
    if (!selectedId) return;
    try {
      const res = await fetch(`${CONFIG.baseUrl}/machine_data/${selectedId}`, { headers: auth.getHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) machineData = data[0];
      else if (data && typeof data === 'object') machineData = data.data?.[0] ?? data;
    } catch (e) { console.error('fetchMachineData:', e); }
  }

  async function fetchProductionEntry() {
    if (!selectedId) return;
    try {
      const res = await fetch(`${CONFIG.baseUrl}/api/production/entries?machine_id=${selectedId}&limit=1`, { headers: auth.getHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      productionEntry = (data.entries || [])[0] ?? null;
    } catch (e) { console.error('fetchProductionEntry:', e); }
  }

  // BOOT
  container.innerHTML = `<div style="padding:32px;text-align:center;color:rgba(255,255,255,0.7);font-size:15px">Loading equipment data...</div>`;
  try {
    const res  = await fetch(`${CONFIG.baseUrl}/machines`, { headers: auth.getHeaders() });
    const data = await res.json();
    machines   = data.machines || [];
    if (machines.length > 0) {
      const savedId = parseInt(localStorage.getItem('selectedMachineId'), 10);
      selectedId = (savedId && machines.find(m => parseInt(m.id) === savedId))
        ? (localStorage.removeItem('selectedMachineId'), savedId)
        : parseInt(machines[0].id, 10);
    }
  } catch (e) {
    container.innerHTML = `<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:8px;padding:24px;color:#fca5a5">Failed to load machines: ${e.message}</div>`;
    return;
  }

  renderPage();
  if (selectedId) {
    await Promise.all([fetchMachineData(), fetchProductionEntry()]);
    patchPage();
  }

  // Polling
  const id1 = setInterval(async () => {
    if (!selectedId || userIsSelecting) return;
    await fetchMachineData();
    patchPage();
  }, 250);
  state.intervals.push(id1);

  const id2 = setInterval(async () => {
    if (!selectedId || userIsSelecting) return;
    await fetchProductionEntry();
    patchPage();
  }, 10000);
  state.intervals.push(id2);
}
// =====================
// MACHINE STATS
// =====================
async function loadMachineStats(container) {
  container.innerHTML=`<div style="color:white">Loading...</div>`;
  try {
    const res=await fetch(`${CONFIG.baseUrl}/api/machines/live-status`,{headers:auth.getHeaders()});
    const data=await res.json();
    const machines=data.machines||[];
    container.innerHTML=`<h1 class="page-title">Equipment Detail</h1><div class="machines-grid">${machines.map(m=>{const status=(m.machine_state||'OFFLINE').toUpperCase();const sc={RUNNING:'#22c55e',IDLE:'#eab308',STOPPED:'#ef4444',PAUSED:'#f97316',OFFLINE:'#9ca3af'};const c=sc[status]||'#9ca3af';return `<div class="card" style="padding:16px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><strong>${m.vfj_no||'Machine '+m.machine_id}</strong><span style="background:${c};color:white;padding:2px 10px;border-radius:50px;font-size:12px">${status}</span></div><div style="font-size:13px;color:#6b7280;margin-bottom:8px">${m.control_type||''} ${m.control_details||''}</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div style="background:#f9fafb;padding:10px;border-radius:6px;text-align:center"><div style="font-size:11px;color:#9ca3af">Part Count</div><div style="font-size:20px;font-weight:700;color:#2563eb">${m.part_count??'-'}</div></div><div style="background:#f9fafb;padding:10px;border-radius:6px;text-align:center"><div style="font-size:11px;color:#9ca3af">Cycle Time</div><div style="font-size:20px;font-weight:700;color:#16a34a">${m.cycle_time??'-'}</div></div><div style="background:#f9fafb;padding:10px;border-radius:6px;text-align:center"><div style="font-size:11px;color:#9ca3af">Spindle Load</div><div style="font-size:20px;font-weight:700;color:#9333ea">${m.spindle_load??'-'}</div></div><div style="background:#f9fafb;padding:10px;border-radius:6px;text-align:center"><div style="font-size:11px;color:#9ca3af">Feed Rate</div><div style="font-size:20px;font-weight:700;color:#f97316">${m.feed_rate??'-'}</div></div></div></div>`;}).join('')}</div>`;
  } catch(e) { container.innerHTML=`<div class="error-state">Failed to load. ${e.message}</div>`; }
}

// =====================
// OVERVIEW MACHINE
// =====================
async function loadOverview(container) {
  container.innerHTML = `<div style="color:white;padding:20px">Loading dashboard...</div>`;

  const statusColors = {
    RUNNING:     { bg: '#22c55e' },
    IDLE:        { bg: '#eab308' },
    STOPPED:     { bg: '#ef4444' },
    PAUSED:      { bg: '#f97316' },
    OFFLINE:     { bg: '#6b7280' },
    MAINTENANCE: { bg: '#3b82f6' },
    EMERGENCY:   { bg: '#b91c1c' },
  };

  const renderDashboard = (fs, machines, liveMachines, alerts) => {

    // ── Status counts ──────────────────────────────────────────────────────
    const statusCounts = { RUNNING: 0, IDLE: 0, STOPPED: 0, PAUSED: 0, OFFLINE: 0 };
    liveMachines.forEach(m => {
      const s = (m.machine_state || 'OFFLINE').toUpperCase();
      statusCounts[s] !== undefined ? statusCounts[s]++ : statusCounts.OFFLINE++;
    });

    // ── Deduplicated alerts ────────────────────────────────────────────────
    const alertMap = new Map();
    alerts.forEach(a => {
      const key = `${a.machine_id}-${a.message || a.code}`;
      if (!alertMap.has(key) || new Date(a.timestamp) > new Date(alertMap.get(key).timestamp))
        alertMap.set(key, a);
    });
    const recentAlerts = Array.from(alertMap.values()).slice(0, 10);

    // ── Status cards ───────────────────────────────────────────────────────
    const statusCardsHtml = `
      <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin-bottom:24px">
        <div style="background:${statusColors.RUNNING.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.RUNNING}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Running Machines</div>
        </div>
        <div style="background:${statusColors.IDLE.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.IDLE}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Idle Machines</div>
        </div>
        <div style="background:${statusColors.STOPPED.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.STOPPED}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Stopped Machines</div>
        </div>
        <div style="background:${statusColors.PAUSED.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.PAUSED}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Paused Machines</div>
        </div>
        <div style="background:${statusColors.OFFLINE.bg};border-radius:12px;padding:20px 16px;box-shadow:0 4px 12px rgba(0,0,0,.2);text-align:center">
          <div style="font-size:32px;font-weight:800;color:white">${statusCounts.OFFLINE}</div>
          <div style="color:rgba(255,255,255,.9);font-size:13px;font-weight:500;margin-top:8px">Offline Machines</div>
        </div>
      </div>
    `;

    // ── Alarms panel ───────────────────────────────────────────────────────
    const alarmsHtml = `
      <div style="background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.08);
                  height:480px;box-sizing:border-box;display:flex;flex-direction:column">
        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;
                    border-bottom:2px solid #f3f4f6;padding-bottom:12px;margin-bottom:16px">
          <span style="font-size:20px">⚠️</span>
          <h3 style="font-size:18px;font-weight:700;color:#111;margin:0">Alarms &amp; Warning</h3>
        </div>
        <div style="flex:1;overflow-y:auto;padding-right:4px">
          ${recentAlerts.length > 0
            ? recentAlerts.map(a => {
                const sCol = a.severity === 'critical' ? '#dc2626' : a.severity === 'warning' ? '#d97706' : '#3b82f6';
                const sBg  = a.severity === 'critical' ? '#fee2e2' : a.severity === 'warning' ? '#fffbeb' : '#eff6ff';
                return `
                  <div style="padding:12px;background:${sBg};border-radius:8px;margin-bottom:8px">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
                      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                        <span style="font-size:14px">⚠️</span>
                        <span style="font-weight:600;color:#374151;font-size:12px">
                          ${a.timestamp ? formatDate(a.timestamp) : new Date().toLocaleString()}
                        </span>
                        <span style="font-weight:600;color:${sCol};font-size:12px">
                          ${a.machine_name || 'Machine ' + a.machine_id}
                        </span>
                      </div>
                      <span style="background:${sCol};color:white;padding:2px 8px;border-radius:12px;
                                   font-size:10px;font-weight:600;flex-shrink:0">
                        ${(a.severity || 'INFO').toUpperCase()}
                      </span>
                    </div>
                    <div style="color:#6b7280;font-size:12px;margin-left:22px">
                      ${a.message || a.code || 'No message'}
                    </div>
                  </div>`;
              }).join('')
            : `<div style="display:flex;flex-direction:column;align-items:center;
                           justify-content:center;height:100%;text-align:center;padding:40px 20px">
                 <span style="font-size:64px">✅</span>
                 <p style="margin-top:16px;font-size:14px;color:#16a34a;font-weight:500">
                   No active alarms or warnings
                 </p>
                 <p style="margin-top:8px;font-size:12px;color:#9ca3af">
                   All systems operating normally
                 </p>
               </div>`
          }
        </div>
      </div>
    `;

    // ── Production trends panel ────────────────────────────────────────────
    const productionItems = machines
      .map(m => ({
        name:  getMachineDisplayName(m),
        parts: m.parts_produced || 0,
        oee:   ((m.overall_oee || 0) * 100).toFixed(1),
      }))
      .filter(i => i.parts > 0)
      .sort((a, b) => b.parts - a.parts)
      .slice(0, 10);

    const maxParts = Math.max(...productionItems.map(p => p.parts), 1);

    const barChartHtml = `
      <div style="background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.08);
                  height:480px;box-sizing:border-box;display:flex;flex-direction:column">
        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;
                    border-bottom:2px solid #f3f4f6;padding-bottom:12px;margin-bottom:16px">
          <span style="font-size:20px">📊</span>
          <h3 style="font-size:18px;font-weight:700;color:#111;margin:0">Machine Wise Production Trends</h3>
        </div>
        <div style="flex:1;overflow-y:auto;padding-right:4px">
          ${productionItems.length > 0
            ? `${productionItems.map(item => `
                <div style="margin-bottom:18px">
                  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
                    <span style="font-weight:600;color:#374151;font-size:13px">${item.name}</span>
                    <span style="font-weight:700;color:#2563eb;font-size:13px">
                      ${item.parts.toLocaleString()} parts
                    </span>
                  </div>
                  <div style="background:#f3f4f6;border-radius:8px;height:34px;overflow:hidden">
                    <div style="background:linear-gradient(90deg,#2563eb,#3b82f6);
                                width:${(item.parts / maxParts) * 100}%;height:100%;border-radius:8px;
                                display:flex;align-items:center;justify-content:flex-end;
                                padding-right:10px;transition:width .3s ease">
                      <span style="color:white;font-size:11px;font-weight:600">
                        ${Math.round((item.parts / maxParts) * 100)}%
                      </span>
                    </div>
                  </div>
                  <div style="margin-top:3px;font-size:10px;color:#9ca3af;text-align:right">
                    OEE: ${item.oee}%
                  </div>
                </div>`).join('')}
              <div style="margin-top:12px;padding-top:10px;border-top:1px solid #e5e7eb;
                          display:flex;justify-content:space-between;align-items:center">
                <span style="color:#6b7280;font-size:11px">
                  Last updated: ${new Date().toLocaleString()}
                </span>
                <span style="color:#2563eb;font-size:12px;font-weight:600">
                  Total: ${productionItems.reduce((s, i) => s + i.parts, 0).toLocaleString()} parts
                </span>
              </div>`
            : `<div style="display:flex;flex-direction:column;align-items:center;
                           justify-content:center;height:100%;text-align:center;padding:40px 20px">
                 <span style="font-size:64px">📉</span>
                 <p style="margin-top:16px;font-size:14px;color:#9ca3af;font-weight:500">
                   No production data available
                 </p>
                 <p style="margin-top:8px;font-size:12px;color:#9ca3af">
                   Machines with parts &gt; 0 will appear here
                 </p>
               </div>`
          }
        </div>
      </div>
    `;

    // ── Final layout ───────────────────────────────────────────────────────
    container.innerHTML = `
      <div style="padding:0 0 24px 0">
        <h1 style="font-size:24px;font-weight:700;color:#fff;margin:0 0 20px 0">Dashboard Overview</h1>
        ${statusCardsHtml}
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start">
          ${alarmsHtml}
          ${barChartHtml}
        </div>
      </div>
    `;
  };

  const doFetch = async () => {
    const today = new Date().toISOString().slice(0, 10);
    const to = 8000;
    const requests = [
      { name: 'oee', p: fetch(`${CONFIG.baseUrl}/api/oee/calculate?start_date=${today}&end_date=${today}`, { headers: auth.getHeaders(), timeout: to }) },
      { name: 'live', p: fetch(`${CONFIG.baseUrl}/api/machines/live-status`, { headers: auth.getHeaders(), timeout: to }) },
      { name: 'alerts', p: fetch(`${CONFIG.baseUrl}/api/alerts?limit=50`, { headers: auth.getHeaders(), timeout: to }) },
    ];

    const results = await Promise.all(requests.map(r => r.p.catch(err => ({ __error: err, __name: r.name }))));
    for (const res of results) {
      if (res && res.__error) throw new Error(`Failed to fetch ${res.__name}: ${res.__error.message || res.__error}`);
      if (!res || !res.ok) throw new Error(`Request failed: ${res && res.url ? new URL(res.url).pathname : 'unknown'} (status ${res ? res.status : 'no response'})`);
    }

    const [oeeData, liveData, alertData] = await Promise.all(results.map(r => r.json()));
    renderDashboard(
      oeeData.fleet_summary       || {},
      oeeData.individual_machines || [],
      liveData.machines           || [],
      alertData.alerts || alertData.alarms || []
    );
  };

  try {
    await doFetch();
    const iv = setInterval(() => doFetch().catch(() => {}), 10000);
    state.intervals.push(iv);
  } catch (e) {
    container.innerHTML = `<div class="error-state">Failed to load dashboard. ${e.message}</div>`;
  }
}

// =====================
// GROUP RESULT  (FIX #7 — 24h default)
// =====================
async function loadGroupResult(container) {
  container.innerHTML = `<div style="color:white">Loading...</div>`;
  container.innerHTML = `<h1 class="page-title">Group Result</h1>
    <div class="filters-row">
      <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="gr-machine"><option value="">All Machines</option></select></div>
      <div class="filter-group"><label class="filter-label">Start</label><input class="filter-input" type="datetime-local" id="gr-start" value="${last24hStart()}"/></div>
      <div class="filter-group"><label class="filter-label">End</label><input class="filter-input" type="datetime-local" id="gr-end" value="${nowDatetime()}"/></div>
      <button class="btn btn-blue" onclick="fetchGroupResult()">Apply</button>
      <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Group Result','gr-table')">PDF</button>
    </div>
    <div id="gr-kpi" class="kpi-grid"></div>
    <div class="chart-container" id="gr-chart"><div style="color:#6b7280;text-align:center;padding:32px">Loading chart...</div></div>
    <div id="gr-table-wrap"></div>`;
  
  try {
    const mRes = await fetch(`${CONFIG.baseUrl}/machines`, { headers: auth.getHeaders() });
    const mData = await mRes.json();
    const sel = $('gr-machine');
    (mData.machines || []).forEach(m => { sel.innerHTML += `<option value="${m.id}">${m.vfj_no}</option>`; });
  } catch(e) {}

  window.fetchGroupResult = async () => {
    const machineId = $('gr-machine').value, start = $('gr-start').value.replace('T', ' '), end = $('gr-end').value.replace('T', ' ');
    const url = `${CONFIG.baseUrl}/api/oee/calculate?start_time=${encodeURIComponent(start)}&end_time=${encodeURIComponent(end)}${machineId ? '&machine_id=' + machineId : ''}`;
    try {
      const res = await fetch(url, { headers: auth.getHeaders() });
      const data = await res.json();
      const avg = data.overall_averages || data.averages || {};
      const machines = data.individual_machines || data.machines || [];
      $('gr-kpi').innerHTML = `<div class="kpi-card kpi-card-oee"><div class="label">Overall OEE</div><div class="value">${(avg.average_oee || avg.oee || 0).toFixed(1)}%</div></div>
        <div class="kpi-card kpi-card-avail"><div class="label">Availability</div><div class="value">${(avg.average_availability || avg.availability || 0).toFixed(1)}%</div></div>
        <div class="kpi-card kpi-card-perf"><div class="label">Performance</div><div class="value">${(avg.average_performance || avg.performance || 0).toFixed(1)}%</div></div>
        <div class="kpi-card kpi-card-quality"><div class="label">Quality</div><div class="value">${(avg.average_quality || avg.quality || 0).toFixed(1)}%</div></div>`;
      const chartData = { keys: ['Availability', 'Performance', 'Quality', 'OEE'], colors: ['#22c55e', '#f97316', '#3b82f6', '#9333ea'], items: machines.map(m => ({ name: getMachineDisplayName(m), Availability: +(m.availability || 0).toFixed(1), Performance: +(m.performance || 0).toFixed(1), Quality: +(m.quality || 0).toFixed(1), OEE: +(m.oee || 0).toFixed(1) })) };
      $('gr-chart').innerHTML = `<div class="chart-title">Machine-wise OEE</div>${createBarChart({ data: chartData, width: Math.max(700, machines.length * 120), height: 280 })}`;
      $('gr-table-wrap').innerHTML = `<div class="table-wrapper"><table class="data-table" id="gr-table"><thead><tr><th>Machine</th><th>Availability %</th><th>Performance %</th><th>Quality %</th><th>OEE %</th><th>Parts</th></tr></thead><tbody>${machines.map(m => `<tr><td>${getMachineDisplayName(m)}</td><td>${((m.availability || 0) * 100).toFixed(1)}%</td><td>${((m.performance || 0) * 100).toFixed(1)}%</td><td>${((m.quality || 0) * 100).toFixed(1)}%</td><td><strong>${((m.oee || 0) * 100).toFixed(1)}%</strong></td><td>${m.parts_produced || 0}</td></tr>`).join('')}</tbody></table></div>`;
    } catch (e) { $('gr-kpi').innerHTML = `<div class="error-state" style="grid-column:1/-1">Failed to load. ${e.message}</div>`; }
  };
  
  // AUTO-FETCH: Load 24-hour data by default
  window.fetchGroupResult();
}

// =====================
// OPERATING RESULT  (FIX #7 — 24h default)
// =====================
async function loadOperatingResult(container) {
  container.innerHTML = `<h1 class="page-title">Operation Result</h1>
    <div class="filters-row">
      <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="or-machine"><option value="">All</option></select></div>
      <div class="filter-group"><label class="filter-label">Start</label><input class="filter-input" type="datetime-local" id="or-start" value="${last24hStart()}"/></div>
      <div class="filter-group"><label class="filter-label">End</label><input class="filter-input" type="datetime-local" id="or-end" value="${nowDatetime()}"/></div>
      <button class="btn btn-blue" onclick="fetchOperatingResult()">Apply</button>
      <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Operation Result','or-table')">PDF</button>
    </div>
    <div id="or-content"><div style="color:white;opacity:0.7">Loading 24-hour data...</div></div>`;
  
  try {
    const mRes = await fetch(`${CONFIG.baseUrl}/machines`, { headers: auth.getHeaders() });
    const mData = await mRes.json();
    const sel = $('or-machine');
    (mData.machines || []).forEach(m => { sel.innerHTML += `<option value="${m.id}">${m.vfj_no}</option>`; });
  } catch {}

  window.fetchOperatingResult = async () => {
    const machineId = $('or-machine').value, start = $('or-start').value.replace('T', ' '), end = $('or-end').value.replace('T', ' ');
    try {
      const res = await fetch(`${CONFIG.baseUrl}/api/oee/calculate?start_time=${encodeURIComponent(start)}&end_time=${encodeURIComponent(end)}${machineId ? '&machine_id=' + machineId : ''}`, { headers: auth.getHeaders() });
      const data = await res.json(), machines = data.individual_machines || data.machines || [];
      $('or-content').innerHTML = `<div class="table-wrapper"><table class="data-table" id="or-table"><thead><tr><th>Machine</th><th>Availability %</th><th>Performance %</th><th>Quality %</th><th>OEE %</th></tr></thead><tbody>${machines.map(m => `<tr><td>${getMachineDisplayName(m)}</td><td>${(m.availability || 0).toFixed(1)}%</td><td>${(m.performance || 0).toFixed(1)}%</td><td>${(m.quality || 0).toFixed(1)}%</td><td><strong>${(m.oee || 0).toFixed(1)}%</strong></td></tr>`).join('')}</tbody></table></div>`;
    } catch (e) { $('or-content').innerHTML = `<div class="error-state">Failed. ${e.message}</div>`; }
  };
  
  // AUTO-FETCH: Load 24-hour data by default
  window.fetchOperatingResult();
}

// =====================
// PRODUCTION RESULT  (FIX #4 + #7 + #8)
// =====================
async function loadProductionResult(container) {
  container.innerHTML = `<h1 class="page-title">Production Result</h1>
    <div class="filters-row">
      <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="pr-machine"><option value="">All</option></select></div>
      <div class="filter-group"><label class="filter-label">Start</label><input class="filter-input" type="datetime-local" id="pr-start" value="${last24hStart()}"/></div>
      <div class="filter-group"><label class="filter-label">End</label><input class="filter-input" type="datetime-local" id="pr-end" value="${nowDatetime()}"/></div>
      <button class="btn btn-blue" onclick="fetchProductionResult()">Apply</button>
      <button class="export-btn export-csv" onclick="exportProductionCSV()">CSV</button>
      <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Production Result','pr-table')">PDF</button>
    </div>
    <div id="pr-content"><div style="color:white;opacity:0.7">Loading 24-hour data...</div></div>`;
  
  let lastData = [];
  
  try {
    const mRes = await fetch(`${CONFIG.baseUrl}/machines`, { headers: auth.getHeaders() });
    const mData = await mRes.json();
    const sel = $('pr-machine');
    (mData.machines || []).forEach(m => { sel.innerHTML += `<option value="${m.id}">${m.vfj_no}</option>`; });
  } catch {}

  window.fetchProductionResult = async () => {
    const machineId = $('pr-machine').value, start = $('pr-start').value.replace('T', ' '), end = $('pr-end').value.replace('T', ' ');
    const url = `${CONFIG.baseUrl}/reports/production?from_datetime=${encodeURIComponent(start)}&to_datetime=${encodeURIComponent(end)}${machineId ? '&machine_id=' + machineId : ''}`;
    try {
      const res = await fetch(url, { headers: auth.getHeaders() });
      const data = await res.json();
      lastData = data.shift_data || data.data || data.records || [];
      if (!Array.isArray(lastData)) lastData = [];
      $('pr-content').innerHTML = `<div class="table-wrapper"><table class="data-table" id="pr-table">
        <thead><tr><th>Date</th><th>Machine</th><th>Operator</th><th>Product</th><th>OK Parts</th><th>Bad Parts</th><th>Status</th></tr></thead>
        <tbody>${lastData.map(r => `<tr>
          <td>${formatDate(r.timestamp)}</td><td>${r.machine_name || r.machine_id || '-'}</td>
          <td>${r.shift_operator_name || '-'}</td><td>${r.product_component_name || '-'}</td>
          <td style="color:#16a34a;font-weight:600">${r.ok_parts || 0}</td>
          <td style="color:#dc2626;font-weight:600">${r.bad_parts || 0}</td>
          <td>${r.machine_status || '-'}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
    } catch (e) { $('pr-content').innerHTML = `<div class="error-state">Failed. ${e.message}</div>`; }
  };
  
  window.exportProductionCSV = () => {
    let csv = 'Date,Machine,Operator,OK Parts,Bad Parts,Status\n';
    lastData.forEach(r => {
      csv += `"${formatDate(r.timestamp)}","${r.machine_name || r.machine_id || ''}","${r.shift_operator_name || ''}","${r.ok_parts || 0}","${r.bad_parts || 0}","${r.machine_status || ''}"\n`;
    });
    downloadCSV(csv, 'production_result.csv');
  };
  
  // AUTO-FETCH: Load 24-hour data by default
  window.fetchProductionResult();
}

// =====================
// POWER CONSUMPTION  (FIX #5 + #7 + #8)
// =====================
async function loadPowerConsumption(container) {
  container.innerHTML = `<h1 class="page-title">Power Consumption</h1>
    <div class="filters-row">
      <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="pc-machine"><option value="">All</option></select></div>
      <div class="filter-group"><label class="filter-label">Start</label><input class="filter-input" type="datetime-local" id="pc-start" value="${last24hStart()}"/></div>
      <div class="filter-group"><label class="filter-label">End</label><input class="filter-input" type="datetime-local" id="pc-end" value="${nowDatetime()}"/></div>
      <button class="btn btn-blue" onclick="fetchPowerData()">Apply</button>
      <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Power Consumption','pc-table')">PDF</button>
    </div>
    <div id="pc-content"><div style="color:white;opacity:0.7">Loading 24-hour data...</div></div>`;
  
  try {
    const mRes = await fetch(`${CONFIG.baseUrl}/machines`, { headers: auth.getHeaders() });
    const mData = await mRes.json();
    const sel = $('pc-machine');
    (mData.machines || []).forEach(m => { sel.innerHTML += `<option value="${m.id}">${m.vfj_no}</option>`; });
  } catch {}

  window.fetchPowerData = async () => {
    const machineId = $('pc-machine').value, start = $('pc-start').value.replace('T', ' '), end = $('pc-end').value.replace('T', ' ');
    const url = `${CONFIG.baseUrl}/reports/energy?from_datetime=${encodeURIComponent(start)}&to_datetime=${encodeURIComponent(end)}${machineId ? '&machine_id=' + machineId : ''}`;
    try {
      const res = await fetch(url, { headers: auth.getHeaders() });
      const data = await res.json();
      let records = data.energy_data || data.data || data.records || [];
      if (!Array.isArray(records)) records = [];
      const labels = records.map(r => r.latest_timestamp ? new Date(r.latest_timestamp).toLocaleTimeString() : '');
      $('pc-content').innerHTML = `
        <div class="chart-container">${createLineChart({ data: [{ name: 'Power (kW)', values: records.map(r => +(r.latest_power_kw || r.avg_power_kw || 0)) }], labels, width: 700, height: 220 })}</div>
        <div class="table-wrapper"><table class="data-table" id="pc-table">
          <thead><tr><th>Machine</th><th>Latest Power (kW)</th><th>Avg Power (kW)</th><th>Peak Power (kW)</th><th>Total Energy (kWh)</th><th>V1</th><th>V2</th><th>V3</th><th>I1</th><th>I2</th><th>I3</th></tr></thead>
          <tbody>${records.map(r => `<tr>
            <td>${r.machine_id || '-'}</td><td>${r.latest_power_kw || '-'}</td><td>${r.avg_power_kw || '-'}</td>
            <td>${r.peak_power_kw || '-'}</td><td>${r.total_energy_kWh || '-'}</td>
            <td>${r.voltage1 || '-'}</td><td>${r.voltage2 || '-'}</td><td>${r.voltage3 || '-'}</td>
            <td>${r.current1 || '-'}</td><td>${r.current2 || '-'}</td><td>${r.current3 || '-'}</td>
          </tr>`).join('')}</tbody>
        </table></div>`;
    } catch (e) { $('pc-content').innerHTML = `<div class="error-state">Failed. ${e.message}</div>`; }
  };
  
  // AUTO-FETCH: Load 24-hour data by default
  window.fetchPowerData();
}

// =====================
// BREAKDOWN RESULT  (FIX #6 + #7 + #8 — correct URL /reports/breakdowns, vfj_no param)
// =====================
async function loadBreakdownResult(container) {
  let machinesList = [];
  container.innerHTML = `<h1 class="page-title">Breakdown Analysis</h1>
    <div class="filters-row">
      <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="bd-machine"><option value="">All</option></select></div>
      <div class="filter-group"><label class="filter-label">Start Date</label><input class="filter-input" type="date" id="bd-start" value="${new Date(Date.now() - 86400000).toISOString().slice(0, 10)}"/></div>
      <div class="filter-group"><label class="filter-label">End Date</label><input class="filter-input" type="date" id="bd-end" value="${new Date().toISOString().slice(0, 10)}"/></div>
      <button class="btn btn-blue" onclick="fetchBreakdownData()">Apply</button>
      <button class="export-btn export-csv" onclick="exportBreakdownCSV()">CSV</button>
      <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Breakdown Analysis','bd-table')">PDF</button>
    </div>
    <div id="bd-kpi" class="kpi-grid" style="grid-template-columns:repeat(3,1fr);margin-bottom:20px"></div>
    <div id="bd-content"><div style="color:white;opacity:0.7">Loading 24-hour data...</div></div>`;
  
  let lastData = [];
  
  try {
    const mRes = await fetch(`${CONFIG.baseUrl}/machines`, { headers: auth.getHeaders() });
    const mData = await mRes.json();
    machinesList = mData.machines || [];
    const sel = $('bd-machine');
    machinesList.forEach(m => { sel.innerHTML += `<option value="${m.vfj_no || ''}">${m.vfj_no || m.oem_name}</option>`; });
  } catch {}

  window.fetchBreakdownData = async () => {
    const vfjNo = $('bd-machine').value;
    const s = $('bd-start').value, e = $('bd-end').value;
    const url = `${CONFIG.baseUrl}/reports/breakdowns?from_date=${encodeURIComponent(s)}&to_date=${encodeURIComponent(e)}${vfjNo ? '&vfj_no=' + encodeURIComponent(vfjNo) : ''}`;
    try {
      const res = await fetch(url, { headers: auth.getHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data = await res.json();
      lastData = data.breakdowns || [];
      if (!Array.isArray(lastData)) lastData = [];
      const totalSec = lastData.reduce((s, r) => s + (r.duration_seconds || 0), 0);
      const avgSec = lastData.length ? totalSec / lastData.length : 0;
      $('bd-kpi').innerHTML = `
        <div class="kpi-card" style="background:#ef4444"><div class="label">Total Breakdowns</div><div class="value">${lastData.length}</div></div>
        <div class="kpi-card" style="background:#f97316"><div class="label">Total Duration</div><div class="value">${(totalSec / 3600).toFixed(1)} hrs</div></div>
        <div class="kpi-card" style="background:#3b82f6"><div class="label">Avg Duration</div><div class="value">${(avgSec / 60).toFixed(1)} min</div></div>`;
      $('bd-content').innerHTML = `<div class="table-wrapper"><table class="data-table" id="bd-table">
        <thead><tr><th>Machine</th><th>Machine No</th><th>Breakdown Start</th><th>Recovery Start</th><th>Duration</th></tr></thead>
        <tbody>${lastData.map(r => `<tr>
          <td>${r.machine_name || '-'}</td><td>${r.vfj_no || '-'}</td>
          <td>${formatDate(r.breakdown_start)}</td>
          <td>${r.idle_start ? formatDate(r.idle_start) : '-'}</td>
          <td>${r.duration_hms || ((r.duration_seconds || 0) / 3600).toFixed(2) + ' hrs'}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
    } catch (e) { $('bd-content').innerHTML = `<div class="error-state">Failed to load. ${e.message}</div>`; }
  };
  
  window.exportBreakdownCSV = () => {
    let csv = 'Machine,Machine No,Breakdown Start,Recovery Start,Duration\n';
    lastData.forEach(r => {
      csv += `"${r.machine_name || ''}","${r.vfj_no || ''}","${formatDate(r.breakdown_start)}","${r.idle_start ? formatDate(r.idle_start) : ''}","${r.duration_hms || ''}"\n`;
    });
    downloadCSV(csv, 'breakdown.csv');
  };
  
  // AUTO-FETCH: Load 24-hour data by default
  window.fetchBreakdownData();
}
// =====================
// REPORTS (Diagnosis tabs)
// =====================
function loadReports(container) {
  state._reportSubTab=state._reportSubTab||'oee';
  const tabs=[{id:'oee',label:'OEE Report'},{id:'production',label:'Production Report'},{id:'downtime',label:'Downtime Report'},{id:'energy',label:'Energy Report'},{id:'breakdown',label:'Breakdown Report'}];
  const tabsHtml=tabs.map(t=>`<button class="report-tab ${state._reportSubTab===t.id?'active':''}" onclick="switchReportTab('${t.id}')">${t.label}</button>`).join('');
  container.innerHTML=`<div class="report-tabs">${tabsHtml}</div><div id="report-body" style="padding-top:12px"></div>`;
  window.switchReportTab=(id)=>{
    state._reportSubTab=id;
    container.querySelectorAll('.report-tab').forEach(b=>{b.classList.toggle('active',tabs.find(t=>t.id===id)?.label===b.textContent.trim());});
    loadReportSubTab(id,$('report-body'));
  };
  loadReportSubTab(state._reportSubTab,$('report-body'));
}

async function loadReportSubTab(tab,container) {
  if(!container) return;
  if(tab==='oee') loadOeeReport(container);
  else if(tab==='production') loadProductionReport(container);
  else if(tab==='downtime') loadDowntimeReport(container);
  else if(tab==='energy') loadEnergyReport(container);
  else if(tab==='breakdown') loadBreakdownReport(container);
}

// ── OEE Report ─────────────────────────────────────────────────────────────
async function loadOeeReport(container) {
  const mOpts=await getMachineOptions();
  container.innerHTML=`<div class="filters-row">
    <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="oee-machine">${mOpts}</select></div>
    <div class="filter-group"><label class="filter-label">Start Date</label><input class="filter-input" type="date" id="oee-start" value="${new Date(Date.now()-86400000).toISOString().slice(0,10)}"/></div>
    <div class="filter-group"><label class="filter-label">End Date</label><input class="filter-input" type="date" id="oee-end" value="${new Date().toISOString().slice(0,10)}"/></div>
    <button class="btn btn-blue" onclick="runOeeReport()">Generate</button>
    <button class="export-btn export-csv" onclick="exportOeeCSV()">CSV</button>
    <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('OEE Report','oee-report-table')">PDF</button>
  </div><div id="oee-report-data"><div style="color:white;opacity:0.6">Click Generate</div></div>`;
  let lastData=[];
  window.runOeeReport=async()=>{
    const m=$('oee-machine').value, s=$('oee-start').value, e=$('oee-end').value;
    try {
      const res=await fetch(`${CONFIG.baseUrl}/api/oee/calculate?start_date=${encodeURIComponent(s)}&end_date=${encodeURIComponent(e)}${m?'&machine_id='+m:''}`,{headers:auth.getHeaders()});
      const data=await res.json();
      lastData=data.individual_machines||[];
      const fs=data.fleet_summary||{}, pct=v=>((v||0)*100).toFixed(1);
      $('oee-report-data').innerHTML=`
        <div class="kpi-grid" style="margin-bottom:20px">
          <div class="kpi-card kpi-card-oee"><div class="label">OEE</div><div class="value">${pct(fs.fleet_overall_oee)}%</div></div>
          <div class="kpi-card kpi-card-avail"><div class="label">Availability</div><div class="value">${pct(fs.fleet_availability)}%</div></div>
          <div class="kpi-card kpi-card-perf"><div class="label">Performance</div><div class="value">${pct(fs.fleet_performance)}%</div></div>
          <div class="kpi-card kpi-card-quality"><div class="label">Quality</div><div class="value">${pct(fs.fleet_quality)}%</div></div>
        </div>
        <div class="chart-container">${createBarChart({data:{keys:['Availability','Performance','Quality','OEE'],colors:['#22c55e','#f97316','#3b82f6','#9333ea'],items:lastData.map(m=>({name:getMachineDisplayName(m),Availability:+((m.availability||0)*100).toFixed(1),Performance:+((m.performance||0)*100).toFixed(1),Quality:+((m.quality||0)*100).toFixed(1),OEE:+((m.overall_oee||0)*100).toFixed(1)}))},width:Math.max(500,lastData.length*120),height:250})}</div>
        <div class="table-wrapper"><table class="data-table" id="oee-report-table">
          <thead><tr><th>Machine</th><th>Machine No</th><th>Availability %</th><th>Performance %</th><th>Quality %</th><th>OEE %</th><th>Parts</th><th>Downtime (min)</th></tr></thead>
          <tbody>${lastData.map(m=>`<tr>
            <td>${getMachineDisplayName(m)}</td><td>${m.vfj_no||'-'}</td>
            <td>${((m.availability||0)*100).toFixed(1)}%</td>
            <td>${((m.performance||0)*100).toFixed(1)}%</td>
            <td>${((m.quality||0)*100).toFixed(1)}%</td>
            <td><strong>${((m.overall_oee||0)*100).toFixed(1)}%</strong></td>
            <td>${m.parts_produced||0}</td>
            <td>${m.total_downtime_minutes||0}</td>
          </tr>`).join('')}</tbody>
        </table></div>`;
    } catch(e) { $('oee-report-data').innerHTML=`<div class="error-state">Failed. ${e.message}</div>`; }
  };
  window.exportOeeCSV=()=>{let csv='Machine,Machine No,Availability,Performance,Quality,OEE,Parts\n';lastData.forEach(m=>{csv+=`"${getMachineDisplayName(m)}","${m.vfj_no||''}","${((m.availability||0)*100).toFixed(1)}","${((m.performance||0)*100).toFixed(1)}","${((m.quality||0)*100).toFixed(1)}","${((m.overall_oee||0)*100).toFixed(1)}","${m.parts_produced||0}"\n`;});downloadCSV(csv,'oee_report.csv');};
}

// ── Production Report ───────────────────────────────────────────────────────
async function loadProductionReport(container) {
  const mOpts=await getMachineOptions();
  container.innerHTML=`<div class="filters-row">
    <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="rpr-machine">${mOpts}</select></div>
    <div class="filter-group"><label class="filter-label">Start</label><input class="filter-input" type="datetime-local" id="rpr-start" value="${last24hStart()}"/></div>
    <div class="filter-group"><label class="filter-label">End</label><input class="filter-input" type="datetime-local" id="rpr-end" value="${nowDatetime()}"/></div>
    <button class="btn btn-blue" onclick="runProductionReport()">Generate</button>
    <button class="export-btn export-csv" onclick="exportRprCSV()">CSV</button>
    <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Production Report','rpr-table')">PDF</button>
  </div><div id="rpr-data"><div style="color:white;opacity:0.6">Click Generate</div></div>`;
  let lastData=[];
  window.runProductionReport=async()=>{
    const m=$('rpr-machine').value, s=$('rpr-start').value.replace('T',' '), e=$('rpr-end').value.replace('T',' ');
    try {
      const res=await fetch(`${CONFIG.baseUrl}/reports/production?from_datetime=${encodeURIComponent(s)}&to_datetime=${encodeURIComponent(e)}${m?'&machine_id='+m:''}`,{headers:auth.getHeaders()});
      const data=await res.json();
      lastData=data.shift_data||data.data||data.records||[];
      if(!Array.isArray(lastData)) lastData=[];
      $('rpr-data').innerHTML=`<div class="table-wrapper"><table class="data-table" id="rpr-table">
        <thead><tr><th>Date</th><th>Machine</th><th>Operator</th><th>Product</th><th>Batch Qty</th><th>OK Parts</th><th>Bad Parts</th><th>Status</th></tr></thead>
        <tbody>${lastData.map(r=>`<tr>
          <td>${formatDate(r.timestamp)}</td><td>${r.machine_name||r.machine_id||'-'}</td>
          <td>${r.shift_operator_name||'-'}</td><td>${r.product_component_name||'-'}</td>
          <td>${r.batch_quantity||'-'}</td>
          <td style="color:#16a34a;font-weight:600">${r.ok_parts||0}</td>
          <td style="color:#dc2626;font-weight:600">${r.bad_parts||0}</td>
          <td>${r.machine_status||'-'}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
    } catch(e) { $('rpr-data').innerHTML=`<div class="error-state">Failed. ${e.message}</div>`; }
  };
  window.exportRprCSV=()=>{let csv='Date,Machine,Operator,OK Parts,Bad Parts,Status\n';lastData.forEach(r=>{csv+=`"${formatDate(r.timestamp)}","${r.machine_name||r.machine_id||''}","${r.shift_operator_name||''}","${r.ok_parts||0}","${r.bad_parts||0}","${r.machine_status||''}"\n`;});downloadCSV(csv,'production_report.csv');};
}

// ── Downtime Report ─────────────────────────────────────────────────────────
async function loadDowntimeReport(container) {
  const mOpts=await getMachineOptions();
  container.innerHTML=`<div class="filters-row">
    <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="dt-machine">${mOpts}</select></div>
    <div class="filter-group"><label class="filter-label">Start</label><input class="filter-input" type="datetime-local" id="dt-start" value="${last24hStart()}"/></div>
    <div class="filter-group"><label class="filter-label">End</label><input class="filter-input" type="datetime-local" id="dt-end" value="${nowDatetime()}"/></div>
    <button class="btn btn-blue" onclick="runDowntimeReport()">Generate</button>
    <button class="export-btn export-csv" onclick="exportDtCSV()">CSV</button>
    <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Downtime Report','dt-table')">PDF</button>
  </div><div id="dt-data"><div style="color:white;opacity:0.6">Click Generate</div></div>`;
  let lastData=[];
  window.runDowntimeReport=async()=>{
    const m=$('dt-machine').value, s=$('dt-start').value.replace('T',' '), e=$('dt-end').value.replace('T',' ');
    try {
      const res=await fetch(`${CONFIG.baseUrl}/reports/downtime?from_datetime=${encodeURIComponent(s)}&to_datetime=${encodeURIComponent(e)}${m?'&machine_id='+m:''}`,{headers:auth.getHeaders()});
      const data=await res.json();
      lastData=data.downtime_events||data.data||data.records||[];
      if(!Array.isArray(lastData)) lastData=[];
      $('dt-data').innerHTML=`<div class="table-wrapper"><table class="data-table" id="dt-table">
        <thead><tr><th>Machine</th><th>Start</th><th>End</th><th>Duration (min)</th><th>Reason</th></tr></thead>
        <tbody>${lastData.map(r=>`<tr>
          <td>${r.machine_name||r.machine_id||'-'}</td>
          <td>${formatDate(r.start_time)}</td><td>${r.end_time?formatDate(r.end_time):'-'}</td>
          <td>${r.duration_minutes!=null?Number(r.duration_minutes).toFixed(1):'-'}</td>
          <td>${r.reason||'-'}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
    } catch(e) { $('dt-data').innerHTML=`<div class="error-state">Failed. ${e.message}</div>`; }
  };
  window.exportDtCSV=()=>{let csv='Machine,Start,End,Duration (min),Reason\n';lastData.forEach(r=>{csv+=`"${r.machine_name||r.machine_id||''}","${formatDate(r.start_time)}","${r.end_time?formatDate(r.end_time):''}","${r.duration_minutes||''}","${r.reason||''}"\n`;});downloadCSV(csv,'downtime_report.csv');};
}

// ── Energy Report ───────────────────────────────────────────────────────────
async function loadEnergyReport(container) {
  const mOpts=await getMachineOptions();
  container.innerHTML=`<div class="filters-row">
    <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="er-machine">${mOpts}</select></div>
    <div class="filter-group"><label class="filter-label">Start</label><input class="filter-input" type="datetime-local" id="er-start" value="${last24hStart()}"/></div>
    <div class="filter-group"><label class="filter-label">End</label><input class="filter-input" type="datetime-local" id="er-end" value="${nowDatetime()}"/></div>
    <button class="btn btn-blue" onclick="runEnergyReport()">Generate</button>
    <button class="export-btn export-csv" onclick="exportErCSV()">CSV</button>
    <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Energy Report','er-table')">PDF</button>
  </div><div id="er-data"><div style="color:white;opacity:0.6">Click Generate</div></div>`;
  let lastData=[];
  window.runEnergyReport=async()=>{
    const m=$('er-machine').value, s=$('er-start').value.replace('T',' '), e=$('er-end').value.replace('T',' ');
    try {
      const res=await fetch(`${CONFIG.baseUrl}/reports/energy?from_datetime=${encodeURIComponent(s)}&to_datetime=${encodeURIComponent(e)}${m?'&machine_id='+m:''}`,{headers:auth.getHeaders()});
      const data=await res.json();
      lastData=data.energy_data||data.data||data.records||[];
      if(!Array.isArray(lastData)) lastData=[];
      const labels=lastData.map(r=>r.latest_timestamp?new Date(r.latest_timestamp).toLocaleTimeString():'');
      $('er-data').innerHTML=`
        <div class="chart-container">${createLineChart({data:[{name:'Power (kW)',values:lastData.map(r=>+(r.latest_power_kw||0))},{name:'Avg Power (kW)',values:lastData.map(r=>+(r.avg_power_kw||0))}],labels,width:700,height:220})}</div>
        <div class="table-wrapper"><table class="data-table" id="er-table">
          <thead><tr><th>Machine</th><th>Latest Power (kW)</th><th>Avg Power (kW)</th><th>Peak Power (kW)</th><th>Total Energy (kWh)</th><th>V1</th><th>V2</th><th>V3</th><th>I1</th><th>I2</th><th>I3</th></tr></thead>
          <tbody>${lastData.map(r=>`<tr>
            <td>${r.machine_id||'-'}</td><td>${r.latest_power_kw||'-'}</td><td>${r.avg_power_kw||'-'}</td>
            <td>${r.peak_power_kw||'-'}</td><td>${r.total_energy_kWh||'-'}</td>
            <td>${r.voltage1||'-'}</td><td>${r.voltage2||'-'}</td><td>${r.voltage3||'-'}</td>
            <td>${r.current1||'-'}</td><td>${r.current2||'-'}</td><td>${r.current3||'-'}</td>
          </tr>`).join('')}</tbody>
        </table></div>`;
    } catch(e) { $('er-data').innerHTML=`<div class="error-state">Failed. ${e.message}</div>`; }
  };
  window.exportErCSV=()=>{let csv='Machine,Latest Power kW,Avg Power kW,Total Energy kWh\n';lastData.forEach(r=>{csv+=`"${r.machine_id||''}","${r.latest_power_kw||''}","${r.avg_power_kw||''}","${r.total_energy_kWh||''}"\n`;});downloadCSV(csv,'energy_report.csv');};
}

// ── Breakdown Report (in Reports tab)  FIX #6 — /reports/breakdowns + vfj_no ─
async function loadBreakdownReport(container) {
  // Use vfj_no-based select since the PHP endpoint only supports vfj_no filter
  let machinesList=[];
  try {const mRes=await fetch(`${CONFIG.baseUrl}/machines`,{headers:auth.getHeaders()});const d=await mRes.json();machinesList=d.machines||[];} catch {}
  const mOptsVfj=`<option value="">All Machines</option>${machinesList.map(m=>`<option value="${m.vfj_no||''}">${m.vfj_no||m.oem_name}</option>`).join('')}`;

  container.innerHTML=`<div class="filters-row">
    <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="br-machine">${mOptsVfj}</select></div>
    <div class="filter-group"><label class="filter-label">Start Date</label><input class="filter-input" type="date" id="br-start" value="${new Date(Date.now()-86400000).toISOString().slice(0,10)}"/></div>
    <div class="filter-group"><label class="filter-label">End Date</label><input class="filter-input" type="date" id="br-end" value="${new Date().toISOString().slice(0,10)}"/></div>
    <button class="btn btn-blue" onclick="runBreakdownReport()">Generate</button>
    <button class="export-btn export-csv" onclick="exportBrCSV()">CSV</button>
    <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Breakdown Report','br-table')">PDF</button>
  </div><div id="br-data"><div style="color:white;opacity:0.6">Click Generate</div></div>`;
  let lastData=[];
  window.runBreakdownReport=async()=>{
    const vfjNo=$('br-machine').value, s=$('br-start').value, e=$('br-end').value;
    try {
      // FIX: correct plural endpoint + vfj_no param
      const url=`${CONFIG.baseUrl}/reports/breakdowns?from_date=${encodeURIComponent(s)}&to_date=${encodeURIComponent(e)}${vfjNo?'&vfj_no='+encodeURIComponent(vfjNo):''}`;
      const res=await fetch(url,{headers:auth.getHeaders()});
      if(!res.ok) throw new Error(`HTTP ${res.status}`);
      const data=await res.json();
      lastData=data.breakdowns||[];
      if(!Array.isArray(lastData)) lastData=[];
      $('br-data').innerHTML=`<div class="table-wrapper"><table class="data-table" id="br-table">
        <thead><tr><th>Machine</th><th>Machine No</th><th>Breakdown Start</th><th>Recovery Start</th><th>Duration</th></tr></thead>
        <tbody>${lastData.map(r=>`<tr>
          <td>${r.machine_name||'-'}</td><td>${r.vfj_no||'-'}</td>
          <td>${formatDate(r.breakdown_start)}</td>
          <td>${r.idle_start?formatDate(r.idle_start):'-'}</td>
          <td>${r.duration_hms||((r.duration_seconds||0)/3600).toFixed(2)+' hrs'}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
    } catch(e) { $('br-data').innerHTML=`<div class="error-state">Failed. ${e.message}</div>`; }
  };
  window.exportBrCSV=()=>{let csv='Machine,Machine No,Breakdown Start,Recovery Start,Duration\n';lastData.forEach(r=>{csv+=`"${r.machine_name||''}","${r.vfj_no||''}","${formatDate(r.breakdown_start)}","${r.idle_start?formatDate(r.idle_start):''}","${r.duration_hms||''}"\n`;});downloadCSV(csv,'breakdown_report.csv');};
}

// =====================
// DATA ENTRIES
// =====================
function loadDataEntries(container) {
  const tabs=['production','quality','downtime','breakdown'];
  state._dataEntriesSubTab=state._dataEntriesSubTab||'production';
  const tabsHtml=`<div class="data-entry-tabs">${tabs.map(t=>`<button class="data-entry-tab ${state._dataEntriesSubTab===t?'active':''}" onclick="switchDataEntryTab('${t}')">${t.charAt(0).toUpperCase()+t.slice(1)}</button>`).join('')}</div>`;
  container.innerHTML=`<h1 class="page-title">Data Entries</h1>${tabsHtml}<div id="de-content"></div>`;
  window.switchDataEntryTab=(tab)=>{state._dataEntriesSubTab=tab;container.querySelectorAll('.data-entry-tab').forEach(b=>b.classList.toggle('active',b.textContent.toLowerCase()===tab));loadDataEntryContent(tab);};
  loadDataEntryContent(state._dataEntriesSubTab);
}

async function loadDataEntryContent(tab) {
  const c=$('de-content'); if(!c) return;
  const mOpts=await getMachineOptions();
  if(tab==='production') {
    c.innerHTML=`<div class="card" style="padding:24px;max-width:700px">
      <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#111">Set Production Target</h2>
      <div class="form-grid">
        <div class="form-group"><label class="form-label">Machine</label><select class="form-select" id="pe-machine">${mOpts}</select></div>
        <div class="form-group"><label class="form-label">Shift Start</label><input class="form-input" type="datetime-local" id="pe-start" value="${todayStart()}"/></div>
        <div class="form-group"><label class="form-label">Shift End</label><input class="form-input" type="datetime-local" id="pe-end" value="${todayEnd()}"/></div>
        <div class="form-group"><label class="form-label">Product Target</label><input class="form-input" type="number" id="pe-target" min="0" placeholder="Target count"/></div>
      </div>
      <div class="form-actions"><button class="btn btn-primary" onclick="submitProductionEntry()">Submit</button></div>
    </div>`;
    window.submitProductionEntry=async()=>{
      const payload={machine_id:+$('pe-machine').value,start_time:$('pe-start').value.replace('T',' '),end_time:$('pe-end').value.replace('T',' '),product_target:+$('pe-target').value};
      try{const res=await fetch(`${CONFIG.baseUrl}/api/production/target`,{method:'POST',headers:auth.getHeaders(),body:JSON.stringify(payload)});const d=await res.json();if(!res.ok) throw new Error(d.error||d.message||'Failed');showToast('Production target saved','success');}catch(e){showToast('Failed: '+e.message,'error');}
    };
  } else if(tab==='quality') {
    c.innerHTML=`<div class="card" style="padding:24px;max-width:700px">
      <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#111">Update Quality Count</h2>
      <div class="form-grid">
        <div class="form-group"><label class="form-label">Entry ID</label><input class="form-input" type="number" id="qe-id" min="1" placeholder="Production entry ID"/></div>
        <div class="form-group"><label class="form-label">Good Parts</label><input class="form-input" type="number" id="qe-good" min="0"/></div>
        <div class="form-group"><label class="form-label">Rejected Parts</label><input class="form-input" type="number" id="qe-bad" min="0"/></div>
      </div>
      <div class="form-actions"><button class="btn btn-primary" onclick="submitQualityEntry()">Update</button></div>
    </div>`;
    window.submitQualityEntry=async()=>{const good=+$('qe-good').value,bad=+$('qe-bad').value;const payload={id:+$('qe-id').value,good_products:good,bad_products:bad,production_done:good+bad};try{const res=await fetch(`${CONFIG.baseUrl}/api/production/entries/update-quality`,{method:'POST',headers:auth.getHeaders(),body:JSON.stringify(payload)});const d=await res.json();if(!res.ok) throw new Error(d.error||d.message||'Failed');showToast('Quality updated','success');}catch(e){showToast('Failed: '+e.message,'error');}};
  } else if(tab==='downtime') {
    c.innerHTML=`<div class="card" style="padding:24px;max-width:700px">
      <h2 style="font-size:16px;font-weight:700;margin-bottom:16px;color:#111">Downtime Entry</h2>
      <div class="form-grid">
        <div class="form-group"><label class="form-label">Machine</label><select class="form-select" id="dte-machine">${mOpts}</select></div>
        <div class="form-group"><label class="form-label">Start Time</label><input class="form-input" type="datetime-local" id="dte-start" value="${todayStart()}"/></div>
        <div class="form-group"><label class="form-label">End Time</label><input class="form-input" type="datetime-local" id="dte-end" value="${todayEnd()}"/></div>
        <div class="form-group"><label class="form-label">Reason</label><input class="form-input" type="text" id="dte-reason" placeholder="Reason for downtime"/></div>
      </div>
      <div class="form-actions"><button class="btn btn-primary" onclick="submitDowntimeEntry()">Submit</button></div>
    </div>`;
    window.submitDowntimeEntry=async()=>{const payload={machine_id:+$('dte-machine').value,start_time:$('dte-start').value.replace('T',' '),end_time:$('dte-end').value.replace('T',' '),reason:$('dte-reason').value};try{const res=await fetch(`${CONFIG.baseUrl}/add_downtime`,{method:'POST',headers:auth.getHeaders(),body:JSON.stringify(payload)});const d=await res.json();if(!res.ok) throw new Error(d.error||d.message||'Failed');showToast('Downtime entry saved','success');}catch(e){showToast('Failed: '+e.message,'error');}};
  } else if(tab==='breakdown') {
    c.innerHTML=`<div class="card" style="padding:24px;max-width:900px">
      <h2 style="font-size:16px;font-weight:700;margin-bottom:8px;color:#111">Recent Breakdowns</h2>
      <p style="font-size:13px;color:#6b7280;margin-bottom:16px">Breakdowns are automatically detected from machine state transitions.</p>
      <button class="btn btn-primary" onclick="loadRecentBreakdowns()">Load Today's Breakdowns</button>
      <div id="bde-list" style="margin-top:16px"></div>
    </div>`;
    window.loadRecentBreakdowns=async()=>{
      try{const today=new Date().toISOString().slice(0,10);const res=await fetch(`${CONFIG.baseUrl}/reports/breakdowns?from_date=${today}&to_date=${today}`,{headers:auth.getHeaders()});const data=await res.json();const rows=data.breakdowns||[];$('bde-list').innerHTML=rows.length?`<div class="table-wrapper"><table class="data-table"><thead><tr><th>Machine</th><th>Breakdown Start</th><th>Recovery Start</th><th>Duration</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.machine_name||r.vfj_no||r.machine_id}</td><td>${formatDate(r.breakdown_start)}</td><td>${r.idle_start?formatDate(r.idle_start):'-'}</td><td>${r.duration_hms||'-'}</td></tr>`).join('')}</tbody></table></div>`:`<div style="color:#6b7280;font-size:14px;padding:12px">No breakdowns recorded today.</div>`;}catch(e){$('bde-list').innerHTML=`<div class="error-state">Failed. ${e.message}</div>`;}
    };
  }
}

// =====================
// ALARM HISTORY
// =====================
async function loadAlarmHistory(container) {
  container.innerHTML=`<h1 class="page-title">Alarm History</h1>
    <div class="filters-row">
      <div class="filter-group"><label class="filter-label">Machine</label><select class="filter-select" id="ah-machine"><option value="">All</option></select></div>
      <div class="filter-group"><label class="filter-label">Type</label><select class="filter-select" id="ah-type"><option value="">All</option><option value="alarm">Alarm</option><option value="warning">Warning</option></select></div>
      <button class="btn btn-blue" onclick="fetchAlarmHistory()">Load</button>
      <button class="export-btn export-csv" onclick="exportAlarmCSV()">CSV</button>
      <button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Alarm History','ah-table')">PDF</button>
    </div>
    <div id="ah-content"><div style="color:white;opacity:0.6">Click Load</div></div>`;
  let lastData=[];
  try{const mRes=await fetch(`${CONFIG.baseUrl}/machines`,{headers:auth.getHeaders()});const mData=await mRes.json();const sel=$('ah-machine');(mData.machines||[]).forEach(m=>{sel.innerHTML+=`<option value="${m.id}">${m.vfj_no}</option>`;});}catch {}
  window.fetchAlarmHistory=async()=>{
    const m=$('ah-machine').value, tp=$('ah-type').value;
    try{
      const endpoint = tp === 'alarm' ? '/api/alarms' : tp === 'warning' ? '/api/warnings' : '/api/alerts';
      const res=await fetch(`${CONFIG.baseUrl}${endpoint}?limit=200${m?'&machine_id='+m:''}`,{headers:auth.getHeaders()});
      const data=await res.json();
      const items = Array.isArray(data.alarms) ? data.alarms
        : Array.isArray(data.warnings) ? data.warnings
        : Array.isArray(data.alerts) ? data.alerts
        : Array.isArray(data.data) ? data.data
        : Array.isArray(data) ? data : [];
      lastData = items;
      $('ah-content').innerHTML=`<div class="table-wrapper"><table class="data-table" id="ah-table"><thead><tr><th>Time</th><th>Machine</th><th>Type</th><th>Code</th><th>Message</th><th>Severity</th></tr></thead><tbody>${lastData.map(a=>`<tr><td>${formatDate(a.timestamp||a.created_at)}</td><td>${a.machine_id||a.vfj_no||'-'}</td><td>${a.alarm_type||a.type||'-'}</td><td>${a.alarm_code||a.code||'-'}</td><td>${a.message||a.description||'-'}</td><td><span class="badge-severity ${a.severity==='critical'?'badge-critical':a.severity==='warning'?'badge-warning':'badge-info'}">${a.severity||'info'}</span></td></tr>`).join('')}</tbody></table></div>`;
    }catch(e){$('ah-content').innerHTML=`<div class="error-state">Failed. ${e.message}</div>`;}
  };
  window.exportAlarmCSV=()=>{let csv='Time,Machine,Type,Code,Message,Severity\n';(Array.isArray(lastData)?lastData:[]).forEach(a=>{csv+=`"${formatDate(a.timestamp||a.created_at)}","${a.machine_id||''}","${a.alarm_type||''}","${a.alarm_code||''}","${a.message||''}","${a.severity||''}"\n`;});downloadCSV(csv,'alarm_history.csv');};
}

// =====================
// SETTING (Machine CRUD)
// =====================
async function loadSetting(container) {
  let machines=[],editId=null,showForm=false,viewMachine=null,deleteId=null;
  const controlTypes=['FANUC','SIEMENS'];
  const controlDetailsOpts={FANUC:['OITC','OITD','OIMF PLUS'],SIEMENS:['802DSL','802D','828D']};

  async function fetchMachines(){try{const res=await fetch(`${CONFIG.baseUrl}/machines`,{headers:auth.getHeaders()});const data=await res.json();machines=data.machines||[];}catch{showToast('Failed to load machines','error');}}

  function render(){
    const deleteModalHtml=deleteId?`<div class="modal-overlay" id="del-modal"><div class="modal"><h2>Confirm Deletion</h2><p>Are you sure?</p><div class="modal-actions"><button class="btn btn-secondary" onclick="closeDeleteModal()">Cancel</button><button class="btn btn-danger" onclick="confirmDeleteMachine()">Delete</button></div></div></div>`:'';
    const viewModalHtml=viewMachine?`<div class="modal-overlay" id="view-modal"><div class="modal modal-lg"><h2>Machine Details</h2><div class="modal-info"><p><strong>ID:</strong> ${viewMachine.id}</p><p><strong>Machine No:</strong> ${viewMachine.vfj_no||'N/A'}</p><p><strong>OEM Name:</strong> ${viewMachine.oem_name||'N/A'}</p><p><strong>Control Type:</strong> ${viewMachine.control_type||'N/A'}</p><p><strong>Control Details:</strong> ${viewMachine.control_details||'N/A'}</p><p><strong>Machine IP:</strong> ${viewMachine.ip_address||'N/A'}</p></div><div class="modal-actions"><button class="btn btn-danger" onclick="closeViewModal()">Close</button></div></div></div>`:'';
    const formHtml=showForm?`<div class="form-card"><h1>${editId?'Edit Machine':'Add Machine'}</h1><form id="machine-form"><div class="form-grid">
      <div class="form-group"><label class="form-label">Machine No</label><input class="form-input" name="vfj_no" required value="${editId?(machines.find(m=>m.id===editId)||{}).vfj_no||'':''}"/></div>
      <div class="form-group"><label class="form-label">OEM Name</label><input class="form-input" name="oem_name" required value="${editId?(machines.find(m=>m.id===editId)||{}).oem_name||'':''}"/></div>
      <div class="form-group"><label class="form-label">Control Type</label><select class="form-select" name="control_type" id="ctrl-type-sel" onchange="updateCtrlDetails()">${controlTypes.map(t=>`<option value="${t}" ${editId&&(machines.find(m=>m.id===editId)||{}).control_type===t?'selected':''}>${t}</option>`).join('')}</select></div>
      <div class="form-group"><label class="form-label">Control Details</label><select class="form-select" name="control_details" id="ctrl-detail-sel"><option value="">Select</option></select></div>
      <div class="form-group"><label class="form-label">Machine IP</label><input class="form-input" name="ip_address" required value="${editId?(machines.find(m=>m.id===editId)||{}).ip_address||'':''}"/></div>
      </div><div class="form-actions"><button type="button" class="btn btn-secondary" onclick="cancelMachineForm()">Cancel</button><button type="submit" class="btn btn-primary">${editId?'Update':'Add'}</button></div></form></div>`
    :`<div class="table-wrapper"><table class="data-table" id="machines-table"><thead><tr><th>ID</th><th>Machine No</th><th>OEM Name</th><th>Control Type</th><th>Control Details</th><th>Machine IP</th><th>Action</th></tr></thead>
    <tbody>${machines.map(m=>`<tr><td>${m.id}</td><td>${m.vfj_no||'N/A'}</td><td>${m.oem_name||'N/A'}</td><td>${m.control_type||'N/A'}</td><td>${m.control_details||'N/A'}</td><td>${m.ip_address||'N/A'}</td>
    <td style="display:flex;gap:8px"><button class="action-btn view" onclick="viewMachineEntry(${m.id})" title="View">&#128065;</button><button class="action-btn edit" onclick="editMachineEntry(${m.id})" title="Edit">&#9998;</button><button class="action-btn delete" onclick="deleteMachineEntry(${m.id})" title="Delete">&#128465;</button></td></tr>`).join('')}</tbody></table></div>`;

    container.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px"><h1 class="page-title" style="margin:0">${showForm?(editId?'Edit Machine':'Add Machine'):'Machine List'}</h1>
      <div style="display:flex;gap:8px">
        ${!showForm?`<button class="export-btn" style="background:#dc2626;color:#fff" onclick="exportToPDF('Machine List','machines-table')">PDF</button>`:''}
        <button class="btn ${showForm?'btn-secondary':'btn-primary'}" onclick="toggleMachineForm()">${showForm?'Cancel':'+ Add Machine'}</button>
      </div>
    </div>${formHtml}${deleteModalHtml}${viewModalHtml}`;

    if(showForm){
      const detSel=$('ctrl-detail-sel');
      const editMachine=editId?machines.find(m=>m.id===editId):null;
      if(editMachine&&editMachine.control_type){const opts=controlDetailsOpts[editMachine.control_type]||[];detSel.innerHTML=`<option value="">Select</option>${opts.map(o=>`<option value="${o}" ${o===editMachine.control_details?'selected':''}>${o}</option>`).join('')}`;}
      window.updateCtrlDetails=()=>{const t=$('ctrl-type-sel').value;const opts=controlDetailsOpts[t]||[];$('ctrl-detail-sel').innerHTML=`<option value="">Select</option>${opts.map(o=>`<option value="${o}">${o}</option>`).join('')}`;};
      $('machine-form').onsubmit=async(e)=>{e.preventDefault();const fd=new FormData(e.target);const payload={};fd.forEach((v,k)=>{payload[k]=v;});payload.operator_ip='12.34.56.78';payload.port='3000';payload.status='active';payload.control_model='HMT STALLION 200';
        try{if(editId){await fetch(`${CONFIG.baseUrl}/machines/${editId}`,{method:'PATCH',headers:auth.getHeaders(),body:JSON.stringify(payload)});showToast('Machine updated','success');}else{await fetch(`${CONFIG.baseUrl}/add_machine`,{method:'POST',headers:auth.getHeaders(),body:JSON.stringify(payload)});showToast('Machine added','success');}editId=null;showForm=false;await fetchMachines();render();}catch(err){showToast('Failed: '+err.message,'error');}
      };
    }
  }

  window.toggleMachineForm=()=>{showForm=!showForm;editId=null;render();};
  window.cancelMachineForm=()=>{showForm=false;editId=null;render();};
  window.viewMachineEntry=(id)=>{viewMachine=machines.find(m=>m.id===id);render();};
  window.editMachineEntry=(id)=>{editId=id;showForm=true;render();};
  window.deleteMachineEntry=(id)=>{deleteId=id;render();};
  window.closeDeleteModal=()=>{deleteId=null;render();};
  window.closeViewModal=()=>{viewMachine=null;render();};
  window.confirmDeleteMachine=async()=>{try{await fetch(`${CONFIG.baseUrl}/machines/${deleteId}`,{method:'DELETE',headers:auth.getHeaders()});showToast('Machine deleted','success');deleteId=null;await fetchMachines();render();}catch(e){showToast('Failed: '+e.message,'error');}};
  await fetchMachines(); render();
}

// =====================
// USERS
// =====================
async function loadUsers(container) {
  let users=[],machines=[],showForm=false,editUser=null,deleteId=null;
  async function fetchAll(){
    try{
      const to = 8000;
      const requests = [
        { name: 'users', p: fetch(`${CONFIG.baseUrl}/users`, { headers: auth.getHeaders(), timeout: to }) },
        { name: 'machines', p: fetch(`${CONFIG.baseUrl}/machines`, { headers: auth.getHeaders(), timeout: to }) },
      ];
      const results = await Promise.all(requests.map(r => r.p.catch(err => ({ __error: err, __name: r.name }))));
      for (const res of results) {
        if (res && res.__error) throw new Error(`Failed to fetch ${res.__name}: ${res.__error.message || res.__error}`);
        if (!res || !res.ok) throw new Error(`Request failed: ${res && res.url ? new URL(res.url).pathname : 'unknown'} (status ${res ? res.status : 'no response'})`);
      }
      const [uRes, mRes] = results;
      const uData = await uRes.json(); users = uData.users || uData || [];
      const mData = await mRes.json(); machines = mData.machines || [];
    } catch (e) {
      console.error('fetchAll error', e);
      users = [];
      machines = [];
    }
  }
  function render(){
    const deleteModalHtml=deleteId?`<div class="modal-overlay"><div class="modal"><h2>Delete User</h2><p>Are you sure?</p><div class="modal-actions"><button class="btn btn-secondary" onclick="cancelUserDelete()">Cancel</button><button class="btn btn-danger" onclick="confirmUserDelete()">Delete</button></div></div></div>`:'';
    const formHtml=showForm?`<div class="form-card"><h1>${editUser?'Edit User':'Add User'}</h1><form id="user-form"><div class="form-grid">
      <div class="form-group"><label class="form-label">Name</label><input class="form-input" name="name" required value="${editUser?editUser.name||'':''}"/></div>
      <div class="form-group"><label class="form-label">Plant</label><input class="form-input" name="plant" required value="${editUser?editUser.plant||'':''}"/></div>
      <div class="form-group"><label class="form-label">Employee ID</label><input class="form-input" name="employee_id" required value="${editUser?editUser.employee_id||'':''}"/></div>
      <div class="form-group"><label class="form-label">Role</label><select class="form-select" name="role"><option value="Operator" ${editUser&&editUser.role==='Operator'?'selected':''}>Operator</option><option value="admin" ${editUser&&editUser.role==='admin'?'selected':''}>Admin</option></select></div>
      <div class="form-group"><label class="form-label">Machine</label><select class="form-select" name="machine_id">${machines.map(m=>`<option value="${m.id}" ${editUser&&editUser.machine_id===m.id?'selected':''}>${m.vfj_no}</option>`).join('')}</select></div>
      ${!editUser?`<div class="form-group"><label class="form-label">Password</label><input class="form-input" type="password" name="password" required/></div>`:''}
      </div><div class="form-actions"><button type="button" class="btn btn-secondary" onclick="cancelUserForm()">Cancel</button><button type="submit" class="btn btn-primary">${editUser?'Update':'Add'}</button></div></form></div>`
    :`<div class="table-wrapper"><table class="data-table"><thead><tr><th>Name</th><th>Employee ID</th><th>Role</th><th>Machine</th><th>Action</th></tr></thead>
    <tbody>${users.map(u=>`<tr><td>${u.name||'-'}</td><td>${u.employee_id||'-'}</td><td>${u.role||'-'}</td><td>${machines.find(m=>m.id===u.machine_id)?.vfj_no||u.machine_id||'-'}</td>
    <td style="display:flex;gap:8px"><button class="action-btn edit" onclick="editUserEntry(${u.id})" title="Edit">&#9998;</button><button class="action-btn delete" onclick="deleteUserEntry(${u.id})" title="Delete">&#128465;</button></td></tr>`).join('')}</tbody></table></div>`;

    container.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px"><h1 class="page-title" style="margin:0">Users</h1>
      <button class="btn ${showForm?'btn-secondary':'btn-primary'}" onclick="toggleUserForm()">${showForm?'Cancel':'+ Add User'}</button>
    </div>${formHtml}${deleteModalHtml}`;

    if(showForm){$('user-form').onsubmit=async(e)=>{e.preventDefault();const fd=new FormData(e.target);const payload={};fd.forEach((v,k)=>{payload[k]=v;});try{if(editUser){await fetch(`${CONFIG.baseUrl}/users/${editUser.id}`,{method:'PATCH',headers:auth.getHeaders(),body:JSON.stringify(payload)});showToast('User updated','success');}else{await fetch(`${CONFIG.baseUrl}/create_user`,{method:'POST',headers:auth.getHeaders(),body:JSON.stringify(payload)});showToast('User created','success');}editUser=null;showForm=false;await fetchAll();render();}catch(err){showToast('Failed: '+err.message,'error');}};}
  }

  window.toggleUserForm=()=>{showForm=!showForm;editUser=null;render();};
  window.cancelUserForm=()=>{showForm=false;editUser=null;render();};
  window.editUserEntry=(id)=>{editUser=users.find(u=>u.id===id);showForm=true;render();};
  window.deleteUserEntry=(id)=>{deleteId=id;render();};
  window.cancelUserDelete=()=>{deleteId=null;render();};
  window.confirmUserDelete=async()=>{try{await fetch(`${CONFIG.baseUrl}/users/${deleteId}`,{method:'DELETE',headers:auth.getHeaders()});showToast('User deleted','success');deleteId=null;await fetchAll();render();}catch(e){showToast('Failed: '+e.message,'error');}};
  await fetchAll(); render();
}

// =====================
// PROFILE PAGE
// =====================
function renderProfile() {
  const header=buildHeader(auth.getRole()==='Operator');
  const user=auth.getUser()||{};
  const content=`<div class="profile-page" style="padding:20px">
    <div class="profile-header-card"><div class="profile-avatar">&#128100;</div><div class="profile-name">${user.name||user.employee_id||'User'}</div><div class="profile-role">${user.role||'User'}</div></div>
    <div class="profile-info-grid">
      <div class="profile-info-item"><div class="info-label">Employee ID</div><div class="info-value">${user.employee_id||'-'}</div></div>
      <div class="profile-info-item"><div class="info-label">Role</div><div class="info-value">${user.role||'-'}</div></div>
      <div class="profile-info-item"><div class="info-label">Plant</div><div class="info-value">${user.plant||'CORE CARBIDE TECH'}</div></div>
      <div class="profile-info-item"><div class="info-label">Machine</div><div class="info-value">${user.machine_id||'-'}</div></div>
    </div>
    <div class="password-change-card"><h3>Change Password</h3>
      <form id="pwd-form">
        <div class="form-group" style="margin-bottom:12px"><label class="form-label" style="color:#4b5563">Current Password</label><input class="form-input" type="password" id="pwd-current" placeholder="Current password" style="background:#f3f4f6;color:#111"/></div>
        <div class="form-group" style="margin-bottom:12px"><label class="form-label" style="color:#4b5563">New Password</label><input class="form-input" type="password" id="pwd-new" placeholder="New password" style="background:#f3f4f6;color:#111"/></div>
        <div class="form-group" style="margin-bottom:16px"><label class="form-label" style="color:#4b5563">Confirm Password</label><input class="form-input" type="password" id="pwd-confirm" placeholder="Confirm password" style="background:#f3f4f6;color:#111"/></div>
        <button type="submit" class="btn btn-primary">Update Password</button>
      </form>
    </div>
  </div>`;
  renderAppShell(header,content,buildFooter(false));
  $('pwd-form').onsubmit=async(e)=>{e.preventDefault();const curr=$('pwd-current').value,nw=$('pwd-new').value,conf=$('pwd-confirm').value;if(nw!==conf){showToast('Passwords do not match','error');return;}try{const res=await fetch(`${CONFIG.baseUrl}/users/me/reset_password`,{method:'POST',headers:auth.getHeaders(),body:JSON.stringify({old_password:curr,new_password:nw,confirm_new_password:conf})});if(!res.ok){const d=await res.json();throw new Error(d.error||d.message||'Failed');}showToast('Password updated successfully','success');}catch(err){showToast('Failed: '+err.message,'error');}};
}

// =====================
// HELPERS
// =====================
async function getMachineOptions() {
  try {
    const res=await fetch(`${CONFIG.baseUrl}/machines`,{headers:auth.getHeaders()});
    const data=await res.json();
    return `<option value="">All Machines</option>${(data.machines||[]).map(m=>`<option value="${m.id}">${m.vfj_no||m.oem_name}</option>`).join('')}`;
  } catch { return '<option value="">All Machines</option>'; }
}

function downloadCSV(csv,filename) {
  const blob=new Blob([csv],{type:'text/csv'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url; a.download=filename; a.click();
  URL.revokeObjectURL(url);
}

// =====================
// INIT
// =====================
window.addEventListener('DOMContentLoaded',()=>{
  const savedTheme=localStorage.getItem('theme')||'dark';
  document.documentElement.setAttribute('data-theme',savedTheme);
  if(!window.location.hash||window.location.hash==='#'){
    if(auth.isAuthenticated()){const role=auth.getRole();if(role==='admin')window.location.hash='#/';else if(role==='Operator')window.location.hash='#/Operator';else window.location.hash='#/login';}
    else{window.location.hash='#/login';}
  }
  router.init();
});