/*
[홍석환] 시스템 MongoDB 최초 초기화
빈 데이터 디렉터리의 초기 실행에서 애플리케이션 계정과 기본 저장 구조를 준비한다.
*/
// Official entrypoint runs this only on an uninitialized data directory.
const target = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE);
globalThis.SYSTEM_MONGO_INITIALIZING = true;
load('/opt/mongo/setup-reader.js');
readerSettings();
const username = process.env.MONGO_WRITER_USERNAME;
if (target.getUser(username) !== null) {
  throw new Error('Writer already exists; refusing to overwrite.');
}
target.createUser({
  user: username,
  pwd: process.env.MONGO_WRITER_PASSWORD,
  roles: [{role: 'readWrite', db: target.getName()}]
});
if (!target.getCollectionNames().includes('raw_events')) {
  target.createCollection('raw_events');
}
print('MongoDB application user and raw_events initialized.');
setupAdminReader(target);
