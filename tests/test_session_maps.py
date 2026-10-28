import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from api.session_maps import make_preview, segment_sections


class SessionMapPreviewTests(unittest.TestCase):
    def test_filters_diagnostic_points_and_bounds_resolutions(self):
        started = datetime.now(timezone.utc)
        points = [
            {"lat": 41.0 + index * 0.00001, "lon": 2.0, "display": True}
            for index in range(1_200)
        ]
        points.insert(10, {"lat": 0, "lon": 0, "display": False})
        segment = SimpleNamespace(
            id=uuid4(), idx=0, started_at=started, ended_at=started,
            steps=100, points=points,
        )
        session = SimpleNamespace(id=uuid4(), user_id=uuid4())

        sections = segment_sections([segment])
        preview = make_preview(session, sections)

        self.assertNotIn([0.0, 0.0], sections[0]["coordinates"])
        self.assertLessEqual(sum(len(s["coordinates"]) for s in preview.preview_sections), 50)
        self.assertLessEqual(sum(len(s["coordinates"]) for s in preview.map_sections), 300)
        self.assertLessEqual(sum(len(s["coordinates"]) for s in preview.detail_sections), 1_000)

    def test_preserves_two_point_section(self):
        started = datetime.now(timezone.utc)
        segment = SimpleNamespace(
            id=uuid4(), idx=0, started_at=started, ended_at=None, steps=0,
            points=[{"lat": 41, "lon": 2}, {"lat": 41.1, "lon": 2.1}],
        )
        session = SimpleNamespace(id=uuid4(), user_id=uuid4())
        preview = make_preview(session, segment_sections([segment]))
        self.assertEqual(len(preview.preview_sections[0]["coordinates"]), 2)

    def test_caps_hold_with_many_sections(self):
        sections = [
            {"coordinates": [[41 + index * 1e-3 + step * 1e-4, 2 + (step % 2) * 1e-4] for step in range(3 + index % 7)]}
            for index in range(40)
        ]
        sections.append({"coordinates": [[42 + step * 1e-4, 2 + (step % 2) * 1e-4] for step in range(500)]})
        preview = make_preview(SimpleNamespace(id=uuid4(), user_id=uuid4()), sections)
        for variant, cap in ((preview.preview_sections, 50), (preview.map_sections, 300), (preview.detail_sections, 1_000)):
            self.assertLessEqual(sum(len(s["coordinates"]) for s in variant), cap)
            self.assertTrue(all(len(s["coordinates"]) >= 2 for s in variant))
        # The longest section survives the preview's section budget.
        self.assertIn([42.0, 2.0], preview.preview_sections[-1]["coordinates"])


if __name__ == "__main__":
    unittest.main()
