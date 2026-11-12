# [홍석환] Spark 처리 이미지 구성
# MongoDB 의존성과 Kafka 연결 라이브러리를 설치하고 Spark 실행 진입점을 구성한다.
FROM spark:3.5.8-scala2.12-java17-python3-ubuntu@sha256:5363cd7d22758958565206f67a764356ebebb9fa8f5721e9c55aa86a78efafda
USER root
COPY requirements.txt /tmp/pipeline-requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/pipeline-requirements.txt
# Resolve all Kafka connector dependencies at build time, not at stream startup.
COPY resolve.py /tmp/resolve.py
RUN /opt/spark/bin/spark-submit --master 'local[1]' \
    --conf spark.driver.host=127.0.0.1 --conf spark.ui.enabled=false \
    --conf spark.jars.ivy=/tmp/ivy \
    --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.8 /tmp/resolve.py \
    && cp /tmp/ivy/jars/*.jar /opt/spark/jars/ \
    && rm -rf /tmp/ivy /tmp/resolve.py
RUN mkdir -p /checkpoints/events /opt/pipeline \
    && chown -R 185:0 /checkpoints /opt/pipeline
COPY --chown=185:0 . /opt/pipeline/
COPY log4j2.properties /opt/spark/conf/log4j2.properties
ENV PYTHONPATH=/opt/pipeline TZ=UTC PYSPARK_PYTHON=python3 PYSPARK_DRIVER_PYTHON=python3
WORKDIR /opt/pipeline
USER 185
ENTRYPOINT ["/opt/spark/bin/spark-submit", "--master", "local[2]", "--conf", "spark.ui.enabled=false", "/opt/pipeline/main.py"]
CMD ["ingest"]
