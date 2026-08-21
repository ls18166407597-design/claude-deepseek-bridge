# ccds-bridge — Claude 桌面版 ↔ 全厂商大模型本地桥接与缓存稳定化插件

<p align="center">
  <a href="README_en.md">English</a> | <b>简体中文</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/Version-0.1.50-brightgreen.svg" alt="Version">
  <img src="https://img.shields.io/badge/Prompt_Cache-99%25%2B-orange.svg" alt="Cache Rate">
  <img src="https://img.shields.io/badge/Thinking-100%25_Preserved-purple.svg" alt="Thinking">
  <img src="https://img.shields.io/badge/Platform-macOS_%7C_Windows-blueviolet.svg" alt="Platform">
</p>

> **让 Claude 桌面版（Code 模式）无缝接入 DeepSeek V4 / 小米 MiMO 等第三方大模型，稳定保持 99%+ 前缀缓存命中率，无损保留完整思维链（Thinking），首字毫秒级响应，API 费用降低 90%！**

---

## 🌟 核心特性与技术亮点

- **⚡ 字节级前缀稳定化（锁定上下文基准，99%+ 命中率）**：
  - **`tool_result` 确定性排序**：对并发工具调用返回的 `tool_result` 消息严格按 `tool_use_id` 字典序排序，彻底消除异步 I/O 完成先后不确定性导致的缓存抖动；
  - **`tools.sort` + `input_schema` 规范化**：对 MCP 工具列表按名称排序，并对 JSON Schema 强制 `sort_keys=True` 重新序列化，确保字节级一致；
  - **`date_pin`（首日日期锁定）**：锁定会话第 1 次创建的日期，彻底消除跨天对话导致的全球全量缓存击穿；
  - **`billing_header` 统一固化**：固定计费上下文头，防止客户端版本变化打乱缓存。
- **🧠 纯无状态思维链与折叠智能拼回（On-demand Hydration & Un-folding）**：
  - 客户端闲置清空内存 thinking，或在多轮交互中微折叠历史记录；
  - 本插件采用**极简无状态架构**：正常请求 **0 毫秒纯内存放行**；当且仅当检测到截断或 thinking 丢失时，**仅耗时 5ms 直读 Claude 本地原生 `.jsonl` 历史底稿**，精准对齐结构指纹并逐字节拼回，**绝不阉割思维链，推理深度完整保留**！
- **🛡️ 物理分界线驱动的上下文压缩（AST Compact Boundary）**：
  - 彻底告别脆弱的关键词盲猜，以转录本原生 `compact_boundary` 物理事件为准，支持单次与多次连续压缩自动截断，平滑重置新基准线，旧历史永不越界误回填。
- **🧹 动态系统消息与环境提醒指纹免疫（System Reminder Stripping）**：
  - 自动剥离客户端在内存中动态注入的 `<system-reminder>` 瞬态环境小纸条，确保网络请求指纹与本地磁盘底稿 100% 精准对齐匹配，杜绝意外击穿。
- **🛡️ 探测请求本地秒回拦截**：
  - 客户端启动时发出的 `max_tokens=1` 探测请求由本地网关直接应答，**不上云、不扣费、响应 0 毫秒**。
- **🔌 3P 设置即插即用（全自动接管）**：
  - 无需手动修改任何底层 CLI 配置文件；只需在 3P 界面填入真实供应商地址与 Key，插件开会话时**自动检测、自动备份并自动接入本地网关**。
- **📊 专属状态监控面板（`/cc-status` 或 `/ccds-status`）**：
  - 在对话框输入 `/cc-status` 即可查看当前会话的实时命中率、上下文 Token 长度、主对话与子代理独立统计、掉落告警，以及自动探测的 OpenCode 额度或 DeepSeek 官方余额。

---

## 🚀 从零开始保姆级完整配置指南（适合全新安装）

无论您使用的是 **macOS** 还是 **Windows**，只需按照以下 5 个步骤，即可在不登录官方账号的前提下，完整搭建好基于 DeepSeek / OpenCode 的极致编程环境。

---

### 第一步：初次开启开发者模式（macOS & Windows 双平台）

下载安装 **Claude Desktop** 后（**无需登录任何官方账号**，停留在初始界面即可），按以下步骤开启 3P 开发者模式：

#### 1. 首次激活 Developer Mode
- 🍎 **macOS 用户**：
  - 在系统顶部菜单栏点击 **Help（帮助） ➔ Troubleshooting ➔ Enable Developer Mode**；
  - 点击后客户端会**自动重启**，重启后即正式激活 3P 开发者环境。
