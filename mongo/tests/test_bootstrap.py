"""
[홍석환] MongoDB 최초 설치와 계정 구성 회귀 검사
별도 시험 프로젝트와 임시 저장소에서 초기화·계정·접속 동작을 확인한다.
실제 환경 파일과 기존 운영 데이터를 사용하지 않는다.
"""
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import unittest
import uuid
from urllib.parse import quote

from pymongo import MongoClient
from pymongo.errors import OperationFailure


ROOT = Path(__file__).resolve().parents[2]


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="ticketguard-bootstrap-")
        cls.projects = []

    @classmethod
    def tearDownClass(cls):
        try:
            for command in reversed(cls.projects):
                result = subprocess.run(command + ["down", "--volumes", "--remove-orphans"],
                                        capture_output=True, text=True, encoding="utf-8")
                if result.returncode:
                    raise RuntimeError("Test project cleanup failed; inspect project names prefixed tg-bootstrap-")
        finally:
            cls.directory.cleanup()

    def command(self, arguments, expected=0):
        result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if expected is not None:
            # Avoid including environment/config contents in failure output.
            self.assertEqual(result.returncode, expected, result.stdout[-1500:] + result.stderr[-1500:])
        return result

    def project(self, raw=False, reader=True):
        project = "tg-bootstrap-" + uuid.uuid4().hex[:10]
        directory = Path(self.directory.name) / project
        directory.mkdir()
        password = secrets.token_hex(20)
        settings = {
            "MONGO_ROOT_USERNAME": "bootstrap_root", "MONGO_ROOT_PASSWORD": password,
            "MONGO_WRITER_USERNAME": "bootstrap_writer", "MONGO_WRITER_PASSWORD": password + "w",
            "MONGO_DATABASE": "bootstrap_system",
            "MONGO_ADMIN_READER_USERNAME": "bootstrap_reader" if reader else "",
            "MONGO_ADMIN_READER_PASSWORD": password + "r" if reader else "",
            "RAW_MONGO_ROOT_USERNAME": "bootstrap_root", "RAW_MONGO_ROOT_PASSWORD": password,
            "RAW_MONGO_WRITER_USERNAME": "bootstrap_writer", "RAW_MONGO_WRITER_PASSWORD": password + "w",
            "RAW_MONGO_READER_USERNAME": "bootstrap_reader", "RAW_MONGO_READER_PASSWORD": password + "r",
            "RAW_MONGO_DATABASE": "bootstrap_raw", "RAW_SOURCE_ID": project,
        }
        env_file = directory / "test.env"
        env_file.write_text("\n".join(f"{key}={value}" for key, value in settings.items()), encoding="utf-8")
        service = "mongo-raw" if raw else "mongo"
        internal_port = 27020 if raw else 27017
        override = directory / "override.json"
        override.write_text(json.dumps({"services": {service: {
            "ports": [f"127.0.0.1::{internal_port}"], "restart": "no"}}}), encoding="utf-8")
        command = ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(env_file),
                   "-p", project, "-f", str(ROOT / ("compose.raw.yml" if raw else "compose.yml")),
                   "-f", str(override)]
        if not raw:
            command += ["--profile", "mongo"]
        self.projects.append(command)
        self.command(command + ["config", "--quiet"])
        self.command(command + ["up", "-d", "--no-deps", "--wait", "--wait-timeout", "120", service])
        container = self.command(command + ["ps", "-q", service]).stdout.strip()
        published = self.command(["docker", "port", container, str(internal_port)]).stdout.strip()
        self.assertTrue(published.startswith("127.0.0.1:"))
        return command, container, int(published.rsplit(":", 1)[1]), settings

    def client(self, port, settings, role="root", raw=False):
        prefix = "RAW_MONGO_" if raw else "MONGO_"
        key = "ROOT" if role == "root" else "WRITER" if role == "writer" else "READER" if raw else "ADMIN_READER"
        database = settings[prefix + "DATABASE"]
        client = MongoClient("127.0.0.1", port=port, username=settings[prefix + key + "_USERNAME"],
                             password=settings[prefix + key + "_PASSWORD"],
                             authSource="admin" if role == "root" else database,
                             serverSelectionTimeoutMS=5000)
        self.addCleanup(client.close)
        client.admin.command("ping")
        return client

    def script(self, container, path, raw=False, extra=(), expected=0):
        args = ["docker", "exec"] + list(extra) + [container, "mongosh", "--quiet", "--norc"]
        if raw:
            args += ["--port", "27020"]
        return self.command(args + [path], expected)

    def test_system_initialization_permissions_and_restart(self):
        command, container, port, settings = self.project()
        writer = self.client(port, settings, "writer")
        database = settings["MONGO_DATABASE"]
        writer[database].raw_events.insert_one({"_id": "persistent-sentinel"})
        reader = self.client(port, settings, "reader")
        self.assertEqual(reader[database].raw_events.count_documents({}), 1)
        with self.assertRaises(OperationFailure) as denied:
            reader[database].raw_events.insert_one({"_id": "must-not-write"})
        self.assertEqual(denied.exception.code, 13)
        root = self.client(port, settings)
        root["another_database"].private.insert_one({"_id": "private"})
        with self.assertRaises(OperationFailure) as cross_database:
            reader["another_database"].private.count_documents({})
        self.assertEqual(cross_database.exception.code, 13)
        before = root[database].command("usersInfo", showCredentials=True)["users"]
        for role in ("administrator", "writer", "reader"):
            self.script(container, "/opt/mongo/verify.js", extra=("-e", f"MONGO_VERIFY_ROLE={role}"))
        for _ in range(2):
            self.script(container, "/opt/mongo/setup-reader.js")
        self.assertEqual(before, root[database].command("usersInfo", showCredentials=True)["users"])
        self.script(container, "/opt/mongo/setup-reader.js",
                    extra=("-e", "MONGO_ADMIN_READER_PASSWORD=incorrect"), expected=1)
        self.script(container, "/opt/mongo/setup-reader.js",
                    extra=("-e", "MONGO_INITDB_ROOT_PASSWORD=incorrect"), expected=1)
        self.command(command + ["restart", "mongo"])
        self.command(command + ["up", "-d", "--no-deps", "--wait", "mongo"])
        port = int(self.command(["docker", "port", container, "27017"]).stdout.strip().rsplit(":", 1)[1])
        root = self.client(port, settings)
        self.assertEqual(self.client(port, settings, "reader")[database].raw_events.count_documents({}), 1)
        self.assertEqual(before, root[database].command("usersInfo", showCredentials=True)["users"])

    def test_existing_system_database_add_reader_without_overwrite(self):
        _, container, port, settings = self.project(reader=False)
        root = self.client(port, settings)
        name = settings["MONGO_DATABASE"]
        root[name].raw_events.insert_one({"_id": "existing"})
        extra = ("-e", "MONGO_ADMIN_READER_USERNAME=bootstrap_reader",
                 "-e", "MONGO_ADMIN_READER_PASSWORD=reader-password")
        for _ in range(2):
            self.script(container, "/opt/mongo/setup-reader.js", extra=extra)
        settings["MONGO_ADMIN_READER_USERNAME"] = "bootstrap_reader"
        settings["MONGO_ADMIN_READER_PASSWORD"] = "reader-password"
        self.assertEqual(self.client(port, settings, "reader")[name].raw_events.count_documents({}), 1)
        root[name].command("grantRolesToUser", "bootstrap_reader", roles=[{"role": "readWrite", "db": name}])
        before = root[name].command("usersInfo", "bootstrap_reader", showCredentials=True)
        self.script(container, "/opt/mongo/setup-reader.js", extra=extra, expected=1)
        self.assertEqual(before, root[name].command("usersInfo", "bootstrap_reader", showCredentials=True))

    def test_raw_initialization_existing_setup_and_host_connection(self):
        command, container, port, settings = self.project(raw=True)
        writer = self.client(port, settings, "writer", raw=True)
        name = settings["RAW_MONGO_DATABASE"]
        collections = {"raw_events", "behavior_events", "booking_events", "auth_events", "http_events",
                       "performance_events", "browser_errors", "collector_events", "raw_chunks", "unclassified_events"}
        self.assertEqual(set(writer[name].list_collection_names()), collections)
        writer[name].http_events.insert_one({"_id": "persistent-sentinel"})
        reader = self.client(port, settings, "reader", raw=True)
        self.assertEqual(reader[name].http_events.count_documents({}), 1)
        with self.assertRaises(OperationFailure) as denied:
            reader[name].http_events.insert_one({"_id": "must-not-write"})
        self.assertEqual(denied.exception.code, 13)
        root = self.client(port, settings, raw=True)
        before = root[name].command("usersInfo", showCredentials=True)
        for _ in range(2):
            self.script(container, "/opt/raw/setup.js", raw=True)
            self.script(container, "/opt/raw/setup-writer.js", raw=True)
            self.script(container, "/opt/raw/setup-reader.js", raw=True)
        self.script(container, "/opt/raw/verify.js", raw=True)
        self.script(container, "/opt/raw/verify.js", raw=True, extra=("-e", "RAW_MONGO_VERIFY_ROLE=reader"))
        self.script(container, "/opt/raw/setup-writer.js", raw=True,
                    extra=("-e", "RAW_MONGO_WRITER_PASSWORD=incorrect"), expected=1)
        self.script(container, "/opt/raw/setup-writer.js", raw=True,
                    extra=("-e", "MONGO_INITDB_ROOT_PASSWORD=incorrect"), expected=1)
        self.assertEqual(before, root[name].command("usersInfo", showCredentials=True))
        for collection in collections - {"raw_events"}:
            indexes = writer[name][collection].index_information()
            self.assertEqual(set(indexes), {"_id_", "raw_kafka_position_v1"})
        self.command(command + ["restart", "mongo-raw"])
        self.command(command + ["up", "-d", "--no-deps", "--wait", "mongo-raw"])
        port = int(self.command(["docker", "port", container, "27020"]).stdout.strip().rsplit(":", 1)[1])
        self.assertEqual(self.client(port, settings, "writer", raw=True)[name].http_events.count_documents({}), 1)
        self.assertEqual(self.client(port, settings, "reader", raw=True)[name].http_events.count_documents({}), 1)
        # Exercise the absent-account path without changing the existing writer.
        extra = ("-e", "RAW_MONGO_WRITER_USERNAME=additional_writer", "-e", "RAW_MONGO_WRITER_PASSWORD=new-password")
        for _ in range(2):
            self.script(container, "/opt/raw/setup-writer.js", raw=True, extra=extra)
        settings["RAW_MONGO_WRITER_USERNAME"] = "additional_writer"
        settings["RAW_MONGO_WRITER_PASSWORD"] = "new-password"
        self.assertEqual(self.client(port, settings, "writer", raw=True)[name].http_events.count_documents({}), 1)
        root = self.client(port, settings, raw=True)
        root[name].command("grantRolesToUser", "additional_writer", roles=[{"role": "read", "db": name}])
        before = root[name].command("usersInfo", "additional_writer", showCredentials=True)
        self.script(container, "/opt/raw/setup-writer.js", raw=True, extra=extra, expected=1)
        self.assertEqual(before, root[name].command("usersInfo", "additional_writer", showCredentials=True))

    def test_existing_raw_reader_setup_preserves_accounts_and_data(self):
        _, container, port, settings = self.project(raw=True)
        root = self.client(port, settings, raw=True)
        name = settings["RAW_MONGO_DATABASE"]
        root[name].http_events.insert_one({"_id": "existing"})
        root[name].command("dropUser", settings["RAW_MONGO_READER_USERNAME"])
        before = root[name].command("usersInfo", showCredentials=True)["users"]
        self.script(container, "/opt/raw/setup-reader.js", raw=True,
                    extra=("-e", "MONGO_INITDB_ROOT_PASSWORD=incorrect"), expected=1)
        self.assertEqual(before, root[name].command("usersInfo", showCredentials=True)["users"])
        for _ in range(2):
            self.script(container, "/opt/raw/setup-reader.js", raw=True)
        reader = self.client(port, settings, "reader", raw=True)
        self.assertEqual(reader[name].http_events.count_documents({}), 1)
        after = root[name].command("usersInfo", showCredentials=True)
        self.script(container, "/opt/raw/setup-reader.js", raw=True,
                    extra=("-e", "RAW_MONGO_READER_PASSWORD=incorrect"), expected=1)
        self.assertEqual(after, root[name].command("usersInfo", showCredentials=True))
        root[name].command("grantRolesToUser", settings["RAW_MONGO_READER_USERNAME"],
                           roles=[{"role": "readWrite", "db": name}])
        after = root[name].command("usersInfo", showCredentials=True)
        self.script(container, "/opt/raw/setup-reader.js", raw=True, expected=1)
        self.assertEqual(after, root[name].command("usersInfo", showCredentials=True))
        # Root and writer credential records remain byte-for-byte equal.
        remaining = [u for u in after["users"] if u["user"] != settings["RAW_MONGO_READER_USERNAME"]]
        self.assertEqual(before, remaining)

    def test_raw_invalid_reader_configuration_fails_before_initialization(self):
        # No DB volume or network: validation must fail before mongod starts.
        settings = ["MONGO_INITDB_ROOT_USERNAME=root", "MONGO_INITDB_ROOT_PASSWORD=test-root",
                    "MONGO_INITDB_DATABASE=test_raw", "RAW_MONGO_WRITER_USERNAME=writer",
                    "RAW_MONGO_WRITER_PASSWORD=test-writer", "RAW_MONGO_READER_PASSWORD=test-reader"]
        for reader in ("", "root", "writer", "CHANGE_ME_READER"):
            args = ["docker", "run", "--rm", "--network", "none", "--entrypoint", "bash",
                    "--mount", f"type=bind,source={ROOT / 'raw_consumer/mongo/start.sh'},target=/start.sh,readonly"]
            for entry in settings + ["RAW_MONGO_READER_USERNAME=" + reader]:
                args += ["-e", entry]
            self.command(args + ["mongo:8.0.34", "/start.sh", "mongod"], expected=1)

    def test_qa_read_only_network_connections_and_source(self):
        _, system_container, _, system = self.project()
        _, raw_container, raw_port, raw = self.project(raw=True)
        writer = self.client(raw_port, raw, "writer", raw=True)
        writer[raw["RAW_MONGO_DATABASE"]].http_events.insert_one({"source": raw["RAW_SOURCE_ID"]})
        system_info = json.loads(self.command(["docker", "inspect", system_container]).stdout)[0]
        raw_info = json.loads(self.command(["docker", "inspect", raw_container]).stdout)[0]
        system_network = next(iter(system_info["NetworkSettings"]["Networks"]))
        raw_network = next(iter(raw_info["NetworkSettings"]["Networks"]))
        system_host, raw_host = system_info["Name"].lstrip("/"), raw_info["Name"].lstrip("/")
        def uri(settings, raw_db, host):
            prefix, account, port = ("RAW_MONGO_", "READER", 27020) if raw_db else ("MONGO_", "ADMIN_READER", 27017)
            user = quote(settings[prefix + account + "_USERNAME"], safe="")
            password = quote(settings[prefix + account + "_PASSWORD"], safe="")
            database = settings[prefix + "DATABASE"]
            return f"mongodb://{user}:{password}@{host}:{port}/{database}?authSource={database}"
        project = "tg-bootstrap-" + uuid.uuid4().hex[:10]
        directory = Path(self.directory.name) / project
        directory.mkdir()
        settings = {
            "TICKET_GUARD_ADMIN_MONGO_NETWORK": system_network,
            "TICKET_GUARD_QA_RAW_MONGO_NETWORK": raw_network,
            "TICKET_GUARD_QA_SYSTEM_MONGO_URI": uri(system, False, system_host),
            "TICKET_GUARD_QA_SYSTEM_RAW_MONGO_URI": uri(raw, True, raw_host),
            "TICKET_GUARD_QA_SYSTEM_RAW_SOURCE_ID": raw["RAW_SOURCE_ID"],
            "RAW_SOURCE_ID": "must-not-override-explicit-qa-source",
            "QA_MONGO_ROOT_USERNAME": "unused_root", "QA_MONGO_ROOT_PASSWORD": "unused-root-password",
            "QA_MONGO_USERNAME": "unused_writer", "QA_MONGO_PASSWORD": "unused-writer-password",
        }
        env_file = directory / "test.env"
        env_file.write_text("\n".join(f"{key}={value}" for key, value in settings.items()), encoding="utf-8")
        command = ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(env_file), "-p", project]
        for file in ("compose.yml", "compose.gateway.yml", "qa/compose.qa-db.yml", "qa/compose.qa-live.yml",
                     "compose.qa-db-access.yml"):
            command += ["-f", str(ROOT / file)]
        self.projects.append(command)
        config = json.loads(self.command(command + ["config", "--format", "json"]).stdout)
        qa = config["services"]["qa-dashboard"]
        self.assertEqual(set(qa["networks"]), {"default", "qa-backend", "qa-system-mongo", "qa-raw-mongo"})
        self.assertEqual(set(config["services"]["qa-mongo"]["networks"]), {"qa-backend"})
        self.assertFalse(qa.get("ports"))
        self.assertFalse(any("docker.sock" in str(volume) for volume in qa["volumes"]))
        self.assertEqual(qa["environment"]["TICKET_GUARD_QA_SYSTEM_RAW_SOURCE_ID"], raw["RAW_SOURCE_ID"])
        self.assertEqual(qa["environment"]["TICKET_GUARD_QA_IS_KAFKA_CONTRACT_INJECTION_ENABLED"], "false")
        self.assertFalse(qa["environment"]["TICKET_GUARD_QA_PIPELINE_CONTAINER_NAME"])
        self.assertFalse(any(key.startswith(("MONGO_ROOT", "MONGO_WRITER", "RAW_MONGO_ROOT", "RAW_MONGO_WRITER"))
                             for key in qa["environment"]))
        result = self.command(command + ["run", "--rm", "--no-deps", "--entrypoint", "python", "qa-dashboard",
                                         "/opt/ticketguard/verify-qa-connections.py"])
        self.assertIn("system: authentication, read-only role and query OK.", result.stdout)
        self.assertIn("raw: authentication, read-only role and query OK.", result.stdout)
        self.assertIn("raw source: matching records found.", result.stdout)


if __name__ == "__main__":
    unittest.main()
