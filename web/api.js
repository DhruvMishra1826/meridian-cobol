import { state } from './state.js';
import { $ } from './dom.js';
export async function api(path, command) {
  const options = { headers: {} };
  if (state.token) options.headers.Authorization = `Bearer ${state.token}`;
  if (command !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify({ command });
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok || !result.ok) {
    if (response.status === 401 && !$('connection-dialog').open) $('connection-dialog').showModal();
    throw new Error(result.message || `Request failed (${response.status})`);
  }
  return result;
}
export const report = (command) => api(`/api/report?command=${encodeURIComponent(command)}`);
