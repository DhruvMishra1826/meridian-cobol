export const state = {
  view: 'overview',
  token: '',
  rows: [],
  report: 'ACCOUNTS',
  generation: 0,
  busy: false,
};
export const today = () => {
  const d = new Date();
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('');
};
