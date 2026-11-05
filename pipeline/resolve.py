"""Build-time dependency resolution only; no external sources or streaming."""
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName('connector-build').getOrCreate()
spark.stop()
