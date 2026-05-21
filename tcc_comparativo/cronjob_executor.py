import os
import glob
import csv
from time import time
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from dotenv import load_dotenv
import logging
import shutil

script_dir = os.path.dirname(os.path.abspath(__file__))

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"{script_dir}/logs/batch_processor.log"),
        logging.StreamHandler(),
    ],
)

load_dotenv()

PG_TABLE = (os.getenv("PG_TABLE", "sensor_data"),)


class CronBatchProcessor:
    def __init__(self):
        self.batch_dir = f"{script_dir}/batches_output"
        self.processed_dir = f"{script_dir}/batches_processed"
        self.connection = None
        self.cursor = None

        # Cria diretórios se não existirem
        os.makedirs(self.processed_dir, exist_ok=True)

        self.connect_to_db()

    def connect_to_db(self):
        """Conecta ao PostgreSQL"""
        try:
            self.connection = psycopg2.connect(
                dbname=os.getenv("PG_DB", "iot_batch"),
                user=os.getenv("PG_USER", "grafana"),
                password=os.getenv("PG_PASSWORD", "grafana"),
                host=os.getenv("PG_HOST", "localhost"),
                port=os.getenv("PG_PORT", "5432"),
            )
            self.cursor = self.connection.cursor()
            logging.info("✅ Conectado ao PostgreSQL")
        except Exception as e:
            logging.error(f"❌ Erro ao conectar PostgreSQL: {e}")
            raise

    def find_csv_files(self):
        """Encontra todos os arquivos CSV pendentes"""
        pattern = os.path.join(self.batch_dir, "*.csv")
        csv_files = glob.glob(pattern)
        logging.info(f"🔍 Encontrados {len(csv_files)} arquivos CSV para processar")
        return sorted(csv_files)  # Processa em ordem cronológica

    def process_csv_file(self, filepath):
        """Processa um arquivo CSV individual"""
        start_time = datetime.now()
        batch_id = os.path.basename(filepath).replace(".csv", "")
        records_processed = 0

        try:
            logging.info(f"📝 Processando: {filepath}")

            with open(filepath, "r", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)
                batch_data = []

                for row in reader:
                    # (sensor_id, production_line_id, location, metric, unit, ingested_at , value, created_at, batch_id)

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

                # Bulk insert
                if batch_data:
                    self.bulk_insert(batch_data)

            # Move arquivo para pasta processada
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
        """Insere dados em lote no PostgreSQL"""
        insert_query = f"""
            INSERT INTO sensor_data_4x
            (sensor_id, production_line_id, location, metric, unit, ingested_at , value, created_at, batch_id)
            VALUES %s
        """
        try:
            psycopg2.extras.execute_values(
                self.cursor, insert_query, batch_data, page_size=1000
            )

            if self.connection:
                self.connection.commit()

        except Exception as e:
            logging.error(f"❌ Erro no bulk insert: {e}")

            if self.connection:
                self.connection.rollback()
            raise

    def move_processed_file(self, filepath):
        """Move arquivo processado para pasta de arquivo"""
        try:
            filename = os.path.basename(filepath)
            new_path = os.path.join(self.processed_dir, filename)
            shutil.move(filepath, new_path)
            logging.info(f"📁 Arquivo movido para: {new_path}")
        except Exception as e:
            logging.warning(f"⚠️ Erro ao mover arquivo: {e}")

    def run(self):
        """Execução principal - processa todos os CSVs pendentes"""
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
                f"🎯 EXECUÇÃO CONCLUÍDA: {total_files} arquivos, "
                f"{total_records} registros em {execution_time:.2f}s"
            )

        except Exception as e:
            logging.error(f"❌ Erro na execução: {e}")
        finally:
            self.close()

    def close(self):
        """Fecha conexões"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()


def main():
    processor = CronBatchProcessor()
    processor.run()


if __name__ == "__main__":
    main()
