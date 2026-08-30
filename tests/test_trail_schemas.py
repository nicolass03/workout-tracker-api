import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import ValidationError

from api.schemas.sessions import CanonicalTrailUpsert, TraceChunkUpsert


class TrailSchemaTests(unittest.TestCase):
    def sample(self, session_id, section_id, sequence, timestamp):
        return {
            "session_id": session_id,
            "section_id": section_id,
            "sequence": sequence,
            "timestamp": timestamp,
            "received_at": timestamp,
            "latitude": 41.4,
            "longitude": 2.1,
            "horizontal_accuracy": 7,
            "is_stationary": False,
            "is_full_accuracy": True,
            "is_simulated_by_software": False,
            "is_produced_by_accessory": False,
            "quality": "usable",
        }

    def test_trace_chunk_accepts_ordered_samples(self):
        now = datetime.now(timezone.utc)
        session_id = uuid4()
        section_id = uuid4()
        chunk = TraceChunkUpsert(
            first_at=now,
            last_at=now + timedelta(seconds=1),
            checksum_sha256="a" * 64,
            samples=[
                self.sample(session_id, section_id, 1, now),
                self.sample(session_id, section_id, 2, now + timedelta(seconds=1)),
            ],
        )
        self.assertEqual(len(chunk.samples), 2)

    def test_trace_chunk_rejects_reordered_sequences(self):
        now = datetime.now(timezone.utc)
        session_id = uuid4()
        section_id = uuid4()
        with self.assertRaises(ValidationError):
            TraceChunkUpsert(
                first_at=now,
                last_at=now + timedelta(seconds=1),
                checksum_sha256="b" * 64,
                samples=[
                    self.sample(session_id, section_id, 2, now),
                    self.sample(session_id, section_id, 1, now + timedelta(seconds=1)),
                ],
            )

    def test_route_rejects_single_point_sections(self):
        with self.assertRaises(ValidationError):
            CanonicalTrailUpsert(
                algorithm_version="trail-v2.1",
                status="gpsOnly",
                confidence=0.8,
                distance_meters=1,
                sections=[{
                    "id": uuid4(),
                    "source": "filteredGPS",
                    "confidence": 0.8,
                    "coordinates": [{"latitude": 41.4, "longitude": 2.1}],
                }],
                processed_at=datetime.now(timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
