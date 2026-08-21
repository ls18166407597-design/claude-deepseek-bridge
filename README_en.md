# ccds-bridge — Claude Desktop ↔ Any LLM Local Bridge & Prompt Cache Stabilization

<p align="center">
  <b>English</b> | <a href="README.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Version-0.1.50-brightgreen.svg" alt="Version">
  <img src="https://img.shields.io/badge/Prompt_Cache-99%25%2B-orange.svg" alt="Cache Rate">
  <img src="https://img.shields.io/badge/Thinking-100%25_Preserved-purple.svg" alt="Thinking">
  <img src="https://img.shields.io/badge/Platform-macOS_%7C_Windows-blueviolet.svg" alt="Platform">
</p>

> **Connect Claude Desktop (Code mode) seamlessly to third-party LLMs like DeepSeek V4 / Xiaomi MiMO / OpenCode while maintaining a 99%+ Prompt Cache Hit Rate, 100% intact Thinking blocks, millisecond first-token response, and cutting API costs by up to 90%!**

---

## 🌟 Key Features & Architectural Innovations

- **⚡ Byte-Level Deterministic Prefix Stabilization (99%+ Cache Hit Rate)**:
  - **`tool_result` Deterministic Sorting**: Sorts parallel tool execution results strictly by `tool_use_id` lexicographical order in `role: "user"` content blocks, eliminating cache drops caused by asynchronous I/O completion jitter;
  - **`tools.sort` + `input_schema` Canonicalization**: Canonicalizes MCP tool schemas with `sort_keys=True` and sorts tools alphabetically for strict byte-level prefix invariance;
  - **`date_pin` (Session Anchor)**: Pins the original session creation date across multi-day conversations, preventing global cache misses caused by daily timestamp roll-overs;
  - **Billing Header Fixation**: Locks system billing context to prevent client version changes from invalidating the Radix tree prefix.
- **🧠 Zero-Loss Thinking Hydration & History Un-folding**:
  - Claude Desktop strips `thinking` blocks from memory when idle (>1h) or compacts historical messages;
  - `ccds-bridge` employs a **stateless, zero-overhead architecture**: standard turns pass through in **0ms (pure in-memory)**. When missing thinking or folding is detected, it reads Claude's native on-disk `.jsonl` transcript in **5ms**, reconstructs structural fingerprints, and rehydrates full thinking chains—**zero degradation in model reasoning depth**!
- **🛡️ AST-Driven Compact Boundary Truncation (`/compact`)**:
  - Replaces fragile keyword matching with native `compact_boundary` system events in the transcript. Supports multiple consecutive compactions, establishing clean new cache baselines without leaking pre-compaction history into active contexts.
- **🧹 Dynamic System Reminder Stripping (`<system-reminder>`)**:
  - Strips transient `<system-reminder>` blocks injected into in-memory payloads by the client UI, ensuring a 100% exact structural match with persistent on-disk transcripts.
- **🛡️ Local Probe Interception (0ms / 0 Token)**:
  - Startup probe requests (`max_tokens=1`) are answered locally by the gateway without forwarding upstream, saving costs and latency.
- **📊 Real-time Diagnostics HUD (`/cc-status` / `/ccds-status`)**:
  - Built-in slash command displays instant prompt cache hit rate, context tokens, upstream vs intercepted calls, cache drop alerts, and live OpenCode / DeepSeek balance probes.

---

## 🚀 Step-by-Step Installation Guide (macOS & Windows)

No official Anthropic account login is required. Follow these 5 steps to get up and running:

---

### Step 1: Enable Developer Mode

Launch **Claude Desktop** (no login required, stay on the landing screen):

- 🍎 **macOS**: Click **Help ➔ Troubleshooting ➔ Enable Developer Mode** in the top menu bar. The app will restart automatically.
- 🪟 **Windows**: Click **☰ (Menu) ➔ Help ➔ Troubleshooting ➔ Enable Developer Mode**. The app will restart automatically.

---

### Step 2: Open 3P Inference Configuration

After restart, open the configuration modal via either method:
- 🎯 **Method A (Quickest)**: Click the **User Account / Avatar area** in the bottom-left corner ➔ Click **`🌐 Inference configuration`**.
- 💻 **Method B (Menu Bar)**:
  - macOS: **Claude ➔ Configure Third-Party Inference...**
  - Windows: **Developer ➔ Configure Third-Party Inference...**

---

### Step 3: Configure Connection & Models

In the **Connection** tab:

