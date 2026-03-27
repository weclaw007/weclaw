"""WebSocket 服务器"""

import asyncio
import logging

import websockets

logger = logging.getLogger(__name__)


class Server:
    """WebSocket 服务器"""

    def __init__(self, host: str = "localhost", port: int = 4567):
        self.host = host
        self.port = port

    async def handle_connection(self, websocket):
        from weclaw.gateway.session import Session
        async with Session(websocket) as session:
            await session.run()

    async def start(self):
        """启动 WebSocket 服务器"""
        logger.info(f"WebSocket 服务器启动: ws://{self.host}:{self.port}")
        async with websockets.serve(
            self.handle_connection, self.host, self.port,
            max_size=100 * 1024 * 1024,  # 100MB
        ):
            await asyncio.Future()  # 永久运行
