/*
[홍석환] 원본 MongoDB 상태 확인
관리자 인증과 응답 상태를 검사해 컨테이너 준비 여부를 판단한다.
*/
try {
  const admin = db.getSiblingDB('admin');
  if (!admin.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD)) quit(1);
  if (admin.runCommand({ping: 1}).ok !== 1) quit(1);
} catch (_) { quit(1); }
