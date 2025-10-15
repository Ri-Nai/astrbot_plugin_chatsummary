# /astrbot_plugin_chatsummary/utils.py

import re
from datetime import timedelta

def parse_time_delta(time_str: str) -> timedelta | None:
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
