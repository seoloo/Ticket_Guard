"""
[홍석환] Kafka와 MongoDB 사이의 Spark 처리 진입점
실행 모드에 따라 환경 점검 또는 스트리밍 적재를 시작하고 종료를 관리한다.
"""
import logging
import signal
import sys
from functools import partial
from pyspark.sql import SparkSession
from configuration.ingest import Settings
from ingestion.mongo_writer import write_batch


def main():
    if sys.argv[1:] == ['flow']:
        from user_flow.runtime import run
        try:
            run()
            return 0
        except Exception as exc:
            print(f'flow failed error_class={type(exc).__name__}', flush=True)
            return 1
    spark = None
    query = None
    stopping = False
    failed = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        print(f'pipeline stop_requested signal={signum}', flush=True)
        if query is not None:
            query.stop()

    try:
        mode = sys.argv[1] if len(sys.argv) == 2 else ''
        if mode not in ('ingest', 'check'):
            raise ValueError('Use ingest or check')
        try:
            config = Settings.load()
        except ValueError as exc:
            print(f'pipeline configuration_error: {exc}', flush=True)
            return 1
        logging.getLogger('pymongo').setLevel(logging.CRITICAL)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        spark = (SparkSession.builder.appName('ticketguard-raw-' + mode)
                 .config('spark.sql.session.timeZone', 'UTC')
                 .config('spark.sql.shuffle.partitions', '2')
                 .config('spark.sql.execution.pyspark.udf.simplifiedTraceback.enabled', 'true')
                 .config('spark.redaction.regex', '(?i)secret|password|token|username|uri')
                 .getOrCreate())
        print(f'pipeline ready mode={mode}', flush=True)
        if mode == 'check':
            from tools.check import check
            check(spark, config)
        elif not stopping:
            source = (spark.readStream.format('kafka')
                      .option('kafka.bootstrap.servers', config.kafka)
                      .option('kafka.group.id', config.group_id)
                      .option('subscribe', config.topic)
                      .option('startingOffsets', 'earliest')
                      .option('failOnDataLoss', 'true')
                      .option('kafka.allow.auto.create.topics', 'false')
                      .option('maxOffsetsPerTrigger', config.max_offsets)
                      .load())
            query = (source.writeStream.queryName('ticketguard-raw-events')
                     .foreachBatch(partial(write_batch, config=config))
                     .option('checkpointLocation', config.checkpoint)
                     .trigger(processingTime=f'{config.interval} seconds').start())
            print('pipeline ingest_started', flush=True)
            if stopping:
                query.stop()
            else:
                query.awaitTermination()
    except Exception as exc:
        if not stopping:
            # Full Spark/PyMongo exceptions can contain records or credentials.
            print(f'pipeline failed error_class={type(exc).__name__}', flush=True)
            failed = True
    finally:
        try:
            if query is not None and query.isActive:
                query.stop()
        except Exception:
            print('pipeline query_cleanup_failed', flush=True)
            failed = True
        finally:
            if spark is not None:
                try:
                    spark.stop()
                except Exception:
                    print('pipeline spark_cleanup_failed', flush=True)
                    failed = True
        print('pipeline stopped', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
