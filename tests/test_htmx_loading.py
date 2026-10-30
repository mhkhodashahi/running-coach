"""Shared HTMX loading state works for submit buttons and links."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_htmx_loading_state_cleans_up_after_success_and_error():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = new Map();
const document = {addEventListener(name, handler) {
  if (!listeners.has(name)) listeners.set(name, []);
  listeners.get(name).push(handler);
}};
vm.runInNewContext(fs.readFileSync('web/static/js/v2.js', 'utf8'), {document});
function fire(name, event) {
  for (const handler of listeners.get(name) || []) handler(event);
}
function control(tag) {
  const attrs = new Map();
  const classes = new Set();
  return {
    attrs, classes,
    matches(selector) {
      if (selector === 'a') return tag === 'a';
      if (selector === 'form') return tag === 'form';
      if (selector.startsWith('form[')) return tag === 'form';
      return tag === 'button' || tag === 'a';
    },
    setAttribute(name, value) { attrs.set(name, value); },
    removeAttribute(name) { attrs.delete(name); },
    classList: {add(name) { classes.add(name); }, remove(name) { classes.delete(name); }},
  };
}
const form = control('form');
const button = control('button');
fire('submit', {target: form, submitter: button});
fire('htmx:beforeRequest', {detail: {elt: form}});
assert(button.classes.has('is-htmx-loading'));
assert.equal(button.attrs.get('aria-busy'), 'true');
assert.equal(button.attrs.has('disabled'), false);
let blocked = false;
fire('submit', {target: form, submitter: button, preventDefault() {blocked = true;},
  stopImmediatePropagation() {}});
assert(blocked);
fire('htmx:afterRequest', {detail: {elt: form}});
assert.equal(button.classes.has('is-htmx-loading'), false);
assert.equal(button.attrs.has('aria-busy'), false);

const link = control('a');
fire('htmx:beforeRequest', {detail: {elt: link}});
assert(link.classes.has('is-htmx-loading'));
assert.equal(link.attrs.get('aria-disabled'), 'true');
fire('htmx:sendError', {detail: {elt: link}});
assert.equal(link.classes.has('is-htmx-loading'), false);
assert.equal(link.attrs.has('aria-disabled'), false);
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_loading_indicator_is_in_shared_stylesheet_and_respects_reduced_motion():
    css = (ROOT / "web/static/css/v2.css").read_text()
    base = (ROOT / "web/templates/base.html").read_text()
    assert ".is-htmx-loading::after" in css
    assert "prefers-reduced-motion:reduce" in css
    assert "js/v2.js" in base
