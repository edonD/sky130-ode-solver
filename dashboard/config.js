const path = require('path');
const os = require('os');

module.exports = {
  // Server
  port: 3000,

  // Paths
  projectRoot: path.resolve(__dirname, '..'),
  infraDir: path.resolve(__dirname, '..', 'infra'),
  blocksDir: path.resolve(__dirname, '..', 'blocks'),

  // SSH
  sshKeyPath: path.join(os.homedir(), '.ssh', 'schemato-key.pem'),
  sshUser: 'ubuntu',

  // Phases → block names
  phases: {
    1: ['gm-cell', 'integrator', 'multiplier'],
    2: ['lorenz-core'],
    3: ['integration'],
  },

  // All blocks in order
  allBlocks: ['gm-cell', 'integrator', 'multiplier', 'lorenz-core', 'integration'],
};
