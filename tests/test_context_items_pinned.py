from nanobot.web.database import Database


def test_context_items_has_summary_columns(tmp_path) -> None:
    db = Database(tmp_path / "fanfan.db")
    rows = db._get_conn().execute("PRAGMA table_info(context_items)").fetchall()
    cols = [str(r["name"]) for r in rows]

    assert "summary" in cols
    assert "summary_sha256" in cols
    assert "summary_updated_at" in cols


def test_upsert_and_update_context_summary(tmp_path) -> None:
    db = Database(tmp_path / "fanfan.db")
    db.create_session("ses_test", title="Test")

    item = db.upsert_context_item_by_ref(
        session_id="ses_test",
        kind="doc",
        title="Project Guide",
        content_ref="PROJECT_GUIDE.md",
        pinned=True,
    )

    assert item["id"]
    assert int(item.get("pinned") or 0) == 1

    row = db.find_context_item_by_ref("ses_test", "doc", "PROJECT_GUIDE.md")
    assert row is not None
    assert row["id"] == item["id"]

    db.update_context_summary(item["id"], summary="Hello", summary_sha256="abc")

    row2 = db.get_context_item(item["id"])
    assert row2 is not None
    assert row2["summary"] == "Hello"
    assert row2["summary_sha256"] == "abc"
    assert row2["summary_updated_at"]
