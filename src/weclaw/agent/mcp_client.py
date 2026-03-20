import argparse
import asyncio
import json
import logging
import os
import re
import sys
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client


def expand_env_vars(value: str) -> str:
    """展开字符串中的环境变量引用。

    支持 $VAR_NAME 格式（VAR 为字母开头，包含字母数字下划线）。
    如果环境变量不存在，保持原样不替换。
    """
    def replace_var(match: re.Match) -> str:
        var_name = match.group(1)
        return os.getenv(var_name, match.group(0))

    pattern = r'\$([A-Za-z_][A-Za-z0-9_]*)'
    return re.sub(pattern, replace_var, value)


def parse_arguments(args_str: str | None) -> dict[str, Any]:
    """解析命令参数，仅支持 JSON 格式。

    支持的格式：
    - JSON 字符串：'{"city": "北京", "count": 5}'

    会自动去除外层可能被 shell 保留的单引号。
    """
    if not args_str:
        return {}

    raw = args_str.strip()
    # 去除可能被 Windows shell 保留的外层单引号
    if raw.startswith("'") and raw.endswith("'"):
        raw = raw[1:-1]

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(
            f"JSON 参数必须是对象格式，但收到了 {type(parsed).__name__}。"
        )
    except json.JSONDecodeError as e:
        raise ValueError(
            f"无法解析 JSON 参数: {e}。"
            f"请使用 JSON 格式，如: '{{\"key\": \"value\"}}'"
        ) from e


