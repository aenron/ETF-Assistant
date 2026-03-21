"""数据库迁移：添加user_id字段"""
import asyncio
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


async def migrate():
    """执行迁移"""
    async with engine.begin() as conn:
        # 添加 user_id 到 portfolio 表
        try:
            await conn.execute(text("ALTER TABLE portfolio ADD COLUMN user_id INTEGER"))
            print("✓ portfolio.user_id 添加成功")
        except Exception as e:
            if "already exists" in str(e):
                print("✓ portfolio.user_id 已存在")
            else:
                print(f"✗ portfolio.user_id 添加失败: {e}")
        
        # 添加 user_id 到 advice_log 表
        try:
            await conn.execute(text("ALTER TABLE advice_log ADD COLUMN user_id INTEGER"))
            print("✓ advice_log.user_id 添加成功")
        except Exception as e:
            if "already exists" in str(e):
                print("✓ advice_log.user_id 已存在")
            else:
                print(f"✗ advice_log.user_id 添加失败: {e}")
        
        # 创建 users 表（如果不存在）
        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(100) UNIQUE,
                    hashed_password VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            print("✓ users 表创建成功")
        except Exception as e:
            print(f"✗ users 表创建失败: {e}")
        
        # 创建索引
        try:
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_portfolio_user_id ON portfolio(user_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_advice_log_user_id ON advice_log(user_id)"))
            print("✓ 索引创建成功")
        except Exception as e:
            print(f"✗ 索引创建失败: {e}")


if __name__ == "__main__":
    asyncio.run(migrate())
