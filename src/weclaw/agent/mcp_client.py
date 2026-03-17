import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client


def parse_arguments(args_list: list[str] | None) -> dict[str, Any]:
    """解析命令参数，支持 JSON 格式和 key=value 格式。

    支持的格式：
    1. JSON 格式（单个字符串）：'{"city": "北京"}'
    2. key=value 格式（多个参数）：city=北京 count=5
    3. 混合格式时优先尝试 JSON 解析

    key=value 格式中，值会自动进行类型推断：
    - 纯数字 -> int/float
    - true/false -> bool
    - 其他 -> str
    """
    if not args_list:
        return {}

    # 如果只有一个参数，先尝试作为 JSON 解析
    if len(args_list) == 1:
        raw = args_list[0]
        # 去除可能被 Windows shell 保留的外层单引号
        if raw.startswith("'") and raw.endswith("'"):
            raw = raw[1:-1]
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        # JSON 解析失败，当作单个 key=value 处理
        if "=" in raw:
            args_list = [raw]
        else:
            raise ValueError(
                f"Invalid argument format: '{raw}'. "
                "Use JSON format '{\"key\": \"value\"}' or key=value format 'key=value'."
            )

    # key=value 格式解析
    result = {}
    for item in args_list:
        if "=" not in item:
            raise ValueError(
                f"Invalid argument: '{item}'. Expected key=value format (e.g. city=北京)."
            )
        key, _, value = item.partition("=")
        key = key.strip()
        value = value.strip()

        # 类型推断
        if value.lower() == "true":
            result[key] = True
        elif value.lower() == "false":
            result[key] = False
        else:
            try:
                result[key] = int(value)
            except ValueError:
                try:
                    result[key] = float(value)
                except ValueError:
                    result[key] = value

    return result


class MCPClient:
    """MCP 客户端，使用官方 SDK 通过 SSE 连接远程 MCP 服务器。"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session: ClientSession | None = None
        self._client_context = None

    async def __aenter__(self):
        """异步上下文管理器入口。"""
        # 直接使用官方 SSE 客户端，传入认证 headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        
        # 使用官方 SSE 客户端连接
        self._client_context = sse_client(self.base_url, headers=headers)
        read_stream, write_stream = await self._client_context.__aenter__()
        
        # 创建会话
        self.session = ClientSession(read_stream, write_stream)
        await self.session.__aenter__()
        
        # 初始化连接
        await self.session.initialize()
        logging.info(f"MCP 会话已初始化: {self.base_url}")
        
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出。"""
        if self.session:
            await self.session.__aexit__(exc_type, exc_val, exc_tb)
        if self._client_context:
            await self._client_context.__aexit__(exc_type, exc_val, exc_tb)

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
        
        result = await self.session.call_tool(name, arguments=arguments or {})
        
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
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # list-tools 命令
    subparsers.add_parser("list-tools", help="列出所有可用工具")
    
    # call_command 命令
    call_parser = subparsers.add_parser("call_command", help="调用指定命令")
    call_parser.add_argument("command_name", help="命令名称")
    call_parser.add_argument("--args", "-a", nargs="*", help="命令参数，支持 JSON 格式或 key=value 格式（如 city=北京 count=5）", default=[])

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

    async with MCPClient(
        base_url=args.base_url,
        api_key=api_key,
    ) as client:
        try:
            if args.command == "list-tools":
                tools = await client.list_tools()
                print(json.dumps(tools, ensure_ascii=False, indent=2))
                
            elif args.command == "call_command":
                try:
                    tool_args = parse_arguments(args.args)
                except (json.JSONDecodeError, ValueError) as e:
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
                
        except Exception as e:
            print(f"错误: {e}", file=sys.stderr)
            logging.exception("执行失败")
            sys.exit(1)


if __name__ == "__main__":
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
