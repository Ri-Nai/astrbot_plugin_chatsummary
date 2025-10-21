# /astrbot_plugin_chatsummary/utils/json_parser.py


class JsonMessageParser:
    """JSON消息解析工具类：负责解析各种类型的JSON消息"""

    @staticmethod
    def parse_json(json_data: dict, indent: int = 0) -> str:
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
            if app_type == "com.tencent.multimsg":
                messages = json_data.get("meta", {}).get("detail", {}).get("news", [])
                if not messages:
                    return "[空的转发消息]"

                # 缩进处理逻辑
                content_indent_str = " " * (indent + 2)
                chat_lines = [
                    f"{content_indent_str}{msg.get('text', '')}"
                    for msg in messages
                    if msg.get("text", "").strip()
                ]

                indent_str = " " * indent
                joined_lines = "\n".join(chat_lines)
                return (
                    "[转发消息]:\n"
                    f"{indent_str}"
                    "\{\n"
                    f"{joined_lines}"
                    f"{indent_str}"
                    "\}"
                )

            # --- 适配类型2: QQ小程序分享 ---
            elif app_type == "com.tencent.miniapp_01":
                detail = json_data.get("meta", {}).get("detail_1", {})
                title = detail.get("title", "未知应用")
                desc = detail.get("desc", "无简介")
                url = detail.get("qqdocurl") or detail.get("url", "无链接")
                return f"[分享 - {title}]\n简介: {desc}\n链接: {url}"

            # --- 适配类型3: 普通图文分享 (如小红书) ---
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