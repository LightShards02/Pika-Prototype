const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const yaml = require('js-yaml');

let mainWindow;
let pikaProcess = null;

const PIKA_ROOT = path.join(__dirname, '..', 'backend');

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // In development, load from Vite dev server
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, 'dist/index.html'));
  }
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// ---------------------------------------------------------------------------
// Shared: spawn a PIKA CLI command via conda
// ---------------------------------------------------------------------------

function spawnPikaCommand(args) {
  const condaArgs = ['run', '-n', 'Local', 'python', '-m', 'cli', ...args];
  const child = spawn('conda', condaArgs, {
    cwd: PIKA_ROOT,
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stdoutBuf = '';

  child.stdout.on('data', (chunk) => {
    stdoutBuf += chunk.toString();
  });

  child.stderr.on('data', (chunk) => {
    const lines = chunk.toString().split(/\r?\n/).filter(Boolean);
    for (const line of lines) {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('pika:stderr', line);
      }
    }
  });

  child.on('close', (code) => {
    let summary = null;
    try {
      summary = JSON.parse(stdoutBuf.trim());
    } catch {
      // stdout may not be valid JSON (e.g. if command crashed)
    }
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('pika:exit', { code, summary });
    }
    if (pikaProcess === child) {
      pikaProcess = null;
    }
  });

  child.on('error', (err) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('pika:stderr', `[ELECTRON] Process error: ${err.message}`);
      mainWindow.webContents.send('pika:exit', { code: 1, summary: null });
    }
    if (pikaProcess === child) {
      pikaProcess = null;
    }
  });

  return child;
}

// ---------------------------------------------------------------------------
// IPC Handlers: File System (existing)
// ---------------------------------------------------------------------------

ipcMain.handle('read-file', async (event, filePath) => {
  try {
    return fs.readFileSync(filePath, 'utf-8');
  } catch (error) {
    console.error('Error reading file:', error);
    throw error;
  }
});

ipcMain.handle('write-file', async (event, filePath, content) => {
  try {
    fs.writeFileSync(filePath, content, 'utf-8');
    return true;
  } catch (error) {
    console.error('Error writing file:', error);
    throw error;
  }
});

ipcMain.handle('list-directory', async (event, dirPath) => {
  try {
    return fs.readdirSync(dirPath);
  } catch (error) {
    console.error('Error listing directory:', error);
    throw error;
  }
});

// ---------------------------------------------------------------------------
// IPC Handlers: File/Folder Dialogs
// ---------------------------------------------------------------------------

ipcMain.handle('dialog:openFile', async (_event, options) => {
  const filters = options?.filters || [{ name: 'All Files', extensions: ['*'] }];
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters,
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

ipcMain.handle('dialog:saveFile', async (_event, options) => {
  const filters = options?.filters || [{ name: 'YAML Files', extensions: ['yaml', 'yml'] }];
  const result = await dialog.showSaveDialog(mainWindow, {
    filters,
    defaultPath: options?.defaultPath,
  });
  if (result.canceled) return null;
  return result.filePath;
});

ipcMain.handle('pika:getRoot', () => PIKA_ROOT);

ipcMain.handle('dialog:openDir', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
});

// ---------------------------------------------------------------------------
// IPC Handlers: PIKA Refine Process Lifecycle
// ---------------------------------------------------------------------------

ipcMain.handle('pika:start-refine', async (_event, { projectRoot, configPath, designSpecPath }) => {
  if (pikaProcess) {
    throw new Error('A PIKA process is already running. Cancel it first.');
  }

  const args = ['agent', 'refine', '--project-root', projectRoot];
  if (configPath) args.push('--config', configPath);
  if (designSpecPath) args.push('--design-spec', designSpecPath);

  pikaProcess = spawnPikaCommand(args);
});

ipcMain.handle('pika:cancel', async () => {
  if (pikaProcess) {
    pikaProcess.kill();
    pikaProcess = null;
  }
});

// ---------------------------------------------------------------------------
// IPC Handlers: Gate I/O
// ---------------------------------------------------------------------------

ipcMain.handle('pika:read-gate', async (_event, { runDir }) => {
  const agentReviewPath = path.join(runDir, 'manual_resolution', 'agent_review.json');
  try {
    const content = fs.readFileSync(agentReviewPath, 'utf-8');
    return JSON.parse(content);
  } catch (error) {
    console.error('Error reading gate output:', error);
    throw error;
  }
});

ipcMain.handle('pika:write-resolution', async (_event, { runDir, resolutions }) => {
  const resolutionsPath = path.join(runDir, 'manual_resolution', 'resolutions.yaml');
  try {
    const content = fs.readFileSync(resolutionsPath, 'utf-8');
    const data = yaml.load(content);

    for (const { itemIndex, chosenOptionId } of resolutions) {
      if (data.items && data.items[itemIndex]) {
        data.items[itemIndex].chosen_option_id = chosenOptionId;
      }
    }

    fs.writeFileSync(resolutionsPath, yaml.dump(data, { lineWidth: -1 }), 'utf-8');
  } catch (error) {
    console.error('Error writing resolution:', error);
    throw error;
  }
});

// ---------------------------------------------------------------------------
// IPC Handlers: Resolve (apply-only) + Resume
// ---------------------------------------------------------------------------

ipcMain.handle('pika:apply-resolutions', async (_event, { projectRoot, runId, configPath }) => {
  if (pikaProcess) {
    throw new Error('A PIKA process is already running.');
  }

  const args = ['agent', 'resolve', '--run', runId, '--project-root', projectRoot, '--apply-only'];
  if (configPath) args.push('--config', configPath);

  pikaProcess = spawnPikaCommand(args);
});

ipcMain.handle('pika:resume-refine', async (_event, { projectRoot, runId, configPath }) => {
  if (pikaProcess) {
    throw new Error('A PIKA process is already running.');
  }

  const args = ['agent', 'refine', '--resume', '--run', runId, '--project-root', projectRoot];
  if (configPath) args.push('--config', configPath);

  pikaProcess = spawnPikaCommand(args);
});

// ---------------------------------------------------------------------------
// IPC Handlers: Preferences Persistence
// ---------------------------------------------------------------------------

const PREFS_FILENAME = 'pika-preferences.json';

function getPrefsPath() {
  return path.join(app.getPath('userData'), PREFS_FILENAME);
}

ipcMain.handle('preferences:load', async () => {
  const prefsPath = getPrefsPath();
  try {
    if (!fs.existsSync(prefsPath)) {
      return null;
    }
    const content = fs.readFileSync(prefsPath, 'utf-8');
    return JSON.parse(content);
  } catch (error) {
    console.error('Error loading preferences:', error);
    return null;
  }
});

ipcMain.handle('preferences:save', async (_event, preferences) => {
  const prefsPath = getPrefsPath();
  try {
    const content = JSON.stringify(preferences, null, 2);
    fs.writeFileSync(prefsPath, content, 'utf-8');
    return true;
  } catch (error) {
    console.error('Error saving preferences:', error);
    return false;
  }
});

ipcMain.handle('preferences:pathExists', async (_event, targetPath) => {
  try {
    return fs.existsSync(targetPath);
  } catch {
    return false;
  }
});
