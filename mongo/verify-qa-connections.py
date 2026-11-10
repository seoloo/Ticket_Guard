"""Read-only connection check run in the QA image, without importing QA code."""
import os
import sys

from pymongo import MongoClient


def main():
    source = os.environ.get("TICKET_GUARD_QA_SYSTEM_RAW_SOURCE_ID", "")
    if not source.strip():
        print("QA raw source configuration missing.")
        return 1
    for label, variable, collection in (
        ("system", "TICKET_GUARD_QA_SYSTEM_MONGO_URI", "raw_events"),
        ("raw", "TICKET_GUARD_QA_SYSTEM_RAW_MONGO_URI", "http_events"),
    ):
        try:
            uri = os.environ[variable]
            with MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                             socketTimeoutMS=5000) as client:
                database = client.get_default_database()
                status = database.command("connectionStatus")
                roles = status["authInfo"]["authenticatedUserRoles"]
                if len(roles) != 1 or roles[0] != {"role": "read", "db": database.name}:
                    print(label + ": expected read permission only; check reader URI.")
                    return 1
                # Exercise actual read permission, rather than ping alone.
                database[collection].find_one({}, {"_id": 1})
                if label == "raw":
                    found = any(database[name].find_one({"source": source}, {"_id": 1}) is not None
                                for name in ("behavior_events", "booking_events", "auth_events", "http_events",
                                             "performance_events", "browser_errors", "collector_events", "raw_chunks",
                                             "unclassified_events"))
                    print("raw source: matching records found." if found else
                          "raw source: no matching records yet; verify RAW_SOURCE_ID against the producer settings.")
                print(label + ": authentication, read-only role and query OK.")
        except Exception as error:
            # Never print exception text: URI and credentials may be embedded.
            print(label + ": connection check failed (" + type(error).__name__ + ").")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
