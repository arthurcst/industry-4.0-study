"""A falha real de inserção não deve produzir confirmação nem mover o arquivo."""

import csv
import os
import sys
import tempfile

sys.path.insert(0, "/app")
import cronjob_executor as batch


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["BATCH_OUTPUT_DIR"] = directory
        os.environ["BATCH_PROCESSED_DIR"] = os.path.join(directory, "processed")
        path = os.path.join(directory, "failure.csv")
        with open(path, "w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=["id", "created_at", "value"])
            writer.writeheader()
            writer.writerow({"id": "failure-check-batch", "created_at": "1700000000000", "value": "1"})

        batch.PG_TABLE = "integration_nonexistent_table"
        processor = batch.CronBatchProcessor()
        try:
            count, _ = processor.process_csv_file(path)
        finally:
            processor.close()
        assert count == 0 and os.path.exists(path), "Falha no banco foi tratada como sucesso"
        with open("/app/metrics/latency_batch.csv", encoding="utf-8") as source:
            assert "failure-check-batch" not in source.read(), "Confirmação falsa após erro do PostgreSQL"
        print("Erro real de inserção no PostgreSQL não gerou confirmação falsa; arquivo permaneceu pendente.")


if __name__ == "__main__":
    main()
