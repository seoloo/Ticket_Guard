/*
[홍석환] 지표 DB 공개 뷰와 최소 읽기 권한 준비
기존 구성을 먼저 검사하고 FLOW_APPLY_SETUP=1인 경우에만 없는 항목을 생성한다.
*/
// 지표 전용 DB의 관리자로 명시 실행한다. 기존 계정은 덮어쓰지 않는다.
const target = db.getSiblingDB(process.env.FLOW_DATABASE || 'ticketguard_flow');
const writer = process.env.FLOW_WRITER_USERNAME;
const reader = process.env.FLOW_READER_USERNAME;
if (!/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(target.getName()) || ['admin','local','config'].includes(target.getName())) {
  throw new Error('지표 전용 DB 이름 확인 필요');
}
if (!writer || !reader || writer === reader || !process.env.FLOW_WRITER_PASSWORD || !process.env.FLOW_READER_PASSWORD) {
  throw new Error('서로 다른 읽기·쓰기 계정 설정 필요');
}
if ([writer, reader].includes(process.env.MONGO_INITDB_ROOT_USERNAME)) {
  throw new Error('관리자와 지표 읽기·쓰기 계정은 분리해야 한다');
}
const role = 'flow_public_reader_v1';
const apply = process.env.FLOW_APPLY_SETUP === '1';
if (process.env.MONGO_INITDB_ROOT_USERNAME && process.env.MONGO_INITDB_ROOT_PASSWORD) {
  if (!db.getSiblingDB('admin').auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD)) {
    throw new Error('DB 관리자 인증 실패');
  }
}
const views = [['flow_read_current', 'flow_versions'], ['flow_read_series', 'flow_series']].map(([name, from]) => ({
  name, pipeline: [
    {$match: {status: 'verified'}},
    {$lookup: {from, let: {version: '$version', scope: '$_id'}, pipeline: [
      {$match: {$expr: {$and: [{$eq: [from === 'flow_versions' ? '$_id' : '$version', '$$version']},
                              {$eq: ['$scope', '$$scope']}]}}}
    ], as: 'result'}},
    {$unwind: '$result'}
  ]
}));
// [홍석환] 모든 기존 항목을 검사한 다음 생성한다. 이름만 같다고 정상으로 간주하지 않는다.
for (const view of views) {
  const existing = target.getCollectionInfos({name: view.name})[0];
  if (existing && (existing.type !== 'view' || existing.options.viewOn !== 'flow_public' ||
      JSON.stringify(existing.options.pipeline) !== JSON.stringify(view.pipeline))) {
    throw new Error('기존 공개 뷰가 다름: ' + view.name + ' (자동 변경 안 함)');
  }
}
const privileges = ['flow_read_current', 'flow_read_series', 'flow_health'].map(collection => (
  {resource: {db: target.getName(), collection}, actions: ['find']}
));
const existingRole = target.getRole(role, {showPrivileges: true});
const normalizedPrivileges = values => JSON.stringify(values.map(p => ({
  db: p.resource.db, collection: p.resource.collection,
  extraResourceKeys: Object.keys(p.resource).filter(k => !['db','collection'].includes(k)).sort(),
  actions: [...p.actions].sort()
})).sort((a,b) => a.collection.localeCompare(b.collection)));
if (existingRole && (existingRole.roles.length || normalizedPrivileges(existingRole.privileges) !== normalizedPrivileges(privileges))) {
  throw new Error('기존 읽기 역할이 다름 (자동 변경 안 함)');
}
for (const [user, password, expectedRole] of [[writer, process.env.FLOW_WRITER_PASSWORD, 'readWrite'],
                                           [reader, process.env.FLOW_READER_PASSWORD, role]]) {
  const existing = target.getUser(user);
  if (existing) {
    if (existing.roles.length !== 1 || existing.roles[0].role !== expectedRole || existing.roles[0].db !== target.getName()) {
      throw new Error('기존 계정 권한이 다름 (자동 변경 안 함)');
    }
    const connection = new Mongo('mongodb://' + (process.env.FLOW_SETUP_HOST || '127.0.0.1') + ':' +
        (process.env.FLOW_SETUP_PORT || '27017') + '/?directConnection=true');
    try {
      if (!connection.getDB(target.getName()).auth(user, password)) throw new Error('기존 계정 인증 실패 (자동 변경 안 함)');
    } finally { connection.close(); }
  }
}
if (!apply) {
  print('사전 검사 완료. 없는 공개 뷰·역할·계정 생성은 FLOW_APPLY_SETUP=1로 명시 실행한다.');
  quit(0);
}
for (const view of views) {
  if (!target.getCollectionInfos({name: view.name}).length) target.createView(view.name, 'flow_public', view.pipeline);
}
if (!target.getRole(role)) {
  target.createRole({role, privileges: ['flow_read_current', 'flow_read_series', 'flow_health'].map(collection => (
    {resource: {db: target.getName(), collection}, actions: ['find']}
  )), roles: []});
}
if (!target.getUser(writer)) target.createUser({user: writer, pwd: process.env.FLOW_WRITER_PASSWORD, roles: [{role: 'readWrite', db: target.getName()}]});
if (!target.getUser(reader)) target.createUser({user: reader, pwd: process.env.FLOW_READER_PASSWORD, roles: [{role, db: target.getName()}]});
print('지표 공개 뷰와 분리 계정 준비 완료. 기존 계정·비밀번호는 변경하지 않았다.');
