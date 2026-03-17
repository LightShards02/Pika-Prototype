const { spawn } = require('child_process');
const electronBinary = require('electron');

async function start() {
  const { createServer } = await import('vite');

  const server = await createServer();
  await server.listen();
  server.printUrls();

  const env = { ...process.env, NODE_ENV: 'development' };
  delete env.ELECTRON_RUN_AS_NODE;

  const child = spawn(String(electronBinary), ['.'], { stdio: 'inherit', env });

  child.on('exit', (code, signal) => {
    server.close();
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
}

start().catch((err) => {
  console.error(err);
  process.exit(1);
});
