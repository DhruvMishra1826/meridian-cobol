import { state, today } from './state.js';
import { $, integer, date, makeEmpty, notify } from './dom.js';
import { reportNames, schemas } from './catalog.js';
export function renderTable(
  target,
  rows,
  emptyTitle = 'No records yet',
  emptyDescription = 'Create your first record in the transaction desk.'
) {
  target.replaceChildren();
  if (!rows.length) {
    makeEmpty(target, emptyTitle, emptyDescription);
    return;
  }
  const groups = new Map();
  rows.forEach((row) => {
    const kind = row[0];
    if (!groups.has(kind)) groups.set(kind, []);
    groups.get(kind).push(row);
  });
  groups.forEach((entries, kind) => {
    if (groups.size > 1) {
      const caption = document.createElement('p');
      caption.className = 'row-group-label';
      caption.textContent = kind.replace(/-/g, ' ');
      target.append(caption);
    }
    const table = document.createElement('table');
    const known = schemas[kind];
    const width = Math.max(...entries.map((row) => row.length - 1));
    const headers = known || Array.from({ length: width }, (_, index) => `Field ${index + 1}`);
    const head = document.createElement('thead');
    const hr = document.createElement('tr');
    headers.forEach((label) => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = label;
      hr.append(th);
    });
    head.append(hr);
    table.append(head);
    const body = document.createElement('tbody');
    entries.forEach((row) => {
      const tr = document.createElement('tr');
      row.slice(1).forEach((value, index) => {
        const td = document.createElement('td');
        const label = headers[index] || '';
        td.title = value;
        if (label === 'Status' || label === 'Type' || label === 'Bucket') {
          const badge = document.createElement('span');
          badge.className = 'badge';
          if (['OPEN', 'PAID', 'VOID', 'DRAFT'].includes(value)) badge.classList.add(value);
          badge.textContent = value;
          td.append(badge);
        } else if (/date|Closed through/i.test(label)) {
          td.textContent = value === '00000000' || value === '0' ? 'Not closed' : date(value);
        } else if (
          /balance|amount|debits|credits|quantity|cost|value|point|shortfall|price|basis|^net$|^tax$|^total$|^paid$|outstanding|lines|^line$|days|result|^current$|^accounts$|^items$|^customers$|^invoices$|^ledger entries$/i.test(
            label
          )
        ) {
          td.className = 'number';
          td.textContent = integer(value);
        } else {
          td.textContent = value || '—';
          if (/ID|SKU|reference|account$/i.test(label)) td.className = 'identifier';
          if (/name/i.test(label)) td.className = 'name';
        }
        tr.append(td);
      });
      body.append(tr);
    });
    table.append(body);
    target.append(table);
  });
}
export function updateSummary(rows) {
  const counts = rows.find((row) => row[0] === 'COUNTS');
  const result = rows.find((row) => row[0] === 'RESULT');
  $('metric-entries').textContent = counts ? integer(counts[2]) : '—';
  $('metric-items').textContent = counts ? integer(counts[3]) : '—';
  $('metric-invoices').textContent = counts ? integer(counts[5]) : '—';
  $('metric-result').textContent = result ? integer(result[1]) : '—';
}
export function filteredTable() {
  const filter = $('table-search').value.toLowerCase();
  const rows = state.rows.filter((row) =>
    row.some((value) => value.toLowerCase().includes(filter))
  );
  renderTable(
    $('report-table'),
    rows,
    filter ? 'No matching records' : 'No records yet',
    filter ? 'Try another search term.' : 'Accepted operations will appear here.'
  );
  $('row-count').textContent = `${rows.length} of ${state.rows.length} report rows`;
}
export function reportCommand() {
  const name = $('report-select').value;
  return ['STATEMENT', 'INVOICE-SHOW', 'AGING'].includes(name)
    ? `${name}|${$('report-argument').value}`
    : name;
}
export function configureReport() {
  const name = $('report-select').value;
  state.report = name;
  $('table-title').textContent = reportNames[name];
  const hasArgument = ['STATEMENT', 'INVOICE-SHOW', 'AGING'].includes(name);
  $('report-argument-wrap').hidden = !hasArgument;
  $('report-argument-label').textContent =
    name === 'AGING' ? 'As-of date' : name === 'STATEMENT' ? 'Account ID' : 'Invoice ID';
  $('report-argument').value =
    name === 'AGING' ? today() : name === 'STATEMENT' ? 'CASH' : 'INV_001';
  $('table-search').value = '';
}
export function exportCSV() {
  if (!state.rows.length) {
    notify('There are no report rows to export.');
    return;
  }
  // Prefix spreadsheet formula markers while preserving values in the on-screen report.
  const escape = (value) =>
    `"${(/^[=+@-]/.test(value) && !/^-?\d+$/.test(value) ? "'" + value : value).replace(/"/g, '""')}"`;
  const csv = state.rows.map((row) => row.map(escape).join(',')).join('\r\n') + '\r\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `meridian-${state.report.toLowerCase()}-${today()}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
