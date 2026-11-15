from fastapi.testclient import TestClient

from tutor_calendar.api.main import create_app
from tutor_calendar.config import Settings


def test_readiness_is_503_when_the_database_is_down() -> None:
    # Port 1 is never a PostgreSQL server, so the connection is refused at once.
    settings = Settings(database_url="postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere")

    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database is not reachable"}
