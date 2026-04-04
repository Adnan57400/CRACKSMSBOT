/**
 * whatsapp_otp.js — Crack SMS WhatsApp OTP Bridge
 * ─────────────────────────────────────────────────────────────────
 * PURPOSE:
 *   When an OTP is received by the Python bot (from any panel/IVAS),
 *   the Python bot ALSO calls this bridge to forward the OTP to a
 *   WhatsApp group or channel simultaneously.
 *
 *   Telegram forwarding is UNCHANGED — this is purely additive.
 *
 * COMMANDS (send from the linked WA number):
 *   /otp on       → enable WhatsApp forwarding
 *   /otp off      → disable WhatsApp forwarding
 *   /otp status   → show current status + target group
 *   /otp group <JID>  → set target WA group (e.g. 120363XXXX@g.us)
 *   /otp help     → list all commands
 *
 * HTTP ENDPOINTS (called by Python bot):
 *   POST /forward_otp  → forward a formatted OTP message to WA group
 *   POST /control      → toggle on/off, get status (from Python admin panel)
 *
 * Requirements:
 *   npm install @whiskeysockets/baileys pino node-cache @hapi/boom
 *               fs-extra qrcode-terminal axios chalk
 * ─────────────────────────────────────────────────────────────────
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

const pino      = require('pino');
const NodeCache = require('node-cache');
const { Boom }  = require('@hapi/boom');
const fs        = require('fs-extra');
const path      = require('path');
const qrterm    = require('qrcode-terminal');
const chalk     = require('chalk');
const http      = require('http');

// ══════════════════════════════════════════════════════════════
//  CONFIG
// ══════════════════════════════════════════════════════════════
const CONFIG = {
  sessionDir:  process.env.WA_SESSION_DIR  || path.join(__dirname, 'wa_session'),
  stateFile:   path.join(__dirname, 'wa_bridge_state.json'),
  secret:      process.env.WA_OTP_SECRET   || 'cracksms_wa_secret_2026',
  bridgePort:  parseInt(process.env.WA_BRIDGE_PORT || '7891'),
  reconnectMs: 5000,
};

// ══════════════════════════════════════════════════════════════
//  PERSISTENT STATE
// ══════════════════════════════════════════════════════════════
let state = {
  otpForwardingOn: false,   // WA forwarding toggle
  waGroupJid:      null,    // target WA group/channel JID  e.g. "120363XXXXX@g.us"
  linkedPhone:     null,
  startedAt:       Date.now(),
  otpsSent:        0,
};

function loadState() {
  try {
    if (fs.existsSync(CONFIG.stateFile))
      Object.assign(state, JSON.parse(fs.readFileSync(CONFIG.stateFile, 'utf8')));
  } catch (e) { console.error('State load error:', e.message); }
}

function saveState() {
  try { fs.writeFileSync(CONFIG.stateFile, JSON.stringify(state, null, 2)); }
  catch (e) { console.error('State save error:', e.message); }
}

loadState();

// ══════════════════════════════════════════════════════════════
//  WHATSAPP SOCKET
// ══════════════════════════════════════════════════════════════
let sock      = null;
let isRunning = false;

/**
 * Send a message to the configured WA group.
 * text may contain *bold* and _italic_ (WA markdown).
 */
async function sendToWaGroup(text) {
  if (!sock) throw new Error('WhatsApp not connected');
  if (!state.waGroupJid) throw new Error('No WA group configured. Send /otp group <JID> from your WA.');
  await sock.sendMessage(state.waGroupJid, { text });
  state.otpsSent++;
  saveState();
}

