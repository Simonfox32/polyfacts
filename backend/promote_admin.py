import asyncio
from sqlalchemy import text
from app.db import engine

async def go():
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_admin = true WHERE username = 'simon'"))
        print("Done - simon is now admin")

asyncio.run(go())
