import pytest

from department_studio.store import Store


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "room.sqlite") as store:
        yield store
