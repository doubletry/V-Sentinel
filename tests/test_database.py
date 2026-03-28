"""Tests for aiosqlite database operations."""
from __future__ import annotations

import pytest

from backend.db.database import (
    create_source,
    delete_source,
    get_rois,
    get_source,
    get_source_by_rtsp,
    init_db,
    list_sources,
    save_rois,
    update_source,
)
from backend.models.schemas import ROICreate, ROIPoint, VideoSourceCreate, VideoSourceUpdate


@pytest.fixture(autouse=True)
async def _setup_db(init_db):
    """Ensure the database is initialised for every test in this module."""
    pass


class TestInitDb:
    async def test_creates_tables(self):
        """init_db should be idempotent."""
        from backend.db.database import init_db as _init_db
        await _init_db()  # call again – should not raise


class TestCreateSource:
    async def test_creates_and_returns(self):
        src = await create_source(
            VideoSourceCreate(name="Cam1", rtsp_url="rtsp://a/b")
        )
        assert src.id
        assert src.name == "Cam1"
        assert src.rtsp_url == "rtsp://a/b"
        assert src.rois == []
        assert src.created_at

    async def test_unique_rtsp_url(self):
        await create_source(VideoSourceCreate(name="A", rtsp_url="rtsp://x"))
        with pytest.raises(Exception, match="UNIQUE"):
            await create_source(VideoSourceCreate(name="B", rtsp_url="rtsp://x"))


class TestGetSource:
    async def test_found(self):
        src = await create_source(
            VideoSourceCreate(name="C", rtsp_url="rtsp://c")
        )
        found = await get_source(src.id)
        assert found is not None
        assert found.id == src.id
        assert found.name == "C"

    async def test_not_found(self):
        assert await get_source("nonexistent") is None


class TestGetSourceByRtsp:
    async def test_found(self):
        src = await create_source(
            VideoSourceCreate(name="D", rtsp_url="rtsp://d")
        )
        found = await get_source_by_rtsp("rtsp://d")
        assert found is not None
        assert found.id == src.id

    async def test_not_found(self):
        assert await get_source_by_rtsp("rtsp://missing") is None


class TestListSources:
    async def test_empty(self):
        result = await list_sources()
        assert result == []

    async def test_multiple(self):
        await create_source(VideoSourceCreate(name="A", rtsp_url="rtsp://1"))
        await create_source(VideoSourceCreate(name="B", rtsp_url="rtsp://2"))
        result = await list_sources()
        assert len(result) == 2


class TestUpdateSource:
    async def test_update_name(self):
        src = await create_source(
            VideoSourceCreate(name="Old", rtsp_url="rtsp://u1")
        )
        updated = await update_source(src.id, VideoSourceUpdate(name="New"))
        assert updated is not None
        assert updated.name == "New"
        assert updated.rtsp_url == "rtsp://u1"

    async def test_update_url(self):
        src = await create_source(
            VideoSourceCreate(name="C", rtsp_url="rtsp://old")
        )
        updated = await update_source(
            src.id, VideoSourceUpdate(rtsp_url="rtsp://new")
        )
        assert updated is not None
        assert updated.rtsp_url == "rtsp://new"

    async def test_update_rois(self):
        src = await create_source(
            VideoSourceCreate(name="R", rtsp_url="rtsp://roi")
        )
        rois = [
            ROICreate(
                type="rectangle",
                points=[ROIPoint(x=0.1, y=0.2), ROIPoint(x=0.8, y=0.9)],
                tag="zone",
            )
        ]
        updated = await update_source(src.id, VideoSourceUpdate(rois=rois))
        assert updated is not None
        assert len(updated.rois) == 1
        assert updated.rois[0].tag == "zone"
        assert updated.rois[0].type == "rectangle"

    async def test_not_found(self):
        result = await update_source("bad", VideoSourceUpdate(name="X"))
        assert result is None


class TestDeleteSource:
    async def test_delete_existing(self):
        src = await create_source(
            VideoSourceCreate(name="Del", rtsp_url="rtsp://del")
        )
        assert await delete_source(src.id) is True
        assert await get_source(src.id) is None

    async def test_delete_nonexistent(self):
        assert await delete_source("nope") is False

    async def test_cascade_rois(self):
        """Deleting a source should also delete its ROIs."""
        src = await create_source(
            VideoSourceCreate(name="Cas", rtsp_url="rtsp://cas")
        )
        await save_rois(
            src.id,
            [
                ROICreate(
                    type="polygon",
                    points=[ROIPoint(x=0, y=0), ROIPoint(x=1, y=0), ROIPoint(x=1, y=1)],
                )
            ],
        )
        assert len(await get_rois(src.id)) == 1
        await delete_source(src.id)
        assert await get_rois(src.id) == []


class TestSaveAndGetRois:
    async def test_save_and_get(self):
        src = await create_source(
            VideoSourceCreate(name="RR", rtsp_url="rtsp://rr")
        )
        rois = await save_rois(
            src.id,
            [
                ROICreate(
                    type="rectangle",
                    points=[ROIPoint(x=0, y=0), ROIPoint(x=1, y=1)],
                    tag="a",
                ),
                ROICreate(
                    type="polygon",
                    points=[ROIPoint(x=0, y=0), ROIPoint(x=0.5, y=0.5)],
                    tag="b",
                ),
            ],
        )
        assert len(rois) == 2
        got = await get_rois(src.id)
        assert len(got) == 2

    async def test_replace_rois(self):
        src = await create_source(
            VideoSourceCreate(name="Rep", rtsp_url="rtsp://rep")
        )
        await save_rois(
            src.id,
            [ROICreate(type="rectangle", points=[], tag="old")],
        )
        await save_rois(
            src.id,
            [
                ROICreate(type="polygon", points=[], tag="new1"),
                ROICreate(type="polygon", points=[], tag="new2"),
            ],
        )
        got = await get_rois(src.id)
        assert len(got) == 2
        assert {r.tag for r in got} == {"new1", "new2"}
