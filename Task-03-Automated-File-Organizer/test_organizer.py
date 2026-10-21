import json
import os
import tempfile
import time
from pathlib import Path

import pytest

# Keep test runs away from the real ~/.organizer folder (set before import).
os.environ["ORGANIZER_HOME"] = tempfile.mkdtemp(prefix="organizer_home_")

import organizer as cli  # noqa: E402
import organizer as core  # noqa: E402
import organizer as history  # noqa: E402
from organizer import (  # noqa: E402
    candidate_names,
    execute_plan,
    get_category,
    plan_moves,
    remove_empty_dirs,
    safe_move,
    scan_files,
    validate_folder,
)

# ---- test_core ----


def make(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_get_category_known_and_unknown():
    assert get_category("report.PDF") == "Documents"
    assert get_category("photo.jpeg") == "Images"
    assert get_category("x.weird") == "Other"
    assert get_category("noextension") == "Other"


def test_candidate_names_sequence(tmp_path):
    names = candidate_names(tmp_path / "a.txt")
    assert [next(names).name for _ in range(3)] == [
        "a.txt",
        "a_1.txt",
        "a_2.txt",
    ]


def test_safe_move_never_overwrites(tmp_path):
    make(tmp_path / "Docs" / "a.txt", "old")
    src = make(tmp_path / "a.txt", "new")
    dest = safe_move(src, tmp_path / "Docs", tmp_path)
    assert dest.name == "a_1.txt"
    assert (tmp_path / "Docs" / "a.txt").read_text() == "old"
    assert dest.read_text() == "new"


def test_safe_move_refuses_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    src = make(root / "a.txt")
    with pytest.raises(PermissionError):
        safe_move(src, tmp_path / "elsewhere", root)
    assert src.exists()


def test_scan_skips_hidden_temp_and_organizer_folders(tmp_path):
    make(tmp_path / "keep.txt")
    make(tmp_path / ".hidden.txt")
    make(tmp_path / "video.crdownload")
    make(tmp_path / "Images" / "done.png")
    make(tmp_path / "2026-10" / "done.txt")
    make(tmp_path / "sub" / "deep.mp3")
    names = {i.name for i in scan_files(tmp_path, recursive=True)}
    assert names == {"keep.txt", "deep.mp3"}


def test_scan_non_recursive_ignores_subfolders(tmp_path):
    make(tmp_path / "a.txt")
    make(tmp_path / "sub" / "b.txt")
    assert [i.name for i in scan_files(tmp_path)] == ["a.txt"]


def test_scan_missing_folder_raises(tmp_path):
    with pytest.raises(OSError):
        scan_files(tmp_path / "nope")


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("type", "Documents"),
        ("date", "2026-03"),
        ("type_date", os.path.join("Documents", "2026-03")),
    ],
)
def test_target_folder_modes(tmp_path, mode, expected):
    f = make(tmp_path / "a.txt")
    ts = time.mktime((2026, 3, 15, 12, 0, 0, 0, 0, -1))
    os.utime(f, (ts, ts))
    item = scan_files(tmp_path)[0]
    assert core.target_folder_for(item, tmp_path, mode) == tmp_path / expected


def test_plan_flags_collisions_without_touching_disk(tmp_path):
    make(tmp_path / "Documents" / "a.txt", "old")
    make(tmp_path / "a.txt", "new")
    make(tmp_path / "sub" / "a.txt", "newer")
    plan = plan_moves(scan_files(tmp_path, True), tmp_path, "type")
    names = sorted(p.destination.name for p in plan)
    assert names == ["a_1.txt", "a_2.txt"]
    assert all(p.renamed for p in plan)
    assert (tmp_path / "a.txt").exists()  # nothing moved


def test_plan_skips_files_already_in_place(tmp_path):
    make(tmp_path / "Documents" / "a.txt")
    items = scan_files(tmp_path, False) + [
        core.FileItem(tmp_path / "Documents" / "a.txt", 1, 0.0)
    ]
    assert plan_moves(items, tmp_path, "type") == []


def test_execute_plan_moves_and_records(tmp_path):
    make(tmp_path / "a.txt")
    make(tmp_path / "b.png")
    plan = plan_moves(scan_files(tmp_path), tmp_path, "type")
    moves = []
    results = execute_plan(plan, tmp_path, moves)
    assert all(r.ok for r in results)
    assert len(moves) == 2
    assert (tmp_path / "Documents" / "a.txt").exists()
    assert (tmp_path / "Images" / "b.png").exists()


