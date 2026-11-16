
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const cli = process.env.SUPABASE_CLI || 'supabase';
const venv = resolve(process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const python = process.env.CHESS_PYTHON || (existsSync(venv) ? venv : process.platform === 'win32' ? 'python' : 'python3');
const fixtures = 'qa-report/tests/run_qa.py';

function command(file, args, env = process.env, capture = false) {
  const result = spawnSync(file, args, {
    env, encoding: 'utf8', windowsHide: true, stdio: capture ? ['ignore', 'pipe', 'ignore'] : 'inherit',
  });
  if (result.error || result.status !== 0) {
    throw new Error(file + ' ' + args[0] + ' failed. Check that the required tool and local stack are ready.');
  }
  return result.stdout;
}

function supabase(args, capture = false) {
  return command(cli, [...args, '--agent=no'], { ...process.env, DO_NOT_TRACK: '1' }, capture);
}

function npmTask(name) {
  command(process.execPath, [process.env.npm_execpath, 'run', name]);
}

export function localUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) ||
      url.username || url.password || url.search || url.hash) {
    throw new Error('Test URLs must use loopback.');
  }
  return url.origin;
}

export function localSupabase() {
  const output = supabase(['status', '-o', 'env'], true);
  const settings = {};
  for (const line of output.split(/\r?\n/)) {
    const entry = /^([A-Z_]+)=(.*)$/.exec(line);
    if (entry) settings[entry[1]] = entry[2].replace(/^"(.*)"$/, '$1');
  }
  const url = localUrl(settings.API_URL || settings.SUPABASE_URL);
  const mail = localUrl(settings.MAILPIT_URL || settings.INBUCKET_URL || 'http://127.0.0.1:54324');
  const publishable = settings.PUBLISHABLE_KEY || settings.ANON_KEY;
  const secret = settings.SECRET_KEY || settings.SERVICE_ROLE_KEY;
  if (!publishable || !secret) throw new Error('Local Supabase status did not provide keys.');
  return { url, mail, publishable, secret };
}

async function freePort() {
  const socket = createServer();
  socket.listen(0, '127.0.0.1');
  await once(socket, 'listening');
  const port = socket.address().port;
  socket.close();
  await once(socket, 'close');
  return port;
}

export async function withLocalApp(test) {
  const settings = localSupabase();
  const port = await freePort();
  const origin = 'http://127.0.0.1:' + port;
  const env = {
    ...process.env,
    CHESS_ENV: 'local',
    CHESS_ROOM_STORE: 'supabase',
    CHESS_ACCOUNT_ENABLED: '1',
    APP_ORIGIN: origin,
    SUPABASE_URL: settings.url,
    SUPABASE_PUBLISHABLE_KEY: settings.publishable,
    SUPABASE_SECRET_KEY: settings.secret,
    AUTH_OAUTH_PROVIDERS: '',
    AUTH_CAPTCHA_SITE_KEY: '',
    CHESS_QA_LOCAL_MAIL_URL: settings.mail,
    PYTHONDONTWRITEBYTECODE: '1',
  };
  const child = spawn(python, ['-B', '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1',
    '--port', String(port), '--no-access-log'], { env, windowsHide: true, stdio: ['ignore', 'ignore', 'inherit'] });
  let launchError;
  child.on('error', error => { launchError = error; });
  try {
    let ready = false;
    for (let attempt = 0; attempt < 40; ++attempt) {
      if (launchError || child.exitCode !== null) throw new Error('Local FastAPI did not start.');
      try {
        const status = await fetch(origin + '/api/account', { signal: AbortSignal.timeout(1000) });
        ready = status.ok && (await status.json()).enabled === true;
        if (ready) break;
      } catch {
        // FastAPI does not bind its port until initialization completes.
      }
      await new Promise(done => setTimeout(done, 250));
    }
    if (!ready) throw new Error('Local FastAPI did not report enabled accounts.');
    test(env);
  } finally {
    if (!launchError && child.exitCode === null) {
      const stopped = once(child, 'exit');
      child.kill();
      await stopped;
    }
  }
}

function generatedTypes(check) {
  const result = supabase(['gen', 'types', '--lang=typescript', '--schema=public'], true)
    .replace(/\r\n/g, '\n').replace(/[ \t]+$/gm, '').trimEnd() + '\n';
  if (!result.includes('export type Database')) throw new Error('Supabase output was not TypeScript database types.');
  const target = 'src/lib/database.types.ts';
  if (!check) writeFileSync(target, result);
  else if (readFileSync(target, 'utf8').replace(/\r\n/g, '\n') !== result) {
    throw new Error('Generated database types differ. Run npm run db:types and commit the result.');
  }
}

async function main(task) {
  switch (task) {
    case 'db:start': supabase(['start']); break;
    case 'db:reset': supabase(['db', 'reset']); break;
    case 'db:migrate': supabase(['migration', 'up']); break;
    case 'db:lint': supabase(['db', 'lint', '--schema', 'public,chessmess_private', '--level', 'warning', '--fail-on', 'warning']); break;
    case 'db:test': supabase(['test', 'db']); break;
    case 'db:types': generatedTypes(false); break;
    case 'db:types:check': generatedTypes(true); break;
    case 'unit': {
      const files = readdirSync('tests/unit').filter(name => name.endsWith('.test.mjs'));
      command(process.execPath, ['--test', ...files.map(name => 'tests/unit/' + name)]);
      command(python, ['-B', fixtures, 'unit', 'accounts']);
      break;
    }
    case 'integration':
      npmTask('build');
      command(python, ['-B', fixtures, 'integration', 'security', 'rooms-db']);
      await withLocalApp(env => command(process.execPath, ['tests/integration/local-auth.mjs'], env));
      break;
    case 'e2e':
      npmTask('build');
      command(python, ['-B', fixtures, 'smoke', 'regression', 'a11y', 'account-browser']);
      await withLocalApp(env => command(python, ['-B', 'tests/e2e/local_auth.py'], env));
      break;
    case 'test:all':
      for (const step of ['lint', 'typecheck', 'test:unit', 'db:lint', 'db:test', 'db:types:check', 'test:integration', 'test:e2e']) {
        npmTask(step);
      }
      break;
    case 'serve': {
      if (existsSync('.env.local')) process.loadEnvFile('.env.local');
      const origin = new URL(process.env.APP_ORIGIN || 'http://127.0.0.1:3210');
      localUrl(origin);
      npmTask('build');
      command(python, ['-B', '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1',
        '--port', origin.port || '80', '--no-access-log']);
      break;
    }
    default: throw new Error('Unknown local task.');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await main(process.argv[2]).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
