"""
[홍석환] Kafka 이벤트 토픽 초기화 명령
설정된 토픽과 보관 정책을 준비하고 실행 환경의 구성을 확인한다.
"""
import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create topic idempotently, report drift without changing existing data.'

    def handle(self,*args,**options):
        from confluent_kafka import KafkaException, KafkaError
        from confluent_kafka.admin import AdminClient, NewTopic, ConfigResource, ResourceType
        admin=AdminClient({'bootstrap.servers':settings.KAFKA_BOOTSTRAP_SERVERS,'socket.timeout.ms':10000})
        topic=settings.KAFKA_EVENTS_TOPIC
        config={'cleanup.policy':'delete','retention.ms':os.environ.get('KAFKA_RETENTION_MS','604800000'),
                'retention.bytes':os.environ.get('KAFKA_RETENTION_BYTES','268435456'),
                'segment.bytes':'67108864','segment.ms':'3600000','min.insync.replicas':'1'}
        if any(int(config[k])<=0 for k in ('retention.ms','retention.bytes')):
            raise CommandError('Retention must be positive and bounded.')
        try:
            admin.create_topics([NewTopic(topic,num_partitions=3,replication_factor=1,config=config)],request_timeout=20)[topic].result(timeout=25)
            self.stdout.write('Created '+topic)
        except KafkaException as exc:
            if exc.args[0].code()!=KafkaError.TOPIC_ALREADY_EXISTS:
                raise CommandError('Topic initialization failed, code='+str(exc.args[0].code())) from None
            self.stdout.write('Topic exists: settings/data retained.')
        metadata=admin.list_topics(topic,timeout=10).topics[topic]
        if metadata.error: raise CommandError('Topic metadata unavailable.')
        resource=ConfigResource(ResourceType.TOPIC,topic)
        actual=admin.describe_configs([resource],request_timeout=10)[resource].result(timeout=15)
        drift={k:{'actual':actual[k].value,'requested':v} for k,v in config.items() if actual[k].value!=v}
        if len(metadata.partitions)!=3 or any(len(p.replicas)!=1 for p in metadata.partitions.values()):
            drift['topology']='Existing topology differs from 3 partitions / RF 1.'
        if drift: self.stdout.write(self.style.WARNING('Drift (not altered): '+str(drift)))
        self.stdout.write('Ready: '+topic+', partitions='+str(len(metadata.partitions)))
