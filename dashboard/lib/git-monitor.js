/**
 * git-monitor.js — Read block status from git repo (local).
 * Does git pull, reads measurements.json, README.md, lists plots.
 */
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const config = require('../config');

function gitPull() {
  try {
    return execSync('git pull --rebase', {
      cwd: config.projectRoot,
      encoding: 'utf-8',
      timeout: 15000,
    });
  } catch (e) {
    return `pull failed: ${e.message}`;
  }
}

function getRecentCommits(block, n = 5) {
  try {
    return execSync(`git log --oneline -${n} -- blocks/${block}/`, {
      cwd: config.projectRoot,
      encoding: 'utf-8',
      timeout: 5000,
    }).trim().split('\n').filter(Boolean);
  } catch {
    return [];
  }
}

function getBlockStatus(block) {
  const blockDir = path.join(config.blocksDir, block);
  const status = {
    name: block,
    score: null,
    specs: {},
    hasReadme: false,
    readmeLines: 0,
    readmeContent: '',
    plots: [],
    commits: [],
  };

  // measurements.json
  const measPath = path.join(blockDir, 'measurements.json');
  if (fs.existsSync(measPath)) {
    try {
      const meas = JSON.parse(fs.readFileSync(measPath, 'utf-8'));
      status.score = meas.score || null;
      status.specs = Object.fromEntries(
        Object.entries(meas).filter(([k]) => k !== 'score')
      );
    } catch {}
  }

  // README.md
  const readmePath = path.join(blockDir, 'README.md');
  if (fs.existsSync(readmePath)) {
    status.hasReadme = true;
    const content = fs.readFileSync(readmePath, 'utf-8');
    status.readmeContent = content;
    status.readmeLines = content.split('\n').length;
  }

  // Plots
  const plotsDir = path.join(blockDir, 'plots');
  if (fs.existsSync(plotsDir)) {
    status.plots = fs.readdirSync(plotsDir)
      .filter((f) => /\.(png|svg|jpg|pdf)$/i.test(f))
      .sort();
  }

  // Git commits
  status.commits = getRecentCommits(block);

  return status;
}

function getAllBlockStatuses() {
  gitPull();
  return config.allBlocks.map(getBlockStatus);
}

module.exports = { gitPull, getBlockStatus, getAllBlockStatuses, getRecentCommits };