#### 1. Basic Credentials
- **Gateway base URL**: Enter your provider endpoint (e.g., `https://api.deepseek.com` or `https://opencode.ai/zen/go` or your custom proxy).
  > **⚠️ Note**: Do **NOT** include `/v1/messages` at the end! Claude Desktop automatically appends `/v1/messages`.
- **Gateway API key**: Enter your API key (`sk-...`).
- **Gateway auth scheme**: Leave as default (`x-api-key`).

#### 2. Client Model Naming & Agent Toolchain Activation Guide
Claude Desktop includes an internal naming filter rules regex that blocks competitors' brand names (`deepseek`, `mimo`, `qwen`, `openai`, etc.). Use clean whitelist aliases in the Model ID (`name`), and set your preferred display name in `labelOverride`:

| Model ID (`name`) in 3P Settings | Mapped Upstream Model | Description |
|---|---|---|
| **`claude-sonnet-5`** | `deepseek-v4-flash` | ⚡ Ultra-fast daily coding, 1M context (Recommended) |
| **`claude-opus-5`** | `deepseek-v4-pro` | 🧠 Deep architectural reasoning, 1M context |
| **`claude-sonnet-4-8`** | `x-preview-f-free` | 🎁 Ox Alpha Free 1M context reasoning (Free tier) |
| **`claude-sonnet-4-6`** | `mimo-v2.5` | 📱 Xiaomi MiMO 2.5 Generalist Agent |
| **`claude-opus-4-6`** | `mimo-v2.5-pro` | 📱 Xiaomi MiMO 2.5 Pro Flagship |

---

### Step 4: Configure Workspace Network Egress (`*`)

> **⚠️ Required**: Claude Desktop's security sandbox blocks all external domain traffic by default. If not configured, Bash execution, `pip install`, and local gateway requests will fail with **403 Forbidden**.

1. In the configuration modal, click **`Workspace`** in the left menu;
2. Find **`Allowed egress hosts`**;
3. Enter an asterisk: **`*`** (allows all external tool network requests);
4. Click **`Apply Changes`** in the bottom-right corner.

---

### Step 5: Install `ccds-bridge` Plugin

1. **Restart Claude Desktop** completely;
2. Click **Plugins** in the UI;
3. Click **Add marketplace**, and enter:
   ```text
   https://github.com/ls18166407597-design/claude-model-bridge
   ```
4. Find **ccds-bridge** in the list and click **Install**;
5. **Activate**:
   - Create a new **Code** session and send any initial message (the plugin automatically hooks the upstream endpoint in the background);
   - Restart Claude Desktop once more for the local gateway daemon to take full effect!

---

### Step 6: Verify with `/cc-status`

Send a prompt in chat, then type:
```text
/cc-status
```
You'll see the live HUD:
```text
======================================================
 Session: b45f4540-5535-4181-8...
------------------------------------------------------
 Cache Hit Rate: 99% (Excellent) · Last 5 turns: 99% →
 Context: 145K · Requests: 223 (Upstream 9 · Intercepted 214)
 Type:    Main Chat 9
 Alerts:  None
------------------------------------------------------
 OpenCode: 5h 1% · W 0% · M 0%
======================================================
```

---

## 🔍 Technical Comparison: Generic Proxies vs `ccds-bridge`

| Feature | Generic Reverse Proxies / Lite Scripts | `ccds-bridge` |
|---|---|---|
| **Thinking Preservation** | Strips/deletes thinking blocks to avoid errors (destroys reasoning depth) | **On-demand Hydration**: 100% intact Thinking & Signatures with zero reasoning loss |
| **History Un-folding** | Client micro-folding causes cache drops and full recalculations | **Structural Fingerprint Stitching**: Restores folded turns from native `.jsonl` in 5ms |
| **State & Storage Overhead** | Heavy databases / redundant snapshot dumps filling disk | **Stateless**: Uses Claude's native `.jsonl` transcript directly with 0ms fast-path |
| **Multi-day Caching** | Date changes across midnight cause 100% cache invalidation | **`date_pin` Session Anchoring**: Keeps cross-day prefixes strictly invariant |
| **Parallel Tool Ordering** | Asynchronous tool completion order jitter causes cache misses | **Deterministic Full Sorting**: Sorts `tool_result` by ID for byte-level determinism |
| **System Reminders (<system-reminder>)** | Dynamic runtime reminder tags break fingerprint matching | **Transient Tag Stripping**: Clean fingerprint extraction immune to UI injections |
| **Context Compaction (/compact)** | Deadlocks or erroneously repends 500k old history | **AST Boundary Truncation**: Truncates cleanly at `compact_boundary` events |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE). Runs 100% locally with zero external telemetry.
