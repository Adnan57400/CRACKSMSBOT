/**
 * whatsapp_otp.js — Crack SMS WhatsApp OTP Bridge v2
 * 
 * FEATURES:
 *   • Forward OTPs from Telegram to WhatsApp group
 *   • Receive OTPs from WhatsApp and send to Telegram bot
 *   • Full 30 OTP GUI themes (controlled by Telegram bot)
 *   • Persistent session, auto-reconnect, logging
 *   • Health check endpoint for Railway
 */

'use strict';

const { 
  default: makeWASocket,
  Browsers,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const NodeCache = require('node-cache');
const { Boom } = require('@hapi/boom');
const fs = require('fs-extra');
const path = require('path');
const qrterm = require('qrcode-terminal');
const chalk = require('chalk');
const http = require('http');
const axios = require('axios');

// ========== CONFIG ==========
const CONFIG = {
  sessionDir:  process.env.WA_SESSION_DIR || path.join(__dirname, 'wa_session'),
  stateFile:   path.join(__dirname, 'wa_bridge_state.json'),
  secret:      process.env.WA_OTP_SECRET || 'cracksms_wa_secret_2026',
  bridgePort:  parseInt(process.env.WA_BRIDGE_PORT || '7891'),
  botApiUrl:   process.env.TELEGRAM_BOT_API_URL || 'http://127.0.0.1:7677', // where bot.py listens
  reconnectBase: 3000,
  logFile:     path.join(__dirname, 'wa_bridge.log'),
};

// Setup logging to file and console
const logStream = fs.createWriteStream(CONFIG.logFile, { flags: 'a' });
const logger = {
  info: (...args) => {
    const msg = `[${new Date().toISOString()}] INFO: ${args.join(' ')}`;
    console.log(chalk.blue(msg));
    logStream.write(msg + '\n');
  },
  error: (...args) => {
    const msg = `[${new Date().toISOString()}] ERROR: ${args.join(' ')}`;
    console.log(chalk.red(msg));
    logStream.write(msg + '\n');
  },
  warn: (...args) => {
    const msg = `[${new Date().toISOString()}] WARN: ${args.join(' ')}`;
    console.log(chalk.yellow(msg));
    logStream.write(msg + '\n');
  },
};

// ========== PERSISTENT STATE ==========
let state = {
  otpForwardingOn: false,
  waGroupJid:      null,
  linkedPhone:     null,
  startedAt:       Date.now(),
  otpsSent:        0,
  otpsReceived:    0,
};

function loadState() {
  try {
    if (fs.existsSync(CONFIG.stateFile))
      Object.assign(state, JSON.parse(fs.readFileSync(CONFIG.stateFile, 'utf8')));
  } catch (e) { logger.error('State load error:', e.message); }
}

function saveState() {
  try { fs.writeFileSync(CONFIG.stateFile, JSON.stringify(state, null, 2)); }
  catch (e) { logger.error('State save error:', e.message); }
}

loadState();

// ========== WHATSAPP SOCKET ==========
let sock = null;
let isRunning = false;
let reconnectAttempt = 0;

async function sendToWaGroup(text) {
  if (!sock) throw new Error('WhatsApp not connected');
  if (!state.waGroupJid) throw new Error('No WA group configured');
  await sock.sendMessage(state.waGroupJid, { text });
  state.otpsSent++;
  saveState();
  logger.info(`📤 Forwarded to WA group: ${state.waGroupJid}`);
}

// Forward incoming WhatsApp message to Telegram bot
async function forwardToTelegramBot(number, body, otpCode, service, panel) {
  if (!CONFIG.botApiUrl) return;
  try {
    await axios.post(`${CONFIG.botApiUrl}/wa_otp`, {
      secret: CONFIG.secret,
      number: number,
      msg_body: body,
      otp_code: otpCode,
      service_name: service,
      panel_name: panel || 'WhatsApp',
    }, { timeout: 5000 });
    state.otpsReceived++;
    saveState();
    logger.info(`📥 Forwarded WA OTP to bot: ${number} -> ${otpCode || 'no OTP'}`);
  } catch (err) {
    logger.error(`Failed to forward to bot: ${err.message}`);
  }
}

// Extract OTP from text (simplified, bot.py does full extraction)
function extractOtpSimple(text) {
  const match = text.match(/\b\d{4,8}\b/);
  return match ? match[0] : null;
}

// Handle commands from the linked WhatsApp number
async function handleSelfCommand(jid, text) {
  const t = text.trim().toLowerCase();

  if (t === '/otp on') {
    if (!state.waGroupJid) {
      await sock.sendMessage(jid, { text: '❌ No WA group set. Use /otp group <JID>' });
      return;
    }
    state.otpForwardingOn = true;
    saveState();
    await sock.sendMessage(jid, { text: '✅ OTP Forwarding: ON\nOTPs will be sent to group.' });
    logger.info('WA OTP forwarding enabled');
    return;
  }

  if (t === '/otp off') {
    state.otpForwardingOn = false;
    saveState();
    await sock.sendMessage(jid, { text: '🔴 OTP Forwarding: OFF' });
    logger.info('WA OTP forwarding disabled');
    return;
  }

  if (t === '/otp status') {
    const upSec = Math.floor((Date.now() - state.startedAt) / 1000);
    const h = Math.floor(upSec / 3600), m = Math.floor((upSec % 3600) / 60);
    await sock.sendMessage(jid, { text:
      `📊 *WhatsApp OTP Bridge*\n\n` +
      `🔀 Forwarding: ${state.otpForwardingOn ? '✅ ON' : '🔴 OFF'}\n` +
      `📲 Linked: ${state.linkedPhone || 'Unknown'}\n` +
      `👥 Target Group: ${state.waGroupJid || '⚠️ Not set'}\n` +
      `📤 OTPs sent: ${state.otpsSent}\n` +
      `📥 OTPs received: ${state.otpsReceived}\n` +
      `⏰ Uptime: ${h}h ${m}m` });
    return;
  }

  if (t === '/otp stats') {
    const upSec = Math.floor((Date.now() - state.startedAt) / 1000);
    const h = Math.floor(upSec / 3600), m = Math.floor((upSec % 3600) / 60);
    await sock.sendMessage(jid, { text:
      `📈 *Bridge Statistics*\n\n` +
      `🟢 Connected: Yes\n` +
      `📤 Forwards to WA: ${state.otpsSent}\n` +
      `📥 Forwards to TG: ${state.otpsReceived}\n` +
      `👥 Group: ${state.waGroupJid || 'none'}\n` +
      `⏱ Uptime: ${h}h ${m}m` });
    return;
  }

  if (t.startsWith('/otp group ')) {
    const jidArg = t.slice(11).trim();
    if (!jidArg.includes('@')) {
      await sock.sendMessage(jid, { text: '❌ Invalid JID. Must contain @' });
      return;
    }
    state.waGroupJid = jidArg;
    saveState();
    await sock.sendMessage(jid, { text: `✅ WA Group set to: ${jidArg}` });
    logger.info(`WA group set: ${jidArg}`);
    return;
  }

  if (t === '/otp getjid') {
    await sock.sendMessage(jid, { text: `📋 This chat's JID: ${jid}` });
    return;
  }

  if (t === '/otp help') {
    await sock.sendMessage(jid, { text:
      `📋 *Commands*\n` +
      `/otp on – enable forwarding\n` +
      `/otp off – disable\n` +
      `/otp status – show status\n` +
      `/otp stats – bridge statistics\n` +
      `/otp group <JID> – set target group\n` +
      `/otp getjid – get JID of this chat\n` +
      `/otp help – this list` });
    return;
  }
}

async function startWhatsAppBridge() {
  if (isRunning) return;
  isRunning = true;

  await fs.ensureDir(CONFIG.sessionDir);
  logger.info(`Starting WhatsApp OTP Bridge... Session: ${CONFIG.sessionDir}`);

  const { state: authState, saveCreds } = await useMultiFileAuthState(CONFIG.sessionDir);
  const { version } = await fetchLatestBaileysVersion();
  const msgRetryCache = new NodeCache();

  sock = makeWASocket({
    version,
    auth: {
      creds: authState.creds,
      keys: makeCacheableSignalKeyStore(authState.keys, pino({ level: 'silent' })),
    },
    logger: pino({ level: 'silent' }),
    printQRInTerminal: true,
    browser: Browsers.macOS('Chrome'),
    msgRetryCounterCache: msgRetryCache,
    defaultQueryTimeoutMs: 60000,
    syncFullHistory: false,
    markOnlineOnConnect: false,
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      qrterm.generate(qr, { small: true });
      logger.info('📱 Scan QR with WhatsApp → Linked Devices → Link a Device');
    }
    if (connection === 'open') {
      state.linkedPhone = (sock.user?.id || '').split(':')[0];
      saveState();
      reconnectAttempt = 0;
      logger.info(`✅ WhatsApp connected! Phone: +${state.linkedPhone}`);
      logger.info(`   Forwarding: ${state.otpForwardingOn ? 'ON' : 'OFF'}`);
      if (state.waGroupJid) logger.info(`   Target group: ${state.waGroupJid}`);
      else logger.warn('⚠️ No target group set. Use /otp group <JID> from this WhatsApp.');
    }
    if (connection === 'close') {
      isRunning = false;
      const reason = new Boom(lastDisconnect?.error)?.output?.statusCode;
      if (reason === DisconnectReason.loggedOut) {
        logger.error('❌ Logged out. Delete wa_session/ and restart.');
      } else {
        const delay = Math.min(30000, CONFIG.reconnectBase * Math.pow(1.5, reconnectAttempt));
        reconnectAttempt++;
        logger.warn(`Disconnected (${reason}). Reconnecting in ${delay/1000}s...`);
        setTimeout(startWhatsAppBridge, delay);
      }
    }
  });

  // Handle incoming messages (including OTPs from WhatsApp)
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const m of messages) {
      // Ignore our own outgoing messages
      if (m.key.fromMe) {
        // But still process commands sent from linked number
        const body = m.message?.conversation || m.message?.extendedTextMessage?.text || '';
        if (body.startsWith('/otp')) {
          await handleSelfCommand(m.key.remoteJid, body);
        }
        continue;
      }

      // Incoming message from someone else (OTP SMS forwarded to WhatsApp)
      const body = m.message?.conversation || m.message?.extendedTextMessage?.text || '';
      const sender = m.key.remoteJid;
      if (!body) continue;

      logger.info(`📨 Incoming WhatsApp message from ${sender}: ${body.slice(0, 50)}`);
      const otp = extractOtpSimple(body);
      // Forward to Telegram bot for processing
      await forwardToTelegramBot(sender.split('@')[0], body, otp, 'WhatsApp', 'WA Bridge');
    }
  });
}