def test_execute_plan_reports_failure_and_continues(tmp_path, monkeypatch):
    make(tmp_path / "a.txt")
    make(tmp_path / "b.txt")
    plan = plan_moves(scan_files(tmp_path), tmp_path, "type")
    real = core.safe_move
    calls = {"n": 0}

    def flaky(*args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked")
        return real(*args)

    monkeypatch.setattr(core, "safe_move", flaky)
    moves = []
    results = execute_plan(plan, tmp_path, moves)
    assert [r.ok for r in results] == [False, True]
    assert "permission denied" in results[0].error
    assert len(moves) == 1


def test_remove_empty_dirs_keeps_root_and_nonempty(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    make(tmp_path / "keep" / "f.txt")
    removed = remove_empty_dirs(
        [tmp_path / "a" / "b", tmp_path / "keep"], tmp_path
    )
    assert removed == 2
    assert not (tmp_path / "a").exists()
    assert (tmp_path / "keep" / "f.txt").exists()
    assert tmp_path.exists()


class TestValidateFolder:
    def test_valid_folder(self, tmp_path):
        folder, problem = validate_folder(str(tmp_path))
        assert folder == tmp_path.resolve() and problem is None

    def test_quotes_are_stripped(self, tmp_path):
        folder, _ = validate_folder(f'"{tmp_path}"')
        assert folder == tmp_path.resolve()

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty(self, raw):
        assert validate_folder(raw)[0] is None

    def test_missing(self, tmp_path):
        assert "does not exist" in validate_folder(str(tmp_path / "x"))[1]

    def test_file_not_folder(self, tmp_path):
        f = make(tmp_path / "a.txt")
        assert "file" in validate_folder(str(f))[1]

    def test_drive_root(self):
        root = os.path.abspath(os.sep)
        assert validate_folder(root)[0] is None

    def test_symlink(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not available")
        assert "Symbolic" in validate_folder(str(link))[1]

    def test_home_folder_rejected(self):
        assert validate_folder(os.path.expanduser("~"))[0] is None

    @pytest.mark.skipif(os.name == "nt", reason="unix paths")
    def test_system_folder(self):
        assert "System" in validate_folder("/etc")[1]


# ---- test_history ----


def organize_tmp(tmp_path, hist):
    plan = plan_moves(scan_files(tmp_path, True), tmp_path, "type")
    moves = []
    execute_plan(plan, tmp_path, moves)
    history.record_run(tmp_path, "type", moves, hist)
    return moves


def test_missing_and_corrupt_history_give_empty_list(tmp_path):
    assert history.load_history(tmp_path / "none.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert history.load_history(bad) == []
    bad.write_text(json.dumps({"a": 1}))
    assert history.load_history(bad) == []


def test_record_and_find_last_run(tmp_path):
    hist = tmp_path / "h.json"
    work = tmp_path / "work"
    make(work / "a.txt")
    organize_tmp(work, hist)
    runs = history.load_history(hist)
    run = history.find_last_run(runs, work)
    assert run is not None and len(run["moves"]) == 1
    assert history.find_last_run(runs, tmp_path / "other") is None


def test_undo_round_trip_restores_and_tidies(tmp_path):
    hist = tmp_path / "h.json"
    work = tmp_path / "work"
    make(work / "sub" / "a.txt", "hello")
    organize_tmp(work, hist)
    runs = history.load_history(hist)
    run = history.find_last_run(runs, work)
    result = history.undo_run(work, run)
    assert result.restored == 1 and result.failed == 0
    assert (work / "sub" / "a.txt").read_text() == "hello"
    assert not (work / "Documents").exists()
    assert run["undone"] is True


def test_undo_uses_numbered_name_when_original_occupied(tmp_path):
    hist = tmp_path / "h.json"
    work = tmp_path / "work"
    make(work / "a.txt", "mine")
    organize_tmp(work, hist)
    make(work / "a.txt", "someone else")
    run = history.find_last_run(history.load_history(hist), work)
    history.undo_run(work, run)
    assert (work / "a.txt").read_text() == "someone else"
    assert (work / "a_1.txt").read_text() == "mine"


def test_partial_undo_is_idempotent(tmp_path):
    hist = tmp_path / "h.json"
    work = tmp_path / "work"
    make(work / "a.txt")
    make(work / "b.txt")
    moves = organize_tmp(work, hist)
    run = history.find_last_run(history.load_history(hist), work)

    gone = [m for m in moves if m[0].endswith("b.txt")][0][1]
    saved = tmp_path / "saved.txt"
    (work / "Documents" / "b.txt").rename(saved)  # simulate a missing file
    first = history.undo_run(work, run)
    assert (first.restored, first.failed) == (1, 1)
    assert run["undone"] is False

    (work / "Documents").mkdir(exist_ok=True)
    saved.rename(gone)  # file comes back
    second = history.undo_run(work, run)
    assert second.already_done == 1  # a.txt not reported as an error
    assert (second.restored, second.failed) == (1, 0)
    assert run["undone"] is True


def test_malformed_moves_are_ignored(tmp_path):
    run = {"moves": [["only-one"], "junk", [1, 2], ["/a", "/b"]]}
    assert history.valid_moves(run) == [(Path("/a"), Path("/b"))]


def test_undo_refuses_paths_outside_folder(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    outside = make(tmp_path / "outside.txt")
    run = {"moves": [[str(tmp_path / "x.txt"), str(outside)]]}
    result = history.undo_run(work, run)
    assert result.failed == 1 and outside.exists()


def test_history_keeps_only_recent_runs(tmp_path):
    hist = tmp_path / "h.json"
    for i in range(history.MAX_RUNS + 5):
        history.record_run(tmp_path, "type", [[f"a{i}", f"b{i}"]], hist)
    assert len(history.load_history(hist)) == history.MAX_RUNS


# ---- test_cli ----


def test_dry_run_changes_nothing(tmp_path, capsys):
    make(tmp_path / "a.txt")
    code = cli.main([str(tmp_path), "--dry-run"])
    assert code == 0
    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / "Documents").exists()
    assert "Preview complete" in capsys.readouterr().out


def test_dry_run_shows_collision_rename(tmp_path, capsys):
    make(tmp_path / "Documents" / "a.txt")
    make(tmp_path / "a.txt")
    cli.main([str(tmp_path), "--dry-run"])
    assert "a_1.txt" in capsys.readouterr().out


def test_organize_then_undo(tmp_path):
    make(tmp_path / "sub" / "a.txt", "hi")
    make(tmp_path / "pic.png")
    assert cli.main([str(tmp_path), "--yes"]) == 0
    assert (tmp_path / "Documents" / "a.txt").exists()
    assert not (tmp_path / "sub").exists()  # empty folder cleaned up
    assert cli.main([str(tmp_path), "--undo", "--yes"]) == 0
    assert (tmp_path / "sub" / "a.txt").read_text() == "hi"
    assert (tmp_path / "pic.png").exists()


def test_no_recursive_leaves_subfolders(tmp_path):
    make(tmp_path / "sub" / "a.txt")
    make(tmp_path / "b.txt")
    cli.main([str(tmp_path), "--yes", "--no-recursive"])
    assert (tmp_path / "sub" / "a.txt").exists()
    assert (tmp_path / "Documents" / "b.txt").exists()


def test_confirmation_declined_moves_nothing(tmp_path, monkeypatch):
    make(tmp_path / "a.txt")
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    assert cli.main([str(tmp_path)]) == 1
    assert (tmp_path / "a.txt").exists()


def test_invalid_folder_returns_error_code(tmp_path):
    assert cli.main([str(tmp_path / "missing")]) == 2


def test_ctrl_c_mid_run_keeps_undo_history(tmp_path, monkeypatch):
    make(tmp_path / "a.txt")
    make(tmp_path / "b.txt")
    real = core.safe_move
    calls = {"n": 0}

    def interrupt(*args):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return real(*args)

    monkeypatch.setattr(core, "safe_move", interrupt)
    assert cli.main([str(tmp_path), "--yes"]) == 130
    monkeypatch.setattr(core, "safe_move", real)

    run = history.find_last_run(history.load_history(), tmp_path)
    assert run is not None and len(run["moves"]) == 1
    assert cli.main([str(tmp_path), "--undo", "--yes"]) == 0
    assert (tmp_path / "a.txt").exists() and (tmp_path / "b.txt").exists()


def test_choose_mode_invalid_input_is_reported(monkeypatch, capsys):
    settings = {"mode": "type", "recursive": True}
    monkeypatch.setattr("builtins.input", lambda *_: "9")
    cli.choose_mode(settings)
    assert settings["mode"] == "type"
    assert "INVALID" in capsys.readouterr().out


def test_choose_mode_valid_input(monkeypatch):
    settings = {"mode": "type", "recursive": True}
    monkeypatch.setattr("builtins.input", lambda *_: "3")
    cli.choose_mode(settings)
    assert settings["mode"] == "date"
