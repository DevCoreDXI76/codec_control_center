def test_project_imports():
    import app  # noqa: F401


async def test_asyncio_mode_works():
    assert True
