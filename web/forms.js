import { state } from './state.js';
import { $, connection, notify } from './dom.js';
import { api } from './api.js';
import { operations } from './operations.js';
function composeOperation() {
  const operation = operations.find((op) => op.name === $('operation-select').value);
  $('operation-hint').textContent = operation.hint;
  $('command-fields').replaceChildren();
  operation.fields.forEach((spec, index) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'field';
    const label = document.createElement('label');
    label.htmlFor = `command-field-${index}`;
    label.textContent = spec.label;
    const input = document.createElement('input');
    input.id = label.htmlFor;
    input.value = spec.value;
    input.required = true;
    input.autocomplete = 'off';
    input.maxLength = 80;
    input.dataset.kind = spec.kind;
    if (spec.kind === 'id') {
      input.pattern = '[A-Z0-9_\\-]+';
      input.maxLength = /Invoice ID/.test(spec.label)
        ? 24
        : /reference/i.test(spec.label)
          ? 32
          : 12;
    }
    if (spec.kind === 'date') {
      input.pattern = '[0-9]{8}';
      input.inputMode = 'numeric';
      input.maxLength = 8;
    }
    if (spec.kind === 'uint') {
      input.pattern = '(0|[1-9][0-9]*)';
      input.inputMode = 'numeric';
    }
    if (spec.kind === 'signed') {
      input.pattern = '-?[1-9][0-9]*';
      input.inputMode = 'text';
    }
    if (spec.kind === 'text') input.pattern = '[^\\x7c\\x7e\\x00-\\x1f\\x7f]+';
    input.addEventListener('input', previewCommand);
    const hint = document.createElement('small');
    hint.textContent = spec.hint || 'No pipe, tilde or control characters';
    wrapper.append(label, input, hint);
    $('command-fields').append(wrapper);
  });
  previewCommand();
}
function previewCommand() {
  const values = Array.from($('command-fields').querySelectorAll('input'), (input) => input.value);
  const command = [$('operation-select').value, ...values].join('|');
  $('command-preview').textContent = command;
  return command;
}

export function initForms() {
  operations.forEach((operation) => {
    const option = document.createElement('option');
    option.value = operation.name;
    option.textContent = operation.label;
    $('operation-select').append(option);
  });
  $('operation-select').addEventListener('change', composeOperation);
  $('command-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (state.busy) return;
    const command = previewCommand();
    if (new TextEncoder().encode(command).length > 4096 || /[\x00-\x1f\x7f~]/.test(command)) {
      notify(
        'Fields must fit within 4096 bytes and cannot contain tilde or control characters.',
        true
      );
      return;
    }
    if (
      Array.from($('command-fields').querySelectorAll('input')).some((input) =>
        input.value.includes('|')
      )
    ) {
      notify('A field cannot contain a pipe character.', true);
      return;
    }
    state.busy = true;
    $('submit-command').disabled = true;
    try {
      const result = await api('/api/command', command);
      connection(true);
      notify(`${result.message}. Accepted into the journal.`);
    } catch (error) {
      notify(error.message, true);
    } finally {
      state.busy = false;
      $('submit-command').disabled = false;
    }
  });

  composeOperation();
}
