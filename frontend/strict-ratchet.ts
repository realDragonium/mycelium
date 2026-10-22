// Tier 2 of the type-checking ratchet. Runs `tsc` in full strict mode over every
// file and fails on an error in any file not listed below. Also fails when a
// listed file has become clean, so the list only shrinks: delete its line.
//
// Every file below is exempt for the same reason unless noted: it came over from
// untyped, browser-compiled JSX, and its component props, state and callbacks
// are not annotated yet (implicit `any`, `useState(null)` widened later, `catch`
// variables read as `Error`).
import { execFileSync } from 'node:child_process';
import { relative } from 'node:path';

const NOT_STRICT_YET = new Set([
  'ui/activity.tsx',
  'ui/alias-suggestions.tsx',
  'ui/documentation-workspace.tsx',
  'ui/entities-graph.tsx',
  'ui/glossary.tsx',
  'ui/graph.tsx',
  'ui/names-workspace.tsx',
]);

const here = new URL('.', import.meta.url).pathname;
let output = '';
try {
  execFileSync(process.execPath, ['node_modules/typescript/bin/tsc', '-p', 'tsconfig.strict.json', '--pretty', 'false'], { cwd: here, encoding: 'utf8' });
} catch (err) {
  output = (err as { stdout: string }).stdout;
}

const errorsByFile = new Map<string, string[]>();
for (const line of output.split('\n')) {
  const match = /^(.+?)\(\d+,\d+\): error TS\d+/.exec(line);
  if (!match) continue;
  const file = relative(here, new URL(match[1], `file://${here}`).pathname);
  errorsByFile.set(file, [...(errorsByFile.get(file) ?? []), line]);
}

const regressions = [...errorsByFile].filter(([file]) => !NOT_STRICT_YET.has(file));
const graduated = [...NOT_STRICT_YET].filter(file => !errorsByFile.has(file));

for (const [, lines] of regressions) console.error(lines.join('\n'));
for (const file of graduated) console.error(`${file} now passes strict mode: remove it from NOT_STRICT_YET in strict-ratchet.ts`);
if (regressions.length || graduated.length) process.exit(1);

const remaining = [...errorsByFile.values()].reduce((n, lines) => n + lines.length, 0);
console.log(`strict: ${NOT_STRICT_YET.size} files not strict yet (${remaining} errors)`);
