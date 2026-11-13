"""
[홍석환] Spark 빌드 의존성 확인
이미지 빌드 중 Spark를 시작·종료해 연결 라이브러리 의존성을 준비한다.
운영 이벤트를 읽거나 저장하지 않는다.
"""
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName('connector-build').getOrCreate()
spark.stop()
