/**
 * server.js — Express + WebSocket server for the agent dashboard.
 *
 * REST API for deploy/destroy/status.
 * WebSocket for live terminal streaming via SSH.
 */
const express = require('express');
const http = require('http');
const { WebSocketServer } = require('ws');
const path = require('path');
const url = require('url');
const config = require('./config');
const terraform = require('./lib/terraform');
const sshManager = require('./lib/ssh-manager');
const gitMonitor = require('./lib/git-monitor');

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ noServer: true });

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Serve plot images from blocks
app.use('/plots', express.static(config.blocksDir));

// --- REST API ---

app.get('/api/status', (req, res) => {
  const instances = terraform.getInstances();
  const blocks = gitMonitor.getAllBlockStatuses();
  res.json({ instances, blocks });
});

app.get('/api/blocks', (req, res) => {
  const blocks = gitMonitor.getAllBlockStatuses();
  res.json(blocks);
});

app.get('/api/readme/:block', (req, res) => {
  const status = gitMonitor.getBlockStatus(req.params.block);
  res.json({ content: status.readmeContent, lines: status.readmeLines });
});

app.get('/api/instances', (req, res) => {
  res.json(terraform.getInstances());
});

app.post('/api/deploy', async (req, res) => {
  const phase = req.body.phase || 1;
  try {
    const output = await terraform.deploy(phase);
    const instances = terraform.getInstances();
    res.json({ ok: true, instances, output });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post('/api/destroy', async (req, res) => {
  try {
    await terraform.destroy();
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post('/api/agent/start/:block', async (req, res) => {
  const block = req.params.block;
  const instances = terraform.getInstances();
  const ip = instances[block];
  if (!ip) return res.status(404).json({ error: `No instance for ${block}` });

  try {
    const output = await sshManager.execOnInstance(ip,
      `cd ~/workspace/sky130-ode-solver/blocks/${block} && bash start.sh 2>&1 | tail -5`
    );
    res.json({ ok: true, output });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post('/api/agent/stop/:block', async (req, res) => {
  const block = req.params.block;
  const instances = terraform.getInstances();
  const ip = instances[block];
  if (!ip) return res.status(404).json({ error: `No instance for ${block}` });

  try {
    const output = await sshManager.execOnInstance(ip, `tmux kill-session -t ${block} 2>&1`);
    res.json({ ok: true, output });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

// --- WebSocket terminal ---

server.on('upgrade', (request, socket, head) => {
  const pathname = url.parse(request.url).pathname;
  const match = pathname.match(/^\/terminal\/(.+)$/);

  if (match) {
    wss.handleUpgrade(request, socket, head, (ws) => {
      const block = match[1];
      handleTerminalConnection(ws, block);
    });
  } else {
    socket.destroy();
  }
});

async function handleTerminalConnection(ws, block) {
  const instances = terraform.getInstances();
  const ip = instances[block];

  if (!ip) {
    ws.send(`\r\nNo instance found for block: ${block}\r\n`);
    ws.close();
    return;
  }

  try {
    const stream = await sshManager.connectToBlock(
      block,
      ip,
      (data) => {
        if (ws.readyState === ws.OPEN) {
          ws.send(data);
        }
      },
      () => {
        if (ws.readyState === ws.OPEN) {
          ws.send('\r\n[SSH connection closed]\r\n');
          ws.close();
        }
      }
    );

    ws.on('message', (msg) => {
      const str = msg.toString();
      // Handle resize messages
      try {
        const parsed = JSON.parse(str);
        if (parsed.type === 'resize') {
          sshManager.resize(block, parsed.cols, parsed.rows);
          return;
        }
      } catch {}
      // Regular input
      sshManager.write(block, str);
    });

    ws.on('close', () => {
      sshManager.disconnect(block);
    });
  } catch (e) {
    ws.send(`\r\nSSH connection failed: ${e.message}\r\n`);
    ws.close();
  }
}

// --- Start ---

server.listen(config.port, () => {
  console.log(`Dashboard running at http://localhost:${config.port}`);
});
