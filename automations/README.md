# automations

存放定时/自动化脚本，独立于 MCP server 运行。

---

## auto_book.py — 自动预约场馆

在指定时间（建议每天 07:00）自动查询明天目标场馆的空闲时段并提交预约。

### 配置（写入项目根目录的 `.env`）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BOOK_VENUE_TYPE` | 场馆类型：`sports`（体育场馆）或 `activity`（活动室） | `sports` |
| `BOOK_RESOURCE_ID` | 父场馆 ID（见下方"如何查询 ID"） | **必填** |
| `BOOK_SUB_IDS` | 子场地 ID 列表，逗号分隔（`sports` 模式用，留空则自动选） | 空 |
| `BOOK_PREFER_TIMES` | 期望时段，逗号分隔，如 `18:00-20:00,20:00-22:00` | 任意空闲 |
| `BOOK_DATE_OFFSET` | 预约哪天，相对今天的偏移天数 | `1`（明天） |
| `BOOK_NUMBER` | 预约人数 | `1` |
| `BOOK_MAX_RETRIES` | 失败重试次数 | `3` |
| `BOOK_RETRY_INTERVAL` | 重试间隔（秒） | `30` |

`activity` 模式还会读取 `fudan_major`、`fudan_email`、`fudan_phone`、`fudan_activity_desc`、`fudan_application_file`（均已在根目录 `.env.example` 中说明）。

### 如何查询场馆 ID

```python
# 在项目根目录执行
from dotenv import load_dotenv; load_dotenv()
from fudan_spider.apis.booking import login_booking, get_resource_list

se = login_booking()
for r in get_resource_list(se):
    print(r["id"], r["name"])
```

### 手动运行

```bash
cd /path/to/ehall
uv run python automations/auto_book.py
```

### 定时运行（crontab）

```crontab
# 每天 07:00 整点运行（根据服务器开放时间自行调整）
0 7 * * * cd /path/to/ehall && uv run python automations/auto_book.py >> /tmp/auto_book.log 2>&1
```

### 定时运行（CodeBuddy Automation）

在 CodeBuddy 中创建 Automation，Prompt 填：

```
Run: uv run python automations/auto_book.py
Working directory: /path/to/ehall
```

Schedule: `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;BYHOUR=7;BYMINUTE=5`

### 通知

设置 `BARK_URL` 后，预约成功/失败均会推送到手机。