// ── Self-command handler ──────────────────────────────────────
async function handleSelfCommand(jid, text) {
  const t = text.trim();

  if (t === '/otp on') {
    if (!state.waGroupJid) {
      await sock.sendMessage(jid, { text:
        '❌ *No WA group set!*\n\nFirst set a target group:\n`/otp group <JID>`\n\nGet the JID by adding the bot to the group and running\n`/otp getjid`' });
      return;
    }
    state.otpForwardingOn = true;
    saveState();
    await sock.sendMessage(jid, { text:
      '✅ *OTP Forwarding: ON*\n\n' +
      `OTPs will now be sent to:\n\`${state.waGroupJid}\`\n\n` +
      'Telegram forwarding is unchanged.\nSend `/otp off` to stop.' });
    console.log(chalk.green('✅ WA OTP forwarding enabled'));
    return;
  }

  if (t === '/otp off') {
    state.otpForwardingOn = false;
    saveState();
    await sock.sendMessage(jid, { text:
      '🔴 *OTP Forwarding: OFF*\n\nWhatsApp OTP forwarding stopped.\nSend `/otp on` to resume.' });
    console.log(chalk.yellow('🔴 WA OTP forwarding disabled'));
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
      `📨 OTPs sent: ${state.otpsSent}\n` +
      `⏰ Uptime: ${h}h ${m}m` });
    return;
  }

  // /otp group <JID>  — set target WA group
  const groupMatch = t.match(/^\/otp group\s+(.+)/i);
  if (groupMatch) {
    const jidArg = groupMatch[1].trim();
    if (!jidArg.includes('@')) {
      await sock.sendMessage(jid, { text:
        '❌ Invalid JID format.\n\nExamples:\n• Group: `120363XXXXX@g.us`\n• Channel: `120363XXXXX@newsletter`' });
      return;
    }
    state.waGroupJid = jidArg;
    saveState();
    await sock.sendMessage(jid, { text:
      `✅ *WA Target Set*\n\nOTPs will be forwarded to:\n\`${jidArg}\`\n\nNow send \`/otp on\` to start.` });
    console.log(chalk.cyan(`📌 WA target group set: ${jidArg}`));
    return;
  }

  // /otp getjid — get the JID of the current chat
  if (t === '/otp getjid') {
    await sock.sendMessage(jid, { text:
      `📋 *This chat's JID:*\n\`${jid}\`\n\nUse this with:\n\`/otp group ${jid}\`` });
    return;
  }

  if (t === '/otp help') {
    await sock.sendMessage(jid, { text:
      `📋 *WhatsApp OTP Bridge Commands*\n\n` +
      `\`/otp on\`             – Enable WA forwarding\n` +
      `\`/otp off\`            – Disable WA forwarding\n` +
      `\`/otp status\`         – Show current status\n` +
      `\`/otp group <JID>\`    – Set target WA group\n` +
      `\`/otp getjid\`         – Get JID of current chat\n` +
      `\`/otp help\`           – This list\n\n` +
      `_Commands only work from the linked number._` });
    return;
  }
}

async function startWhatsAppBridge() {
  if (isRunning) return;
  isRunning = true;

  await fs.ensureDir(CONFIG.sessionDir);
  console.log(chalk.blue(`🔄 Starting WhatsApp OTP Bridge…\n   Session: ${CONFIG.sessionDir}`));

  const { state: authState, saveCreds } = await useMultiFileAuthState(CONFIG.sessionDir);
  const { version } = await fetchLatestBaileysVersion();
  const msgRetryCache = new NodeCache();

  const browsers = [Browsers.macOS('Chrome'), Browsers.macOS('Safari'), Browsers.windows('Edge')];

  sock = makeWASocket({
    version,
    auth: {
      creds: authState.creds,
      keys:  makeCacheableSignalKeyStore(authState.keys, pino({ level: 'silent' })),
    },
    logger:                        pino({ level: 'silent' }),
    printQRInTerminal:             true,
    browser:                       browsers[Math.floor(Math.random() * browsers.length)],
    msgRetryCounterCache:          msgRetryCache,
    defaultQueryTimeoutMs:         60_000,
    syncFullHistory:               false,
    markOnlineOnConnect:           false,
    generateHighQualityLinkPreview: false,
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      qrterm.generate(qr, { small: true });
      console.log(chalk.yellow('📱 Scan QR → WhatsApp → Linked Devices → Link a Device'));
    }
    if (connection === 'open') {
      state.linkedPhone = (sock.user?.id || '').split(':')[0].split('@')[0];
      saveState();
      console.log(chalk.green(`✅ WA connected! Phone: +${state.linkedPhone}`));
      console.log(chalk.cyan(
        state.waGroupJid
          ? `   Target group: ${state.waGroupJid}`
          : `   ⚠️  No target group set. Send "/otp group <JID>" from this WhatsApp.`
      ));
      console.log(chalk.cyan(`   Forwarding: ${state.otpForwardingOn ? 'ON ✅' : 'OFF 🔴'}`));
    }
    if (connection === 'close') {
      isRunning = false;
      const reason = new Boom(lastDisconnect?.error)?.output?.statusCode;
      if (reason === DisconnectReason.loggedOut) {
        console.log(chalk.red('❌ Logged out. Delete wa_session/ and restart.'));
      } else {
        console.log(chalk.yellow(`⚠️  Disconnected (${reason}). Reconnect in ${CONFIG.reconnectMs / 1000}s…`));
        setTimeout(startWhatsAppBridge, CONFIG.reconnectMs);
      }
    }
  });

  // Only process self-sent messages (commands from linked number)
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const m of messages) {
      if (!m.message || !m.key.fromMe) continue;
      const body =
        m.message?.conversation ||
        m.message?.extendedTextMessage?.text || '';
      if (!body.startsWith('/otp')) continue;
      try { await handleSelfCommand(m.key.remoteJid, body); }
      catch (e) { console.error('Command error:', e.message); }
    }
  });
}

