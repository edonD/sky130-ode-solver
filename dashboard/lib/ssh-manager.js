/**
 * ssh-manager.js — SSH connection pool + tmux session management.
 * Each block gets an SSH connection. WebSocket messages are piped to/from the SSH shell.
 */
const { Client } = require('ssh2');
const fs = require('fs');
const config = require('../config');

// Active connections: block -> { conn, stream }
const connections = {};

/**
 * Connect to an instance and attach to its tmux session.
 * Returns a duplex stream (stdin/stdout of the remote shell).
 */
function connectToBlock(block, ip, onData, onClose) {
  return new Promise((resolve, reject) => {
    if (connections[block]) {
      // Already connected — reuse
      resolve(connections[block].stream);
      return;
    }

    const conn = new Client();
    const privateKey = fs.readFileSync(config.sshKeyPath);

    conn.on('ready', () => {
      // Open a PTY shell and attach to tmux
      conn.shell({ term: 'xterm-256color', cols: 200, rows: 50 }, (err, stream) => {
        if (err) return reject(err);

        connections[block] = { conn, stream, ip };

        stream.on('data', (data) => onData(data));
        stream.on('close', () => {
          delete connections[block];
          onClose();
        });

        // Attach to tmux or start a fresh shell
        stream.write(`tmux attach -t ${block} 2>/dev/null || bash\n`);

        resolve(stream);
      });
    });

    conn.on('error', (err) => {
      delete connections[block];
      reject(err);
    });

    conn.connect({
      host: ip,
      port: 22,
      username: config.sshUser,
      privateKey,
      readyTimeout: 10000,
    });
  });
}

/**
 * Disconnect from a block's instance.
 */
function disconnect(block) {
  const entry = connections[block];
  if (entry) {
    entry.stream.end();
    entry.conn.end();
    delete connections[block];
  }
}

/**
 * Resize the PTY for a block.
 */
function resize(block, cols, rows) {
  const entry = connections[block];
  if (entry && entry.stream) {
    entry.stream.setWindow(rows, cols, 0, 0);
  }
}

/**
 * Send data (keystrokes) to a block's SSH session.
 */
function write(block, data) {
  const entry = connections[block];
  if (entry && entry.stream) {
    entry.stream.write(data);
  }
}

/**
 * Run a single command on an instance via SSH (non-interactive).
 */
function execOnInstance(ip, command) {
  return new Promise((resolve, reject) => {
    const conn = new Client();
    const privateKey = fs.readFileSync(config.sshKeyPath);

    conn.on('ready', () => {
      conn.exec(command, (err, stream) => {
        if (err) return reject(err);
        let output = '';
        stream.on('data', (d) => (output += d.toString()));
        stream.stderr.on('data', (d) => (output += d.toString()));
        stream.on('close', () => {
          conn.end();
          resolve(output);
        });
      });
    });

    conn.on('error', reject);

    conn.connect({
      host: ip,
      port: 22,
      username: config.sshUser,
      privateKey,
      readyTimeout: 10000,
    });
  });
}

function getConnectedBlocks() {
  return Object.keys(connections);
}

module.exports = { connectToBlock, disconnect, resize, write, execOnInstance, getConnectedBlocks };
