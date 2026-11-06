try {
  const target = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE);
  if (!target.auth(process.env.RAW_MONGO_WRITER_USERNAME, process.env.RAW_MONGO_WRITER_PASSWORD)) quit(1);
  for (const name of ['raw_events', 'behavior_events', 'booking_events', 'auth_events',
    'http_events', 'performance_events', 'browser_errors', 'collector_events', 'raw_chunks', 'unclassified_events']) {
    const col = target.getCollection(name);
    printjson({collection: name, count: col.countDocuments({}), indexes: col.getIndexes().map(i => i.name)});
  }
} catch (_) { print('Verification failed'); quit(1); }
