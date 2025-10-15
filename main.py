import os
import re
from datetime import datetime, timedelta
import json
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

# 新增一个辅助函数，用于解析时间字符串
def _parse_time_delta(time_str: str) -> timedelta | None:
    """
    将 '1d2h30m' 格式的字符串解析为 timedelta 对象。
    支持 d (天), h (小时), m (分钟)。
    """
    parts = re.findall(r'(\d+)([dhm])', time_str.lower())
    if not parts:
        return None
    
    delta_args = {}
    for value, unit in parts:
        if unit == 'd':
            delta_args['days'] = int(value)
        elif unit == 'h':
            delta_args['hours'] = int(value)
        elif unit == 'm':
            delta_args['minutes'] = int(value)
    return timedelta(**delta_args)

@register("astrbot_plugin_chatsummary", "laopanmemz", "一个基于LLM的历史聊天记录总结插件", "1.2.0")
class ChatSummary(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.wake_prefix = self.context.get_config()["wake_prefix"]
        # 优化配置文件读取，增加默认值
        try:
            with open(os.path.join('data', 'config', 'astrbot_plugin_chatsummary_config.json'), 'r',
                      encoding='utf-8-sig') as a:
                config = json.load(a)
                self.prompt = str(config.get('prompt', '请总结以下聊天记录：')).replace('\\n', '\n')
        except FileNotFoundError:
            self.prompt = "请总结以下聊天记录："
            logger.warning("聊天总结插件配置文件未找到，将使用默认Prompt。")

    def _format_messages(self, messages: list, my_id: int) -> str:
        """将从API获取的消息列表格式化为文本"""
        chat_lines = []
        for msg in reversed(messages):  # 将消息反转，使其按时间正序排列
            sender = msg.get('sender', {})
            if my_id == sender.get('user_id'):
                continue
            
            nickname = sender.get('nickname', '未知用户')
            msg_time = datetime.fromtimestamp(msg.get('time', 0))
            message_text = ""

            # 确保 'message' 键存在且为列表
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

            if any(message_text.strip().startswith(prefix) for prefix in self.wake_prefix):
                continue

            if message_text.strip():
                chat_lines.append(f"[{msg_time.strftime('%Y-%m-%d %H:%M:%S')}]「{nickname}」: {message_text.strip()}")
        
        return "\n".join(chat_lines)

    async def _get_messages_by_time(self, event: AstrMessageEvent, group_id: int, time_delta: timedelta) -> list:
        """通过渐进式拉取的方式获取指定时间范围内的消息"""
        client = event.bot
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

    async def _process_summary(self, event: AstrMessageEvent, group_id: int, arg: str):
        """处理总结逻辑的通用函数"""
        client = event.bot
        assert isinstance(event, AiocqhttpMessageEvent)
        
        # 获取bot自身ID
        try:
            login_info = await client.api.call_action("get_login_info")
            my_id = login_info.get("user_id")
        except Exception as e:
            logger.error(f"获取登录信息失败: {e}")
            yield event.plain_result("抱歉，获取Bot信息失败，无法继续操作。")
            return

        messages = []
        # 尝试解析为时间范围
        time_delta = _parse_time_delta(arg)
        
        logger.info(time_delta)

        if time_delta:
            yield event.plain_result(f"正在为您总结群 {group_id} 过去 {arg} 内的聊天记录，请稍候...")
            messages = await self._get_messages_by_time(event, group_id, time_delta)
        # 尝试解析为数字（消息数量）
        elif arg.isdigit():
            count = int(arg)
            if count <= 0 or count > 500: # 增加数量限制，防止滥用
                yield event.plain_result("请提供一个介于 1 和 500 之间的数字。")
                return
            yield event.plain_result(f"正在为您总结群 {group_id} 最近 {count} 条聊天记录，请稍候...")
            payloads = {"group_id": group_id, "count": count}
            try:
                ret = await client.api.call_action("get_group_msg_history", **payloads)
                messages = ret.get("messages", [])
            except Exception as e:
                 logger.error(f"获取群聊 {group_id} 历史消息失败: {e}")
                 yield event.plain_result(f"获取群 {group_id} 的历史消息时发生错误。")
                 return
        else:
            yield event.plain_result("参数格式不正确哦~\n请使用如「 /消息总结 30 」(数量) 或「 /消息总结 1h30m 」(时间) 的格式。")
            return

        if not messages:
            yield event.plain_result("在指定范围内没有找到可以总结的聊天记录。")
            return

        formatted_chat = self._format_messages(messages, my_id)
        
        if not formatted_chat:
            yield event.plain_result("筛选后没有可供总结的聊天内容。")
            return
            
        logger.info(f"chat_summary: group_id={group_id} a_param={arg} msg_length={len(formatted_chat)}\n content:\n{formatted_chat}")
        
        try:
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=self.prompt,
                contexts=[{"role": "user", "content": formatted_chat}],
            )
            yield event.plain_result(llm_response.completion_text)
        except Exception as e:
            logger.error(f"调用LLM服务失败: {e}")
            yield event.plain_result("抱歉，总结服务出现了一点问题，请稍后再试。")

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("消息总结")
    async def summary(self, event: AstrMessageEvent, arg: str = None):
        """
        群聊场景触发消息总结。
        用法: /消息总结 [数量 或 时间范围]
        示例:
        /消息总结 20  (总结最近20条)
        /消息总结 1h  (总结过去1小时)
        /消息总结 30m (总结过去30分钟)
        /消息总结 1d12h (总结过去1天12小时)
        """
        if arg is None:
            yield event.plain_result("请提供要总结的消息数量或时间范围。\n例如:「 /消息总结 100 」或「 /消息总结 1h 」")
            return
        
        group_id = event.get_group_id()
        async for result in self._process_summary(event, group_id, str(arg)):
            yield result

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("群总结")
    async def private_summary(self, event: AstrMessageEvent, arg: str = None, group_id: int = None):
        """
        私聊场景触发群消息总结。
        用法: /群总结 [数量 或 时间范围] [群号]
        示例:
        /群总结 30 114514
        /群总结 1h 114514
        """
        if arg is None or group_id is None:
            yield event.plain_result("参数不足！\n请按照「 /群总结 [数量或时间] [群号] 」格式发送。\n例如「 /群总结 30 1145141919 」或「 /群总结 1h 1145141919 」")
            return

        async for result in self._process_summary(event, group_id, str(arg)):
            yield result