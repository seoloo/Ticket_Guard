// Repeatable setup for existing volumes. Does not change users or raw_events.
function setupRawRouting(target) {
  const names = ['behavior_events', 'booking_events', 'auth_events', 'http_events',
    'performance_events', 'browser_errors', 'collector_events', 'raw_chunks', 'unclassified_events'];
  for (const name of names) {
    if (!target.getCollectionNames().includes(name)) {
      try { target.createCollection(name); }
      catch (error) { if (error.code !== 48) throw error; }
    }
    target.getCollection(name).createIndex(
      {source: 1, topic: 1, partition: 1, offset: 1}, {name: 'raw_kafka_position_v1'});
  }
  print('Raw routing collections and indexes ready.');
}
if (typeof RAW_INITIALIZING === 'undefined') {
  const target = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE);
  if (!target.auth(process.env.RAW_MONGO_WRITER_USERNAME, process.env.RAW_MONGO_WRITER_PASSWORD)) {
    throw new Error('Raw setup authentication failed');
  }
  setupRawRouting(target);
}
