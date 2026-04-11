"""
MCP Server - 复旦校园服务工具集
Phase 3: 将 fudan_spider 的各类 API 封装为 MCP Tools，
         供 Claude Desktop / Cursor 等客户端调用。

TODO:
  - tool: uis_login       登录并缓存 Session
  - tool: get_card_info   查询一卡通余额
  - tool: get_electricity 查询宿舍用电
  - tool: get_bus         查询校车班次
  - tool: get_empty_rooms 查询空教室
"""

# 依赖: pip install mcp
# 启动: python -m mcp_server.server

# from mcp.server.fastmcp import FastMCP
# from fudan_spider.uis import login
# from fudan_spider.apis.card import get_card_info
# from fudan_spider.apis.electricity import get_electricity

# app = FastMCP("fudan-campus")
# ...
