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
│       ├── electricity.py  # 宿舍用电查询
│       └── booking.py      # 体育场馆预约（booking.fudan.edu.cn）
├── tests/                  # 测试与调试脚本
│   ├── test_phase1_login.py    # 登录流程测试
│   ├── test_phase1_apis.py     # 一卡通 + 用电测试
│   └── test_phase1_booking.py  # 体育场馆预约测试
├── automations/            # Phase 2：定时自动化任务
├── mcp_server/             # Phase 3：MCP Server
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
service = "https://booking.fudan.edu.cn/api/login/cas"
```

## 已实现 API

### 一卡通（`fudan_spider.apis.card`）

```python
from fudan_spider.uis import login
from fudan_spider.apis.card import get_card_info

se = login()
info = get_card_info(se)
# info["balance"]   → 余额（元）
# info["status"]    → 状态
# info["expire"]    → 有效期
# info["campuses"]  → 可用校区列表
```

### 宿舍用电（`fudan_spider.apis.electricity`）

```python
from fudan_spider.apis.electricity import get_electricity_records

rows = get_electricity_records(se)
# rows: [(日期, 宿舍名称, 用电度数), ...]
```

### 体育场馆预约（`fudan_spider.apis.booking`）

```python
from fudan_spider.apis.booking import login_booking, get_resource_list, get_available_slots

booking_se = login_booking(se)                              # booking 独立登录
resources = get_resource_list(booking_se, topic_id=48)      # 场馆列表
slots = get_available_slots(booking_se, resource_id=938)    # 空闲时段
# slots: [{"slot_id", "resource_name", "time", "date"}, ...]
```

## 开发计划

| 阶段 | 内容 | 状态 |
|------|------|------|
| **Phase 1** | UIS 登录、基础 API（一卡通、用电、场馆预约） | ✅ 完成 |
| **Phase 2** | 自动化任务：电量预警、定时通知（GitHub Actions） | 🚧 进行中 |
| **Phase 3** | MCP Server：将校园 API 暴露为 AI 工具 | 📋 待开始 |
