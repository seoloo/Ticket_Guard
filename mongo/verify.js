// Read-only: authenticate, inspect roles/metadata and count, never insert.
try {
  const conn = new Mongo('mongodb://mongo:27017/?directConnection=true');
  const name = process.env.MONGO_INITDB_DATABASE;
  const writer = process.env.MONGO_VERIFY_ROLE === 'writer';
  const authDb = conn.getDB(writer ? name : 'admin');
  const user = writer ? process.env.MONGO_WRITER_USERNAME : process.env.MONGO_INITDB_ROOT_USERNAME;
  const password = writer ? process.env.MONGO_WRITER_PASSWORD : process.env.MONGO_INITDB_ROOT_PASSWORD;
  if (!authDb.auth(user, password)) throw new Error();
  if (authDb.runCommand({ping: 1}).ok !== 1) throw new Error();
  const status = authDb.runCommand({connectionStatus: 1});
  const roles = status.authInfo.authenticatedUserRoles;
  if (writer && (roles.length !== 1 || roles[0].role !== 'readWrite' || roles[0].db !== name)) throw new Error();
  if (!writer && !roles.some(r => r.role === 'root' && r.db === 'admin')) throw new Error();
  const target = conn.getDB(name);
  const info = target.getCollectionInfos({name: 'raw_events'});
  if (info.length !== 1 || Object.keys(info[0].options || {}).length !== 0) throw new Error();
  const indexes = target.raw_events.getIndexes();
  if (indexes.length !== 1 || indexes[0].key._id !== 1) throw new Error();
  const count = target.raw_events.countDocuments({});
  print((writer ? 'writer' : 'administrator') + ': authentication, ping, roles, collection, _id index OK; documents=' + count);
} catch (_) {
  print('MongoDB verification failed; check initialization and credentials.');
  quit(1);
}
