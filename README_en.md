# ccds-bridge — Claude Desktop ↔ Any LLM Local Bridge & Prompt Cache Stabilization

<p align="center">
  <b>English</b> | <a href="README.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Version-0.1.52-brightgreen.svg" alt="Version">
  <img src="https://img.shields.io/badge/Prompt_Cache-99%25%2B-orange.svg" alt="Cache Rate">
  <img src="https://img.shields.io/badge/Thinking-100%25_Preserved-purple.svg" alt="Thinking">
  <img src="https://img.shields.io/badge/Platform-macOS_%7C_Windows-blueviolet.svg" alt="Platform">
</p>

> **Connect Claude Desktop (Code & Cowork modes) seamlessly to DeepSeek / OpenCode / Any third-party LLM while maintaining a 99%+ Prompt Cache Hit Rate, 100% intact Thinking blocks, millisecond first-token response, and cutting API costs by up to 90%!**

---

## 🌟 Key Features & Architectural Innovations

- **🔌 Zero-Config Philosophy (Dual-Mode Plug-and-Play)**:
  - Built with a strict **"transparent, seamless, plug-and-play"** design principle: 100% compliant with standard native Anthropic protocols without burdening the client with complex setting UIs;
  - **Full Dual-Mode Support**: Seamlessly supports both Claude Desktop **Code Mode** and **Cowork (Code Work / Multi-Agent) Mode** with independent subagent tracing and statistics.
- **⚡ Byte-Level Deterministic Prefix Stabilization (99%+ Cache Hit Rate)**:
  - **`tool_result` Deterministic Sorting**: Sorts parallel tool execution results strictly by `tool_use_id` lexicographical order in `role: "user"` content blocks, eliminating cache drops caused by asynchronous I/O completion jitter;
  - **`tools.sort` + `input_schema` Canonicalization**: Canonicalizes MCP tool schemas with `sort_keys=True` and sorts tools alphabetically for strict byte-level prefix invariance;
  - **`date_pin` (Session Anchor)**: Pins the original session creation date across multi-day conversations, preventing global cache misses caused by daily timestamp roll-overs (with built-in `date_pin_regex_miss` defense alerts);
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
- **🛣️ Ecosystem Roadmap: Custom-Engineered OpenAI Protocol Translation for Claude Code**:
  - **Background**: Most mainstream LLMs (open-source and third-party commercial models) natively support only the **OpenAI Chat completions** protocol, whereas Claude Desktop (Code mode) strictly mandates the **Anthropic Messages** protocol with specialized thinking blocks, tool signatures, and streaming constraints;
  - **Custom Translation Engine**: To bridge this gap, we custom-engineered a high-availability **heterogeneous protocol translation engine** specifically adapted for Claude Code (featuring lossless thinking restoration, stream token synchronization, and full tool calling), currently verified on private backend servers;
  - **Future Roadmap**: To preserve the local plugin's lightweight and zero-configuration design, the plugin currently functions purely as a standard client-side gateway. Depending on community feedback and demand, we plan to release this specialized Claude Code translation engine as a standalone open-source gateway script or an optional built-in module. Stay tuned!

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

Empirical compatibility testing reveals two key client-side validation rules for Model IDs:

1. **Rule 1: Third-Party Brand Name Filter**
   - Claude Desktop filters Model IDs containing third-party vendor brand names (such as `deepseek`, `openai`, `mimo`, `qwen`, etc.), showing a naming validation error in the UI.

2. **Rule 2: Capability Tier & Advanced Toolchain Activation (Crucial Caveat)**
   - Claude Desktop determines agent capability based on the Model ID format;
   - **If the Model ID does not follow the standard `claude-sonnet-...` or `claude-opus-...` pattern**, the client treats it as a basic lightweight model and **silently disables core Agent coding tools (missing the 87+ tool suite and degrading into basic chat)**.

