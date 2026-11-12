/*
[홍석환] 시스템 MongoDB 상태 확인
관리자 인증과 응답 여부를 확인하고 컨테이너 상태 검사 결과를 반환한다.
*/
try {
  const admin = new Mongo('mongodb://127.0.0.1:27017/?directConnection=true').getDB('admin');
  if (!admin.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD)) quit(1);
  if (admin.runCommand({ping: 1}).ok !== 1) quit(1);
} catch (_) {
  quit(1);
}
