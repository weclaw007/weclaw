"""Agent 启动入口 - WebSocket 服务器"""
import asyncio
import logging
from pathlib import Path

import websockets

from weclaw.agent.skill_manager import SkillManager


class Server:
    """
    WebSocket服务器类
    """

    def __init__(self, host: str = "localhost", port: int = 4567):
        self.host = host
        self.port = port

    async def handle_connection(self, websocket):
        from weclaw.agent.client import Client
        async with Client(websocket) as client:
            await client.run()

    async def start_server(self):
        """启动WebSocket服务器"""
        print("=" * 60)
        print("WebSocket服务器启动中...")
        print(f"监听地址: ws://{self.host}:{self.port}")
        print("=" * 60)

        # 启动服务器
        async with websockets.serve(self.handle_connection, self.host, self.port):
            print("服务器已启动，等待客户端连接...")
            print("按 Ctrl+C 停止服务器")
            print("=" * 60)

            # 保持服务器运行
            await asyncio.Future()

async def main():
    """主函数"""
    # 初始化全局 SkillManager 实例
    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    skill_manager = SkillManager.get_instance(skills_dir)
    await skill_manager.load()

    server = Server(host="0.0.0.0")

    try:
        await server.start_server()
    except KeyboardInterrupt:
        print("\n服务器正在关闭...")
    except Exception as e:
        print(f"服务器错误: {e}")

if __name__ == '__main__':
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    logging.basicConfig(
        level="INFO",
        format='[%(asctime)s] %(levelname)s %(name)s: %(message)s'
    )
    asyncio.run(main())
