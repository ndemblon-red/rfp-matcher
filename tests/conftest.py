import os
import pytest

# Must be set before importing app so init_db() uses the test database
os.environ["DB_PATH"] = "rfp_matcher_test.db"
os.environ["SECRET_KEY"] = "test-secret-not-for-production"
os.environ["PPTX_PATH"] = ""
os.environ["EXCEL_PATH"] = ""

from app import app as flask_app
from db import init_db


@pytest.fixture(scope="session")
def app():
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture(scope="session")
def setup_db(app):
    db_path = os.environ.get("DB_PATH", "rfp_matcher_test.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    init_db()
    yield


@pytest.fixture()
def client(app, setup_db):
    with app.test_client() as c:
        yield c
