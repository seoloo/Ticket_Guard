"""No record reads or writes: local Spark, metadata, auth and volume probes."""
import os
import platform
import socket
import tempfile
from pathlib import Path
import pymongo
from mongo_writer import client_for


def worker_import_check(_):
    import pymongo
    import records
    import mongo_writer
    import settings
    return pymongo.version == '4.15.5' and callable(records.document) and callable(mongo_writer.write_partition)


def check(spark, config):
    jvm = spark.sparkContext._jvm
    loader = jvm.java.lang.Thread.currentThread().getContextClassLoader()
    loader.loadClass('org.apache.spark.sql.kafka010.KafkaSourceProvider')
    loader.loadClass('org.apache.kafka.clients.admin.AdminClient')
    print(f'check versions spark={spark.version} python={platform.python_version()} '
          f'java={jvm.java.lang.System.getProperty("java.version")} '
          f'scala={jvm.scala.util.Properties.versionNumberString()} pymongo={pymongo.version}', flush=True)
    if spark.range(10).count() != 10:
        raise RuntimeError('Local Spark job failed')
    results = spark.sparkContext.parallelize([0, 1], 2).map(worker_import_check).fold(True, lambda a, b: a and b)
    if not results:
        raise RuntimeError('Python worker import check failed')
    print('check local_spark_connector_worker_imports OK', flush=True)

    print('check kafka_metadata begin', flush=True)
    props = jvm.java.util.Properties()
    props.setProperty('bootstrap.servers', config.kafka)
    props.setProperty('request.timeout.ms', str(config.timeout_ms))
    props.setProperty('default.api.timeout.ms', str(config.timeout_ms))
    admin = jvm.org.apache.kafka.clients.admin.AdminClient.create(props)
    try:
        topics = jvm.java.util.Collections.singletonList(config.topic)
        description = admin.describeTopics(topics).allTopicNames().get().get(config.topic)
        if description.partitions().size() < 1:
            raise RuntimeError('No Kafka partitions')
        print(f'check kafka_metadata OK partitions={description.partitions().size()}', flush=True)
    finally:
        admin.close()

    print('check mongo_target begin', flush=True)
    address = socket.gethostbyname(config.mongo_host)
    expected = os.environ.get('SPARK_EXPECTED_MONGO_IP')
    if expected and address != expected:
        raise RuntimeError('MongoDB DNS target differs from inspected workspace DB')
    with client_for(config) as client:
        db = client[config.database]
        db.command('ping')
        roles = db.command('connectionStatus')['authInfo']['authenticatedUserRoles']
        if len(roles) != 1 or roles[0] != {'role': 'readWrite', 'db': config.database}:
            raise RuntimeError('Unexpected writer roles')
    print(f'check mongo_writer OK host={config.mongo_host} ip={address}', flush=True)

    folder = Path(config.checkpoint)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=folder) as handle:
        handle.write(b'checkpoint-permission-probe')
        handle.flush()
        os.fsync(handle.fileno())
    print('check checkpoint_permissions OK', flush=True)
    if spark.streams.active:
        raise RuntimeError('Unexpected active streaming query')
    print('check complete: no Kafka records consumed and no MongoDB writes', flush=True)
