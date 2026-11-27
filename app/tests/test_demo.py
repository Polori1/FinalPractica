"""TODO 8: ejecuta  pytest -q  ahora (verás rojo) y otra vez al terminar los TODO 1-7 (verde).
Así sabes que terminaste sin probar a mano cada endpoint."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from database import get_session
from main import app

@pytest.fixture()
def engine():
    # Base de datos en memoria: cada test empieza de cero y no toca clase2.db
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine

@pytest.fixture()
def client():
    # Base de datos en memoria: cada test empieza de cero y no toca clase2.db
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)


    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield TestClient(app)  # sin `with`: no ejecuta el lifespan (que usaría la BD real)
    app.dependency_overrides.clear()

def new_post(client, headers, title="Hola") -> int:
    r = client.post("/posts", json={"title": title, "content": "contenido"}, headers=headers)
    assert r.status_code == 201
    return r.json()["id"]

@pytest.fixture()
def sql_log(engine):
    """Lista con cada sentencia SQL que se ejecuta: sirve para contar consultas."""
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    yield statements
    event.remove(engine, "before_cursor_execute", record)

def register_and_login(client, username: str) -> dict:
    body = {"username": username, "password": "supersecreta123"}
    assert client.post("/auth/register", json=body).status_code == 201
    r = client.post("/auth/login", data=body)
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def user_id(client, headers) -> int:
    return client.get("/auth/me", headers=headers).json()["id"]


def test_register_ignores_role_sent_by_client(client):
    r = client.post(
        "/auth/register",
        json={"username": "mallory", "password": "supersecreta123", "role": "admin"},
    )
    assert r.status_code == 201
    assert r.json()["role"] == "user"
    assert "hashed_password" not in r.json()

#Posts

def test_post_author_comes_from_the_token(client):
    alice = register_and_login(client, "alice")
    r = client.post("/posts", json={"title": "Hola", "content": "Primer post"}, headers=alice)
    assert r.status_code == 201
    assert r.json()["author_id"] == client.get("/auth/me", headers=alice).json()["id"]


def test_401_without_token_and_403_for_non_author(client):
    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    post = {"title": "Mío", "content": "De alice"}

    assert client.post("/posts", json=post).status_code == 401  # sin token: ¿quién eres?
    post_id = client.post("/posts", json=post, headers=alice).json()["id"]

    assert client.patch(f"/posts/{post_id}", json={"title": "hack"}, headers=bob).status_code == 403
    assert client.delete(f"/posts/{post_id}", headers=bob).status_code == 403
    assert client.patch(f"/posts/{post_id}", json={"title": "ok"}, headers=alice).status_code == 200
    assert client.delete(f"/posts/{post_id}", headers=alice).status_code == 204
    assert client.get(f"/posts/{post_id}").status_code == 404

def test_post_without_likes_shows_zero(client):
    # Si usaste un JOIN común en vez de LEFT JOIN, este post "desaparece" y el test falla.
    alice = register_and_login(client, "alice")
    post_id = new_post(client, alice)

    assert client.get(f"/posts/{post_id}").json()["likes_count"] == 0
    assert [p["likes_count"] for p in client.get("/posts").json()] == [0]

#Likes

def test_like_increments_count_in_list_and_detail(client):
    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    liked, ignored = new_post(client, alice, "gustado"), new_post(client, alice, "ignorado")

    r = client.put(f"/posts/{liked}/like", headers=bob)
    assert r.status_code == 200
    assert r.json()["likes_count"] == 1

    counts = {p["id"]: p["likes_count"] for p in client.get("/posts").json()}
    assert counts == {liked: 1, ignored: 0}
    assert client.get(f"/posts/{liked}").json()["likes_count"] == 1


def test_like_is_idempotent(client):
    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    post_id = new_post(client, alice)

    assert client.put(f"/posts/{post_id}/like", headers=bob).status_code == 200
    r = client.put(f"/posts/{post_id}/like", headers=bob)  # segunda vez: no rompe ni duplica
    assert r.status_code == 200
    assert r.json()["likes_count"] == 1


def test_many_users_like_the_same_post(client):
    alice = register_and_login(client, "alice")
    post_id = new_post(client, alice)
    for name in ("bob", "carol", "dave"):
        client.put(f"/posts/{post_id}/like", headers=register_and_login(client, name))

    assert client.get(f"/posts/{post_id}").json()["likes_count"] == 3
    likers = client.get(f"/posts/{post_id}/likes").json()
    assert sorted(u["username"] for u in likers) == ["bob", "carol", "dave"]
    assert all("hashed_password" not in u for u in likers)


def test_unlike_and_unlike_again(client):
    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    post_id = new_post(client, alice)
    client.put(f"/posts/{post_id}/like", headers=bob)

    r = client.delete(f"/posts/{post_id}/like", headers=bob)
    assert r.status_code == 200
    assert r.json()["likes_count"] == 0
    assert client.delete(f"/posts/{post_id}/like", headers=bob).status_code == 200  # idempotente


def test_like_errors_401_and_404(client):
    alice = register_and_login(client, "alice")
    post_id = new_post(client, alice)

    assert client.put(f"/posts/{post_id}/like").status_code == 401  # sin token
    assert client.put("/posts/9999/like", headers=alice).status_code == 404
    assert client.delete("/posts/9999/like", headers=alice).status_code == 404
    assert client.get("/posts/9999/likes").status_code == 404


def test_user_likes_endpoint(client):
    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    p1, p2, _ = (new_post(client, alice, t) for t in ("uno", "dos", "tres"))
    client.put(f"/posts/{p1}/like", headers=bob)
    client.put(f"/posts/{p2}/like", headers=bob)
    client.put(f"/posts/{p1}/like", headers=alice)  # el like de alice no cuenta para bob

    bob_id = client.get("/auth/me", headers=bob).json()["id"]
    liked = client.get(f"/users/{bob_id}/likes").json()
    assert sorted(p["id"] for p in liked) == sorted([p1, p2])
    assert client.get("/users/9999/likes").status_code == 404

def test_deleting_a_post_deletes_its_likes(client, engine):
    from models import Like
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    post_id = new_post(client, alice)
    client.put(f"/posts/{post_id}/like", headers = bob).status_code == 200
    with Session(engine) as db:
        assert len(db.exec(select(Like)).all()) == 1
    assert client.delete(f"/posts/{post_id}", headers = alice).status_code == 204
    with Session(engine) as db:
            assert db.exec(select(Like)).all() == []

#Follows

def test_follow_updates_both_counters_and_is_idempotent(client):
    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    alice_id, bob_id = user_id(client, alice), user_id(client, bob)

    r = client.put(f"/users/{bob_id}/follow", headers=alice)  # alice sigue a bob
    assert r.status_code == 200
    assert (r.json()["followers_count"], r.json()["following_count"]) == (1, 0)  # bob

    assert client.put(f"/users/{bob_id}/follow", headers=alice).json()["followers_count"] == 1

    alice_profile = client.get(f"/users/{alice_id}").json()
    assert (alice_profile["followers_count"], alice_profile["following_count"]) == (0, 1)


def test_cannot_follow_yourself(client, engine):
    from models import Follow

    alice = register_and_login(client, "alice")
    alice_id = user_id(client, alice)

    assert client.put(f"/users/{alice_id}/follow", headers=alice).status_code == 400

    with Session(engine) as db:
        db.add(Follow(follower_id=alice_id, followed_id=alice_id))
        with pytest.raises(IntegrityError):
            db.commit()


def test_follow_errors_401_and_404(client):
    alice = register_and_login(client, "alice")
    bob_id = user_id(client, register_and_login(client, "bob"))

    assert client.put(f"/users/{bob_id}/follow").status_code == 401
    assert client.put("/users/9999/follow", headers=alice).status_code == 404
    assert client.delete("/users/9999/follow", headers=alice).status_code == 404
    assert client.get("/users/9999/followers").status_code == 404
    assert client.get("/users/9999/following").status_code == 404


def test_unfollow_and_unfollow_again(client):
    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    bob_id = user_id(client, bob)
    client.put(f"/users/{bob_id}/follow", headers=alice)

    assert client.delete(f"/users/{bob_id}/follow", headers=alice).json()["followers_count"] == 0
    assert client.delete(f"/users/{bob_id}/follow", headers=alice).status_code == 200  # idempotente

def test_followers_and_following_are_not_mixed_up(client):
    alice = register_and_login(client, "alice")
    bob = register_and_login(client, "bob")
    carol = register_and_login(client, "carol")
    dave = register_and_login(client, "dave")

    alice_id = user_id(client, alice)
    bob_id = user_id(client, bob)

    # Alice sigue a Bob y a Carol
    client.put(f"/users/{user_id(client, bob)}/follow", headers=alice)
    client.put(f"/users/{user_id(client, carol)}/follow", headers=alice)

    # Dave sigue a Alice
    client.put(f"/users/{alice_id}/follow", headers=dave)

    # Consultar las listas
    alice_following = client.get(
        f"/users/{alice_id}/following"
    ).json()

    alice_followers = client.get(
        f"/users/{alice_id}/followers"
    ).json()

    bob_followers = client.get(
        f"/users/{bob_id}/followers"
    ).json()

    bob_following = client.get(
        f"/users/{bob_id}/following"
    ).json()

    # Comprobar los usernames de cada lista
    assert {u["username"] for u in alice_following} == {"bob", "carol"}
    assert {u["username"] for u in alice_followers} == {"dave"}
    assert {u["username"] for u in bob_followers} == {"alice"}
    assert {u["username"] for u in bob_following} == set()

#Feed

def test_feed_only_has_posts_from_followed_users_and_updates_on_unfollow(client):
    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    carol = register_and_login(client, "carol")
    bob_id = user_id(client, bob)
    own = new_post(client, alice, "propio")
    from_bob = new_post(client, bob, "de bob")
    new_post(client, carol, "de carol")  # alice no sigue a carol
    assert client.get("/feed", headers=alice).json() == []  # todavía no sigue a nadie

    client.put(f"/users/{bob_id}/follow", headers=alice)
    client.put(f"/posts/{from_bob}/like", headers=carol)
    feed = client.get("/feed", headers=alice).json()
    assert [p["id"] for p in feed] == [from_bob]
    assert own not in [p["id"] for p in feed]
    assert feed[0]["likes_count"] == 1  # el feed reutiliza la consulta con likes

    client.delete(f"/users/{bob_id}/follow", headers=alice)
    assert client.get("/feed", headers=alice).json() == []


def test_feed_requires_token(client):
    assert client.get("/feed").status_code == 401


def test_feed_query_count_does_not_grow_with_followed_users(client, sql_log):
    # Detector de N+1: seguir a 1 persona o a 10 debe costar la MISMA cantidad de consultas.
    authors = []
    for i in range(10):
        h = register_and_login(client, f"autor{i}")
        new_post(client, h, f"post {i}")
        authors.append(user_id(client, h))
    few, many = register_and_login(client, "pocos"), register_and_login(client, "muchos")
    client.put(f"/users/{authors[0]}/follow", headers=few)
    for a in authors:
        client.put(f"/users/{a}/follow", headers=many)

    sql_log.clear()
    assert len(client.get("/feed", headers=few).json()) == 1
    queries_for_one = len(sql_log)

    sql_log.clear()
    assert len(client.get("/feed", headers=many).json()) == 10
    assert len(sql_log) == queries_for_one


def test_unfollow_then_refollow_keeps_a_single_row(client, engine):
    # seguir, dejar de seguir y volver a seguir deja UNA sola fila
    from models import Follow
    from sqlmodel import select

    alice, bob = register_and_login(client, "alice"), register_and_login(client, "bob")
    bob_id = user_id(client, bob)
    for _ in range(2):
        client.put(f"/users/{bob_id}/follow", headers=alice)
        client.put(f"/users/{bob_id}/follow", headers=alice)
        client.delete(f"/users/{bob_id}/follow", headers=alice)
    client.put(f"/users/{bob_id}/follow", headers=alice)

    with Session(engine) as db:
        assert len(db.exec(select(Follow)).all()) == 1