import redis.asyncio as redis
import json
from typing import Optional, Any
from datetime import timedelta

from config import settings


class RedisService:
    """Redis缓存服务"""
    
    _client: Optional[redis.Redis] = None
    
    @classmethod
    async def get_client(cls) -> redis.Redis:
        """获取Redis客户端（单例）"""
        if cls._client is None and settings.redis_enabled:
            cls._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return cls._client
    
    @classmethod
    async def close(cls):
        """关闭连接"""
        if cls._client:
            await cls._client.close()
            cls._client = None
    
    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        """获取缓存"""
        client = await cls.get_client()
        if not client:
            return None
        try:
            value = await client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            print(f"[Redis] GET error: {e}")
            return None
    
    @classmethod
    async def set(cls, key: str, value: Any, expire: int = 3600):
        """设置缓存"""
        client = await cls.get_client()
        if not client:
            return False
        try:
            await client.set(key, json.dumps(value), ex=expire)
            return True
        except Exception as e:
            print(f"[Redis] SET error: {e}")
            return False
    
    @classmethod
    async def delete(cls, key: str):
        """删除缓存"""
        client = await cls.get_client()
        if not client:
            return False
        try:
            await client.delete(key)
            return True
        except Exception as e:
            print(f"[Redis] DELETE error: {e}")
            return False
    
    @classmethod
    async def exists(cls, key: str) -> bool:
        """检查key是否存在"""
        client = await cls.get_client()
        if not client:
            return False
        try:
            return await client.exists(key) > 0
        except Exception:
            return False
