"""Tests for the /test app-shell support endpoints: system-info, tech-docs
serving, danger-zone hard ceilings and the dishes.json delete/source-tag
round trip.

No supermarket network calls — DATA_DIR / TECH_DOCS_DIR are monkeypatched
onto tmp paths where file contents matter.
"""
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from NZMealOptimiser.web import main as web_main
from NZMealOptimiser.web.main import (
    CustomIngredient,
    HARD_LIMITS,
    SaveDishRequest,
    _enforce_hard_limits,
)


@pytest.fixture()
def client():
    return TestClient(web_main.app)


@pytest.fixture()
def docs_dir(tmp_path, monkeypatch):
    docs = tmp_path / "technical"
    docs.mkdir()
    (docs / "FastAPI.md").write_text("# FastAPI\nhello", encoding="utf-8")
    monkeypatch.setattr(web_main, "TECH_DOCS_DIR", docs)
    return docs


# ── GET /system-info ──────────────────────────────────────────────────────────

def test_system_info_reports_workers_and_limits(client):
    data = client.get("/system-info").json()
    assert data["max_workers"] >= 1
    assert data["slider_min"] == web_main.WORKER_POOL_MIN
    assert data["slider_max"] == web_main.WORKER_POOL_MAX
    assert data["slider_step"] == web_main.WORKER_POOL_STEP
    assert isinstance(data["running_jobs"], int) and data["running_jobs"] >= 0
    assert data["hard_limits"] == {
        "max_distance_km": 50.0,
        "max_stores_per_company": 20,
    }
    # ``configured_workers`` was removed when the .env ceiling went away.
    assert "configured_workers" not in data


def test_thread_pool_matches_effective_workers():
    assert web_main._THREAD_POOL.max_workers == web_main._THREAD_POOL.executor._max_workers
    assert web_main._THREAD_POOL.max_workers == web_main.WORKER_POOL_MIN


# ── POST /system/thread-pool + /system/running-jobs ──────────────────────────

def _original_pool_size() -> int:
    """Snapshot the live pool size so each test can restore it. Reads
    through the wrapper so we never touch the underlying executor.
    """
    return web_main._THREAD_POOL.max_workers


def _swap_to(client, n: int):
    return client.post("/system/thread-pool", json={"max_workers": n})


@pytest.fixture()
def restore_pool():
    """Restore the thread pool to its pre-test size after every test
    that mutates it. Without this, test order would leak state into
    later tests in the same session.
    """
    original = _original_pool_size()
    yield
    if web_main._THREAD_POOL.max_workers != original:
        web_main._THREAD_POOL.set_max_workers(original)


@pytest.mark.parametrize("target", [25, 30, 35, 40])
def test_thread_pool_swap_in_range(target, client, restore_pool):
    response = _swap_to(client, target)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_workers"] == target
    assert body["running_jobs"] == 0
    assert body["changed"] is True
    assert web_main._THREAD_POOL.max_workers == target


def test_thread_pool_swap_to_lower_bound_succeeds(client, restore_pool):
    """Lower-boundary case — first move away from 20, then back, and
    confirm the 20 boundary accepts a real swap (not just a noop).
    """
    _swap_to(client, 35)
    response = _swap_to(client, 20)
    assert response.status_code == 200
    assert response.json()["max_workers"] == 20
    assert web_main._THREAD_POOL.max_workers == 20


def test_thread_pool_swap_noop_when_already_at_target(client, restore_pool):
    current = web_main._THREAD_POOL.max_workers
    response = _swap_to(client, current)
    assert response.status_code == 200
    assert response.json()["changed"] is False


@pytest.mark.parametrize("bad", [19, 15, 1, 41, 50, 100])
def test_thread_pool_swap_rejects_out_of_range(bad, client, restore_pool):
    response = _swap_to(client, bad)
    assert response.status_code == 400
    assert "between" in response.json()["detail"]


@pytest.mark.parametrize("bad", [21, 22, 23, 24, 26, 27, 28, 29, 31, 32, 33, 34, 36, 37, 38, 39])
def test_thread_pool_swap_rejects_non_step_values(bad, client, restore_pool):
    response = _swap_to(client, bad)
    assert response.status_code == 400
    assert "step" in response.json()["detail"]


