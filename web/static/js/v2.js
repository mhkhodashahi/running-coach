document.addEventListener('click', function (event) {
  const open = event.target.closest('[data-open-coach]');
  const close = event.target.closest('[data-close-coach]');
  if (!open && !close) return;
  document.body.classList.toggle('v2-coach-open', Boolean(open));
  document.querySelectorAll('[data-open-coach]').forEach(function (button) {
    button.setAttribute('aria-expanded', String(Boolean(open)));
  });
  if (open) document.querySelector('#v2-coach-panel h2')?.focus();
  if (close) document.querySelector('[data-open-coach]')?.focus();
});
document.addEventListener('keydown', function (event) {
  if (event.key !== 'Escape' || !document.body.classList.contains('v2-coach-open')) return;
  document.body.classList.remove('v2-coach-open');
  document.querySelectorAll('[data-open-coach]').forEach(function (button) {
    button.setAttribute('aria-expanded', 'false');
  });
  document.querySelector('[data-open-coach]')?.focus();
});
document.addEventListener('click', function (event) {
  const opener = event.target.closest('[data-open-proposal]');
  const closer = event.target.closest('[data-close-proposal]');
  if (!opener && !closer) return;
  const id = opener?.dataset.openProposal || closer?.dataset.closeProposal;
  const wrapper = document.querySelector('#proposal-' + id);
  wrapper?.classList.toggle('is-open', Boolean(opener));
  document.querySelector('[data-open-proposal="' + id + '"]')?.setAttribute('aria-expanded', String(Boolean(opener)));
  if (opener) wrapper?.querySelector('.v2-proposal h2')?.focus();
  if (closer) document.querySelector('[data-open-proposal="' + id + '"]')?.focus();
});
document.addEventListener('change', function (event) {
  const checkbox = event.target.closest('.v2-proposal-change input[type=checkbox]');
  if (!checkbox) return;
  const form = checkbox.closest('form');
  form.querySelectorAll('input[data-group]').forEach(function (other) {
    if (other.dataset.group === checkbox.dataset.group) other.checked = checkbox.checked;
  });
  const count = form.querySelectorAll('input[name=change_ids]:checked').length;
  form.querySelector('.v2-apply, .v2-apply-secondary').textContent = 'Apply ' + count + (count === 1 ? ' change' : ' changes');
  if (window.htmx) {
    const id = form.closest('.v2-proposal-wrap').id.split('-')[1];
    window.htmx.ajax('POST', '/plan/proposals/' + id + '/preview', {
      target: '#proposal-feedback-' + id,
      swap: 'outerHTML',
      values: {change_ids: [...form.querySelectorAll('input[name=change_ids]:checked')].map((item) => item.value)},
    });
  }
});
document.addEventListener('htmx:afterSwap', function () {
  document.querySelectorAll('[id^=proposal-feedback-][data-percent]').forEach(function (feedback) {
    const id = feedback.id.split('-').at(-1);
    const proposal = document.querySelector('#proposal-' + id);
    const value = feedback.dataset.percent;
    const label = proposal?.querySelector('#proposal-applied-' + id);
    const bar = proposal?.querySelector('.v2-proposal-track .is-applied');
    if (label) label.textContent = value === '' ? 'No data' : value + '%';
    if (bar) bar.style.width = value === '' ? '0%' : Math.min(100, Number(value)) + '%';
  });
});
document.addEventListener('click', function (event) {
  const edit = event.target.closest('[data-open-recurring]');
  const add = event.target.closest('[data-open-add-session]');
  if (!edit && !add) return;
  event.preventDefault();
  const editor = document.querySelector('.v2-recurring-editor');
  if (!editor) return;
  editor.open = true;
  if (add) document.querySelector('#add-session').open = true;
  (add ? document.querySelector('#add-session') : editor).scrollIntoView({block: 'nearest'});
});