// ========== HTTP SERVER (for Telegram bot to call) ==========
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', d => { body += d; if (body.length > 50000) req.destroy(); });
    req.on('end', () => {
      try { resolve(JSON.parse(body)); }
      catch (e) { reject(e); }
    });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  // Health check for Railway
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', uptime: Date.now() - state.startedAt }));
    return;
  }

  if (req.method !== 'POST') {
    res.writeHead(405); res.end('Method Not Allowed');
    return;
  }

  let data;
  try { data = await parseBody(req); }
  catch (e) { res.writeHead(400); res.end(JSON.stringify({ error: 'bad json' })); return; }

  if (data.secret !== CONFIG.secret) {
    res.writeHead(403); res.end(JSON.stringify({ error: 'forbidden' }));
    return;
  }

  // POST /forward_otp – Telegram bot sends OTP to forward to WA group
  if (req.url === '/forward_otp') {
    if (!state.otpForwardingOn) {
      res.writeHead(200); res.end(JSON.stringify({ ok: true, skipped: 'forwarding off' }));
      return;
    }
    if (!state.waGroupJid) {
      res.writeHead(200); res.end(JSON.stringify({ ok: false, error: 'no group set' }));
      return;
    }
    const text = String(data.text || '').trim();
    if (!text) {
      res.writeHead(400); res.end(JSON.stringify({ error: 'no text' }));
      return;
    }
    try {
      await sendToWaGroup(text);
      res.writeHead(200); res.end(JSON.stringify({ ok: true }));
    } catch (e) {
      logger.error(`Forward error: ${e.message}`);
      res.writeHead(500); res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // POST /control – admin commands
  if (req.url === '/control') {
    const action = data.action;
    if (action === 'on') {
      if (!state.waGroupJid) {
        res.writeHead(200); res.end(JSON.stringify({ ok: false, error: 'no_group' }));
        return;
      }
      state.otpForwardingOn = true; saveState();
      res.writeHead(200); res.end(JSON.stringify({ ok: true, forwarding: true }));
      return;
    }
    if (action === 'off') {
      state.otpForwardingOn = false; saveState();
      res.writeHead(200); res.end(JSON.stringify({ ok: true, forwarding: false }));
      return;
    }
    if (action === 'set_group') {
      const jid = String(data.jid || '').trim();
      if (!jid || !jid.includes('@')) {
        res.writeHead(400); res.end(JSON.stringify({ error: 'invalid JID' }));
        return;
      }
      state.waGroupJid = jid; saveState();
      res.writeHead(200); res.end(JSON.stringify({ ok: true, jid }));
      return;
    }
    if (action === 'status') {
      const upSec = Math.floor((Date.now() - state.startedAt) / 1000);
      res.writeHead(200); res.end(JSON.stringify({
        ok: true,
        forwarding: state.otpForwardingOn,
        waGroupJid: state.waGroupJid,
        phone: state.linkedPhone,
        connected: sock?.user != null,
        uptime: upSec,
        otpsSent: state.otpsSent,
        otpsReceived: state.otpsReceived,
      }));
      return;
    }
    res.writeHead(400); res.end(JSON.stringify({ error: 'unknown action' }));
    return;
  }

  res.writeHead(404); res.end(JSON.stringify({ error: 'not found' }));
});

server.listen(CONFIG.bridgePort, '0.0.0.0', () => {
  logger.info(`🌐 Bridge HTTP server on port ${CONFIG.bridgePort}`);
  logger.info(`   POST /forward_otp  ← from Python bot`);
  logger.info(`   POST /control      ← admin commands`);
  logger.info(`   GET  /health       ← for Railway`);
});

// ========== START ==========
(async () => {
  console.log(chalk.bold.green('\n╔═══ Crack SMS WA OTP Bridge v2 ═══╗'));
  console.log(chalk.green    ('║   WhatsApp ⇄ Telegram OTP        ║'));
  console.log(chalk.green    ('╚═══════════════════════════════════╝\n'));
  await startWhatsAppBridge();
})();

process.on('SIGINT', async () => {
  logger.info('Shutting down...');
  saveState();
  try { if (sock) sock.end(); } catch (_) {}
  server.close();
  process.exit(0);
});