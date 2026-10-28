"""HTTP-level tests against a throwaway, migrated Postgres (setup in AGENTS.md).

Skipped unless TEST_DATABASE_URL is set; never point it at a real database.
"""

import asyncio
import os
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    # Settings are read lazily, so overriding the environment here wins over .env.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")

import httpx
from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

import api.routers.sessions as sessions_router
from api.auth import CurrentUser, get_current_user
from api.config import get_settings
from api.database import close_db, get_session_factory, init_db
from api.main import app

T0 = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


def _header_user(request: Request) -> CurrentUser:
    return CurrentUser(id=request.headers["x-test-user"], email=None, role="authenticated", claims={})


def session_body(session_id: str | None = None, *, start: datetime = T0, points: int = 10, **extra) -> dict:
    trail = [
        {"lat": 41.4 + index * 1e-4, "lon": 2.1, "t": (start + timedelta(seconds=index)).isoformat()}
        for index in range(points)
    ]
    body = {
        "type": "walk",
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(hours=2)).isoformat(),
        "active_duration_seconds": 3600,
        "active_energy_kcal": 120,
        "steps": 1000,
        "distance_meters": 800,
        "segments": [{"idx": 0, "started_at": start.isoformat(), "points": trail}] if points else [],
        **extra,
    }
    if session_id:
        body["id"] = session_id
    return body


def workout_body(
    day: date, *, ended_at: datetime | None = None, minutes: int = 60,
    exercise_id: str = "0001", weight: float = 100, reps: int = 5,
) -> dict:
    ended_at = ended_at or datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9)
    return {
        "id": str(uuid.uuid4()),
        "date": day.isoformat(),
        "name": "Workout",
        "startedAt": (ended_at - timedelta(minutes=minutes)).isoformat(),
        "endedAt": ended_at.isoformat(),
        "entries": [{
            "id": str(uuid.uuid4()),
            "exerciseId": exercise_id,
            "target": {"id": str(uuid.uuid4()), "exerciseId": exercise_id},
            "sets": [{"id": str(uuid.uuid4()), "weight": weight, "reps": reps}],
        }],
    }


