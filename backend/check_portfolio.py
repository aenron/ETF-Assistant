import asyncio
from database import engine
from sqlalchemy import text

async def add_cols():
    async with engine.begin() as conn:
        try:
            await conn.execute(text('ALTER TABLE advice_log ADD COLUMN llm_provider VARCHAR(30)'))
            print('added llm_provider')
        except Exception as e:
            print(f'llm_provider: {e}')
        try:
            await conn.execute(text('ALTER TABLE advice_log ADD COLUMN llm_model VARCHAR(100)'))
            print('added llm_model')
        except Exception as e:
            print(f'llm_model: {e}')

asyncio.run(add_cols())
