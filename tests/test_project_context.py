def test_project_context_loader_importable_from_root():
    """ProjectContextLoader must be importable from project_context (not context.project_context)."""
    from everstaff.project_context import ProjectContextLoader
    loader = ProjectContextLoader()
    assert loader is not None


def test_project_context_loader_returns_empty_for_missing_dir(tmp_path):
    from everstaff.project_context import ProjectContextLoader
    loader = ProjectContextLoader()
    result = loader.load(project_dir=str(tmp_path / "nonexistent"))
    assert result == ""
