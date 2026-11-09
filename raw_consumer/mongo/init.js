// The official entrypoint supplies db on its temporary initialization server.
const target = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE);
globalThis.RAW_READER_INITIALIZING = true;
load('/opt/raw/setup-reader.js');
rawReaderSettings();
const user = process.env.RAW_MONGO_WRITER_USERNAME;
const password = process.env.RAW_MONGO_WRITER_PASSWORD;
if (!user || !password || user.startsWith('CHANGE_ME') || password.startsWith('CHANGE_ME')) {
  throw new Error('Configure raw writer credentials');
}
if (user === process.env.MONGO_INITDB_ROOT_USERNAME) throw new Error('Separate writer required');
target.createUser({user, pwd: password, roles: [{role: 'readWrite', db: target.getName()}]});
target.createCollection('raw_events');
globalThis.RAW_INITIALIZING = true;
load('/opt/raw/setup.js');
setupRawRouting(target);
setupRawReader(target);
