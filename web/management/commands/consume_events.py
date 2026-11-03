import json
import time
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from web.event_schema import validate_event


class Command(BaseCommand):
    help='Bounded diagnostic consumer; no persistence and no committed offsets.'
    def add_arguments(self,parser):
        parser.add_argument('--group',required=True)
        parser.add_argument('--max-messages',type=int,default=10)
        parser.add_argument('--timeout',type=int,default=20)
        parser.add_argument('--from-beginning',action='store_true')

    def handle(self,*args,**options):
        from confluent_kafka import Consumer, OFFSET_BEGINNING, OFFSET_END
        if not options['group'].startswith('ticketguard-debug-'):
            raise CommandError('Use a dedicated ticketguard-debug-* group.')
        if not 1<=options['max_messages']<=10000 or not 1<=options['timeout']<=300:
            raise CommandError('max-messages 1..10000, timeout 1..300 required.')
        consumer=Consumer({'bootstrap.servers':settings.KAFKA_BOOTSTRAP_SERVERS,'group.id':options['group'],
                           'enable.auto.commit':False,'auto.offset.reset':'earliest' if options['from_beginning'] else 'latest',
                           'allow.auto.create.topics':False})
        def assign(c,parts):
            for part in parts: part.offset=OFFSET_BEGINNING if options['from_beginning'] else OFFSET_END
            c.assign(parts)
            self.stderr.write('Consumer assigned; ready for events.')
        consumer.subscribe([settings.KAFKA_EVENTS_TOPIC],on_assign=assign)
        count=0
        deadline=time.monotonic()+options['timeout']
        try:
            while count<options['max_messages'] and time.monotonic()<deadline:
                message=consumer.poll(.5)
                if message is None: continue
                if message.error():
                    self.stderr.write('Consumer error code='+str(message.error().code()))
                    continue
                item={'topic':message.topic(),'partition':message.partition(),'offset':message.offset()}
                try:
                    event=json.loads(message.value())
                    validate_event(event)
                    item.update(key=message.key().decode() if message.key() else None,event=event)
                except (ValueError,TypeError,UnicodeDecodeError): item['error']='invalid event; payload suppressed'
                self.stdout.write(json.dumps(item,ensure_ascii=False))
                count+=1
        finally: consumer.close()
        self.stderr.write('Read '+str(count)+' message(s). No offsets committed.')
