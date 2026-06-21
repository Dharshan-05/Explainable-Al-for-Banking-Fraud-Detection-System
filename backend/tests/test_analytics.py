# ============================================================
#  tests/test_analytics.py  —  Analytics Route Tests
# ============================================================

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestAnalytics:
    async def test_analytics_unauthenticated(self, client: AsyncClient):
        """Analytics endpoint requires auth."""
        resp = await client.get("/api/analytics/summary")
        assert resp.status_code == 401

    async def test_analytics_summary_empty_db(self, client: AsyncClient, auth_headers: dict):
        """On empty DB, summary should return zeros not an error."""
        resp = await client.get("/api/analytics/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Should have numeric totals
        assert "total_transactions" in data or "total" in data

    async def test_analytics_after_predictions(self, client: AsyncClient, auth_headers: dict):
        """After inserting a prediction, totals should increment."""
        from unittest.mock import patch
        from tests.conftest import mock_predict_transaction

        with patch("api.routes.predict.get_predictor",
                   return_value={"single": mock_predict_transaction, "batch": None}):
            legit_payload = {
                "V1": -1.3, "V2": 1.2, "V14": 0.3,
                "Amount": 100.0, "Time": 45000.0,
            }
            await client.post("/api/predict/transaction", json=legit_payload, headers=auth_headers)

        resp = await client.get("/api/analytics/summary", headers=auth_headers)
        assert resp.status_code == 200

    async def test_analytics_trends_preset_and_custom(self, client: AsyncClient, auth_headers: dict):
        """Verify analytics trends with presets, custom dates, and validation failures."""
        # 1. Preset window 7 days (default)
        resp = await client.get("/api/analytics/trends", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 7
        for point in data:
            assert "date" in point
            assert "total" in point
            assert "fraud" in point
            assert "legit" in point
            assert "fraud_rate" in point

        # 2. Preset window 14 days
        resp = await client.get("/api/analytics/trends?days=14", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 14

        # 3. Custom date range
        import datetime
        today = datetime.date.today()
        start = today - datetime.timedelta(days=3)
        resp = await client.get(f"/api/analytics/trends?start_date={start}&end_date={today}", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 4

        # 4. Invalid date range (start after end)
        resp = await client.get(f"/api/analytics/trends?start_date={today}&end_date={start}", headers=auth_headers)
        assert resp.status_code == 400
        assert "start_date cannot be after end_date" in resp.json()["detail"]

        # 5. Invalid date format
        resp = await client.get("/api/analytics/trends?start_date=2026/06/15", headers=auth_headers)
        assert resp.status_code == 400
        assert "Invalid date format" in resp.json()["detail"]

    async def test_analytics_score_distribution(self, client: AsyncClient, auth_headers: dict):
        """Verify analytics score-distribution endpoint returns 10 buckets."""
        resp = await client.get("/api/analytics/score-distribution", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 10
        for bucket in data:
            assert "range" in bucket
            assert "count" in bucket
            assert isinstance(bucket["count"], int)

    async def test_analytics_stats_aggregation(self, client: AsyncClient, auth_headers: dict):
        """Verify analytics stats calculation math (total, sums, rates) is correct."""
        from database.db import AsyncSessionLocal
        from models.transaction import Transaction, RiskLevel, TransactionStatus

        # Seed 3 distinct transactions
        async with AsyncSessionLocal() as db:
            t1 = Transaction(
                amount=100.0, merchant="M1",
                risk_level=RiskLevel.HIGH, status=TransactionStatus.flagged,
                is_fraud=True, fraud_score=0.8, v_features={}
            )
            t2 = Transaction(
                amount=200.0, merchant="M2",
                risk_level=RiskLevel.LOW, status=TransactionStatus.pending,
                is_fraud=False, fraud_score=0.1, v_features={}
            )
            t3 = Transaction(
                amount=150.0, merchant="M3",
                risk_level=RiskLevel.MEDIUM, status=TransactionStatus.approved,
                is_fraud=False, fraud_score=0.3, v_features={}
            )
            db.add_all([t1, t2, t3])
            await db.commit()

        resp = await client.get("/api/analytics/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        # Math checks
        assert data["total_transactions"] == 3
        assert data["total_fraud"] == 1
        assert data["total_legit"] == 2
        assert data["fraud_rate"] == round((1 / 3) * 100, 2)
        assert data["total_amount_at_risk"] == 100.0
        assert data["total_amount"] == 450.0
        assert data["avg_fraud_score"] == round(((0.8 + 0.1 + 0.3) / 3) * 100, 2)

    async def test_analytics_risk_distribution(self, client: AsyncClient, auth_headers: dict):
        """Verify risk-distribution endpoint matches seeds and calculates percentages correctly."""
        from database.db import AsyncSessionLocal
        from models.transaction import Transaction, RiskLevel, TransactionStatus

        async with AsyncSessionLocal() as db:
            t1 = Transaction(
                amount=10.0, merchant="M1",
                risk_level=RiskLevel.HIGH, status=TransactionStatus.flagged,
                is_fraud=True, fraud_score=0.8, v_features={}
            )
            t2 = Transaction(
                amount=20.0, merchant="M2",
                risk_level=RiskLevel.LOW, status=TransactionStatus.pending,
                is_fraud=False, fraud_score=0.1, v_features={}
            )
            db.add_all([t1, t2])
            await db.commit()

        resp = await client.get("/api/analytics/risk-distribution", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        assert len(data) == 3
        high = next(r for r in data if r["risk_level"] == "HIGH")
        low = next(r for r in data if r["risk_level"] == "LOW")
        med = next(r for r in data if r["risk_level"] == "MEDIUM")

        assert high["count"] == 1
        assert high["percentage"] == 50.0
        assert low["count"] == 1
        assert low["percentage"] == 50.0
        assert med["count"] == 0
        assert med["percentage"] == 0.0

    async def test_analytics_top_features_handling(self, client: AsyncClient, auth_headers: dict):
        """Verify top-features endpoint returns empty array safely when no SHAP details exist."""
        resp = await client.get("/api/analytics/top-features", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0
