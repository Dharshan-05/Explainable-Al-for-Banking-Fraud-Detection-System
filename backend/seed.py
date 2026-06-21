import asyncio, random
from datetime import datetime, timedelta
from database.db import engine
from models.transaction import Transaction
from sqlalchemy.ext.asyncio import AsyncSession

async def seed():
    async with AsyncSession(engine) as db:
        for i in range(200):
            score = random.uniform(0, 1)
            risk = 'HIGH' if score > 0.7 else 'MEDIUM' if score > 0.4 else 'LOW'
            t = Transaction(
                amount=round(random.uniform(10, 50000), 2),
                fraud_score=score,
                is_fraud=score > 0.7,
                risk_level=risk,
                status=random.choice(['pending', 'approved', 'rejected', 'flagged']),
                created_at=datetime.utcnow() - timedelta(days=random.randint(0, 29))
            )
            db.add(t)
        await db.commit()
        print('✅ 200 transactions seeded!')

asyncio.run(seed())
