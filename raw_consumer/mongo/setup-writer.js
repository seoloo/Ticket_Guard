/*
[홍석환] 기존 원본 DB의 쓰기 계정 설정
명시적으로 인증한 환경에서 쓰기 계정을 준비하고 기존 자격 증명을 덮어쓰지 않는다.
*/
// Explicit account setup for existing volumes; never resets existing credentials.
let stage = 'configuration';
try {
  const name = process.env.MONGO_INITDB_DATABASE;
  const user = process.env.RAW_MONGO_WRITER_USERNAME;
  const password = process.env.RAW_MONGO_WRITER_PASSWORD;
  if (!name || !user || !password || user.startsWith('CHANGE_ME') || password.startsWith('CHANGE_ME') ||
      user === process.env.MONGO_INITDB_ROOT_USERNAME) throw new Error('Invalid settings');
  const admin = db.getSiblingDB('admin');
  stage = 'administrator authentication';
  if (!admin.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD)) {
    throw new Error('Administrator authentication required');
  }
  const target = db.getSiblingDB(name);
  stage = 'existing account permissions';
  const existing = target.getUser(user);
  if (existing) {
    if (existing.roles.length !== 1 || existing.roles[0].role !== 'readWrite' || existing.roles[0].db !== name) {
      throw new Error('Existing roles differ');
    }
    stage = 'existing account password';
    const connection = new Mongo('mongodb://127.0.0.1:27020/?directConnection=true');
    try {
      if (!connection.getDB(name).auth(user, password)) throw new Error('Existing password differs');
    } finally { connection.close(); }
  } else {
    stage = 'account creation';
    target.createUser({user, pwd: password, roles: [{role: 'readWrite', db: name}]});
  }
  print('Raw writer ready. Run setup.js separately for collections and indexes.');
} catch (_) {
  print('Raw account setup failed at ' + stage + '. No existing account is modified.');
  quit(1);
}
