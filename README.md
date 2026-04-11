# ehall - 复旦校园自动化工具集

基于复旦大学统一身份认证（BambooCloud IDP + CAS），封装校园常用 API，支持自动化脚本与 MCP Server。

## 项目结构

```
ehall/
├── fudan_spider/           # 核心库
│   ├── uis.py              # 统一身份认证（id.fudan.edu.cn）
│   ├── utils.py            # 公共工具（Bark 通知等）
│   └── apis/               # 各类 API 封装
│       ├── card.py         # 一卡通余额查询
│       ├── electricity.py  # 宿舍用电记录（my.fudan.edu.cn）
│       ├── zlapp_electric.py  # 宿舍剩余电量（zlapp.fudan.edu.cn）
│       └── booking.py      # 体育场馆预约（booking.fudan.edu.cn）
├── tests/                  # 测试与调试脚本
│   ├── test_phase1_login.py    # 登录流程测试
│   ├── test_phase1_apis.py     # 一卡通 + 用电测试
│   └── test_phase1_booking.py  # 体育场馆预约测试
├── automations/            # 定时自动化任务
├── mcp_server/             # MCP Server
│   └── server.py
├── pyproject.toml
├── .env.example
└── README.md
```

## 快速开始

```bash
# 1. 安装依赖（需先安装 uv）
uv sync

# 2. 配置账号
cp .env.example .env
# 编辑 .env，填入学号、密码（及可选 TOTP 密钥）

# 3. 运行测试
uv run python -m tests.test_phase1_login    # 登录
uv run python -m tests.test_phase1_apis     # 一卡通 + 用电
uv run python -m tests.test_phase1_booking  # 体育场馆预约
```

## 环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `fudan_username` | 复旦学号 | ✅ |
| `fudan_password` | UIS 密码 | ✅ |
| `fudan_otp_secret` | TOTP 动态口令密钥（base32），开启 MFA 的账号必填 | 视账号而定 |
| `fudan_phone` | 手机号（活动室预约必填） | 视场馆而定 |
| `fudan_major` | 专业（活动室预约必填，内容随意） | 视场馆而定 |
| `fudan_email` | 邮箱（活动室预约必填） | 视场馆而定 |
| `fudan_activity_desc` | 活动简介（如 `打台球`） | 视场馆而定 |
| `fudan_application_file` | 申请表扫描件路径（可选，不填则上传占位图片） | 可选 |
| `BARK_URL` | Bark 推送地址，用于手机通知 | 可选 |

