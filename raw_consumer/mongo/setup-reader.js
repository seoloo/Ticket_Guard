// Used by initial bootstrap and explicit administrator-authenticated setup.
function rawReaderSettings() {
  const user = process.env.RAW_MONGO_READER_USERNAME;
  const password = process.env.RAW_MONGO_READER_PASSWORD;
  const names = [process.env.MONGO_INITDB_ROOT_USERNAME, process.env.RAW_MONGO_WRITER_USERNAME, user];
  if (!user || !password || user.startsWith('CHANGE_ME') || password.startsWith('CHANGE_ME')) {
    throw new Error('Configure RAW_MONGO_READER_USERNAME and RAW_MONGO_READER_PASSWORD');
  }
  if (new Set(names).size !== names.length) throw new Error('Root, writer and reader usernames must differ');
  return {user, password};
}

function setupRawReader(target) {
  const settings = rawReaderSettings();
  const existing = target.getUser(settings.user);
  if (existing) {
    if (existing.roles.length !== 1 || existing.roles[0].role !== 'read' || existing.roles[0].db !== target.getName()) {
      throw new Error('Existing reader roles differ; no account changed');
    }
    const connection = new Mongo('mongodb://127.0.0.1:27020/?directConnection=true');
    try {
      if (!connection.getDB(target.getName()).auth(settings.user, settings.password)) {
        throw new Error('Existing reader authentication failed; no account changed');
      }
    } finally { connection.close(); }
  } else {
    target.createUser({user: settings.user, pwd: settings.password,
      roles: [{role: 'read', db: target.getName()}]});
  }
  print('Raw reader ready (read only).');
}

if (typeof RAW_READER_INITIALIZING === 'undefined') {
  let stage = 'configuration';
  try {
    rawReaderSettings();
    stage = 'administrator authentication';
    const admin = db.getSiblingDB('admin');
    if (!admin.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD)) {
      throw new Error('Administrator authentication required');
    }
    stage = 'reader account creation or verification';
    setupRawReader(db.getSiblingDB(process.env.MONGO_INITDB_DATABASE));
  } catch (_) {
    print('Raw reader setup failed at ' + stage + '. No existing account is modified.');
    quit(1);
  }
}
