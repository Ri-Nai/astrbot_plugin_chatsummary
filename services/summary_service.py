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

                return f"[分享内容]\n标题: {title}\n简介: {desc}\n链接: {url}"

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
        for msg in messages:
            sender = msg.get("sender", {})
            if my_id == sender.get("user_id"):
                continue
            if not isinstance(msg.get("message"), list):
                continue

            nickname = sender.get("card")
            if not nickname:
                nickname = sender.get("nickname", "未知用户")
            msg_time = datetime.fromtimestamp(msg.get("time", 0))
            message_text = ""
            indent_str = " " * indent
            for part in msg["message"]:
                if part.get("type") == "text":
                    message_text += part.get("data", {}).get("text", "").strip() + " "
                elif part.get("type") == "json":
                    try:
                        json_data = json.loads(part.get("data", {}).get("data", "{}"))

                        # --- 关键改动 ---
                        # 调用解析函数时，传入当前的 indent 值
                        formatted_json_text = self.parse_json(json_data, indent)

                        # 拼接格式化文本
                        message_text += formatted_json_text + "\n"

                    except json.JSONDecodeError:
                        message_text += "[无法读取的分享内容] "
                elif part.get("type") == "face":
                    message_text += "[表情] "
                elif part.get("type") == "forward":
                    message_text += (
                        "[转发消息]: \n"
                        f"{indent_str}"  # 缩进
                        "{\n"
                    )

                    forward_msg_list = part.get("data", {}).get("content", [])
                    formatted_forward = self.format_messages(
                        forward_msg_list,
                        my_id,
                        indent + 2,
                    )
                    message_text += formatted_forward + "\n" + indent_str + "}" + "\n"
            pure_text = message_text.strip()
            for prefix in self.config.wake_prefix:
                if pure_text.startswith(f"{prefix}image"):
                    pure_text = pure_text[len(f"{prefix}image") :].strip()

            if any(pure_text.startswith(prefix) for prefix in self.config.wake_prefix):
                continue

            if pure_text:
                chat_lines.append(
                    (
                        f"{indent_str}"
                        f"[{msg_time.strftime('%Y-%m-%d %H:%M:%S')}]"
                        f"「{nickname}」: "
                        f"{pure_text.strip()}"
                    )
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
