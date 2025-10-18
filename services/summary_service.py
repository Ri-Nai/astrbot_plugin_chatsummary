# /astrbot_plugin_chatsummary/services/summary_service.py

import json
from datetime import datetime, timedelta
from astrbot.api import logger
from ..utils import parse_time_delta


class SummaryService:
    """消息总结服务：负责获取、格式化和总结聊天消息"""

    def __init__(self, config):
        self.config = config

    async def get_messages_by_arg(
        self, client, group_id: int, arg: str
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
            messages = await self.get_messages_by_time(client, group_id, time_delta)
            return messages, status_message
        elif arg.isdigit():
            count = int(arg)
            if not (0 < count <= 500):
                return None, "请提供一个介于 1 和 500 之间的数字。"
            status_message = (
                f"正在为您总结群 {group_id} 最近 {count} 条聊天记录，请稍候..."
            )
            messages = await self.get_messages_by_count(client, group_id, count)
            return messages, status_message
        else:
            return (
                None,
                "参数格式不正确哦~\n请使用如「 /消息总结 30 」(数量) 或「 /消息总结 1h30m 」(时间) 的格式。",
            )

    def format_messages(self, messages: list, my_id: int, indent: int = 0) -> str:
        """
        将从API获取的消息列表格式化为文本

        Args:
            messages: 消息列表
            my_id: 机器人自己的ID

        Returns:
            格式化后的聊天文本
        """
        chat_lines = []
        for msg in reversed(messages):
            sender = msg.get("sender", {})
            if my_id == sender.get("user_id"):
                continue
            if not isinstance(msg.get("message"), list):
                continue

            nickname = sender.get("card", sender.get("nickname", "未知用户"))
            msg_time = datetime.fromtimestamp(msg.get("time", 0))
            message_text = ""

            for part in msg["message"]:
                if part.get("type") == "text":
                    message_text += part.get("data", {}).get("text", "").strip() + " "
                elif part.get("type") == "json":
                    try:
                        json_data = json.loads(part.get("data", {}).get("data", "{}"))
                        desc = json_data.get("meta", {}).get("news", {}).get("desc")
                        if desc:
                            message_text += f"[分享内容]{desc} "
                    except (json.JSONDecodeError, AttributeError):
                        pass
                elif part.get("type") == "face":
                    message_text += "[表情] "
                elif part.get("type") == "forward":
                    message_text += "[转发消息]: \n"
                    forward_msg_list = part.get("data", {}).get("content", [])
                    formatted_forward = self.format_messages(forward_msg_list, my_id, indent + 2)
                    message_text += formatted_forward + " "

            if any(
                message_text.strip().startswith(prefix)
                for prefix in self.config.wake_prefix
            ):
                continue

            if message_text.strip():
                chat_lines.append(
                    f"{' ' * indent}[{msg_time.strftime('%Y-%m-%d %H:%M:%S')}]「{nickname}」: {message_text.strip()}"
                )

        return "\n".join(chat_lines)

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
            messages = messages[::-1]
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

        return all_messages

    async def get_messages_by_count(self, client, group_id: int, count: int) -> list:
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
                "get_group_msg_history", group_id=group_id, count=count
            )
            return ret.get("messages", [])
        except Exception as e:
            logger.error(f"获取群聊 {group_id} 历史消息失败: {e}")
            return []
