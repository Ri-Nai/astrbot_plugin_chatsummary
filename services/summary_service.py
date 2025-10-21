# /astrbot_plugin_chatsummary/services/summary_service.py

import json
from datetime import datetime, timedelta
from astrbot.api import logger
from ..utils import parse_time_delta


class SummaryService:
    """消息总结服务：负责获取、格式化和总结聊天消息"""

    def __init__(
        self,
        config,
    ):
        self.config = config

    def parse_json(self, json_data: dict, indent: int = 0) -> str:
        """
        解析从聊天消息中获取的不同类型JSON数据，并将其格式化为可读文本。
        增加了对缩进的处理，以适配嵌套的消息结构。

        Args:
            json_data: 包含消息详情的JSON数据 (已从字符串解析为字典)。
            indent: 当前消息的缩进级别，用于格式化转发消息。

        Returns:
            格式化后的消息文本字符串。
        """
        app_type = json_data.get("app")

        try:
            # --- 适配类型1: 转发消息 (聊天记录) ---
            # 对应文件: 1.json
            if app_type == "com.tencent.multimsg":
                messages = json_data.get("meta", {}).get("detail", {}).get("news", [])
                if not messages:
                    return "[空的转发消息]"

                # --- 缩进处理逻辑 ---
                # 定义内容缩进，比当前级别多2个空格
                content_indent_str = " " * (indent + 2)

                # 提取并为每一行消息添加缩进
                chat_lines = [
                    f"{content_indent_str}{msg.get('text', '')}"
                    for msg in messages
                    if msg.get("text", "").strip()
                ]

                # 按照您原有的风格，构建带大括号和缩进的转发消息块
                # 注意：这里的开头 "[转发消息]:" 不加缩进，因为它将拼接在主消息行后面
                # --- FIX: Use a triple-quoted f-string for clarity and compatibility ---
                indent_str = " " * indent
                joined_lines = "\n".join(chat_lines)
                return (
                    "[转发消息]:\n"
                    f"{indent_str}"
                    "\{\n"
                    f"{joined_lines}"
                    f"{indent_str}"
                    "\}"
                )  # 注意这里的反斜杠用于转义大括号
            # --- 适配类型2: QQ小程序分享 ---
            # 对应文件: 2.json, 4.json
            elif app_type == "com.tencent.miniapp_01":
                detail = json_data.get("meta", {}).get("detail_1", {})
                title = detail.get("title", "未知应用")
                desc = detail.get("desc", "无简介")
                url = detail.get("qqdocurl") or detail.get("url", "无链接")

                # 对于非转发的分享，内容自成一体，通常不需要额外缩进
                return f"[分享 - {title}]\n简介: {desc}\n链接: {url}"

            # --- 适配类型3: 普通图文分享 (如小红书) ---
            # 对应文件: 3.json
            elif app_type == "com.tencent.tuwen.lua":
                news = json_data.get("meta", {}).get("news", {})
                title = news.get("title", "无标题")
                desc = news.get("desc", "无简介")
                url = news.get("jumpUrl", "无链接")
                tag = news.get("tag", "")

                return f"[分享 - {tag}]\n标题: {title}\n简介: {desc}\n链接: {url}"

            # --- 其他未知的JSON类型 ---
            else:
                prompt_text = json_data.get("prompt", "[未知的JSON分享]")
                return prompt_text

        except (KeyError, TypeError, AttributeError) as e:
            return f"[无法解析的JSON内容: {e}]"

    async def get_messages_by_arg(
        self,
        client,
        group_id: int,
        arg: str,
    ) -> tuple[list | None, str]:
        """
        根据参数获取消息，返回消息列表和一条状态消息。

        Args:
            client: 平台客户端
            group_id: 群组ID
            arg: 参数（数量或时间）

        Returns:
            (消息列表, 状态消息)
        """
        time_delta = parse_time_delta(arg)

        if time_delta:
            status_message = (
                f"正在为您总结群 {group_id} 过去 {arg} 内的聊天记录，请稍候..."
            )
            messages = await self.get_messages_by_time(
                client,
                group_id,
                time_delta,
            )
            return messages, status_message
        elif arg.isdigit():
            count = int(arg)
            if not (0 < count <= 500):
                return None, "请提供一个介于 1 和 500 之间的数字。"
            status_message = (
                f"正在为您总结群 {group_id} 最近 {count} 条聊天记录，请稍候..."
            )
            messages = await self.get_messages_by_count(
                client,
                group_id,
                count,
            )
            return messages, status_message
        else:
            return (
                None,
                "参数格式不正确哦~\n请使用如「 /消息总结 30 」(数量) 或「 /消息总结 1h30m 」(时间) 的格式。",
            )
    def _get_sender_display_name(self, sender: dict) -> str:
        """获取发送者的显示名称，优先使用card，然后是nickname，最后是未知用户"""
        return sender.get("card") or sender.get("nickname", "未知用户")

    def _format_message_part(self, part: dict, messages: list, current_indent: int) -> str:
        """格式化单个消息部分"""
        part_type = part.get("type")
        data = part.get("data", {})
        indent_str = " " * current_indent

        if part_type == "text":
            return data.get("text", "").strip()
        elif part_type == "image":
            return "[图片]"
        elif part_type == "video":
            return "[视频]"
        elif part_type == "face":
            return "[表情]"
        elif part_type == "reply":
            replied_id = data.get("id")
            if replied_id:
                # 尝试查找被回复的消息
                replied_message = next((msg for msg in messages if msg.get("message_id") == replied_id), None)
                if replied_message and isinstance(replied_message.get("message"), list):
                    # 如果找到了，递归格式化被回复消息的内容
                    replied_text = "".join(
                        self._format_message_part(p, messages, 0)
                        for p in replied_message["message"]
                        if p.get("type") in ["text", "image", "video", "face"] # 只展示部分类型以避免无限递归或过于冗长
                    ).strip()
                    if len(replied_text) > 20:
                        replied_text = replied_text[:17] + "..."
                    return f"[回复消息: 「{replied_text}」]"
            return "[回复消息]" # 如果找不到或不是有效消息，显示通用提示
        elif part_type == "json":
            try:
                json_data = json.loads(data.get("data", "{}"))
                # 假设 self.parse_json 已经存在且能处理缩进
                # 注意：这里需要确保 parse_json 方法是 MessageFormatter 的成员
                return f"\n{self.parse_json(json_data, current_indent + 2)}\n{indent_str}"
            except json.JSONDecodeError:
                return "[无法读取的分享内容]"
        elif part_type == "forward":
            forward_msg_list = data.get("content", [])
            formatted_forward = self.format_messages(
                forward_msg_list,
                self.config.my_id, # 假设 self.config.my_id 存储了机器人ID
                current_indent + 2,
            )
            return (
                f"\n{indent_str}{{\n"
                f"{formatted_forward}\n"
                f"{indent_str}}}"
            )
        return "" # 未知消息类型

    def format_messages(self, messages: list, my_id: int, indent: int = 0) -> str:
        """
        将从API获取的消息列表格式化为文本

        Args:
            messages: 消息列表
            my_id: 机器人自己的ID
            indent: 当前的缩进级别

        Returns:
            格式化后的聊天文本
        """
        formatted_lines = []
        indent_str = " " * indent

        for msg in messages:
            sender = msg.get("sender", {})
            if my_id == sender.get("user_id"):
                continue # 忽略机器人自己的消息

            # 确保 message 是列表类型
            message_parts = msg.get("message")
            if not isinstance(message_parts, list) or not message_parts:
                continue

            nickname = self._get_sender_display_name(sender)
            msg_time = datetime.fromtimestamp(msg.get("time", 0))

            full_message_text = []
            for part in message_parts:
                part_text = self._format_message_part(part, messages, indent)
                if part_text:
                    full_message_text.append(part_text)

            pure_text = " ".join(full_message_text).strip()

            # 处理唤醒前缀
            is_wake_message = False
            for prefix in self.config.wake_prefix:
                if pure_text.startswith(f"{prefix}image"):
                    pure_text = pure_text[len(f"{prefix}image"):].strip()
                    is_wake_message = True
                    break # 找到匹配项后跳出
                elif pure_text.startswith(prefix):
                    is_wake_message = True
                    break

            if is_wake_message and not self.config.include_wake_messages: # 假设有一个配置项来决定是否包含唤醒消息
                 continue # 如果是唤醒消息且配置为不包含，则跳过

            # 只有当消息内容不为空时才添加
            if pure_text:
                formatted_lines.append(
                    f"{indent_str}"
                    f"[{msg_time.strftime('%Y-%m-%d %H:%M:%S')}]"
                    f"「{nickname}」: "
                    f"{pure_text}"
                )
        return "\n".join(formatted_lines)

    async def get_messages_by_time(
        self, client, group_id: int, time_delta: timedelta
    ) -> list:
        """
        通过渐进式拉取的方式获取指定时间范围内的消息

        Args:
            client: 平台客户端
            group_id: 群组ID
            time_delta: 时间范围

        Returns:
            消息列表
        """
        target_start_time = datetime.now() - time_delta
        logger.info(f"目标开始时间: {target_start_time}")

        all_messages = []
        last_msg_seq = 0

        while True:
            logger.info(last_msg_seq)
            payloads = {
                "group_id": group_id,
                "message_seq": last_msg_seq,
                "count": 100,
                "reverseOrder": True,
            }
            try:
                ret = await client.api.call_action("get_group_msg_history", **payloads)
                messages = ret.get("messages", [])
            except Exception as e:
                logger.error(f"获取群聊 {group_id} 历史消息失败: {e}")
                break

            if not messages:
                break

            breakFlag = False
            messages = reversed(messages)
            for msg in messages:
                msg_seq = msg.get("message_seq")
                if msg_seq == last_msg_seq and last_msg_seq != 0:
                    continue
                msg_time = datetime.fromtimestamp(msg.get("time", 0))
                if msg_time < target_start_time:
                    breakFlag = True
                    break
                all_messages.append(msg)
                last_msg_seq = msg_seq

            if breakFlag:
                break

        return reversed(all_messages)

    async def get_messages_by_count(
        self,
        client,
        group_id: int,
        count: int,
    ) -> list:
        """
        按数量获取消息

        Args:
            client: 平台客户端
            group_id: 群组ID
            count: 消息数量

        Returns:
            消息列表
        """
        try:
            ret = await client.api.call_action(
                "get_group_msg_history",
                group_id=group_id,
                count=count,
            )
            return ret.get("messages", [])
        except Exception as e:
            logger.error(f"获取群聊 {group_id} 历史消息失败: {e}")
            return []
