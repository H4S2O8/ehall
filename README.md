# ehall - 复旦校园自动化工具集

基于复旦大学统一身份认证（UIS/CAS），封装校园常用 API，支持自动化脚本与 MCP Server。

## 项目结构

```
ehall/
├── fudan_spider/           # 核心库（各期复用）
│   ├── uis.py              # UIS 统一身份认证
│   ├── utils.py            # 公共工具（Bark 通知等）
│   └── apis/               # 各类 API 封装
│       ├── card.py         # 一卡通
│       └── electricity.py  # 宿舍用电
├── tests/                  # Phase 1：测试脚本
│   └── test_phase1_login.py
├── automations/            # Phase 2：定时自动化任务
├── mcp_server/             # Phase 3：MCP Server
│   └── server.py
├── .env.example
├── requirements.txt
└── README.md
```

## 开发计划

| 阶段 | 内容 |
|------|------|
| **Phase 1** | UIS 登录、基础 API 测试脚本 |
| **Phase 2** | 自动化任务：电量预警、定时通知（GitHub Actions） |
| **Phase 3** | MCP Server：将校园 API 暴露为 AI 工具 |

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖（需安装 uv）
uv sync

# 2. 配置账号
cp .env.example .env
# 编辑 .env，填入学号和密码

# 3. 运行测试
uv run python -m tests.test_phase1_login
uv run python -m tests.test_phase1_apis
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `fudan_username` | 复旦学号 |
| `fudan_password` | UIS 密码 |
| `BARK_URL` | Bark 推送地址（可选） |
