/*
[홍석환] 시스템 MongoDB 조회 계정 설정
조회 계정의 입력값을 검사하고 최초 설치 또는 명시적 설정 시 읽기 권한을 준비한다.
*/
// Shared by first initialization and explicit, authenticated existing-DB setup.
function readerSettings() {
  const username = process.env.MONGO_ADMIN_READER_USERNAME || '';
  const password = process.env.MONGO_ADMIN_READER_PASSWORD || '';
  if (!username && !password) return null;
  if (!username || !password || username.startsWith('CHANGE_ME') || password.startsWith('CHANGE_ME')) {
    throw new Error('Configure both MONGO_ADMIN_READER_USERNAME and MONGO_ADMIN_READER_PASSWORD');
  }
  if ([process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_WRITER_USERNAME].includes(username)) {
    throw new Error('Reader must have a separate username');
  }
  return {username, password};
}

function setupAdminReader(target) {
  const settings = readerSettings();
  if (!settings) return;
  const existing = target.getUser(settings.username);
  if (existing) {
    if (existing.roles.length !== 1 || existing.roles[0].role !== 'read' || existing.roles[0].db !== target.getName()) {
      throw new Error('Existing reader roles differ; refusing to change permissions');
    }
    // A separate connection verifies the configured password without changing it.
    const connection = new Mongo('mongodb://127.0.0.1:27017/?directConnection=true');
    try {
      if (!connection.getDB(target.getName()).auth(settings.username, settings.password)) {
        throw new Error('Existing reader authentication failed; no account changed');
      }
    } finally { connection.close(); }
  } else {
    target.createUser({user: settings.username, pwd: settings.password,
      roles: [{role: 'read', db: target.getName()}]});
  }
  print('Administrator dashboard reader ready (read only).');
}

if (typeof SYSTEM_MONGO_INITIALIZING === 'undefined') {
  try {
    if (!readerSettings()) throw new Error('Reader configuration required');
    const admin = db.getSiblingDB('admin');
    if (!admin.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD)) {
      throw new Error('Administrator authentication required');
    }
    setupAdminReader(db.getSiblingDB(process.env.MONGO_INITDB_DATABASE));
  } catch (_) {
    print('Reader setup failed: check administrator authentication, reader configuration and existing roles/password. No existing account is modified.');
    quit(1);
  }
}
