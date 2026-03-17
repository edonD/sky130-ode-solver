# ODE Solver Agent Dashboard

Web-based control panel for deploying and monitoring autonomous analog design agents on AWS.

## What It Does

- **One-click deploy/destroy** — spins up EC2 instances via Terraform
- **Live terminal panels** — horizontally scrollable tmux sessions from each instance, streamed via SSH + xterm.js
- **Agent status** — shows which blocks are running, their score, latest commit, README preview
- **Multi-instance view** — open/close terminal panels, resize, scroll between them
- **Git monitor** — pulls latest commits and shows README + plots from each block

## Architecture

```
Browser                          Node.js Server
┌─────────────────────────┐     ┌──────────────────────────┐
│                         │     │                          │
│  [Deploy Phase 1]       │     │  POST /api/deploy        │
│  [Deploy Phase 2]       │────▶│    → terraform apply     │
│  [Destroy All]          │     │                          │
│                         │     │  POST /api/destroy       │
│  Status bar:            │     │    → terraform destroy   │
│  gm-cell ● integrator ● │     │                          │
│  multiplier ●           │     │  GET /api/status         │
│                         │     │    → terraform output    │
│  ┌───────┐┌───────┐┌──┐│     │    → git log per block   │
│  │ term  ││ term  ││  ││     │                          │
│  │gm-cell││integr.││..││ ws  │  WS /terminal/:block     │
│  │       ││       ││  ││◄───▶│    → ssh2 to instance    │
│  │ tmux  ││ tmux  ││  ││     │    → tmux attach         │
│  │attach ││attach ││  ││     │                          │
│  └───────┘└───────┘└──┘│     │  GET /api/readme/:block  │
│  ◄── horizontal scroll──▶│     │    → git pull + read     │
│                         │     │                          │
│  README preview panel   │     │  GET /api/plots/:block   │
│  [block selector]       │     │    → serve plot images   │
│  rendered markdown +    │     │                          │
│  inline plot images     │     └──────────────────────────┘
└─────────────────────────┘
```

## Tech Stack

| Layer | Tech | Why |
|-------|------|-----|
| Terminal emulation | xterm.js + xterm-addon-fit | Industry standard, same as VS Code |
| SSH tunnel | ssh2 (Node.js) | Pure JS SSH client, no native deps |
| WebSocket | ws | Bridges ssh2 streams to browser |
| Backend | Express.js | Simple REST + WS server |
| Frontend | Vanilla JS + CSS Grid | No framework needed, keeps it fast |
| Deploy | Terraform CLI (shelled out) | Already set up in ../infra/ |
| Markdown | marked.js | Render README in browser |
| Status | git CLI (shelled out) | Pull commits, read measurements.json |

## Pages / Views

### 1. Deploy View
- Phase selector (Phase 1 / Phase 2 / Phase 3)
- Deploy button → runs terraform, shows progress
- Instance status cards with IPs
- Destroy button with confirmation

### 2. Terminal View (main)
- Horizontally scrollable strip of terminal panels
- Each panel = one xterm.js instance connected via WebSocket to an SSH session
- Click panel header to maximize / restore
- Auto-connects to `tmux attach -t <block>` on the instance
- New terminal button (opens raw SSH shell to the instance)

### 3. Monitor View
- Block cards showing: score, specs passed, latest commit, README preview
- Plot gallery per block (thumbnails, click to expand)
- Auto-refreshes via git pull

## API Endpoints

```
POST /api/deploy          { phase: 1|2|3 }  → runs terraform apply
POST /api/destroy         → runs terraform destroy
GET  /api/status          → { instances: { block: { ip, state } }, git: { commits } }
GET  /api/blocks          → [ { name, score, specs_passed, plots: [...] } ]
GET  /api/readme/:block   → raw markdown
GET  /api/plots/:block/:file → serves png
WS   /terminal/:block     → bidirectional SSH stream
POST /api/agent/start/:block → starts claude agent in tmux
POST /api/agent/stop/:block  → kills tmux session
```

## File Structure

```
dashboard/
├── server.js              ← Express + WebSocket server
├── package.json
├── config.js              ← SSH key path, infra dir, project root
├── lib/
│   ├── terraform.js       ← terraform apply/destroy/output wrappers
│   ├── ssh-manager.js     ← SSH connection pool + tmux attach
│   └── git-monitor.js     ← git pull, read measurements, list plots
├── public/
│   ├── index.html         ← SPA entry point
│   ├── style.css          ← CSS Grid layout, terminal panels, dark theme
│   └── js/
│       ├── app.js         ← Main app controller
│       ├── deploy.js      ← Deploy/destroy UI
│       ├── terminals.js   ← xterm.js panel manager
│       └── monitor.js     ← Block status + README viewer
└── README.md
```

## Key Design Decisions

- **No React/Vue** — vanilla JS is enough for this. Fewer deps, faster to build, no build step.
- **Dark theme** — matches terminal aesthetic, easier on eyes for long monitoring sessions.
- **Horizontal scroll** — CSS scroll-snap for smooth panel switching. Each panel is viewport-width or configurable.
- **SSH key from config** — reads `~/.ssh/schemato-key.pem` path from config.js, never hardcoded.
- **Terraform path** — points to `../infra/` directory, runs terraform from there.
- **Git operations** — runs in `../` (project root), does `git pull` before reading READMEs/plots.

## Running

```bash
cd dashboard
npm install
node server.js
# Open http://localhost:3000
```

## Security Notes

- Runs locally only (localhost:3000) — no auth needed
- SSH key path configured in config.js, never exposed to browser
- Terraform credentials come from AWS CLI profile / env vars
- GitHub token only used server-side for git operations