def test_thread_pool_swap_rejects_when_jobs_running(client, restore_pool):
    req = web_main.DishRequest(dish="x", address="Auckland", companies=["Woolworths"])
    fake = web_main.JobState(req)
    fake.status = "running"
    web_main.JOBS[fake.id] = fake
    original = web_main._THREAD_POOL.max_workers
    try:
        response = _swap_to(client, 25)
        assert response.status_code == 409
        body = response.json()["detail"]
        assert body["error"] == "running_jobs"
        assert body["count"] >= 1
        # Pool must not have been mutated.
        assert web_main._THREAD_POOL.max_workers == original
    finally:
        web_main.JOBS.pop(fake.id, None)


def test_thread_pool_swap_accepted_after_jobs_finish(client, restore_pool):
    req = web_main.DishRequest(dish="x", address="Auckland", companies=["Woolworths"])
    fake = web_main.JobState(req)
    fake.status = "complete"
    web_main.JOBS[fake.id] = fake
    try:
        response = _swap_to(client, 25)
        assert response.status_code == 200
        assert response.json()["max_workers"] == 25
    finally:
        web_main.JOBS.pop(fake.id, None)


def test_running_jobs_endpoint_counts_only_running(client):
    req = web_main.DishRequest(dish="x", address="Auckland", companies=["Woolworths"])
    a = web_main.JobState(req); a.status = "running"
    b = web_main.JobState(req); b.status = "complete"
    c = web_main.JobState(req); c.status = "error"
    web_main.JOBS[a.id] = a
    web_main.JOBS[b.id] = b
    web_main.JOBS[c.id] = c
    try:
        assert client.get("/system/running-jobs").json() == {"count": 1}
    finally:
        for k in (a.id, b.id, c.id):
            web_main.JOBS.pop(k, None)