> **关于 TOTP 密钥**：在 [id.fudan.edu.cn](https://id.fudan.edu.cn) → 个人中心 → 安全设置 → 动态口令 中绑定，绑定时记录 base32 密钥填入 `fudan_otp_secret`。

## 认证流程

复旦统一认证使用 **BambooCloud IDP + CAS** 链式 MFA：

```
GET  /authserver/login          → lck token
POST /authn/queryAuthMethods    → authChainCode
POST /authn/getJsPublicKey      → RSA 公钥（加密密码）
POST /authn/authExecute         → 密码认证（返回 requestNumber）
POST /authn/authExecute         → TOTP 认证 → loginToken
POST /authCenter/authnEngine    → 解析 HTML 提取 CAS ticket URL
GET  https://my.fudan.edu.cn/?ticket=ST-xxx  → 完成 CAS 兑换
```

不同子系统（如 booking）通过各自的 CAS service URL 换取独立 session：

```python
# booking.fudan.edu.cn 使用独立 CAS service
service = "https://booking.fudan.edu.cn/reservation/api/login/cas"
```

## MCP Server

将场馆预约 API 封装为 MCP Tools，供 Claude Desktop / Cursor / Windsurf 等支持 MCP 协议的 AI 客户端调用。

支持两种部署模式：
- **本地模式（stdio）**：MCP Client 直接启动子进程，适合个人开发机使用
- **远端模式（SSE）**：Server 部署在云服务器，MCP Client 通过 HTTP 连接，适合多设备共享

---

### 部署方式一：本地 stdio（单机使用）

账号信息和服务进程均在本地，MCP Client 直接调起。

**1. 克隆并安装**

```bash
git clone https://github.com/H4S2O8/ehall.git
cd ehall
uv sync --extra mcp
cp .env.example .env  # 填入学号、密码等（见"环境变量"一节）
```

**2. 配置 Claude Desktop**

配置文件：
- macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows：`%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "fudan-booking": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "python", "-m", "mcp_server.server"],
      "cwd": "/path/to/ehall"
    }
  }
}
```

> 账号信息写在 `cwd` 目录下的 `.env` 文件中，无需在配置里明文填写。如果不想使用 `.env`，也可以在配置中加 `"env": { ... }` 块直接注入环境变量。

**3. 配置 Cursor**

在项目根目录创建 `.cursor/mcp.json`，内容同上（或使用 Cursor 设置面板的 MCP Servers 栏）。

---

### 部署方式二：远端 SSE（多设备共享）

Server 运行在远程机器（VPS / 云服务器），本地 MCP Client 通过 HTTP 连接，账号信息只存在服务端。

#### 服务端部署

```bash
# 1. 克隆并安装
git clone https://github.com/H4S2O8/ehall.git
cd ehall
uv sync --extra mcp
cp .env.example .env  # 填入账号信息

# 2. 启动 SSE Server（默认监听 0.0.0.0:8000）
uv run --extra mcp python -m mcp_server.server --transport sse

# 指定端口
uv run --extra mcp python -m mcp_server.server --transport sse --port 9000

# 仅监听本地（配合 Nginx 反代时使用）
uv run --extra mcp python -m mcp_server.server --transport sse --host 127.0.0.1 --port 8000
```

**使用 systemd 保持后台运行（Linux）**

```ini
# /etc/systemd/system/fudan-mcp.service
[Unit]
Description=Fudan Booking MCP Server
After=network.target

[Service]
WorkingDirectory=/path/to/ehall
ExecStart=uv run --extra mcp python -m mcp_server.server --transport sse --port 8000
Restart=on-failure
EnvironmentFile=/path/to/ehall/.env

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now fudan-mcp
```

**（可选）Nginx 反代 + HTTPS**

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";   # SSE 需要保持长连接
        proxy_buffering off;
        proxy_cache off;
    }
}
```

#### 客户端配置

在 MCP Client 中填写 SSE endpoint URL，无需在本地部署代码或写账号信息：

**Claude Desktop**

```json
{
  "mcpServers": {
    "fudan-booking": {
      "type": "sse",
      "url": "http://your-server-ip:8000/sse"
    }
  }
}
```

**Cursor**（`.cursor/mcp.json`）

```json
{
  "mcpServers": {
    "fudan-booking": {
      "type": "sse",
      "url": "http://your-server-ip:8000/sse"
    }
  }
}
```

> 若配置了 HTTPS，将 `http://` 替换为 `https://` 并使用对应域名。

---

### 可用 Tools

**校园卡 & 宿舍用电**

| Tool | 参数 | 说明 |
|------|------|------|
| `card_get_info` | — | 查询一卡通余额、状态、有效期、可用校区 |
| `electricity_get_records` | `length=10` | 查询宿舍近期用电记录（最多 100 条） |
| `electricity_get_remaining` | — | 查询宿舍当前剩余电量（度），含已用 / 总量 |
| `electricity_get_recharge_history` | `limit=10` | 查询电费充值历史记录 |

**体育场馆（TOPIC_ID=48）**

| Tool | 参数 | 说明 |
|------|------|------|
| `sports_list_venues` | — | 查询所有体育场馆列表，返回 id / name |
| `sports_get_availability` | `resource_id`, `days=3` | 查询指定场馆未来 N 天空闲时段 |
| `sports_book` | `group_id`, `sub_resource_ids`, `period_id`, `date`, `phone?`, `number?` | 预约体育场馆时段 |
| `sports_cancel` | `reserve_id?` | 取消体育场馆预约（不传则取消最近一条） |

**江湾生活园区台球室（新光华悦动馆）**

| Tool | 参数 | 说明 |
|------|------|------|
| `billiards_get_availability` | `days=3` | 查询台球室未来 N 天空闲时段 |
| `billiards_book` | `period_id`, `date`, `major?`, `email?`, `phone?`, `activity_desc?`, `application_file?` | 预约台球室并自动提交 workflow5 审批表单 |
| `billiards_cancel` | `reserve_id?` | 取消台球室预约（不传则取消最近一条） |

> 标 `?` 的参数可省略，省略时自动读取服务端 `.env` 中对应变量。

### 返回值说明

所有预约 tool 在以下情况下不抛异常，而是返回结构化结果：

| `reason` | 含义 |
|----------|------|
| `not_in_service_time` | 当前不在系统受理时间（体育场馆受理窗口：07:00–24:00） |
| `existing_reservation` | 已有未结束的预约，需先取消后再预约 |
