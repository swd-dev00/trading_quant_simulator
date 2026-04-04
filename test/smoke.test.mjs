import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

test('fastapi entrypoint exists', () => {
  assert.equal(existsSync('main.py'), true);
  const source = readFileSync('main.py', 'utf8');
  assert.match(source, /FastAPI/);
});

test('gamma shock buffer app exists and includes expected heading', () => {
  assert.equal(existsSync('frontend/src/App.jsx'), true);
  const source = readFileSync('frontend/src/App.jsx', 'utf8');
  assert.match(source, /GAMMA SHOCK BUFFER/);
});
test('gamma shock buffer frontend exists in repo root and includes expected heading', () => {
  assert.equal(existsSync('src/app.js'), true);
  assert.equal(existsSync('index.html'), true);
  const source = readFileSync('src/app.js', 'utf8');
  assert.match(source, /GAMMA SHOCK BUFFER/);
});

test('gamma helpers expose deterministic shape and flip detection', () => {
  const { genGEXStrikes, findFlipStrike } = require('../src/app.js');
  const sample = genGEXStrikes(100, 7);

  assert.equal(sample.length, 7);
  assert.ok(sample.every((row) => 'strike' in row && 'gex' in row));

  const flip = findFlipStrike([
    { strike: '95', gex: -10 },
    { strike: '100', gex: -1 },
    { strike: '105', gex: 2 },
  ]);

  assert.deepEqual(flip, { strike: '105', gex: 2 });
  assert.equal(findFlipStrike([{ strike: '100', gex: 1 }]), null);
});
