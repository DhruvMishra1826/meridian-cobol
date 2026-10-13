import { state } from './state.js';
import { $ } from './dom.js';
import { initForms } from './forms.js';
import { initNavigation, navigate, refresh } from './navigation.js';
$('connection-button').addEventListener('click', () => $('connection-dialog').showModal());
$('close-connection').addEventListener('click', () => $('connection-dialog').close());
$('connection-form').addEventListener('submit', (event) => {
  event.preventDefault();
  state.token = $('token-input').value;
  $('token-input').value = '';
  $('connection-dialog').close();
  $('notice').hidden = true;
  refresh();
});

initForms();
initNavigation();
navigate('overview');
