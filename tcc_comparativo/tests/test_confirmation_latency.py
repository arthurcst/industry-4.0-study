import csv
import os
import tempfile
import unittest
import json
from unittest.mock import Mock, patch

import async_consumer_v2 as stream
import cronjob_executor as batch
import batch_consumer as batch_receiver
from sensors.clock_context import CLOCK_ID


class ConfirmationLatencyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"EXPERIMENT_METRICS_DIR": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.pending = patch.object(stream, "PENDING_DIR", os.path.join(self.temp.name, "pending"))
        self.pending.start()
        self.addCleanup(self.pending.stop)
        stream.STOP_EVENT.clear()
        stream.FATAL_ERROR.clear()

    def read_records(self, approach):
        with open(os.path.join(self.temp.name, f"latency_{approach}.csv"), newline="") as source:
            return list(csv.reader(source))

    def test_stream_records_after_success_only(self):
        payloads = [{"id": "a", "created_at": 100, "created_mono_ns": 100000000, "clock_id": CLOCK_ID}, {"id": "b", "created_at": 150, "created_mono_ns": 150000000, "clock_id": CLOCK_ID}]
        with patch.object(stream.write_api, "write") as write, patch.object(stream, "time", return_value=0.2), patch.object(stream.std_time, "monotonic_ns", return_value=200000000):
            stream.write_points([Mock(), Mock()], payloads)
        write.assert_called_once()
        self.assertEqual(self.read_records("stream"), [["a", "100", "200", "100000000", "200000000", CLOCK_ID], ["b", "150", "200", "150000000", "200000000", CLOCK_ID]])

    def test_stream_does_not_record_failed_writes(self):
        with patch.object(stream.write_api, "write", side_effect=RuntimeError("failure")), patch.object(stream.std_time, "sleep"):
            stream.write_points([Mock()], [{"id": "a", "created_at": 100}])
        self.assertFalse(os.path.exists(os.path.join(self.temp.name, "latency_stream.csv")))
        paths = stream.pending_files()
        self.assertEqual(len(paths), 1)
        with open(paths[0], encoding="utf-8") as source:
            self.assertEqual(json.load(source), [{"id": "a", "created_at": 100}])

    def test_wall_clock_can_move_back_without_negative_monotonic_latency(self):
        payload = {"id": "clock", "created_at": 300, "created_mono_ns": 100000000, "clock_id": CLOCK_ID}
        with patch.object(stream.write_api, "write"), patch.object(stream, "time", return_value=0.2), patch.object(stream.std_time, "monotonic_ns", return_value=200000000):
            stream.write_points([Mock()], [payload])
        row = self.read_records("stream")[0]
        self.assertEqual(int(row[2]) - int(row[1]), -100)
        self.assertEqual(int(row[4]) - int(row[3]), 100000000)

    def test_incompatible_clock_context_is_rejected(self):
        payload = {"id": "clock", "created_at": 100, "created_mono_ns": 100, "clock_id": "other-boot"}
        with patch.object(stream.write_api, "write"):
            stream.write_points([Mock()], [payload])
        self.assertTrue(stream.FATAL_ERROR.is_set())

    def test_stream_recovers_pending_after_outage(self):
        payload = {"id": "a", "created_at": 100, "sensor_id": "s", "location": "l",
                   "production_line_id": "p", "metric": "temperature", "unit": "C", "value": 3,
                   "created_mono_ns": 100000000, "clock_id": CLOCK_ID}
        stream.save_pending([payload])
        with patch.object(stream.write_api, "write") as write, patch.object(stream, "time", return_value=0.2), patch.object(stream.std_time, "monotonic_ns", return_value=200000000):
            stream.retry_pending()
        write.assert_called_once()
        self.assertEqual(stream.pending_files(), [])
        self.assertEqual(self.read_records("stream"), [["a", "100", "200", "100000000", "200000000", CLOCK_ID]])
        point = stream.payload_to_point(payload)
        self.assertTrue(point.to_line_protocol().endswith(" 100"))
        self.assertEqual(point.write_precision, stream.WritePrecision.MS)

    def test_batch_restores_buffer_if_csv_write_fails(self):
        batch_receiver.BUFFER.clear()
        batch_receiver.BUFFER.extend([{"id": "a"}, {"id": "b"}])
        with patch.object(batch_receiver, "write_batch_to_csv", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                batch_receiver.flush_buffer()
        self.assertEqual(list(batch_receiver.BUFFER), [{"id": "a"}, {"id": "b"}])
        batch_receiver.BUFFER.clear()

    def test_batch_records_only_after_commit(self):
        path = os.path.join(self.temp.name, "batch.csv")
        with open(path, "w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["id", "created_at", "value", "created_mono_ns", "clock_id"])
            writer.writeheader()
            writer.writerow({"id": "c", "created_at": "100", "value": "1", "created_mono_ns": "100000000", "clock_id": CLOCK_ID})
        processor = batch.CronBatchProcessor.__new__(batch.CronBatchProcessor)
        processor.connection = Mock()
        processor.bulk_insert = Mock()
        processor.move_processed_file = Mock()
        with patch.object(batch, "time", return_value=0.2), patch.object(batch, "monotonic_ns", return_value=200000000):
            count, _ = processor.process_csv_file(path)
        self.assertEqual(count, 1)
        processor.bulk_insert.assert_called_once()
        self.assertEqual(self.read_records("batch"), [["c", "100", "200", "100000000", "200000000", CLOCK_ID]])

    def test_batch_does_not_record_failed_commit(self):
        path = os.path.join(self.temp.name, "batch.csv")
        with open(path, "w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["id", "created_at", "value"])
            writer.writeheader()
            writer.writerow({"id": "c", "created_at": "100", "value": "1"})
        processor = batch.CronBatchProcessor.__new__(batch.CronBatchProcessor)
        processor.connection = Mock()
        processor.bulk_insert = Mock(side_effect=RuntimeError("commit failure"))
        processor.move_processed_file = Mock()
        processor.process_csv_file(path)
        processor.move_processed_file.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.temp.name, "latency_batch.csv")))


if __name__ == "__main__":
    unittest.main()
