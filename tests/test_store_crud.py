import pytest
from pathlib import Path

from agent.store import Store


@pytest.fixture
async def store(tmp_path: Path) -> Store:  # type: ignore[misc]
    s = await Store.connect(tmp_path / "test.db")
    yield s  # type: ignore[misc]
    await s.close()


# --- kv ---

async def test_kv_round_trip(store: Store) -> None:
    await store.kv_set("foo", "bar")
    assert await store.kv_get("foo") == "bar"


async def test_kv_overwrite(store: Store) -> None:
    await store.kv_set("foo", "bar")
    await store.kv_set("foo", "baz")
    assert await store.kv_get("foo") == "baz"


async def test_kv_get_missing_returns_none(store: Store) -> None:
    assert await store.kv_get("nonexistent") is None


# --- facts ---

async def test_fact_crud(store: Store) -> None:
    await store.set_fact("color", "blue")
    fact = await store.get_fact("color")
    assert fact is not None
    assert fact.key == "color"
    assert fact.value == "blue"
    assert fact.updated_at


async def test_fact_update(store: Store) -> None:
    await store.set_fact("color", "blue")
    await store.set_fact("color", "red")
    fact = await store.get_fact("color")
    assert fact is not None
    assert fact.value == "red"


async def test_get_fact_missing_returns_none(store: Store) -> None:
    assert await store.get_fact("nonexistent") is None


async def test_list_facts(store: Store) -> None:
    await store.set_fact("b", "2")
    await store.set_fact("a", "1")
    facts = await store.list_facts()
    assert len(facts) == 2
    assert facts[0].key == "a"
    assert facts[1].key == "b"


# --- people ---

async def test_person_crud(store: Store) -> None:
    await store.set_person("p1", "Alice", "hello alice", phone="+1234")
    person = await store.get_person("p1")
    assert person is not None
    assert person.id == "p1"
    assert person.name == "Alice"
    assert person.phone == "+1234"
    assert person.content == "hello alice"
    assert person.updated_at


async def test_person_update(store: Store) -> None:
    await store.set_person("p1", "Alice", "old content")
    await store.set_person("p1", "Alice B", "new content", phone="+9999")
    person = await store.get_person("p1")
    assert person is not None
    assert person.name == "Alice B"
    assert person.content == "new content"
    assert person.phone == "+9999"


async def test_get_person_missing_returns_none(store: Store) -> None:
    assert await store.get_person("nonexistent") is None


async def test_list_people(store: Store) -> None:
    await store.set_person("p2", "Bob", "hi bob")
    await store.set_person("p1", "Alice", "hi alice")
    people = await store.list_people()
    assert len(people) == 2
    assert people[0].name == "Alice"
    assert people[1].name == "Bob"
