import { appendFileSync, readFileSync } from 'node:fs';

const sbom = JSON.parse(readFileSync(process.argv[2], 'utf8'));
if (!Array.isArray(sbom.components)) throw new Error('Expected a CycloneDX components list.');
const counts = new Map();
for (const component of sbom.components) {
  const licenses = component.licenses?.map(({ license, expression }) => license?.id || license?.name || expression)
    .filter(Boolean) ?? [];
  const names = licenses.length ? new Set(licenses) : ['UNKNOWN'];
  for (const name of names) counts.set(name, (counts.get(name) ?? 0) + 1);
}
const rows = [...counts].sort(([a], [b]) => a.localeCompare(b))
  .map(([license, count]) => `| ${license.replace(/[^a-zA-Z0-9.+ ()-]/g, ' ')} | ${count} |`);
const report = ['### npm licenses from the lockfile', '', '| License | Components |', '| --- | --- |',
  ...rows, '', 'UNKNOWN means the lockfile does not report a license. Review it before release.', ''].join('\n');
if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, report);
else console.log(report);
