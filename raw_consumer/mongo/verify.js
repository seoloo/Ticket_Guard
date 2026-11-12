/*
[홍석환] 원본 MongoDB 계정과 조회 권한 점검
지정된 쓰기 또는 조회 계정으로 인증하고 저장소 구성을 확인한다.
*/
try {
  const target = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE);
  const reader = process.env.RAW_MONGO_VERIFY_ROLE === 'reader';
  const user = reader ? process.env.RAW_MONGO_READER_USERNAME : process.env.RAW_MONGO_WRITER_USERNAME;
  const password = reader ? process.env.RAW_MONGO_READER_PASSWORD : process.env.RAW_MONGO_WRITER_PASSWORD;
  if (!target.auth(user, password)) quit(1);
  const roles = target.runCommand({connectionStatus: 1}).authInfo.authenticatedUserRoles;
  if (roles.length !== 1 || roles[0].role !== (reader ? 'read' : 'readWrite') || roles[0].db !== target.getName()) quit(1);
  for (const name of ['raw_events', 'behavior_events', 'booking_events', 'auth_events',
    'http_events', 'performance_events', 'browser_errors', 'collector_events', 'raw_chunks', 'unclassified_events']) {
    const col = target.getCollection(name);
    printjson({collection: name, count: col.countDocuments({}), indexes: col.getIndexes().map(i => i.name)});
  }
} catch (_) { print('Verification failed'); quit(1); }
