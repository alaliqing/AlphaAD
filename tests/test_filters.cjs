const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

// Exercise the shipped filter functions with a minimal DOM for facet labels.
function makeApp() {
  const nodes = new Map();
  const node = () => ({
    value: 'all', textContent: '', dataset: {}, children: [], scrollLeft: 0,
    addEventListener() {}, setAttribute() {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
  });
  const document = {
    documentElement: { dataset: {} },
    addEventListener() {}, querySelectorAll() { return []; },
    createElement: node, createTextNode: text => ({ textContent: text }),
    querySelector(selector) {
      if (selector === '#initial-data') return null;
      if (!nodes.has(selector)) nodes.set(selector, node());
      return nodes.get(selector);
    },
  };
  const context = vm.createContext({
    document, URLSearchParams, Intl, console,
    Option: function (text, value) { this.text = text; this.value = value; },
    window: {
      location: { search: '', pathname: '/' },
      localStorage: { getItem() { return null; }, setItem() {} },
      requestAnimationFrame() {},
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../site/assets/app.js'), 'utf8'), context);
  const papers = [
    { id: 'new-vla', title: 'Safe driving', age_days: 2, category: 'Planning', tags: ['VLA', 'Simulation'] },
    { id: 'new-data', title: 'Road dataset', age_days: 4, category: 'Perception', tags: ['Dataset'] },
    { id: 'old-vla', title: 'Safe world model', age_days: 20, category: 'Planning', tags: ['VLA'] },
    { id: 'old-data', title: 'Old dataset', age_days: 70, category: 'Planning', tags: ['Dataset'] },
  ].map(paper => ({ ...paper, authors: ['Ada'], abstract: 'Driving research', published: '2026-10-01' }));
  context.fixture = papers;
  vm.runInContext(`
    state.papers = fixture;
    state.ready = true;
    meta = { window_days: 180, categories: [{ name: 'Planning' }, { name: 'Perception' }],
      tags: [{ name: 'VLA', count: 2 }, { name: 'Dataset', count: 2 }, { name: 'Simulation', count: 1 }] };
  `, context);
  return {
    run: source => vm.runInContext(source, context),
    tags() {
      vm.runInContext('renderTagFilter(matchingPapers({ ignoreTag: true }))', context);
      return Object.fromEntries(nodes.get('#tag-filter').children.map(option => [option.value, option.text]));
    },
    selectedTag: () => nodes.get('#tag-filter').value,
  };
}

test('recency and tag filters intersect, and tag counts use the selected time range', () => {
  const app = makeApp();
  app.run('state.days = "7"; state.tag = "VLA"');
  assert.equal(app.run('JSON.stringify(filteredPapers().map(paper => paper.id))'), '["new-vla"]');
  assert.deepEqual(app.tags(), {
    all: 'All research tags · 2', VLA: 'VLA · 1', Dataset: 'Dataset · 1', Simulation: 'Simulation · 1',
  });
  app.run('state.days = "30"');
  assert.equal(app.run('filteredPapers().length'), 2);
  assert.equal(app.tags().VLA, 'VLA · 2');
  assert.equal(app.selectedTag(), 'VLA');
});

test('tag counts also reflect topic and search, without restricting to the selected tag', () => {
  const app = makeApp();
  app.run('state.days = "30"; state.category = "Planning"; state.query = "safe"; state.tag = "Simulation"');
  assert.equal(app.run('filteredPapers().length'), 1);
  assert.equal(app.tags().VLA, 'VLA · 2');
  assert.equal(app.tags().Dataset, 'Dataset · 0');
  assert.equal(app.tags().Simulation, 'Simulation · 1');
});

test('a selected tag with zero matches stays selected and produces an empty result', () => {
  const app = makeApp();
  app.run('state.days = "7"; state.category = "Perception"; state.tag = "VLA"');
  assert.equal(app.run('filteredPapers().length'), 0);
  assert.equal(app.tags().VLA, 'VLA · 0');
  assert.equal(app.tags().Dataset, 'Dataset · 1');
  assert.equal(app.selectedTag(), 'VLA');
});

test('topic facet counts keep recency and tag active', () => {
  const app = makeApp();
  app.run('state.days = "7"; state.tag = "VLA"; state.category = "Perception"');
  assert.equal(app.run('JSON.stringify(matchingPapers({ ignoreCategory: true }).map(paper => paper.id))'), '["new-vla"]');
});
