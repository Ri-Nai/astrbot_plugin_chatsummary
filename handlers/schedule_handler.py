# /astrbot_plugin_chatsummary/handlers/schedule_handler.py

from ..services import SchedulerService


class ScheduleHandler:
    """定时任务处理器：负责启动和停止定时任务"""
    
    def __init__(self, scheduler_service: SchedulerService):
        self.scheduler_service = scheduler_service
    
    def start_scheduled_tasks(self):
        """启动所有定时任务"""
        self.scheduler_service.start_all_scheduled_tasks()
    
    async def stop_scheduled_tasks(self):
        """停止所有定时任务"""
        await self.scheduler_service.stop_all_tasks()
