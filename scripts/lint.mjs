import { readFileSync, existsSync } from 'node:fs';

const requiredFiles = [
  'package.json',
  'index.html',
  'src/app.js',
  'test/smoke.test.mjs',
];

for (const file of requiredFiles) {
  if (!existsSync(file)) {
    console.error(`Missing required file: ${file}`);
    process.exit(1);
  }
}

const repoPkg = JSON.parse(readFileSync('package.json', 'utf8'));
if (!repoPkg.scripts?.lint || !repoPkg.scripts?.test) {
  console.error('Root package.json must define lint and test scripts');
  process.exit(1);
}

// Keep nested frontend support for legacy paths while preferring repo-root frontend files.
if (existsSync('frontend/package.json')) {
  const frontendPkg = JSON.parse(readFileSync('frontend/package.json', 'utf8'));
  if (!frontendPkg.scripts?.start) {
    console.error('frontend/package.json exists but does not define a start script');
    process.exit(1);
  }
}

const app = readFileSync('src/app.js', 'utf8');
const checks = [
  ['title', 'GAMMA SHOCK BUFFER'],
  ['generator', 'genGEXStrikes'],
  ['flip', 'findFlipStrike'],
  ['render', 'function render'],
  ['symbol selector', 'symbolSelect'],
];

for (const [name, snippet] of checks) {
  if (!app.includes(snippet)) {
    console.error(`Lint check failed (${name}): missing snippet -> ${snippet}`);
    process.exit(1);
  }
}

console.log('lint checks passed');
