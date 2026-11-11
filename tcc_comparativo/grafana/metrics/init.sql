CREATE EXTENSION IF NOT EXISTS file_fdw;
CREATE SERVER metric_files FOREIGN DATA WRAPPER file_fdw;

CREATE FOREIGN TABLE confirmed_batch (
    message_id text,
    created_at_ms bigint,
    confirmed_at_ms bigint,
    created_mono_ns bigint,
    confirmed_mono_ns bigint,
    clock_id text
) SERVER metric_files OPTIONS (filename '/metrics/latency_batch.csv', format 'csv');

CREATE FOREIGN TABLE confirmed_stream (
    message_id text,
    created_at_ms bigint,
    confirmed_at_ms bigint,
    created_mono_ns bigint,
    confirmed_mono_ns bigint,
    clock_id text
) SERVER metric_files OPTIONS (filename '/metrics/latency_stream.csv', format 'csv');
