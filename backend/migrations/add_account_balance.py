"""添加用户账户金额字段"""
from sqlalchemy import text
from database import engine

async def migrate():
    async with engine.begin() as conn:
        # 检查列是否已存在
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'users' AND column_name = 'account_balance'
        """))
        
        if result.scalar_one_or_none():
            print("Column account_balance already exists")
            return
        
        # 添加列
        await conn.execute(text("""
            ALTER TABLE users 
            ADD COLUMN account_balance NUMERIC(18,2)
        """))
        print("✓ Added account_balance column to users table")

if __name__ == "__main__":
    import asyncio
    asyncio.run(migrate())