- 🪟 **Windows 用户**：
  - 在应用窗口左上角点击汉堡菜单 **☰（或菜单栏） ➔ Help ➔ Troubleshooting ➔ Enable Developer Mode**；
  - 点击后客户端会**自动重启**并进入 3P 开发者模式。

---

### 第二步：打开 3P（第三方推理）配置面板

客户端重启后，可通过以下 **两种极简方式（任选其一）** 打开配置弹窗：

- 🎯 **方式 A（双平台通用，最快捷）**：
  点击应用左下角的 **个人账号/昵称区域** ➔ 在弹出菜单中直接点击 **`🌐 Inference configuration`**（推理配置）；
- 💻 **方式 B（系统菜单栏）**：
  - **macOS**：系统顶部菜单栏点击 **Claude ➔ Configure Third-Party Inference...**；
  - **Windows**：应用顶部菜单栏点击 **Developer ➔ Configure Third-Party Inference...**。

---

### 第三步：配置 Connection（连接与模型列表）

在弹出的 **Configure third-party inference** 窗口中，默认停留在左侧 **Connection** 功能区：

#### 1. 基础连接凭据配置
- **Gateway base URL**：填入您的真实供应商基础地址或自建中转端点（例如 `https://api.deepseek.com` 或 `https://opencode.ai/zen/go` 或您的代理端点）；
  > **⚠️ 重点避坑**：**末尾千万不要带 `/v1/messages`**！客户端发请求时会自动拼接该路径，填了会导致路径变成 `/v1/messages/v1/messages` 报 404 错误！
- **Gateway API key**：填入与该地址配对的有效 API Key（如 `sk-...`）；
- **Gateway auth scheme**：保持默认 `x-api-key`。

#### 2. Claude 桌面端内部模型命名与工具链激活机制说明（避免 3P 校验拦截）
根据对客户端接口行为与兼容性的实测验证，客户端内部写死了一段针对非 Anthropic 竞品名称的强校验正则表达式：

*(已根据客户端接口规范进行合规化命名映射)*

- **拦截表现**：若模型 `name` 命中上述任何关键字（例如直接填 `claude-mimo-5` 或 `deepseek-v4`），3P 界面会直接弹出红字报错：*`Doesn’t look like an Anthropic model`* 并拒绝保存！
- **优雅规避策略**：我们在模型 ID（`name`）中使用**合规、干净、能望文生义且符合品牌词过滤规则的别名**，在显示名称（`labelOverride`）中自由展示真实厂商名字。

#### 3. 官方白名单模型推荐表（全量激活 87 工具与顶级 Agent 规范）

在下方的 **MODELS** 区域添加您需要使用的模型 ID（别名须符合客户端命名规范）：

| 3P 界面填写的 Model ID (`name`) | 映射转发的真实上游模型 | 场景说明 |
|---|---|---|
| **`claude-sonnet-5`** | `deepseek-v4-flash` | ⚡ 日常高速编码，支持 1M 上下文（强烈推荐） |
| **`claude-opus-5`** | `deepseek-v4-pro` | 🧠 复杂架构与深度推理，支持 1M 上下文 |
| **`claude-sonnet-4-8`** | `x-preview-f-free` | 🎁 Ox Alpha Free 100万长上下文推理（完全免费） |
| **`claude-sonnet-4-6`** | `mimo-v2.5` | 📱 小米 MiMO 2.5 全能版（满血 Agent 工具链） |
| **`claude-opus-4-6`** | `mimo-v2.5-pro` | 📱 小米 MiMO 2.5 Pro 旗舰版 |

> 需要更多模型（如 Kimi、GLM、MiniMax）？在对话中输入 `/cc-config-add <别名> <目标模型>` 即可添加，无需改代码。

---

### 第四步：配置 Workspace 出网白名单（必须填 `*`，防止网络 403）

> **⚠️ 核心必设项**：Claude 桌面端自带严格的网络沙箱，默认拦截所有非 Anthropic 域名。如果不配置，会导致 Python 执行、`pip install`、网页抓取工具以及访问网关时全部报 **403 拒绝访问**！

1. 在当前配置弹窗左侧菜单中，点击 **`Workspace`**；
2. 在右侧面板中找到 **`Allowed egress hosts`** 输入框；
3. 输入一个星号 **`*`**（星号代表放行所有外部工具出网请求与 API 调用）；
4. 其他功能区（Connectors、Limits、Appearance 等）保持默认即可；
5. 点击窗口右下角的 **`Apply Changes`（应用更改）** 保存配置！

---

### 第五步：重启客户端并安装 `ccds-bridge` 插件

