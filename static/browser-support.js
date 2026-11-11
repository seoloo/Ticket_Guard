/* Loaded first. Browser tools the site relies on, with stand-ins when the browser refuses them:
   - storage: sessionStorage, or page memory when storage is blocked/full (survives clicks, not reloads)
   - uuid: crypto.randomUUID needs a secure page (https or localhost); on http://<IP> build one instead
   A refused tool is reported once as browser_error {kind:'browser_capability'} for the dashboard. */
(() => {
  'use strict';
  const problems = [];
  const reported = new Set();
  function note(capability, reason) {
    if (reported.has(capability)) return;
    reported.add(capability);
    const problem = {capability, reason: reason || null, secureContext: window.isSecureContext === true};
    problems.push(problem);
    // telemetry.js reports earlier problems itself once it is ready.
    window.ticketGuardCapture?.record('browser_error', {kind: 'browser_capability', ...problem});
  }

  function uuid() {
    try { if (typeof crypto.randomUUID === 'function') return crypto.randomUUID(); } catch (_) { /* fall through */ }
    note('random_uuid_unavailable', window.isSecureContext ? 'not_supported' : 'insecure_context');
    let bytes;
    try { bytes = crypto.getRandomValues(new Uint8Array(16)); }  // available on http:// pages too
    catch (_) {
      note('secure_random_unavailable', 'get_random_values_failed');
      bytes = Uint8Array.from({length: 16}, () => Math.floor(Math.random() * 256));
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;  // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80;  // RFC 4122 variant
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  const memory = new Map();
  let session = null;
  try {
    const probe = '__tg_probe__';
    window.sessionStorage.setItem(probe, '1');
    window.sessionStorage.removeItem(probe);
    session = window.sessionStorage;
  } catch (error) { note('session_storage_unavailable', error && error.name); }
  const storage = {
    getItem(key) {
      if (memory.has(key)) return memory.get(key);
      try { return session ? session.getItem(key) : null; } catch (_) { return null; }
    },
    setItem(key, value) {
      value = String(value);
      if (session) {
        try { session.setItem(key, value); memory.delete(key); return; }
        catch (error) { note('session_storage_write_failed', error && error.name); }
      }
      memory.set(key, value);
    },
    removeItem(key) {
      memory.delete(key);
      try { if (session) session.removeItem(key); } catch (_) { /* nothing stored there */ }
    },
  };

  window.tgBrowser = {uuid, storage, problems};
})();
