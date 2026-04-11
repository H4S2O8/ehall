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
| `fudan_major` | 专业代码（如 `081200`，活动室预约必填） | 视场馆而定 |
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

所有功能均为纯 requests 实现，无需浏览器依赖。

```python
from fudan_spider.uis import login
from fudan_spider.apis.booking import (
    login_booking,
    get_resource_list, get_available_slots,
    get_calendar, launch_resource,
    fill_workflow_form, cancel_reserve,
)

# 登录
uis_se = login()
se = login_booking(uis_se)  # 复用 UIS session，只做一次 CAS 换取

# 查询场馆列表 / 空闲时段（体育馆类，如羽毛球）
resources = get_resource_list(se, topic_id=48)
slots = get_available_slots(se, resource_id=938)

# 查询活动室类场馆（如 id=751 江湾生活园区学生活动中心）
cal = get_calendar(se, resource_id=751, date="2026-04-13")
# cal["time_slots"]    → 时段列表
# cal["sub_resources"] → 子场地列表
# cal["availability"]  → 占用情况 {日期: {场地id: {时段id: {status, ...}}}}

# 提交预约（活动室类，返回 process_id 用于后续填表）
result = launch_resource(se, resource_id=759, period_id=3319, date="2026-04-13")
reserve_id = result["process_id"]

# 填写 workflow5 申请表并提交（纯 requests）
fill_workflow_form(
    uis_session=uis_se,
    reserve_id=reserve_id,
    major="081200",
    email="xxx@m.fudan.edu.cn",
    phone="138xxxxxxxx",
    activity_desc="打台球，1人",
    detail_info="多功能厅 2026-04-13 20:00-22:00",  # 预约信息描述
    application_file="/path/to/申请表.pdf",           # 可选
)

# 取消预约（取消所有可取消的，或指定 appointment_id）
cancel_reserve(se)
cancel_reserve(se, appointment_id=800919)
```

#### 台球室全流程示例

```bash
uv run python tests/debug_pure_requests.py
```

脚本会自动完成：登录 → 查询明日时段 → 发起预约 → 提交 workflow5 表单 → 取消预约。

## 开发计划

| 阶段 | 内容 | 状态 |
|------|------|------|
| **Phase 1** | UIS 登录、基础 API（一卡通、用电、场馆预约） | ✅ 完成 |
| **Phase 2** | 移除 Playwright 依赖，改为纯 requests 实现；定时自动化任务 | ✅ 完成 |
| **Phase 3** | MCP Server：将校园 API 暴露为 AI 工具 | 📋 待开始 |
