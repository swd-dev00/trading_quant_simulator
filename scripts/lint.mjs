import { readFileSync, existsSync } from 'node:fs';

const requiredFiles = [
  'frontend/package.json',
  'frontend/index.html',
  'frontend/src/app.js',
];

for (const file of requiredFiles) {
  if (!existsSync(file)) {
    console.error(`Missing required file: ${file}`);
    process.exit(1);
  }
}

const app = readFileSync('frontend/src/app.js', 'utf8');
const checks = [
  ['title', 'GAMMA SHOCK BUFFER'],
  ['generator', 'genGEXStrikes'],
  ['flip', 'findFlipStrike'],
  ['render', 'function render'],
];

for (const [name, snippet] of checks) {
  if (!app.includes(snippet)) {
    console.error(`Lint check failed (${name}): missing snippet -> ${snippet}`);
    process.exit(1);
  }
}

console.log('lint checks passed');