> 💡 **Best Practice**: Use our recommended whitelist aliases (such as `claude-sonnet-5`, `claude-sonnet-4-8`), which pass the name validation cleanly while **fully unlocking the 87+ Agent toolchain**!

#### 3. Recommended Whitelist Models Table (Full 87+ Toolchain Unlocked)

In the **Model list** section, click **+ Add** to add the recommended models. Expanding each item reveals the precise roles of the three key fields:

1. **Model ID (Internal Identifier)**: **Must follow the official whitelist format** (e.g. `claude-sonnet-5`, `claude-sonnet-4-8`), ensuring compliance with client-side naming rules and unlocking the full 87+ Agent toolchain;
2. **Display name (UI Label)**: **Recommended to enter the actual upstream model name** (e.g. `DeepSeek V4 Flash`, `Xiaomi MiMO 2.5`, `Ox Alpha Free`), or any custom name of your choice (purely visual in the model picker dropdown and does not affect backend routing);
3. **Offer 1M-context variant (1M Context Toggle)**: **Recommended to toggle ON** (provides a 1-Million token context option in the model picker, unleashing extreme long-context reasoning).

| Model ID (`name`)<br>*(Official Whitelist Format)* | Display name (`labelOverride`)<br>*(Upstream Name or Custom)* | Offer 1M-context<br>*(1M Context)* | Actual Upstream Model | Description & Use Case |
|---|---|:---:|---|---|
| **`claude-sonnet-5`** | `DeepSeek V4 Flash` | ✅ ON | `deepseek-v4-flash` | ⚡ Ultra-fast daily coding, 87+ tools unlocked (Recommended) |
| **`claude-opus-5`** | `DeepSeek V4 Pro` | ✅ ON | `deepseek-v4-pro` | 🧠 Complex architecture & deep reasoning, 87+ tools unlocked |
| **`claude-sonnet-4-8`** | `Ox Alpha Free` | ✅ ON | `x-preview-f-free` | 🎁 1M ultra-long context reasoning (Free preview) |
| **`claude-sonnet-4-6`** | `Xiaomi MiMO 2.5` | ✅ ON | `mimo-v2.5` | 📱 Xiaomi MiMO 2.5 All-Rounder (Multi-modal agent toolchain) |
| **`claude-opus-4-6`** | `Xiaomi MiMO 2.5 Pro` | ✅ ON | `mimo-v2.5-pro` | 📱 Xiaomi MiMO 2.5 Pro Flagship |

> 💡 **Configure Once, Enjoy Forever**: Add all 5 models during initial setup. You can switch freely between them in the model picker dropdown without touching configuration again!
> Map additional custom models anytime via `/cc-config-add <alias> <target-model>` in chat.

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

## 🛠️ Frequently Asked Questions (FAQ)

### Q1: 503 `Unconfigured Upstream` error?
- **Cause**: Gateway base URL was set to `http://127.0.0.1:<PORT>` before the local config recorded the true upstream URL.
- **Solution**: Re-enter your true provider Base URL (e.g. `https://opencode.ai/zen/go`) in 3P settings. The app will restart, and the plugin will auto-capture it upon the next conversation turn.

### Q2: Gateway not running after computer reboot? (Auto Wake-up)
- **Symptom**: After restarting macOS/Windows, the background local gateway (port 8789) is not running initially.
- **Zero-Effort Auto Wake-up (Recommended)**:
  - **Simply send any message in any chat box (even a single character or press Enter)**;
  - The plugin's built-in `UserPromptSubmit` hook **instantly detects and launches the local gateway & watchdog in 100ms**, fully restoring connectivity!
- **Manual CLI Management (Alternative)**:
  ```bash
  python3 scripts/manager.py start    # Start gateway
  python3 scripts/manager.py status   # Check status and prompt cache rate
  python3 scripts/manager.py restart  # Restart gateway
  ```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE). Runs 100% locally with zero external telemetry.
