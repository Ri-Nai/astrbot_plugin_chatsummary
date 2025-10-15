# /astrbot_plugin_chatsummary/services.py

import json
from datetime import datetime, timedelta
from astrbot.api.event import AstrMessageEvent
from astrbot.core import logger
from .utils import parse_time_delta

from astrbot.api.event import MessageChain
import astrbot.api.message_components as Comp

class SummaryService:
    def __init__(self, context, config):
        self.context = context
        self.config = config

    async def get_messages_by_arg(self, client, group_id: int, arg: str) -> tuple[list | None, str]:
        """
        根据参数获取消息，返回消息列表和一条状态消息。
        """
        time_delta = parse_time_delta(arg)
        
        if time_delta:
            status_message = f"正在为您总结群 {group_id} 过去 {arg} 内的聊天记录，请稍候..."
            messages = await self._get_messages_by_time(client, group_id, time_delta)
            return messages, status_message
        elif arg.isdigit():
            count = int(arg)
            if not (0 < count <= 500):
                return None, "请提供一个介于 1 和 500 之间的数字。"
            status_message = f"正在为您总结群 {group_id} 最近 {count} 条聊天记录，请稍候..."
            messages = await self.get_messages_by_count(client, group_id, count)
            return messages, status_message
        else:
            return None, "参数格式不正确哦~\n请使用如「 /消息总结 30 」(数量) 或「 /消息总结 1h30m 」(时间) 的格式。"

    def _format_messages(self, messages: list, my_id: int) -> str:
        """将从API获取的消息列表格式化为文本"""
        chat_lines = []
        for msg in reversed(messages):
            sender = msg.get('sender', {})
            if my_id == sender.get('user_id'):
                continue
            
            nickname = sender.get('nickname', '未知用户')
            msg_time = datetime.fromtimestamp(msg.get('time', 0))
            message_text = ""

            if not isinstance(msg.get('message'), list):
                continue
            
            for part in msg['message']:
                if part.get('type') == 'text':
                    message_text += part.get('data', {}).get('text', '').strip() + " "
                elif part.get('type') == 'json':
                    try:
                        json_data = json.loads(part.get('data', {}).get('data', '{}'))
                        desc = json_data.get('meta', {}).get('news', {}).get('desc')
                        if desc:
                            message_text += f"[分享内容]{desc} "
                    except (json.JSONDecodeError, AttributeError):
                        pass
                elif part.get('type') == 'face':
                    message_text += "[表情] "

            if any(message_text.strip().startswith(prefix) for prefix in self.config.wake_prefix):
                continue

            if message_text.strip():
                chat_lines.append(f"[{msg_time.strftime('%Y-%m-%d %H:%M:%S')}]「{nickname}」: {message_text.strip()}")
        
        return "\n".join(chat_lines)
    async def _get_messages_by_time(self, client, group_id: int, time_delta: timedelta) -> list:
        """通过渐进式拉取的方式获取指定时间范围内的消息"""
        target_start_time = datetime.now() - time_delta
        
        logger.info(f"目标开始时间: {target_start_time}")
        
        all_messages = []
        last_msg_seq = 0
        
        
        while True:
            logger.info(last_msg_seq)
            payloads = {"group_id": group_id, "message_seq": last_msg_seq, "count": 100, "reverseOrder": True}
            try:
                ret = await client.api.call_action("get_group_msg_history", **payloads)
                messages = ret.get("messages", [])
            except Exception as e:
                logger.error(f"获取群聊 {group_id} 历史消息失败: {e}")
                break

            if not messages:
                break # 没有更多消息了
            breakFlag = False
            messages = messages[::-1]
            for msg in messages:
                msg_seq = msg.get('message_seq')
                if msg_seq == last_msg_seq and last_msg_seq != 0:
                    continue
                msg_time = datetime.fromtimestamp(msg.get('time', 0))
                if msg_time < target_start_time:
                    breakFlag = True
                    break
                all_messages.append(msg)
                last_msg_seq = msg_seq
            
            if breakFlag:
                break

            # 如果拉取到的消息不足一批，说明已经到头了
            if len(messages) < 100:
                break
                
        return all_messages

    async def get_summary_from_llm(self, formatted_chat: str) -> str:
        """调用LLM获取总结"""
        try:
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=self.config.prompt,
                contexts=[{"role": "user", "content": formatted_chat}],
            )
            return llm_response.completion_text
        except Exception as e:
            logger.error(f"调用LLM服务失败: {e}")
            raise  # 抛出异常由 handler 处理

    async def get_messages_by_count(self, client, group_id: int, count: int) -> list:
        """按数量获取消息"""
        try:
            ret = await client.api.call_action("get_group_msg_history", group_id=group_id, count=count)
            return ret.get("messages", [])
        except Exception as e:
            logger.error(f"获取群聊 {group_id} 历史消息失败: {e}")
            return []

    async def create_and_send_scheduled_summary(self, group_id: str, interval: str):
        """
        生成并发送定时的聊天总结。
        这是一个主动消息发送的例子。
        """
        client = self.context.bot  # 假设 context 有 bot
        
        try:
            login_info = await client.api.call_action("get_login_info")
            my_id = login_info.get("user_id")
        except Exception as e:
            logger.error(f"获取登录信息失败: {e}")
            return

        # 1. 获取消息记录
        time_delta = parse_time_delta(interval)
        if not time_delta:
            logger.error(f"无效的时间间隔: {interval}")
            return
        messages = await self._get_messages_by_time(client, int(group_id), time_delta)

        if not messages:
            summary = "在过去的一天里，本群没有任何新消息。"
        else:
            # 2. 生成总结
            formatted_chat = self._format_messages(messages, my_id)
            if not formatted_chat:
                summary = "筛选后没有可供总结的聊天内容。"
            else:
                try:
                    summary = await self.get_summary_from_llm(formatted_chat)
                except Exception as e:
                    logger.error(f"调用LLM失败: {e}")
                    summary = "抱歉，总结服务出现了一点问题。"

        # 3. 构建消息链并发送
        message_chain = MessageChain([Comp.Plain(text=f"【每日聊天总结】\n\n{summary}")])
        
        # 4. 构建统一消息源 (unified_msg_origin) 以指定发送目标
        # 格式为 "platform:message_type:session_id"
        # 假设我们使用的是 aiocqhttp 平台
        umo = f"aiocqhttp:group:{group_id}"

        await self.context.send_message(umo, message_chain)
