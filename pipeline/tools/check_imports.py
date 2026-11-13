"""외부 DB·Kafka 연결 없이 진입점과 Spark 작업자의 모듈 경로를 확인한다."""
from pyspark.sql import SparkSession
import main
from tools.check import worker_import_check
from user_flow.runtime import Processor


def check_imports():
    spark = SparkSession.builder.getOrCreate()
    try:
        assert callable(main.main) and callable(Processor.batch)
        if spark.sparkContext.parallelize([1], 1).map(worker_import_check).collect() != [True]:
            raise RuntimeError('Spark 작업자 모듈 경로 확인 실패')
        print('진입점·Spark 작업자 모듈 확인 완료', flush=True)
    finally:
        spark.stop()


if __name__ == '__main__':
    check_imports()
