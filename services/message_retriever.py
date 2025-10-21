# /astrbot_plugin_chatsummary/services/message_retriever.py

from datetime import datetime, timedelta
from astrbot.api import logger


class MessageRetriever:
    """消息获取服务：负责从平台API获取消息数据"""

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