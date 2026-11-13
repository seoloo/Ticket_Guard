// 지표 전용 DB의 관리자로 명시 실행한다. 기존 계정은 덮어쓰지 않는다.
const target = db.getSiblingDB(process.env.FLOW_DATABASE || 'ticketguard_flow');
const writer = process.env.FLOW_WRITER_USERNAME;
const reader = process.env.FLOW_READER_USERNAME;
if (!writer || !reader || writer === reader || !process.env.FLOW_WRITER_PASSWORD || !process.env.FLOW_READER_PASSWORD) {
  throw new Error('서로 다른 읽기·쓰기 계정 설정 필요');
}
const role = 'flow_public_reader_v1';
for (const [name, from] of [['flow_read_current', 'flow_versions'], ['flow_read_series', 'flow_series']]) {
  if (!target.getCollectionInfos({name}).length) target.createView(name, 'flow_public', [
    {$lookup: {from, localField: 'version', foreignField: from === 'flow_versions' ? '_id' : 'version', as: 'result'}},
    {$unwind: '$result'}
  ]);
}
if (!target.getRole(role)) {
  target.createRole({role, privileges: ['flow_read_current', 'flow_read_series', 'flow_health'].map(collection => (
    {resource: {db: target.getName(), collection}, actions: ['find']}
  )), roles: []});
}
if (!target.getUser(writer)) target.createUser({user: writer, pwd: process.env.FLOW_WRITER_PASSWORD, roles: [{role: 'readWrite', db: target.getName()}]});
if (!target.getUser(reader)) target.createUser({user: reader, pwd: process.env.FLOW_READER_PASSWORD, roles: [{role, db: target.getName()}]});
