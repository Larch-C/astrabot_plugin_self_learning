"""
消息收集服务 - 负责收集、存储和管理用户消息数据
"""
import asyncio
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta

from astrbot.api import logger
from astrbot.api.star import Context

from ..config import PluginConfig
from ..exceptions import MessageCollectionError, DataStorageError
from .database_manager import DatabaseManager


class MessageCollectorService:
    """消息收集服务类"""
    
    def __init__(self, config: PluginConfig, context: Context, database_manager: DatabaseManager):
        self.config = config
        self.context = context
        self.database_manager = database_manager # 注入数据库管理器
        
        # 消息缓存（用于批量写入优化）
        self._message_cache = []
        self._cache_size_limit = 100
        self._last_flush_time = time.time()
        self._flush_interval = 30  # 30秒强制刷新一次
        
        logger.info("消息收集服务初始化完成")

    # 移除 _init_database 方法，因为数据库初始化现在由 DatabaseManager 负责

    async def collect_message(self, message_data: Dict[str, Any]) -> bool:
        """收集消息到缓存"""
        try:
            # 验证消息数据
            required_fields = ['sender_id', 'message', 'timestamp']
            for field in required_fields:
                if field not in message_data:
                    logger.warning(f"消息数据缺少必要字段: {field}")
                    return False
            
            # 添加到缓存
            self._message_cache.append(message_data)
            
            # 检查是否需要刷新缓存
            if (len(self._message_cache) >= self._cache_size_limit or 
                time.time() - self._last_flush_time > self._flush_interval):
                await self._flush_message_cache()
            
            return True
            
        except Exception as e:
            logger.error(f"消息收集失败: {e}")
            raise MessageCollectionError(f"消息收集失败: {str(e)}")

    async def _flush_message_cache(self):
        """刷新消息缓存到数据库"""
        if not self._message_cache:
            return
            
        try:
            # 并发插入消息
            tasks = [self.database_manager.save_raw_message(msg) for msg in self._message_cache]
            await asyncio.gather(*tasks)
            
            logger.debug(f"已刷新 {len(self._message_cache)} 条消息到数据库")
            
            # 清空缓存
            self._message_cache.clear()
            self._last_flush_time = time.time()
            
        except Exception as e:
            logger.error(f"消息缓存刷新失败: {e}")
            raise DataStorageError(f"消息缓存刷新失败: {str(e)}")

    async def get_unprocessed_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取未处理的消息"""
        try:
            # 先刷新缓存
            await self._flush_message_cache()
            
            messages = await self.database_manager.get_unprocessed_messages(limit)
            return messages
            
        except Exception as e:
            logger.error(f"获取未处理消息失败: {e}")
            raise DataStorageError(f"获取未处理消息失败: {str(e)}")

    async def add_filtered_message(self, filtered_data: Dict[str, Any]) -> bool:
        """添加筛选后的消息"""
        try:
            await self.database_manager.add_filtered_message(filtered_data)
            return True
            
        except Exception as e:
            logger.error(f"添加筛选消息失败: {e}")
            raise DataStorageError(f"添加筛选消息失败: {str(e)}")

    async def mark_messages_processed(self, message_ids: List[int]):
        """标记消息为已处理"""
        try:
            if not message_ids:
                return
            
            await self.database_manager.mark_messages_processed(message_ids)
            logger.debug(f"已标记 {len(message_ids)} 条消息为已处理")
            
        except Exception as e:
            logger.error(f"标记消息处理状态失败: {e}")
            raise DataStorageError(f"标记消息处理状态失败: {str(e)}")

    async def get_filtered_messages_for_learning(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取用于学习的筛选消息"""
        try:
            messages = await self.database_manager.get_filtered_messages_for_learning(limit)
            return messages
            
        except Exception as e:
            logger.error(f"获取学习消息失败: {e}")
            raise DataStorageError(f"获取学习消息失败: {str(e)}")

    async def get_recent_filtered_messages(self, group_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        获取指定群组最近的、包含多维度评分的筛选消息。
        """
        try:
            messages = await self.database_manager.get_recent_filtered_messages(group_id, limit)
            return messages

        except Exception as e:
            logger.error(f"获取最近筛选消息失败: {e}")
            return []

    async def get_statistics(self) -> Dict[str, Any]:
        """获取收集统计信息"""
        try:
            # 先刷新缓存
            await self._flush_message_cache()
            
            statistics = await self.database_manager.get_messages_statistics()
            statistics['cache_size'] = len(self._message_cache) # 缓存大小仍然由 MessageCollectorService 管理
            return statistics
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}

    async def export_learning_data(self) -> Dict[str, Any]:
        """导出学习数据"""
        try:
            await self._flush_message_cache()
            
            learning_data = await self.database_manager.export_messages_learning_data()
            learning_data['config'] = self.config.to_dict() # 配置信息仍然由 MessageCollectorService 提供
            return learning_data
            
        except Exception as e:
            logger.error(f"导出学习数据失败: {e}")
            raise DataStorageError(f"导出学习数据失败: {str(e)}")

    async def clear_all_data(self):
        """清空所有数据"""
        try:
            await self._flush_message_cache()
            await self.database_manager.clear_all_messages_data()
            self._message_cache.clear()
            logger.info("所有学习数据已清空")
            
        except Exception as e:
            logger.error(f"清空数据失败: {e}")
            raise DataStorageError(f"清空数据失败: {str(e)}")

    async def save_state(self):
        """保存当前状态"""
        try:
            await self._flush_message_cache()
            logger.info("消息收集服务状态已保存")
            
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    async def create_learning_batch(self, batch_name: str) -> int:
        """创建学习批次记录"""
        try:
            batch_id = await self.database_manager.create_learning_batch(batch_name)
            return batch_id
            
        except Exception as e:
            logger.error(f"创建学习批次失败: {e}")
            raise DataStorageError(f"创建学习批次失败: {str(e)}")

    async def update_learning_batch(self, batch_id: int, **kwargs):
        """更新学习批次信息"""
        try:
            await self.database_manager.update_learning_batch(batch_id, **kwargs)
            
        except Exception as e:
            logger.error(f"更新学习批次失败: {e}")
            raise DataStorageError(f"更新学习批次失败: {str(e)}")
