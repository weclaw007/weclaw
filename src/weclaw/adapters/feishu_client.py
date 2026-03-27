"""飞书 API 客户端 - 纯 I/O 封装层。

将飞书 SDK 调用封装为独立的客户端类，不含业务逻辑。
同时实现 MessageTransport 协议，可直接作为 AgentRuntime 的消息传输层。
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateFileRequest, CreateFileRequestBody,
    CreateImageRequest, CreateImageRequestBody,
    CreateMessageRequest, CreateMessageRequestBody,
    GetMessageResourceRequest,
)

logger = logging.getLogger(__name__)


class FeishuClient:
    """飞书 API 客户端 - 封装所有飞书 SDK 调用。

    所有公开方法均为同步（飞书 SDK 本身是同步的），
    调用方需自行通过 asyncio.to_thread 包装。
    """

    # 文件类型映射：后缀 → 飞书 file_type
    _FILE_TYPE_MAP = {
        ".opus": "opus", ".mp4": "mp4", ".pdf": "pdf",
        ".doc": "doc", ".docx": "doc",
        ".xls": "xls", ".xlsx": "xls",
        ".ppt": "ppt", ".pptx": "ppt",
    }

    # 媒体类型配置
    MEDIA_TYPE_CONFIG = {
        "image": {
            "resource_type": "image",
            "content_key": "image_key",
            "file_ext": ".jpg",
            "tmp_subdir": "feishu_image",
            "display_name": "图片",
        },
        "audio": {
            "resource_type": "file",
            "content_key": "file_key",
            "file_ext": ".opus",
            "tmp_subdir": "feishu_audio",
            "display_name": "语音",
        },
        "video": {
            "resource_type": "file",
            "content_key": "file_key",
            "file_ext": ".mp4",
            "tmp_subdir": "feishu_video",
            "display_name": "视频",
        },
    }

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.lark_client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()

    # ── 发送消息 ──────────────────────────────────────────────

    def send_reply(self, chat_id: str, text: str) -> None:
        """发送富文本消息（Markdown 渲染）"""
        try:
            content = json.dumps({
                "zh_cn": {
                    "content": [[{"tag": "md", "text": text}]]
                }
            })
            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("post")
                    .content(content)
                    .build()
                ).build()
            response = self.lark_client.im.v1.message.create(request)
            if not response.success():
                logger.error(f"发送飞书消息失败: code={response.code}, msg={response.msg}")
            else:
                logger.info(f"已发送飞书消息到会话 {chat_id}")
        except Exception as e:
            logger.exception(f"发送飞书消息异常: {e}")

    def upload_image(self, image_path: str) -> str | None:
        """上传图片返回 image_key"""
        try:
            image_path = os.path.expanduser(image_path)
            if not os.path.isfile(image_path):
                logger.error(f"图片文件不存在: {image_path}")
                return None
            with open(image_path, "rb") as f:
                request = CreateImageRequest.builder() \
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    ).build()
                response = self.lark_client.im.v1.image.create(request)
            if not response.success():
                logger.error(f"上传图片失败: code={response.code}, msg={response.msg}")
                return None
            image_key = response.data.image_key
            logger.info(f"图片上传成功: {image_path} -> {image_key}")
            return image_key
        except Exception as e:
            logger.exception(f"上传图片异常: {e}")
            return None

    def upload_file(self, file_path: str, file_type_override: str | None = None) -> str | None:
        """上传文件返回 file_key"""
        try:
            file_path = os.path.expanduser(file_path)
            if not os.path.isfile(file_path):
                logger.error(f"文件不存在: {file_path}")
                return None
            file_name = os.path.basename(file_path)
            if file_type_override:
                file_type = file_type_override
            else:
                suffix = os.path.splitext(file_name)[1].lower()
                file_type = self._FILE_TYPE_MAP.get(suffix, "stream")
            with open(file_path, "rb") as f:
                request = CreateFileRequest.builder() \
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(f)
                        .build()
                    ).build()
                response = self.lark_client.im.v1.file.create(request)
            if not response.success():
                logger.error(f"上传文件失败: code={response.code}, msg={response.msg}")
                return None
            file_key = response.data.file_key
            logger.info(f"文件上传成功: {file_path} -> {file_key}")
            return file_key
        except Exception as e:
            logger.exception(f"上传文件异常: {e}")
            return None

    def send_file(self, chat_id: str, file_path: str) -> bool:
        """发送文件消息"""
        file_key = self.upload_file(file_path)
        if not file_key:
            return False
        try:
            file_name = os.path.basename(os.path.expanduser(file_path))
            content = json.dumps({"file_key": file_key, "file_name": file_name})
            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("file")
                    .content(content)
                    .build()
                ).build()
            response = self.lark_client.im.v1.message.create(request)
            if not response.success():
                logger.error(f"发送文件消息失败: code={response.code}, msg={response.msg}")
                return False
            logger.info(f"已发送文件消息到会话 {chat_id}: {file_path}")
            return True
        except Exception as e:
            logger.exception(f"发送文件消息异常: {e}")
            return False

    def send_image(self, chat_id: str, image_path: str) -> bool:
        """发送图片消息"""
        image_key = self.upload_image(image_path)
        if not image_key:
            return False
        try:
            content = json.dumps({"image_key": image_key})
            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("image")
                    .content(content)
                    .build()
                ).build()
            response = self.lark_client.im.v1.message.create(request)
            if not response.success():
                logger.error(f"发送图片消息失败: code={response.code}, msg={response.msg}")
                return False
            logger.info(f"已发送图片消息到会话 {chat_id}: {image_path}")
            return True
        except Exception as e:
            logger.exception(f"发送图片消息异常: {e}")
            return False

    def send_video(self, chat_id: str, video_path: str) -> bool:
        """发送视频消息（含封面提取）"""
        file_key = self.upload_file(video_path, file_type_override="mp4")
        if not file_key:
            return False

        # 尝试提取视频封面
        image_key = ""
        try:
            tmp_cover = os.path.join(
                tempfile.gettempdir(), "feishu_video_cover",
                f"{os.path.basename(video_path)}.jpg"
            )
            os.makedirs(os.path.dirname(tmp_cover), exist_ok=True)
            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-vframes", "1", "-q:v", "2", tmp_cover],
                capture_output=True, timeout=10,
            )
            if os.path.isfile(tmp_cover):
                image_key = self.upload_image(tmp_cover) or ""
        except Exception as e:
            logger.warning(f"提取视频封面失败（不影响发送）: {e}")

        try:
            file_name = os.path.basename(os.path.expanduser(video_path))
            content_data = {"file_key": file_key, "file_name": file_name}
            if image_key:
                content_data["image_key"] = image_key
            content = json.dumps(content_data)
            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("media")
                    .content(content)
                    .build()
                ).build()
            response = self.lark_client.im.v1.message.create(request)
            if not response.success():
                logger.error(f"发送视频消息失败: code={response.code}, msg={response.msg}")
                return False
            logger.info(f"已发送视频消息到会话 {chat_id}: {video_path}")
            return True
        except Exception as e:
            logger.exception(f"发送视频消息异常: {e}")
            return False

    def download_resource(self, feishu_message_id: str, file_key: str, media_type: str) -> str | None:
        """从飞书下载媒体资源到本地临时文件"""
        config = self.MEDIA_TYPE_CONFIG[media_type]
        display_name = config["display_name"]
        try:
            request = GetMessageResourceRequest.builder() \
                .message_id(feishu_message_id) \
                .file_key(file_key) \
                .type(config["resource_type"]) \
                .build()
            response = self.lark_client.im.v1.message_resource.get(request)
            if not response.success():
                logger.error(f"下载{display_name}资源失败: code={response.code}, msg={response.msg}")
                return None
            tmp_dir = os.path.join(tempfile.gettempdir(), config["tmp_subdir"])
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_path = os.path.join(tmp_dir, f"{file_key}{config['file_ext']}")
            with open(tmp_path, "wb") as f:
                f.write(response.file.read())
            logger.info(f"{display_name}资源已下载: {feishu_message_id}/{file_key} -> {tmp_path}")
            return tmp_path
        except Exception as e:
            logger.exception(f"下载{display_name}资源异常: {e}")
            return None


class FeishuMessageTransport:
    """飞书消息传输层 - 实现 MessageTransport 协议。

    将 message 工具的 action 路由到 FeishuClient 的对应方法，
    所有同步 API 调用自动通过 asyncio.to_thread 异步化。
    """

    def __init__(self, client: FeishuClient, chat_id: str) -> None:
        self._client = client
        self._chat_id = chat_id

    async def send_message(self, query_params: dict) -> dict:
        """实现 MessageTransport 协议"""
        action = query_params.get("action")
        if not action:
            return {"error": "query_params must contain 'action' field"}

        chat_id = self._chat_id
        if not chat_id:
            return {"error": "LARK_GREETING_CHAT_ID not set, cannot send message"}

        try:
            if action == "send_pic":
                path = query_params.get("path", "")
                if not path:
                    return {"status": "error", "error": "缺少图片路径"}
                ok = await asyncio.to_thread(self._client.send_image, chat_id, path)
                return {"status": "success" if ok else "error", "action": action}

            elif action == "send_text":
                text = query_params.get("text", "")
                if not text:
                    return {"status": "error", "error": "缺少文本内容"}
                await asyncio.to_thread(self._client.send_reply, chat_id, text)
                return {"status": "success", "action": action}

            elif action == "send_file":
                path = query_params.get("path", "")
                if not path:
                    return {"status": "error", "error": "缺少文件路径"}
                ok = await asyncio.to_thread(self._client.send_file, chat_id, path)
                return {"status": "success" if ok else "error", "action": action}

            elif action == "send_video":
                path = query_params.get("path", "")
                if not path:
                    return {"status": "error", "error": "缺少视频路径"}
                ok = await asyncio.to_thread(self._client.send_video, chat_id, path)
                return {"status": "success" if ok else "error", "action": action}

            else:
                return {"status": "error", "error": f"未知 action: {action}"}
        except Exception as e:
            logger.exception(f"message 工具执行异常: action={action}, error={e}")
            return {"status": "error", "error": str(e)}
