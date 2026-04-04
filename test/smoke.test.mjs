import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

test('fastapi entrypoint exists', () => {
  assert.equal(existsSync('main.py'), true);
  const source = readFileSync('main.py', 'utf8');
  assert.match(source, /FastAPI/);
});

test('gamma shock buffer static app exists and includes expected heading', () => {
  assert.equal(existsSync('frontend/src/app.js'), true);
  const source = readFileSync('frontend/src/app.js', 'utf8');
  assert.match(source, /GAMMA SHOCK BUFFER/);
});
