/**
 * terraform.js — Wrapper around Terraform CLI for deploy/destroy/status.
 * All commands run from the infra/ directory.
 */
const { execSync, spawn } = require('child_process');
const config = require('../config');

function runTerraform(args, opts = {}) {
  return new Promise((resolve, reject) => {
    const proc = spawn('terraform', args, {
      cwd: config.infraDir,
      shell: true,
      ...opts,
    });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (d) => {
      stdout += d.toString();
      if (opts.onStdout) opts.onStdout(d.toString());
    });
    proc.stderr.on('data', (d) => {
      stderr += d.toString();
      if (opts.onStderr) opts.onStderr(d.toString());
    });
    proc.on('close', (code) => {
      if (code === 0) resolve(stdout);
      else reject(new Error(`terraform exit ${code}: ${stderr}`));
    });
  });
}

async function deploy(phase) {
  const blocks = config.phases[phase];
  if (!blocks) throw new Error(`Unknown phase: ${phase}`);

  // Update terraform.tfvars blocks list
  // For now, we modify the -var flag directly
  const blockList = blocks.map((b) => `"${b}"`).join(', ');

  await runTerraform(['init', '-upgrade']);
  const output = await runTerraform([
    'apply',
    '-auto-approve',
    `-var=blocks=[${blockList}]`,
  ]);
  return output;
}

async function destroy() {
  return runTerraform(['destroy', '-auto-approve']);
}

function getInstances() {
  try {
    const raw = execSync('terraform output -json instances', {
      cwd: config.infraDir,
      encoding: 'utf-8',
      timeout: 10000,
    });
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function getSSHCommands() {
  try {
    const raw = execSync('terraform output -json ssh_commands', {
      cwd: config.infraDir,
      encoding: 'utf-8',
      timeout: 10000,
    });
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

module.exports = { deploy, destroy, getInstances, getSSHCommands, runTerraform };