class MCPClient:
    """MCP 客户端，使用官方 SDK 通过 SSE 连接远程 MCP 服务器。"""

    def __init__(self, base_url: str, api_key: str, extra_headers: dict[str, str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.extra_headers = extra_headers or {}
        self.session: ClientSession | None = None
        self._client_context = None
        self._http_client = None

    def _is_sse_url(self) -> bool:
        """判断 URL 是否使用 SSE 传输方式（URL 路径中包含 'sse'）。"""
        from urllib.parse import urlparse
        path = urlparse(self.base_url).path.lower()
        # 路径中包含 /sse 或以 /sse 结尾
        return "/sse" in path

    async def __aenter__(self):
        """异步上下文管理器入口。"""
        # 构建认证 headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        # 合并自定义 headers（可覆盖默认 Authorization）
        headers.update(self.extra_headers)
        
        transport = "SSE" if self._is_sse_url() else "Streamable HTTP"
        try:
            # 根据 URL 选择传输方式：包含 sse 使用 SSE，否则使用 Streamable HTTP
            if self._is_sse_url():
                logging.info(f"使用 SSE 传输方式连接: {self.base_url}")
                self._client_context = sse_client(self.base_url, headers=headers)
            else:
                logging.info(f"使用 Streamable HTTP 传输方式连接: {self.base_url}")
                self._http_client = create_mcp_http_client(headers=headers)
                self._client_context = streamable_http_client(self.base_url, http_client=self._http_client)
            
            streams = await self._client_context.__aenter__()
            # SSE 返回 (read, write)，Streamable HTTP 返回 (read, write, get_session_id)
            read_stream, write_stream = streams[0], streams[1]
            
            # 创建会话
            self.session = ClientSession(read_stream, write_stream)
            await self.session.__aenter__()
            
            # 初始化连接
            await self.session.initialize()
            logging.info(f"MCP 会话已初始化: {self.base_url}")
        except Exception as e:
            # 连接失败时给出明确的错误提示，不打印完整异常栈
            error_type = type(e).__name__
            raise ConnectionError(
                f"MCP 服务连接失败 [{transport}]: {self.base_url} — {error_type}: {e}"
            ) from None
        
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出。"""
        try:
            if self.session:
                await self.session.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logging.debug(f"关闭 session 时出错: {e}")
        try:
            if self._client_context:
                await self._client_context.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logging.debug(f"关闭 client context 时出错: {e}")
        try:
            if self._http_client:
                await self._http_client.aclose()
        except Exception as e:
            logging.debug(f"关闭 http client 时出错: {e}")

    async def list_tools(self) -> list[dict[str, Any]]:
        """列出所有可用工具。"""
        if not self.session:
            raise RuntimeError("客户端未初始化，请使用 async with MCPClient(...) as client")
        
        result = await self.session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """调用指定工具。"""
        if not self.session:
            raise RuntimeError("客户端未初始化，请使用 async with MCPClient(...) as client")
        
        try:
            result = await self.session.call_tool(name, arguments=arguments or {})
        except Exception as e:
            error_type = type(e).__name__
            raise RuntimeError(
                f"MCP 工具调用失败: tool={name}, error={error_type}: {e}"
            ) from None
        
        # 检查服务端是否返回了 isError 标志
        if getattr(result, 'isError', False):
            error_texts = [c.text for c in result.content if hasattr(c, 'text')]
            raise RuntimeError(
                f"MCP 工具 '{name}' 返回错误: {' | '.join(error_texts) if error_texts else '未知错误'}"
            )
        
        # 返回结构化输出（如果有）或文本内容
        if hasattr(result, 'structuredContent') and result.structuredContent:
            return result.structuredContent
        
        # 返回文本内容
        contents = []
        for content in result.content:
            if hasattr(content, 'text'):
                contents.append(content.text)
            elif hasattr(content, 'data'):
                contents.append(f"<binary data: {len(content.data)} bytes>")
        
        return contents if len(contents) > 1 else (contents[0] if contents else None)

    async def list_resources(self) -> list[dict[str, Any]]:
        """列出所有可用资源。"""
        if not self.session:
            raise RuntimeError("客户端未初始化，请使用 async with MCPClient(...) as client")
        
        result = await self.session.list_resources()
        return [
            {
                "uri": str(resource.uri),
                "name": resource.name,
                "description": resource.description,
            }
            for resource in result.resources
        ]

    async def read_resource(self, uri: str) -> Any:
        """读取指定资源。"""
        if not self.session:
            raise RuntimeError("客户端未初始化，请使用 async with MCPClient(...) as client")
        
        from pydantic import AnyUrl
        result = await self.session.read_resource(AnyUrl(uri))
        
        contents = []
        for content in result.contents:
            if hasattr(content, 'text'):
                contents.append(content.text)
            elif hasattr(content, 'blob'):
                contents.append(f"<binary: {len(content.blob)} bytes>")
        
        return contents if len(contents) > 1 else (contents[0] if contents else None)


# 示例用法
async def main():
    parser = argparse.ArgumentParser(description="MCP 客户端命令行工具")
    parser.add_argument("--base-url", "-u", required=True, help="MCP 服务器 URL")
    parser.add_argument("--api-key", "-k", required=True, help="API key 的环境变量名（如 DASHSCOPE_API_KEY），程序会自动从环境变量中读取实际值")
    parser.add_argument("--header", "-H", action="append", default=[], help="自定义 HTTP 头，格式为 key=value（可多次指定），如 -H a=b -H c=d")
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # list-tools 命令
    subparsers.add_parser("list-tools", help="列出所有可用工具")
    
    # call_command 命令
    call_parser = subparsers.add_parser("call_command", help="调用指定命令")
    call_parser.add_argument("command_name", help="命令名称")
    call_parser.add_argument("--args", "-a", type=str, help="命令参数，JSON 格式字符串（如 '{\"city\": \"北京\", \"count\": 5}'）", default=None)

    # list-resources 命令
    subparsers.add_parser("list-resources", help="列出所有可用资源")
    
    # read-resource 命令
    read_parser = subparsers.add_parser("read-resource", help="读取指定资源")
    read_parser.add_argument("uri", help="资源 URI")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # 从环境变量名解析出实际的 API key
    api_key = os.getenv(args.api_key) or args.api_key
    if api_key == args.api_key:
        logging.warning(f"环境变量 {args.api_key} 未设置，将直接使用传入的值作为 API key")

    # 解析自定义 headers
    extra_headers = {}
    for h in args.header:
        if "=" not in h:
            print(f"Error: invalid header format: '{h}'. Expected key=value format (e.g. X-Custom=value).", file=sys.stderr)
            sys.exit(1)
        key, _, value = h.partition("=")
        extra_headers[key.strip()] = expand_env_vars(value.strip())

    async with MCPClient(
        base_url=args.base_url,
        api_key=api_key,
        extra_headers=extra_headers,
    ) as client:
        try:
            if args.command == "list-tools":
                tools = await client.list_tools()
                print(json.dumps(tools, ensure_ascii=False, indent=2))
                
            elif args.command == "call_command":
                try:
                    tool_args = parse_arguments(args.args)
                except ValueError as e:
                    print(f"Error: invalid command arguments: {e}", file=sys.stderr)
                    sys.exit(1)
                
                result = await client.call_tool(args.command_name, tool_args)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                
            elif args.command == "list-resources":
                resources = await client.list_resources()
                print(json.dumps(resources, ensure_ascii=False, indent=2))
                
            elif args.command == "read-resource":
                content = await client.read_resource(args.uri)
                print(json.dumps(content, ensure_ascii=False, indent=2))
                
        except ConnectionError as e:
            # 连接类错误：信息已在 __aenter__ 中格式化，直接输出
            print(f"连接错误: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            error_type = type(e).__name__
            print(f"执行失败 [{error_type}]: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
