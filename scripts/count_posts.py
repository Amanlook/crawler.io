"""Count posts in DB."""
import asyncio
from sqlalchemy import select, func
from shared.db.database import async_session_factory
from shared.db.models import Post

async def main():
    async with async_session_factory() as s:
        r = await s.execute(select(func.count()).select_from(Post).where(Post.creator_id == "cr_qnvo4urvptsa1cn4"))
        count = r.scalar()
        print(f"Total posts in DB for virat.kohli: {count}")
        
        # Get post type breakdown
        r2 = await s.execute(
            select(Post.post_type, func.count()).where(Post.creator_id == "cr_qnvo4urvptsa1cn4").group_by(Post.post_type)
        )
        for row in r2.all():
            print(f"  {row[0]}: {row[1]}")

asyncio.run(main())