1. **重启应用**：完全退出并重新启动一次 Claude 桌面端；
2. **打开插件中心**：点击进入 **Plugins** 管理页面；
3. **添加市场源**：点击 **Add marketplace**，在输入框中填入：
   ```text
   https://github.com/ls18166407597-design/claude-model-bridge
   ```
4. **安装插件**：在列表中找到 **ccds-bridge** 插件，点击 **Install（安装）**；
5. **两步激活**：
   - ① 安装完成后，**新建一个 Code 会话**发送任意一句话（插件的 `SessionStart` 钩子会在后台自动将真实上游地址记录并重定向至本地守护网关）；
   - ② **再次完全退出并重启一次 Claude 应用**，让本地网关正式全面接管！

---

### 第六步：验证运行效果与状态查看

1. 在对话框发送任意编程问题（例如：`请帮我用 Python 实现一个快速排序算法`）；
2. 随后在对话框输入命令：
   ```text
   /cc-status
   ```
   （或 `/ccds-status`）；
3. 界面将呈现如下格式的实时统计面板：
   ```text
   ======================================================
    会话: b45f4540-5535-4181-8...
   ------------------------------------------------------
    缓存命中: 99%（极佳）· 近5轮: 99% →
    上下文: 145K · 请求: 223 次（上游 9 · 本地拦截 214）
    分类:     主对话 9
    异常: 无
   ------------------------------------------------------
    OpenCode: 5h 1% · 周 0% · 月 0%
   ======================================================
   ```

---

## 🔍 技术对比：本插件与普通代理方案的区别

| 对比维度 | 社区普通反向代理 / 简易脚本 | 本项目 (`ccds-bridge`) |
|---|---|---|
| **思维链 (Thinking) 保留** | 为避开报错，粗暴地**剥离/删除 thinking 块**（严重损耗模型代码质量与推理深度） | **按需直读回填 (Hydration)**：完整保留 Thinking 与 Signature 签名，推理深度毫无损耗 |
| **消息折叠恢复 (Un-folding)** | 遇到客户端微折叠导致历史截断，直接击穿缓存全量重算 | **结构指纹自动缝合**：无论折叠 1 条还是 10 条，从原生底稿中 5ms 精准无损拼回 |
| **持久化与架构开销** | 引入数据库或生成海量重复快照文件，占满磁盘且重启易丢状态 | **极简无状态 (Stateless)**：直接以 Claude 原生 `.jsonl` 为真理底稿，0ms 快速路径，零重复存储 |
| **跨天缓存保护** | 跨天后因日期变更导致缓存 100% 被击穿 | **`date_pin` 会话首日锁定**：跨天续聊前缀完全一致，稳稳命中缓存 |
| **并发工具乱序** | 并发调用 Read/Bash 结果返回先后随机，导致前缀哈希抖动击穿 | **确定性全序排序**：对 `tool_result` 严格按 ID 字典序排序，保证多次请求字节级一致 |
| **动态系统提醒 (<system-reminder>)** | 客户端内存动态插入时间/环境提醒，导致指纹比对失败并击穿缓存 | **动态标签自动剥离**：纯净指纹免疫，确保与磁盘底稿 100% 绝对精准对齐 |
| **对话压缩 (/compact)** | 遇到 `/compact` 产生死锁或误拼旧历史导致超出窗口崩溃 | **物理分界线自动截断**：底层精准感知 `compact_boundary`，平滑重置新基准线，永不越界误拼回旧历史 |

---

## 🛠️ 常见问题排查（FAQ）

### Q1: 提示 503 `未配置上游` 怎么办？
- **原因**：3P 的 Gateway base URL 已被写为本地网关地址（`http://127.0.0.1:<PORT>`），但本地尚未记录真实上游地址。
- **解决**：在 3P 设置里把 Gateway base URL 改回你的真实供应商地址（如 `https://opencode.ai/zen/go`），保存后应用会自动重启；然后新开一个会话，插件就会重新完成自动接管。

### Q2: 切换供应商或更换 API Key 怎么操作？
- 直接在 Claude 的 3P 设置中修改你的 Base URL 或 Key 并保存。插件在下次开会话时会自动捕获并同步更新。

### Q3: 插件更新后，需要重新打开新对话吗？
- **插件代码更新需要重启**：本地网关会在插件更新后自动重启（`SessionStart` 钩子检测代码路径变化），当前会话的下一条消息即可使用新版本逻辑。如果自动重启未生效，完全退出并重启 Claude 桌面端即可。

---

## 📄 开源协议

本项目遵循 [MIT 许可证](LICENSE) 开源。代码完全本地运行，零外部依赖，安全透明。
