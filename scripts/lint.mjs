import { readFileSync, existsSync } from 'node:fs';

const requiredFiles = [
  'frontend/package.json',
  'frontend/index.html',
  'frontend/src/main.jsx',
  'frontend/src/App.jsx',
];

for (const file of requiredFiles) {
  if (!existsSync(file)) {
    console.error(`Missing required file: ${file}`);
    process.exit(1);
  }
}

const app = readFileSync('frontend/src/App.jsx', 'utf8');
const checks = [
  ['title', 'GAMMA SHOCK BUFFER'],
  ['chart', 'BarChart'],
  ['flip', 'findFlipStrike'],
  ['memoized data', 'useMemo(() => genGEXStrikes(spot), [spot])'],
];

for (const [name, snippet] of checks) {
  if (!app.includes(snippet)) {
    console.error(`Lint check failed (${name}): missing snippet -> ${snippet}`);
    process.exit(1);
  }
}

console.log('lint checks passed');