// ══════════════════════════════════════════════════════════════
//  HTTP SERVER — Python bot calls these endpoints
// ══════════════════════════════════════════════════════════════
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', d => { body += d; if (body.length > 50_000) req.destroy(); });
    req.on('end', () => {
      try { resolve(JSON.parse(body)); }
      catch (e) { reject(e); }
    });
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  if (req.method !== 'POST') {
    res.writeHead(405); res.end('Method Not Allowed'); return;
  }

  let data;
  try { data = await parseBody(req); }
  catch (e) { res.writeHead(400); res.end(JSON.stringify({ error: 'bad json' })); return; }

  if (data.secret !== CONFIG.secret) {
    res.writeHead(403); res.end(JSON.stringify({ error: 'forbidden' })); return;
  }

  // ── POST /forward_otp ──────────────────────────────────────
  // Python bot sends formatted OTP text here; bridge forwards to WA group.
  // Fields: secret, text (formatted OTP message in plain text, not HTML)
  if (req.url === '/forward_otp') {
    if (!state.otpForwardingOn) {
      res.writeHead(200); res.end(JSON.stringify({ ok: true, skipped: 'forwarding off' })); return;
    }
    if (!state.waGroupJid) {
      res.writeHead(200); res.end(JSON.stringify({ ok: false, error: 'no group set' })); return;
    }
    const text = String(data.text || '').trim();
    if (!text) {
      res.writeHead(400); res.end(JSON.stringify({ error: 'no text' })); return;
    }
    try {
      await sendToWaGroup(text);
      console.log(chalk.green(`📤 OTP forwarded to WA group: ${state.waGroupJid.slice(0, 15)}…`));
      res.writeHead(200); res.end(JSON.stringify({ ok: true }));
    } catch (e) {
      console.error('Forward error:', e.message);
      res.writeHead(500); res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // ── POST /control ──────────────────────────────────────────
  // Python admin panel: on / off / status / set_group
  if (req.url === '/control') {
    const action = data.action;

    if (action === 'on') {
      if (!state.waGroupJid) {
        res.writeHead(200);
        res.end(JSON.stringify({ ok: false, error: 'no_group', hint: 'Set WA group first' }));
        return;
      }
      state.otpForwardingOn = true; saveState();
      res.writeHead(200); res.end(JSON.stringify({ ok: true, forwarding: true })); return;
    }

    if (action === 'off') {
      state.otpForwardingOn = false; saveState();
      res.writeHead(200); res.end(JSON.stringify({ ok: true, forwarding: false })); return;
    }

    if (action === 'set_group') {
      const jid = String(data.jid || '').trim();
      if (!jid || !jid.includes('@')) {
        res.writeHead(400); res.end(JSON.stringify({ error: 'invalid JID' })); return;
      }
      state.waGroupJid = jid; saveState();
      res.writeHead(200); res.end(JSON.stringify({ ok: true, jid })); return;
    }

    if (action === 'status') {
      const upSec = Math.floor((Date.now() - state.startedAt) / 1000);
      res.writeHead(200); res.end(JSON.stringify({
        ok:          true,
        forwarding:  state.otpForwardingOn,
        waGroupJid:  state.waGroupJid,
        phone:       state.linkedPhone,
        connected:   sock?.user != null,
        uptime:      upSec,
        otpsSent:    state.otpsSent,
      })); return;
    }

    res.writeHead(400); res.end(JSON.stringify({ error: 'unknown action' })); return;
  }

  res.writeHead(404); res.end(JSON.stringify({ error: 'not found' }));
});

server.listen(CONFIG.bridgePort, '127.0.0.1', () => {
  console.log(chalk.cyan(`🌐 Bridge HTTP server on 127.0.0.1:${CONFIG.bridgePort}`));
  console.log(chalk.cyan(`   /forward_otp  ← Python posts OTPs here`));
  console.log(chalk.cyan(`   /control       ← Python admin panel control`));
});

// ══════════════════════════════════════════════════════════════
//  START
// ══════════════════════════════════════════════════════════════
(async () => {
  console.log(chalk.bold.green('\n╔═══ Crack SMS WA OTP Bridge ═══╗'));
  console.log(chalk.green    ('║   Telegram + WhatsApp OTPs    ║'));
  console.log(chalk.green    ('║   Dev: @NONEXPERTCODER        ║'));
  console.log(chalk.green    ('╚═══════════════════════════════╝\n'));
  await startWhatsAppBridge();
})();

process.on('SIGINT', async () => {
  console.log(chalk.yellow('\n👋 Shutting down…'));
  saveState();
  try { if (sock) sock.end(); } catch (_) {}
  server.close();
  process.exit(0);
});
