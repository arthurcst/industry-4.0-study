import os
import glob
import csv
from time import time, monotonic_ns
import psycopg2
import psycopg2.extras
from datetime import datetime
from dotenv import load_dotenv
from utils.latency_metrics import record_confirmed_batch
import logging
import shutil

script_dir = os.path.dirname(os.path.abspath(__file__))
logs_dir = os.path.join(script_dir, "logs")
os.makedirs(logs_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

load_dotenv()
load_dotenv("/app/cron.env", override=True)

EXPERIMENT_LABEL = os.getenv("EXPERIMENT_LABEL", "completa")
PG_TABLE = os.getenv("PG_TABLE", "sensor_data")


class CronBatchProcessor:
    def __init__(self):
        self.batch_dir = os.getenv("BATCH_OUTPUT_DIR", f"{script_dir}/batches_output")
        self.processed_dir = os.getenv(
            "BATCH_PROCESSED_DIR", f"{script_dir}/batches_processed"
        )
        self.connection = None
        self.cursor = None

        os.makedirs(self.processed_dir, exist_ok=True)
        self.connect_to_db()

    def connect_to_db(self):
        try:
            self.connection = psycopg2.connect(
                dbname=os.getenv("PG_DB", "iot_batch"),
                user=os.getenv("PG_USER", "grafana"),
                password=os.getenv("PG_PASSWORD", "grafana"),
                host=os.getenv("PG_HOST", "localhost"),
                port=os.getenv("PG_PORT", "5432"),
            )
            self.cursor = self.connection.cursor()
            logging.info(
                f"✅ Conectado ao PostgreSQL (tabela={PG_TABLE}, exp={EXPERIMENT_LABEL})"
            )
        except Exception as e:
            logging.error(f"❌ Erro ao conectar PostgreSQL: {e}")
            raise

    def find_csv_files(self):
        pattern = os.path.join(self.batch_dir, "*.csv")
        csv_files = glob.glob(pattern)
        logging.info(f"🔍 Encontrados {len(csv_files)} arquivos CSV para processar")
        return sorted(csv_files)

    def process_csv_file(self, filepath):
        start_time = datetime.now()
        batch_id = os.path.basename(filepath).replace(".csv", "")
        records_processed = 0

        try:
            logging.info(f"📝 Processando: {filepath}")

            with open(filepath, "r", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                batch_data = []
                latency_records = []

                for row in reader:
                    batch_data.append(
                        (
                            row.get("sensor_id"),
                            row.get("production_line_id"),
                            row.get("location"),
                            row.get("metric"),
                            row.get("unit"),
                            int(time() * 1000),
                            str(row.get("value", 0)),
                            row.get("created_at"),
                            batch_id,
                        )
                    )
                    records_processed += 1
                    latency_records.append((row.get("id"), row.get("created_at"), row.get("created_mono_ns"), row.get("clock_id")))

                if batch_data:
                    self.bulk_insert(batch_data)
                    confirmed_mono_ns = monotonic_ns()
                    confirmed_at_ms = int(time() * 1000)
                    try:
                        record_confirmed_batch("batch", latency_records, confirmed_at_ms, confirmed_mono_ns)
                    except Exception as exc:
                        logging.error("LATENCY ERROR: confirmação não registrada para %s mensagens: %s", len(latency_records), exc)

            self.move_processed_file(filepath)

            processing_time = (datetime.now() - start_time).total_seconds()
            throughput = (
                records_processed / processing_time if processing_time > 0 else 0
            )

            logging.info(
                f"✅ {batch_id} processado: {records_processed} registros "
                f"em {processing_time:.2f}s ({throughput:.2f} records/s)"
            )

            return records_processed, processing_time

        except Exception as e:
            logging.error(f"❌ Erro ao processar {filepath}: {e}")

            if self.connection:
                self.connection.rollback()

            return 0, 0

    def bulk_insert(self, batch_data):
        insert_query = f"""
            INSERT INTO {PG_TABLE}
            (sensor_id, production_line_id, location, metric, unit, ingested_at, value, created_at, batch_id)
            VALUES %s
        """
        try:
            psycopg2.extras.execute_values(
                self.cursor, insert_query, batch_data, page_size=1000
            )

            if self.connection:
                self.connection.commit()

        except Exception as e:
            logging.error(f"❌ Erro no bulk insert em {PG_TABLE}: {e}")

            if self.connection:
                self.connection.rollback()
            raise

    def move_processed_file(self, filepath):
        try:
            filename = os.path.basename(filepath)
            new_path = os.path.join(self.processed_dir, filename)
            shutil.move(filepath, new_path)
            logging.info(f"📁 Arquivo movido para: {new_path}")
        except Exception as e:
            logging.warning(f"⚠️ Erro ao mover arquivo: {e}")

    def run(self):
        execution_start = datetime.now()

        try:
            csv_files = self.find_csv_files()

            if not csv_files:
                logging.info("ℹ️ Nenhum arquivo CSV encontrado para processar")
                return

            total_records = 0
            total_files = len(csv_files)

            for csv_file in csv_files:
                records, _ = self.process_csv_file(csv_file)
                total_records += records

            execution_time = (datetime.now() - execution_start).total_seconds()

            logging.info(
                f"🎯 EXECUÇÃO CONCLUÍDA [{EXPERIMENT_LABEL}]: {total_files} arquivos, "
                f"{total_records} registros em {execution_time:.2f}s → {PG_TABLE}"
            )

        except Exception as e:
            logging.error(f"❌ Erro na execução: {e}")
        finally:
            self.close()

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()


def main():
    processor = CronBatchProcessor()
    processor.run()


if __name__ == "__main__":
    main()
