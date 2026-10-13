export const $ = (id) => document.getElementById(id);
export const integer = (value) =>
  /^-?\d+$/.test(String(value)) ? Number(value).toLocaleString('en-US') : value;
export const date = (value) =>
  /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : value;
export function notify(message, error = false) {
  $('notice').hidden = false;
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
}
export function connection(ok) {
  $('engine-dot').classList.toggle('connected', ok);
  $('sidebar-status').textContent = ok ? 'Journal ready' : 'Connection unavailable';
  $('status-chip').textContent = ok ? 'Engine connected' : 'Connection unavailable';
}
export function makeEmpty(target, title, description) {
  target.replaceChildren();
  const box = document.createElement('div');
  box.className = 'empty-state';
  const icon = document.createElement('span');
  icon.className = 'empty-icon';
  icon.textContent = '◫';
  const heading = document.createElement('strong');
  heading.textContent = title;
  const detail = document.createElement('span');
  detail.textContent = description;
  box.append(icon, heading, detail);
  target.append(box);
}
