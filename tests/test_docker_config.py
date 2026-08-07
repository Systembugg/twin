from pathlib import Path
import yaml

def test_dockerfile_exists_and_valid():
    dockerfile = Path("Dockerfile")
    assert dockerfile.exists(), "Dockerfile is missing!"
    content = dockerfile.read_text("utf-8")
    assert "FROM python:" in content
    assert "EXPOSE 8000" in content


def test_docker_compose_valid():
    compose_file = Path("docker-compose.yml")
    assert compose_file.exists(), "docker-compose.yml is missing!"
    content = compose_file.read_text("utf-8")
    data = yaml.safe_load(content)

    services = data.get("services", {})
    assert "postgres" in services, "postgres service missing in docker-compose.yml"
    assert "redis" in services, "redis service missing in docker-compose.yml"
    assert "api" in services, "api service missing in docker-compose.yml"
    assert "worker" in services, "worker service missing in docker-compose.yml"


def test_schema_sql_has_required_tables():
    schema_file = Path("schema.sql")
    assert schema_file.exists(), "schema.sql is missing!"
    content = schema_file.read_text("utf-8")
    for table in ["users", "sessions", "runs", "run_events", "usage_ledger"]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in content, f"Table {table} missing in schema.sql"