@unittest.skipUnless(TEST_DATABASE_URL, "set TEST_DATABASE_URL to a migrated throwaway Postgres")
class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        get_settings.cache_clear()
        self.assertEqual(get_settings().database_url, TEST_DATABASE_URL)
        init_db(get_settings())
        app.dependency_overrides[get_current_user] = _header_user
        self.user = await self.new_user()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"x-test-user": self.user},
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        app.dependency_overrides.clear()
        await close_db()

    async def sql(self, statement: str, **params):
        async with get_session_factory()() as db:
            result = await db.execute(text(statement), params)
            await db.commit()
            return result

    async def new_user(self) -> str:
        user_id = str(uuid.uuid4())
        await self.sql("INSERT INTO auth.users (id) VALUES (:id)", id=user_id)
        return user_id

    # Sessions

    async def test_session_replay_returns_the_full_response(self):
        session_id = str(uuid.uuid4())
        first = await self.client.post("/sessions", json=session_body(session_id))
        replay = await self.client.post("/sessions", json=session_body(session_id))
        self.assertEqual((first.status_code, replay.status_code), (201, 201))
        self.assertEqual(len(replay.json()["segments"][0]["points"]), 10)

    async def test_racing_duplicate_create_is_a_conflict(self):
        original = sessions_router.upsert_map_preview

        async def slow_upsert(*args, **kwargs):
            await asyncio.sleep(0.3)  # keeps the first insert uncommitted
            return await original(*args, **kwargs)

        session_id = str(uuid.uuid4())
        with patch.object(sessions_router, "upsert_map_preview", slow_upsert):
            first = asyncio.create_task(self.client.post("/sessions?compact=true", json=session_body(session_id)))
            await asyncio.sleep(0.1)
            second = await self.client.post("/sessions?compact=true", json=session_body(session_id))
        self.assertEqual(((await first).status_code, second.status_code), (201, 409))
        replay = await self.client.post("/sessions?compact=true", json=session_body(session_id))
        self.assertEqual(replay.status_code, 201)

    async def test_delete_cascades_in_the_database(self):
        session_id = str(uuid.uuid4())
        await self.client.post("/sessions?compact=true", json=session_body(session_id, points=500))
        engine = get_session_factory().kw["bind"]
        statements: list[str] = []
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(engine.sync_engine, "before_cursor_execute", listener)
        try:
            response = await self.client.delete(f"/sessions/{session_id}")
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", listener)
        self.assertEqual(response.status_code, 204)
        self.assertFalse([s for s in statements if "session_segments" in s or "session_map_previews" in s])
        remaining = await self.sql(
            "SELECT (SELECT count(*) FROM session_segments WHERE session_id = :id)"
            " + (SELECT count(*) FROM session_map_previews WHERE session_id = :id)",
            id=session_id,
        )
        self.assertEqual(remaining.scalar(), 0)
        self.assertEqual((await self.client.delete(f"/sessions/{session_id}")).status_code, 404)

    async def test_history_reports_trails_from_previews(self):
        with_trail, without_trail = str(uuid.uuid4()), str(uuid.uuid4())
        await self.client.post("/sessions?compact=true", json=session_body(with_trail))
        await self.client.post("/sessions?compact=true", json=session_body(without_trail, start=T0 + timedelta(days=1), points=0))
        items = {item["id"]: item["has_trail"] for item in (await self.client.get("/sessions/history")).json()["items"]}
        self.assertEqual(items, {with_trail: True, without_trail: False})

    async def test_list_without_points_omits_series(self):
        speed = [{"t": index, "d": index, "v": 1.0} for index in range(50)]
        await self.client.post("/sessions?compact=true", json=session_body(points=40, speed_samples=speed))
        window = {"from": T0.date().isoformat(), "to": T0.date().isoformat()}
        bare = (await self.client.get("/sessions", params=window)).json()[0]
        full = (await self.client.get("/sessions", params={**window, "includePoints": "true", "pointLimit": 5})).json()[0]
        self.assertEqual((bare["speed_samples"], bare["segments"][0]["points"]), ([], []))
        self.assertEqual((len(full["speed_samples"]), len(full["segments"][0]["points"])), (50, 5))

    async def test_trace_chunks_accept_location_only(self):
        session_id = str(uuid.uuid4())
        await self.client.post("/sessions?compact=true", json=session_body(session_id))
        fix = {
            "session_id": session_id, "section_id": str(uuid.uuid4()), "sequence": 0,
            "timestamp": T0.isoformat(), "received_at": T0.isoformat(), "latitude": 41.4, "longitude": 2.1,
            "horizontal_accuracy": 5, "is_stationary": False, "is_full_accuracy": True,
            "is_simulated_by_software": False, "is_produced_by_accessory": False, "quality": "usable",
        }
        chunk = {"first_at": T0.isoformat(), "last_at": T0.isoformat(), "checksum_sha256": "a" * 64, "samples": [fix]}
        location = await self.client.put(f"/sessions/{session_id}/trace-chunks/location/0/0", json=chunk)
        motion = await self.client.put(f"/sessions/{session_id}/trace-chunks/motion/0/0", json=chunk)
        self.assertEqual((location.status_code, motion.status_code), (204, 422))
        manifest = (await self.client.get(f"/sessions/{session_id}/trace-chunks")).json()
        self.assertEqual([item["kind"] for item in manifest], ["location"])

    async def test_backfill_builds_missing_previews(self):
        from scripts.backfill_map_previews import backfill

        session_id = str(uuid.uuid4())
        await self.client.post("/sessions?compact=true", json=session_body(session_id))
        await self.sql("DELETE FROM session_map_previews WHERE session_id = :id", id=session_id)
        await backfill()
        preview = await self.sql(
            "SELECT jsonb_array_length(map_sections) FROM session_map_previews WHERE session_id = :id",
            id=session_id,
        )
        self.assertEqual(preview.scalar(), 1)

    async def test_saved_route_saves_are_serialized(self):
        session_id = str(uuid.uuid4())
        await self.client.post("/sessions?compact=true", json=session_body(session_id))
        await self.sql(
            "INSERT INTO session_routes (session_id, user_id, revision, algorithm_version, status,"
            " confidence, distance_meters, sections, processed_at)"
            " VALUES (:s, :u, 1, 'v1', 'gps_only', 0.9, 10, CAST(:sections AS jsonb), now())",
            s=session_id, u=self.user,
            sections='[{"id": "%s", "source": "filteredGPS", "confidence": 0.9, "coordinates":'
                     ' [{"latitude": 41, "longitude": 2}, {"latitude": 41.1, "longitude": 2.1}]}]' % uuid.uuid4(),
        )
        original_commit = AsyncSession.commit

        async def slow_commit(db):
            await asyncio.sleep(0.2)  # holds the first save's lock while the second arrives
            return await original_commit(db)

        body = {"source_session_id": session_id, "name": "Loop"}
        with patch.object(AsyncSession, "commit", slow_commit):
            responses = await asyncio.gather(*(self.client.post("/saved-routes", json=body) for _ in range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 201])
        self.assertEqual(len((await self.client.get("/saved-routes")).json()), 1)

    # Strength

    async def test_foreign_routine_id_is_a_conflict(self):
        routine_id = str(uuid.uuid4())
        routine = {"id": routine_id, "name": "Push", "exercises": []}
        other = {"x-test-user": await self.new_user()}
        self.assertEqual((await self.client.put(f"/strength/routines/{routine_id}", json=routine, headers=other)).status_code, 200)
        self.assertEqual((await self.client.put(f"/strength/routines/{routine_id}", json=routine)).status_code, 409)

    async def test_pound_weights_round_trip(self):
        preference = await self.client.put("/strength/preferences", json={"weightUnit": "lb"})
        self.assertEqual(preference.json(), {"weightUnit": "lb"})
        routine_id = str(uuid.uuid4())
        item = {"id": str(uuid.uuid4()), "exerciseId": "0001", "weight": 30, "increment": 2.5}
        response = await self.client.put(
            f"/strength/routines/{routine_id}", json={"id": routine_id, "name": "Legs", "exercises": [item]}
        )
        saved = response.json()["exercises"][0]
        self.assertEqual((saved["weight"], saved["increment"]), (30, 2.5))
        bootstrap = (await self.client.get("/strength/bootstrap")).json()
        self.assertEqual(bootstrap["weightUnit"], "lb")

    async def test_delete_workout(self):
        workout = workout_body(date(2026, 9, 1))
        self.assertEqual((await self.client.post("/strength/workouts", json=workout)).status_code, 201)
        self.assertEqual((await self.client.delete(f"/strength/workouts/{workout['id']}")).status_code, 204)
        self.assertEqual((await self.client.get(f"/strength/workouts/{workout['id']}")).status_code, 404)
        self.assertEqual((await self.client.delete(f"/strength/workouts/{workout['id']}")).status_code, 404)

    async def test_analytics_windows_follow_the_client_date(self):
        day = date(2026, 9, 10)
        await self.client.post("/strength/workouts", json=workout_body(day))
        same_day = await self.client.get("/strength/analytics/muscles", params={"days": 1, "today": day.isoformat()})
        next_day = await self.client.get("/strength/analytics/muscles", params={"days": 1, "today": (day + timedelta(days=1)).isoformat()})
        self.assertTrue(same_day.json())
        self.assertEqual(next_day.json(), [])

    async def test_heatmap_levels_use_daily_totals(self):
        today = date(2026, 9, 30)
        for offset, minutes in enumerate((10, 20, 30, 40), start=1):
            await self.client.post("/strength/workouts", json=workout_body(today - timedelta(days=offset), minutes=minutes))
        busy_day = today - timedelta(days=5)
        for hour in range(3):
            ended = datetime.combine(busy_day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=8 + hour)
            await self.client.post("/strength/workouts", json=workout_body(busy_day, ended_at=ended, minutes=10))
        overview = (await self.client.get("/strength/analytics/overview", params={"today": today.isoformat()})).json()
        levels = {item["day"]: item["level"] for item in overview["heatmap"] if item["workoutCount"]}
        # Daily totals 10/20/30/30/40 -> quartiles 20/30/30; per-workout ones were 10/10/25.
        self.assertEqual(levels[(today - timedelta(days=1)).isoformat()], 1)
        self.assertEqual(levels[(today - timedelta(days=2)).isoformat()], 2)
        self.assertEqual(levels[busy_day.isoformat()], 4)

    async def test_one_rm_has_a_point_per_workout(self):
        ended = datetime(2026, 9, 5, 9, tzinfo=timezone.utc)
        for weight in (100, 105):
            await self.client.post("/strength/workouts", json=workout_body(ended.date(), ended_at=ended, weight=weight))
        exercises = (await self.client.get("/strength/analytics/one-rm", params={"today": "2026-09-30"})).json()
        self.assertEqual(len(exercises[0]["points"]), 2)

    # Account and platform

    async def test_account_deletion_removes_every_owned_row(self):
        await self.client.post("/sessions?compact=true", json=session_body())
        await self.client.post("/places", json={"name": "Home", "latitude": 41.4, "longitude": 2.1})
        await self.client.put("/strength/preferences", json={"weightUnit": "lb"})
        await self.sql(
            "INSERT INTO strength_exercises (id, owner_user_id, name, is_catalog) VALUES (:id, :u, 'Custom', false)",
            id=f"custom-{self.user}", u=self.user,
        )
        await self.client.post("/strength/workouts", json=workout_body(date(2026, 9, 1), exercise_id=f"custom-{self.user}"))
        routine_id = str(uuid.uuid4())
        await self.client.put(f"/strength/routines/{routine_id}", json={
            "id": routine_id, "name": "Custom", "exercises": [{"id": str(uuid.uuid4()), "exerciseId": f"custom-{self.user}"}],
        })

        self.assertEqual((await self.client.delete("/auth/me")).status_code, 204)
        self.assertEqual((await self.client.delete("/auth/me")).status_code, 204)
        leftovers = await self.sql(
            "SELECT (SELECT count(*) FROM auth.users WHERE id = :u)"
            " + (SELECT count(*) FROM sessions WHERE user_id = :u)"
            " + (SELECT count(*) FROM frequent_places WHERE user_id = :u)"
            " + (SELECT count(*) FROM strength_preferences WHERE user_id = :u)"
            " + (SELECT count(*) FROM strength_exercises WHERE owner_user_id = :u)"
            " + (SELECT count(*) FROM strength_workouts WHERE user_id = :u)"
            " + (SELECT count(*) FROM strength_routines WHERE user_id = :u)",
            u=self.user,
        )
        self.assertEqual(leftovers.scalar(), 0)

    async def test_oversized_body_is_rejected_before_auth(self):
        response = await self.client.post(
            "/sessions", content=b"x" * (16 * 1024 * 1024 + 1),
            headers={"content-type": "application/json", "x-test-user": ""},
        )
        self.assertEqual(response.status_code, 413)

    async def test_unhandled_errors_carry_the_request_id(self):
        async def boom():
            raise RuntimeError("boom")

        app.add_api_route("/_test/boom", boom)
        try:
            with self.assertLogs("workout_tracker.errors", level="ERROR") as logs:
                response = await self.client.get("/_test/boom")
        finally:
            app.router.routes.pop()
        self.assertEqual(response.status_code, 500)
        self.assertIn(response.headers["x-request-id"], logs.output[0])


if __name__ == "__main__":
    unittest.main()
