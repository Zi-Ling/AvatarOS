const path = require("node:path");
const { existsSync, readFileSync, writeFileSync, mkdirSync } = require("node:fs");
const { app, BrowserWindow, ipcMain, screen } = require("electron");

const DEFAULT_HOST = process.env.RENDERER_HOST || "127.0.0.1";
const DEFAULT_PORT = process.env.RENDERER_PORT || "3000";

process.env.ELECTRON_DISABLE_SECURITY_WARNINGS = "true";

let mainWindow = null;
let floatingWindow = null;

// 配置文件路径
const configPath = path.join(app.getPath('userData'), 'avatar-config.json');

// 读取配置
function loadConfig() {
  try {
    if (existsSync(configPath)) {
      const data = readFileSync(configPath, 'utf8');
      return JSON.parse(data);
    }
  } catch (error) {
    console.error('Failed to load config:', error);
  }
  return { floatingWindowEnabled: false }; // 默认关闭
}

// 保存配置
function saveConfig(config) {
  try {
    const dir = path.dirname(configPath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
    writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf8');
  } catch (error) {
    console.error('Failed to save config:', error);
  }
}

const resolvePreloadPath = () => path.join(__dirname, "preload.js");

const resolveHtmlEntry = () => path.join(__dirname, "../renderer/index.html");

async function loadRenderer(win, route = "") {
  const devUrl =
    process.env.ELECTRON_RENDERER_URL || `http://${DEFAULT_HOST}:${DEFAULT_PORT}`;
  const packagedEntry = resolveHtmlEntry();

  if (!app.isPackaged || !existsSync(packagedEntry)) {
    await win.loadURL(`${devUrl}${route}`);
    return;
  }

  await win.loadFile(packagedEntry, { hash: route });
}

function createFloatingWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  
  // 固定大小窗口：宽度足够容纳光球 + Timeline
  floatingWindow = new BrowserWindow({
    width: 420,  // 光球 100px + Timeline 300px + 间距
    height: 160, // 增加高度，防止 Timeline 被截断
    x: width - 440,
    y: height - 180,
    show: false, // 默认隐藏，完全由配置控制
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: resolvePreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 加载页面后确保窗口保持隐藏（除非配置要求显示）
  loadRenderer(floatingWindow, "/avatar")
    .catch((err) => {
      console.error("Failed to load floating window:", err);
    });

  floatingWindow.on('closed', () => {
    floatingWindow = null;
  });

  // 防止窗口被意外显示 - 添加保护机制
  floatingWindow.on('show', () => {
    // 检查配置，如果配置中是关闭状态，立即隐藏
    const config = loadConfig();
    if (!config.floatingWindowEnabled && floatingWindow) {
      setTimeout(() => {
        if (floatingWindow && !floatingWindow.isDestroyed()) {
          floatingWindow.hide();
        }
      }, 0);
    }
  });

  // 限制窗口不能拖出屏幕边界
  floatingWindow.on('will-move', (event, newBounds) => {
    const { width: screenWidth, height: screenHeight } = screen.getPrimaryDisplay().workAreaSize;
    let { x, y, width: winWidth, height: winHeight } = newBounds;
    
    const limitX = winWidth / 2;
    const limitY = winHeight / 2;

    if (x < -limitX) x = -limitX;
    if (x > screenWidth - limitX) x = screenWidth - limitX;
    if (y < -limitY) y = -limitY;
    if (y > screenHeight - limitY) y = screenHeight - limitY;
    
    if (x !== newBounds.x || y !== newBounds.y) {
      event.preventDefault();
      floatingWindow.setPosition(Math.round(x), Math.round(y));
    }
  });
}

function createMainWindow() {
  const isMac = process.platform === "darwin";
  const iconPath = path.join(__dirname, "../public/logo.ico");

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1120,
    minHeight: 720,
    title: "IntelliFlow",
    icon: iconPath,
    backgroundColor: "#020617",
    frame: false,
    show: false,
    webPreferences: {
      preload: resolvePreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  mainWindow.once("closed", () => {
    mainWindow = null;
    if (floatingWindow && !floatingWindow.isDestroyed()) {
      floatingWindow.close();
    }
  });

  // 强制检查逻辑 - 当主窗口恢复时，确保精灵球状态正确
  mainWindow.on("restore", () => {
    const config = loadConfig();
    if (!config.floatingWindowEnabled && floatingWindow && !floatingWindow.isDestroyed()) {
      if (floatingWindow.isVisible()) {
        floatingWindow.hide();
      }
    }
  });

  mainWindow.on("show", () => {
    const config = loadConfig();
    if (!config.floatingWindowEnabled && floatingWindow && !floatingWindow.isDestroyed()) {
      if (floatingWindow.isVisible()) {
        floatingWindow.hide();
      }
    }
  });


  loadRenderer(mainWindow).catch((error) => {
    console.error("加载渲染进程失败：", error);
  });
}

ipcMain.handle("app:get-version", () => app.getVersion());

ipcMain.on("window:minimize", () => {
  if (mainWindow) mainWindow.minimize();
});

ipcMain.on("window:maximize", () => {
  if (mainWindow) {
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  }
});

ipcMain.on("window:close", () => {
  if (mainWindow) mainWindow.close();
});

ipcMain.on("floating:expand", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
  // 不再自动隐藏精灵球，由用户通过 Avatar Mode 控制
  // if (floatingWindow) floatingWindow.hide();
});

// 处理悬浮窗移动
ipcMain.on("floating:move", (event, { deltaX, deltaY }) => {
  if (!floatingWindow) return;
  const [x, y] = floatingWindow.getPosition();
  floatingWindow.setPosition(x + deltaX, y + deltaY);
});

// 控制鼠标穿透
ipcMain.on("floating:set-ignore-mouse-events", (event, ignore, options) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) {
    win.setIgnoreMouseEvents(ignore, options);
  }
});

// 切换悬浮窗显示/隐藏
ipcMain.handle("floating:toggle", () => {
  if (!floatingWindow) return false;
  const isVisible = floatingWindow.isVisible();
  const newState = !isVisible;
  
  if (newState) {
    floatingWindow.show();
  } else {
    floatingWindow.hide();
  }
  
  // 保存状态
  const config = loadConfig();
  config.floatingWindowEnabled = newState;
  saveConfig(config);
  
  return newState;
});

// 获取悬浮窗状态
ipcMain.handle("floating:is-visible", () => {
  if (!floatingWindow) return false;
  return floatingWindow.isVisible();
});

const singleInstanceLock = app.requestSingleInstanceLock();

if (!singleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(() => {
    createMainWindow();
    createFloatingWindow();
    
    // 根据保存的配置决定是否显示精灵球
    const config = loadConfig();
    if (config.floatingWindowEnabled && floatingWindow) {
      floatingWindow.show();
    }

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow();
        createFloatingWindow();
        
        // 恢复状态
        const config = loadConfig();
        if (config.floatingWindowEnabled && floatingWindow) {
          floatingWindow.show();
        }
      }
    });
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
