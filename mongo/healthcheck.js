try {
  const admin = new Mongo('mongodb://127.0.0.1:27017/?directConnection=true').getDB('admin');
  if (!admin.auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.MONGO_INITDB_ROOT_PASSWORD)) quit(1);
  if (admin.runCommand({ping: 1}).ok !== 1) quit(1);
} catch (_) {
  quit(1);
}
