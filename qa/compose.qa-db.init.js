// QA DB 첫 실행 때만 · 빈 데이터 폴더일 때 공식 이미지가 실행 · QA 계정 = ticketguard_qa 읽기 · 쓰기만
const target = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE);
const username = process.env.QA_MONGO_USERNAME;
const password = process.env.QA_MONGO_PASSWORD;
if (!username || !password) {
  throw new Error('QA_MONGO_USERNAME · QA_MONGO_PASSWORD 필요');
}
if (username === process.env.MONGO_INITDB_ROOT_USERNAME) {
  throw new Error('QA 계정과 관리자 계정 분리 필요');
}
target.createUser({user: username, pwd: password, roles: [{role: 'readWrite', db: target.getName()}]});
print('QA DB 계정 생성 · ' + target.getName());
