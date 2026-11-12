/*
[홍석환] 시스템 MongoDB 계정과 저장 구조 점검
인증·역할·컬렉션 정보와 건수를 조회하며 데이터를 추가하거나 변경하지 않는다.
*/
// Read-only: authenticate, inspect roles/metadata and count, never insert.
try {
  const conn = new Mongo('mongodb://127.0.0.1:27017/?directConnection=true');
  const name = process.env.MONGO_INITDB_DATABASE;
  const writer = process.env.MONGO_VERIFY_ROLE === 'writer';
  const reader = process.env.MONGO_VERIFY_ROLE === 'reader';
  const authDb = conn.getDB(writer || reader ? name : 'admin');
  const user = reader ? process.env.MONGO_ADMIN_READER_USERNAME : writer ? process.env.MONGO_WRITER_USERNAME : process.env.MONGO_INITDB_ROOT_USERNAME;
  const password = reader ? process.env.MONGO_ADMIN_READER_PASSWORD : writer ? process.env.MONGO_WRITER_PASSWORD : process.env.MONGO_INITDB_ROOT_PASSWORD;
  if (!authDb.auth(user, password)) throw new Error();
  if (authDb.runCommand({ping: 1}).ok !== 1) throw new Error();
  const status = authDb.runCommand({connectionStatus: 1});
  const roles = status.authInfo.authenticatedUserRoles;
  if (writer && (roles.length !== 1 || roles[0].role !== 'readWrite' || roles[0].db !== name)) throw new Error();
  if (reader && (roles.length !== 1 || roles[0].role !== 'read' || roles[0].db !== name)) throw new Error();
  if (!writer && !reader && !roles.some(r => r.role === 'root' && r.db === 'admin')) throw new Error();
  const target = conn.getDB(name);
  const info = target.getCollectionInfos({name: 'raw_events'});
  if (info.length !== 1 || Object.keys(info[0].options || {}).length !== 0) throw new Error();
  const indexes = target.raw_events.getIndexes();
  if (indexes.length !== 1 || indexes[0].key._id !== 1) throw new Error();
  const count = target.raw_events.countDocuments({});
  print((reader ? 'reader' : writer ? 'writer' : 'administrator') + ': authentication, ping, roles, collection, _id index OK; documents=' + count);
} catch (_) {
  print('MongoDB verification failed; check initialization and credentials.');
  quit(1);
}
