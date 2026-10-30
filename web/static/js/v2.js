let coachOpener = null;
const proposalOpeners = new Map();
const focusableSelector = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
const htmxSubmitters = new WeakMap();
const htmxLoading = new WeakMap();

// A form owns the HTMX request, but its clicked submitter is the control users watch.
document.addEventListener('submit', function (event) {
  const form = event.target;
  if (!form.matches('form[hx-post],form[hx-get],form[hx-put],form[hx-delete],form[hx-patch]')) return;
  if (htmxLoading.has(form)) {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  }
  htmxSubmitters.set(form, event.submitter || form.querySelector('button[type="submit"],input[type="submit"],button:not([type])'));
}, true);

document.addEventListener('click', function (event) {
  if (event.target.closest('.is-htmx-loading')) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

document.addEventListener('htmx:beforeRequest', function (event) {
  const source = event.detail.elt;
  if (!source || htmxLoading.has(source)) return;
  const control = source.matches('form') ? htmxSubmitters.get(source) : source;
  if (!control || !control.matches('button,a,input[type="submit"]')) return;
  htmxLoading.set(source, control);
  control.classList.add('is-htmx-loading');
  control.setAttribute('aria-busy', 'true');
  if (control.matches('a')) control.setAttribute('aria-disabled', 'true');
});

function clearHtmxLoading(event) {
  const source = event.detail.elt;
  const control = source && htmxLoading.get(source);
  if (!control) return;
  control.classList.remove('is-htmx-loading');
  control.removeAttribute('aria-busy');
  if (control.matches('a')) control.removeAttribute('aria-disabled');
  htmxLoading.delete(source);
  htmxSubmitters.delete(source);
}

['htmx:afterRequest', 'htmx:sendError', 'htmx:timeout'].forEach(function (name) {
  document.addEventListener(name, clearHtmxLoading);
});

function scrollCoachToNewest() {
  const thread = document.querySelector('#coach-thread');
  if (thread) thread.scrollTop = thread.scrollHeight;
}

document.addEventListener('DOMContentLoaded', function () {
  requestAnimationFrame(scrollCoachToNewest);
});
document.addEventListener('htmx:afterSwap', function () {
  if (document.body.classList.contains('v2-coach-page')) requestAnimationFrame(scrollCoachToNewest);
});

function trapFocus(event, panel) {
  const candidates = [...panel.querySelectorAll(focusableSelector)].filter((item) => item.getClientRects().length);
  if (!candidates.length) return;
  const first = candidates[0];
  const last = candidates.at(-1);
  if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.querySelector('h2'))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function closeCoach() {
  document.body.classList.remove('v2-coach-open');
  const panel = document.querySelector('#v2-coach-panel');
  panel?.removeAttribute('role');
  panel?.removeAttribute('aria-modal');
  document.querySelectorAll('[data-open-coach]').forEach((button) => button.setAttribute('aria-expanded', 'false'));
  coachOpener?.focus();
}

function closeProposal(wrapper) {
  wrapper.classList.remove('is-open');
  const id = wrapper.id.split('-').at(-1);
  const proposal = wrapper.querySelector('.v2-proposal');
  proposal?.removeAttribute('role');
  proposal?.removeAttribute('aria-modal');
  document.querySelector('[data-open-proposal="' + id + '"]')?.setAttribute('aria-expanded', 'false');
  proposalOpeners.get(id)?.focus();
}

document.addEventListener('click', function (event) {
  const open = event.target.closest('[data-open-coach]');
  const close = event.target.closest('[data-close-coach]');
  if (!open && !close) return;
  if (close) { closeCoach(); return; }
  coachOpener = open;
  document.body.classList.add('v2-coach-open');
  document.querySelectorAll('[data-open-coach]').forEach(function (button) {
    button.setAttribute('aria-expanded', 'true');
  });
  const panel = document.querySelector('#v2-coach-panel');
  panel?.setAttribute('role', 'dialog');
  panel?.setAttribute('aria-modal', 'true');
  panel?.querySelector('h2')?.focus();
});
document.addEventListener('keydown', function (event) {
  const proposal = matchMedia('(max-width:767px)').matches ? document.querySelector('.v2-proposal-wrap.is-open') : null;
  const panel = proposal?.querySelector('.v2-proposal') ||
    (document.body.classList.contains('v2-coach-open') ? document.querySelector('#v2-coach-panel') : null);
  if (event.key === 'Tab' && panel) { trapFocus(event, panel); return; }
  if (event.key !== 'Escape') return;
  if (proposal) { closeProposal(proposal); return; }
  if (panel) { closeCoach(); return; }
  const menu = [...document.querySelectorAll('details[open]')].at(-1);
  if (menu) { menu.open = false; menu.querySelector('summary')?.focus(); }
});
document.addEventListener('click', function (event) {
  const opener = event.target.closest('[data-open-proposal]');
  const closer = event.target.closest('[data-close-proposal]');
  if (!opener && !closer) return;
  const id = opener?.dataset.openProposal || closer?.dataset.closeProposal;
  const wrapper = document.querySelector('#proposal-' + id);
  if (!wrapper) return;
  if (closer) { closeProposal(wrapper); return; }
  proposalOpeners.set(id, opener);
  wrapper.classList.add('is-open');
  opener.setAttribute('aria-expanded', 'true');
  if (matchMedia('(max-width:767px)').matches) {
    wrapper.querySelector('.v2-proposal')?.setAttribute('role', 'dialog');
    wrapper.querySelector('.v2-proposal')?.setAttribute('aria-modal', 'true');
  }
  wrapper.querySelector('.v2-proposal h2')?.focus();
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