def test_thread_pool_swap_serialises_under_concurrent_load(client, restore_pool):
    """Fire two POSTs in parallel from threads; the lock in
    ``_ResizableThreadPool.set_max_workers`` must serialise them so
    neither call is lost or interleaves. We don't assert which wins,
    only that both complete without raising and the final size is one
    of the two requested values.
    """
    import threading

    barrier = threading.Barrier(2)
    results: list[dict] = []

    def worker(target: int) -> None:
        barrier.wait()
        results.append(_swap_to(client, target).json())

    t1 = threading.Thread(target=worker, args=(25,))
    t2 = threading.Thread(target=worker, args=(35,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(results) == 2
    final_size = web_main._THREAD_POOL.max_workers
    assert final_size in (25, 35)


def test_thread_pool_swap_drains_old_executor(restore_pool):
    """After a swap, the old executor must have been shut down. The
    cleanest signal is that ``_executor`` is no longer the object that
    was there before the swap.
    """
    original = web_main._THREAD_POOL.executor
    web_main._THREAD_POOL.set_max_workers(25)
    new = web_main._THREAD_POOL.executor
    assert new is not original
    # ``shutdown(wait=False)`` returns quickly; we don't wait for
    # in-flight futures here because the running-jobs gate guarantees
    # there are none.


def test_system_info_includes_slider_metadata_and_running_jobs(client):
    data = client.get("/system-info").json()
    assert data["slider_min"] >= 1
    assert data["slider_max"] >= data["slider_min"]
    assert data["slider_step"] >= 1
    assert data["running_jobs"] >= 0
    assert data["max_workers"] <= data["slider_max"]
    assert data["max_workers"] >= data["slider_min"]


# ── Pool-swap regression: /stores/nearby + /geocode must keep working ────────
#
# These guard logs.md #67. The original bug had two layers:
#
# 1. ``_ResizableThreadPool.set_max_workers`` ended with a
#    ``try: loop = asyncio.get_running_loop(); loop.set_default_executor(new)
#    except RuntimeError: pass`` block that was supposed to rebind the
#    asyncio loop's default executor after a swap. But ``set_max_workers``
#    is invoked via ``await asyncio.to_thread(set_max_workers, ...)`` from
#    the swap handler, so it runs on a threadpool worker thread — where
#    ``asyncio.get_running_loop()`` ALWAYS raises
#    ``RuntimeError("no running event loop")``. The exception was
#    silently swallowed, the rebind never fired, the loop kept pointing
#    at the just-``shutdown(wait=False)``-d old executor, and every
#    subsequent ``await asyncio.to_thread(...)`` raised
#    ``RuntimeError("cannot schedule new futures after shutdown")`` → 500.
#
# 2. The handler being ``def`` (sync) added a second layer of confusion:
#    FastAPI would have run it on anyio's threadpool, so even if (1) were
#    fixed in-place the rebind still wouldn't fire. The fix flips (1) and
#    (2) at the same time:
#      - ``set_max_workers`` no longer touches the loop executor at all.
#      - The async handler captures ``_THREAD_POOL.executor`` after the
#        swap and calls ``asyncio.get_running_loop().set_default_executor``
#        itself (it IS on the loop thread).
#
# The white-box ``test_pool_swap_handler_is_async`` +
# ``test_set_max_workers_does_not_touch_loop_executor`` tests pin the
# invariants so the original bug can't be re-introduced.

def test_stores_nearby_works_after_pool_swap(client, restore_pool):
    """Regression for logs.md #67: after a successful pool swap, the
    dashboard's preview endpoint must still return 200 + a non-empty
    ``stores`` list. Before the fix, the post-swap ``/stores/nearby``
    call 500-ed with "Executor shutdown has been called" because the
    loop's default executor was never rebound.
    """
    swap = _swap_to(client, 25)
    assert swap.status_code == 200, swap.text
    response = client.get(
        "/stores/nearby",
        params={
            "lat": -36.84,
            "lon": 174.74,
            "distance_km": 5,
            "companies": "Woolworths,PaknSave,NewWorld",
            "max_per_company": 3,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "stores" in body, body
    assert body["stores"], f"expected non-empty store list after pool swap, got: {body}"


def test_geocode_works_after_pool_swap(client, restore_pool):
    """Regression for logs.md #67: /geocode must keep returning 200
    after a pool swap. Same root cause as ``/stores/nearby`` — the
    loop's default executor must be rebound or every
    ``asyncio.to_thread`` call 500-s.
    """
    _swap_to(client, 25)
    response = client.get("/geocode", params={"address": "Auckland"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "lat" in body and "lon" in body, body


def test_pool_swap_handler_is_async(monkeypatch, client, restore_pool):
    """White-box regression for logs.md #67: ``thread_pool_swap`` must
    be declared ``async def`` so FastAPI runs it on the event-loop
    thread — that's where the asyncio loop executor rebind has to happen.
    """
    import inspect

    assert inspect.iscoroutinefunction(web_main.thread_pool_swap), (
        "thread_pool_swap must be async def — only the loop thread can "
        "rebind asyncio's default executor (logs.md #67)."
    )


def test_set_max_workers_does_not_touch_loop_executor(restore_pool, monkeypatch):
    """White-box regression for logs.md #67: ``_ResizableThreadPool.set_max_workers``
    must NOT call ``asyncio.get_running_loop`` or
    ``loop.set_default_executor``. The method is invoked via
    ``await asyncio.to_thread(set_max_workers, ...)`` from the swap
    handler, so it runs on a threadpool worker thread where both calls
    either fail (``get_running_loop``) or have no effect on the loop
    that will be running future ``asyncio.to_thread`` calls. The actual
    rebind is the swap handler's responsibility (it IS on the loop
    thread).

    We compile the method's source into an AST and assert there are no
    ``Call`` nodes referring to either name. A naive substring check on
    the source would trip over the docstring that explains *why* the
    names aren't called.
    """
    import ast
    import inspect

    src = inspect.getsource(web_main._THREAD_POOL.set_max_workers)
    tree = ast.parse(src.lstrip())
    func = tree.body[0]  # the ``def set_max_workers(...)`` node
    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))

    called_names: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            name = ast.unparse(node.func)
            called_names.add(name)
            self.generic_visit(node)

    _Visitor().visit(func)

    assert not any(n == "asyncio.get_running_loop" for n in called_names), (
        "_ResizableThreadPool.set_max_workers must not call "
        "asyncio.get_running_loop — it runs on a worker thread where "
        "that always raises RuntimeError, so any rebind attempt is a "
        "silent no-op (logs.md #67)."
    )
    assert not any(n.endswith(".set_default_executor") for n in called_names), (
        "_ResizableThreadPool.set_max_workers must not call "
        "set_default_executor — the rebind must happen on the loop "
        "thread, which means the swap handler does it (logs.md #67)."
    )


# ── GET /tech-docs ────────────────────────────────────────────────────────────

def test_tech_docs_lists_all_manuals(client):
    docs = client.get("/tech-docs").json()
    names = {d["name"] for d in docs}
    assert {"FastAPI.md", "PaknSave_API.md", "Woolworths_API.md"} <= names
    assert all(set(d) == {"name", "title"} for d in docs)


def test_tech_doc_file_serves_markdown(client, docs_dir):
    response = client.get("/tech-docs/FastAPI.md")
    assert response.status_code == 200
    assert "markdown" in response.headers["content-type"]
    assert response.text.startswith("# FastAPI")


def test_tech_doc_rejects_unknown_names(client):
    assert client.get("/tech-docs/not-a-doc.md").status_code == 404
    # Path traversal attempts fall outside the whitelist too.
    assert client.get("/tech-docs/..%2Fmain.py").status_code in (404, 400)


# ── Danger-zone hard ceilings ────────────────────────────────────────────────

@pytest.mark.parametrize("distance,stores", [(51, 3), (-1, 3), (5, 21), (5, 0)])
def test_enforce_hard_limits_rejects(distance, stores):
    with pytest.raises(HTTPException) as exc:
        _enforce_hard_limits(distance, stores)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("distance,stores", [(50, 20), (0.5, 1), (5, 3)])
def test_enforce_hard_limits_accepts_edge_values(distance, stores):
    _enforce_hard_limits(distance, stores)  # no raise


def test_job_submission_rejects_over_ceiling(client):
    payload = {
        "dish": "spaghetti bolognese",
        "address": "Auckland CBD",
        "distance_km": 51,
        "companies": ["Woolworths"],
    }
    response = client.post("/optimise/jobs", json=payload)
    assert response.status_code == 400
    assert "distance_km" in response.json()["detail"]


def test_nearby_preview_caps_at_hard_limit(client):
    params = {"lat": -36.85, "lon": 174.76, "distance_km": 60}
    response = client.get("/stores/nearby", params=params)
    assert response.status_code == 400


# ── dishes.json: source tag + DELETE ─────────────────────────────────────────

def test_save_tags_user_source_and_delete_round_trip(tmp_path, monkeypatch, client):
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    seed = {"beef curry": {"dish_name": "Beef Curry", "portion": 4, "ingredients": []}}
    (tmp_path / "dishes.json").write_text(json.dumps(seed), encoding="utf-8")

    save = client.post("/dishes/save", json=SaveDishRequest(
        dish_name="Kumara Hash",
        base_portions=2,
        ingredients=[CustomIngredient(search_term="kumara", quantity=300, unit="g")],
    ).model_dump())
    assert save.status_code == 200
    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    assert stored["kumara hash"]["source"] == "user"
    assert "source" not in seed["beef curry"] or seed["beef curry"].get("source") != "user"

    deleted = client.delete("/dishes/kumara hash")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True, "key": "kumara hash", "was_user": True, "dishes_count": 1}
    assert "kumara hash" not in json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))


def test_delete_curated_dish_flags_was_user_false(tmp_path, monkeypatch, client):
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    seed = {"lasagna": {"dish_name": "Lasagna", "portion": 4, "ingredients": []}}
    (tmp_path / "dishes.json").write_text(json.dumps(seed), encoding="utf-8")

    deleted = client.delete("/dishes/lasagna")
    assert deleted.status_code == 200
    assert deleted.json()["was_user"] is False
    assert deleted.json()["dishes_count"] == 0


def test_delete_unknown_dish_404(tmp_path, monkeypatch, client):
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    (tmp_path / "dishes.json").write_text("{}", encoding="utf-8")
    assert client.delete("/dishes/nope").status_code == 404


def test_save_persists_notes_top_level_key(tmp_path, monkeypatch, client):
    """POST /dishes/save with a notes field persists it as a top-level
    key on the entry (trimmed to <=100 chars); omitting notes leaves
    the key absent. See main.py:849-851."""
    monkeypatch.setattr(web_main, "DATA_DIR", tmp_path)
    (tmp_path / "dishes.json").write_text("{}", encoding="utf-8")

    save = client.post("/dishes/save", json=SaveDishRequest(
        dish_name="Kumara Hash",
        base_portions=4,
        ingredients=[CustomIngredient(search_term="kumara", quantity=300, unit="g")],
        notes="  from bbcgoodfood.com ",
    ).model_dump())
    assert save.status_code == 200
    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    assert stored["kumara hash"]["notes"] == "from bbcgoodfood.com"

    save2 = client.post("/dishes/save", json=SaveDishRequest(
        dish_name="No Notes Dish",
        base_portions=2,
        ingredients=[CustomIngredient(search_term="rice", quantity=500, unit="g")],
    ).model_dump())
    assert save2.status_code == 200
    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    assert "notes" not in stored["no notes dish"]

    long_notes = "x" * 200
    save3 = client.post("/dishes/save", json=SaveDishRequest(
        dish_name="Truncated Notes",
        base_portions=2,
        ingredients=[CustomIngredient(search_term="rice", quantity=500, unit="g")],
        notes=long_notes,
    ).model_dump())
    assert save3.status_code == 200
    stored = json.loads((tmp_path / "dishes.json").read_text(encoding="utf-8"))
    assert len(stored["truncated notes"]["notes"]) == 100
