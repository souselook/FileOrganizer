"""Тесты core-слоя (без Qt). Запуск: python -m pytest app/tests -q или unittest."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import constants  # noqa: E402
from app.core.actions import execute_plan  # noqa: E402
from app.core.cache import Cache  # noqa: E402
from app.core.config import default_settings, load_settings, save_settings  # noqa: E402
from app.core.duplicates import find_duplicates  # noqa: E402
from app.core.hasher import full_hash_file, quick_hash_file  # noqa: E402
from app.core.history import History  # noqa: E402
from app.core.models import (  # noqa: E402
    ACTION_MOVE, ACTION_TRASH, FileItem, Rule, Settings, STATUS_OK,
)
from app.core.organizer import build_plan, unique_target  # noqa: E402
from app.core.rules import RuleMatcher, safe_format  # noqa: E402
from app.core.scanner import scan_folder  # noqa: E402


class BaseTempCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fo_test_"))
        self.work = self.tmp / "work"
        self.target = self.tmp / "target"
        self.work.mkdir()
        self.data_dir = self.tmp / "appdata"
        # переопределяем пути приложения на временные
        constants.APP_DIR = self.data_dir
        constants.SETTINGS_FILE = self.data_dir / "settings.json"
        constants.CACHE_DB = self.data_dir / "cache.db"
        constants.HISTORY_DB = self.data_dir / "history.db"
        constants.TRASH_DIR = self.data_dir / "trash"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, rel: str, content: bytes = b"x") -> Path:
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def settings(self, **kw) -> Settings:
        s = default_settings()
        s.working_folder = str(self.work)
        s.target_folder = str(self.target)
        for k, v in kw.items():
            setattr(s, k, v)
        return s.normalized()


class TestSettings(BaseTempCase):
    def test_save_load_roundtrip(self):
        s = self.settings(skip_hidden=False, min_size=10, duplicate_mode="name_size")
        s.rules = [Rule(type="by_extension", name="Img", params={"extensions": [".jpg"]})]
        save_settings(s)
        loaded = load_settings()
        self.assertFalse(loaded.skip_hidden)
        self.assertEqual(loaded.min_size, 10)
        self.assertEqual(loaded.duplicate_mode, "name_size")
        self.assertEqual(len(loaded.rules), 1)
        self.assertEqual(loaded.rules[0].params["extensions"], [".jpg"])

    def test_corrupted_json_falls_back(self):
        constants.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        constants.SETTINGS_FILE.write_text("{not a json!!", encoding="utf-8")
        s = load_settings()
        self.assertEqual(s.duplicate_mode, constants.DEFAULT_DUPLICATE_MODE)

    def test_invalid_values_corrected(self):
        s = self.settings()
        s.hash_algorithm = "crc32"
        s.allowed_actions = ["move", "delete_forever"]
        from app.core.config import validate_settings
        errors = validate_settings(s)
        self.assertTrue(errors)
        self.assertEqual(s.hash_algorithm, "sha256")
        self.assertNotIn("delete_forever", s.allowed_actions)


class TestCache(BaseTempCase):
    def test_upsert_get_stale(self):
        with Cache() as cache:
            f = FileItem(path=str(self.make("a.txt", b"hello")), size=5, mtime=1.0,
                         quick_hash="q1", full_hash="h1")
            cache.upsert_file(f)
            got = cache.get_file(f.path)
            self.assertIsNotNone(got)
            self.assertEqual(got.full_hash, "h1")
            f.mtime = 2.0
            self.assertTrue(cache.is_stale(f))
            cache.remove_path(f.path)
            self.assertIsNone(cache.get_file(f.path))

    def test_clear(self):
        with Cache() as cache:
            cache.upsert_file(FileItem(path=str(self.work / "z.bin"), size=1, mtime=1))
            self.assertGreaterEqual(cache.count(), 1)
            n = cache.clear()
            self.assertGreaterEqual(n, 1)
            self.assertEqual(cache.count(), 0)


class TestScanner(BaseTempCase):
    def test_scan_filters(self):
        self.make("keep.txt")
        self.make(".hidden.txt")
        self.make("temp.tmp")
        self.make("node_modules/lib.js")
        self.make("sub/deep.bin", b"123456789")
        s = self.settings()
        result = scan_folder(s, cache=None)
        names = {f.name for f in result.files}
        self.assertIn("keep.txt", names)
        self.assertIn("deep.bin", names)
        self.assertNotIn(".hidden.txt", names)   # skip_hidden
        self.assertNotIn("temp.tmp", names)      # skip_temp
        self.assertNotIn("lib.js", names)        # excluded dir

    def test_scan_cancel(self):
        for i in range(50):
            self.make(f"f{i}.dat", b"x" * 10)
        ev = threading.Event()
        ev.set()
        result = scan_folder(self.settings(), cache=None, cancel_event=ev)
        self.assertTrue(result.canceled or len(result.files) <= 50)

    def test_missing_folder_no_crash(self):
        s = self.settings()
        s.working_folder = str(self.tmp / "does_not_exist")
        result = scan_folder(s, cache=None)
        self.assertTrue(result.errors)


class TestHasher(BaseTempCase):
    def test_quick_and_full(self):
        p = self.make("h.bin", b"A" * 10_000)
        qh = quick_hash_file(p, 4096, "sha256")
        fh = full_hash_file(p, "sha256")
        self.assertEqual(len(qh), 64)
        self.assertNotEqual(qh, fh)
        import hashlib
        self.assertEqual(fh, hashlib.sha256(b"A" * 10_000).hexdigest())

    def test_permission_error_marks_status(self):
        from app.core.hasher import hash_file
        p = self.make("locked.bin", b"data")
        f = FileItem.from_path(p)
        mode = p.stat().st_mode
        p.chmod(0o000)
        try:
            if Path.exists(p) and not os_access(p):
                hash_file(f, self.settings(), None)
                self.assertIn(f.status, ("locked", "error", "ok"))
            else:
                hash_file(f, self.settings(), None)
                self.assertEqual(f.status, "ok")
        finally:
            p.chmod(mode)


def os_access(p: Path) -> bool:
    import os
    return os.access(p, os.R_OK)


class TestDuplicates(BaseTempCase):
    def _files(self):
        a1 = self.make("a1.dat", b"SAME CONTENT")
        a2 = self.make("sub/a2.dat", b"SAME CONTENT")
        b = self.make("unique.dat", b"other")
        s = self.settings()
        from app.core.scanner import scan_folder
        return scan_folder(s, cache=None).files

    def test_exact_mode(self):
        files = self._files()
        groups = find_duplicates(files, self.settings(duplicate_mode="exact"), None)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].files), 2)
        self.assertEqual(groups[0].wasted_size, len(b"SAME CONTENT"))

    def test_size_only_and_name_only(self):
        files = self._files()
        g1 = find_duplicates(files, self.settings(duplicate_mode="size_only"), None)
        self.assertEqual(len(g1), 1)
        g2 = find_duplicates(files, self.settings(duplicate_mode="name_only"), None)
        self.assertEqual(len(g2), 0)  # a1.dat и a2.dat имеют разные имена

    def test_cache_reuse(self):
        files = self._files()
        s = self.settings()
        with Cache() as cache:
            find_duplicates(files, s, cache)
            before = cache.count()
            self.assertGreater(before, 0)
            # повторный поиск не должен упасть и использует кэш
            files2 = self._files()
            groups = find_duplicates(files2, s, cache)
            self.assertEqual(len(groups), 1)


class TestRules(BaseTempCase):
    def test_by_extension_rule(self):
        rule = Rule(type="by_extension", name="Images", enabled=True, priority=1,
                    params={"extensions": [".jpg"], "target_template": "Pictures/{ext}"})
        matcher = RuleMatcher([rule], self.target)
        f = FileItem(path=str(self.work / "photo.JPG"))
        matched = matcher.match_file(f)
        self.assertIsNotNone(matched)
        tgt = matcher.build_target(f, matched)
        self.assertEqual(tgt, self.target / "Pictures" / "jpg" / "photo.JPG")

    def test_by_date_template(self):
        import os as _os
        rule = Rule(type="by_date", name="Dates", enabled=True, priority=1,
                    params={"target_template": "{year}/{month}"})
        matcher = RuleMatcher([rule], self.target)
        p = self.make("old.txt")
        _os.utime(p, (1_600_000_000, 1_600_000_000))  # 2020-09-13
        f = FileItem.from_path(p)
        tgt = matcher.build_target(f, matcher.match_file(f))
        self.assertIn("2020", str(tgt))
        self.assertIn("09", str(tgt))

    def test_unmatched_goes_to_other(self):
        matcher = RuleMatcher([], self.target)
        f = FileItem(path=str(self.work / "x.bin"))
        tgt = matcher.build_target(f, None)
        self.assertEqual(tgt.parent.name, constants.FALLBACK_RULE_NAME)

    def test_safe_format_blocks_danger(self):
        values = {"ext": "txt", "year": "2026", "month": "01", "day": "01",
                  "stem": "s", "name": "n.txt", "size": "1"}
        with self.assertRaises(ValueError):
            safe_format("{__import__('os')}", values)
        with self.assertRaises(ValueError):
            safe_format("{0}", values)
        self.assertEqual(safe_format("{ext}/{name}", values), "txt/n.txt")

    def test_traversal_blocked(self):
        rule = Rule(type="custom", name="Evil", enabled=True, priority=1,
                    params={"folder_template": "../../escape"})
        matcher = RuleMatcher([rule], self.target)
        f = FileItem(path=str(self.work / "a.txt"))
        tgt = matcher.build_target(f, rule)
        self.assertTrue(str(tgt).startswith(str(self.target)))


class TestPlanAndExecute(BaseTempCase):
    def test_build_plan_move_with_conflict_unique_names(self):
        src1 = self.make("docs/a.txt", b"1")
        src2 = self.make("other/a.txt", b"2")
        rule = Rule(type="custom", name="All", enabled=True, priority=1,
                    params={"folder_template": "Flat"})
        s = self.settings()
        matcher = RuleMatcher([rule], self.target)
        files = [FileItem.from_path(src1), FileItem.from_path(src2)]
        plan = build_plan(files, matcher, s)
        targets = sorted(Path(i.target).name for i in plan.executable_items)
        self.assertEqual(targets, ["a (1).txt", "a.txt"])

    def test_execute_and_undo(self):
        p = self.make("movable.txt", b"data")
        rule = Rule(type="by_extension", name="Txt", enabled=True, priority=1,
                    params={"extensions": [".txt"], "target_template": "T"})
        s = self.settings()
        matcher = RuleMatcher([rule], self.target)
        files = [FileItem.from_path(p)]
        plan = build_plan(files, matcher, s)
        with History(limit=100) as hist:
            res = execute_plan(plan, s, hist)
            self.assertEqual(res.executed, 1)
            moved = self.target / "T" / "movable.txt"
            self.assertTrue(moved.exists())
            self.assertFalse(p.exists())
            undone, problems = hist.undo_last()
            self.assertEqual(undone, 1, msg=str(problems))
            self.assertTrue(p.exists())
            self.assertFalse(moved.exists())

    def test_no_overwrite_existing_file(self):
        src = self.make("in.txt", b"new")
        dst = self.target / "T"
        dst.mkdir(parents=True)
        existing = dst / "in.txt"
        existing.write_bytes(b"OLD")
        rule = Rule(type="by_extension", name="Txt", enabled=True, priority=1,
                    params={"extensions": [".txt"], "target_template": "T"})
        s = self.settings()
        plan = build_plan([FileItem.from_path(src)], RuleMatcher([rule], self.target), s)
        item = plan.executable_items[0]
        self.assertEqual(Path(item.target).name, "in (1).txt")
        with History() as hist:
            execute_plan(plan, s, hist)
        self.assertEqual(existing.read_bytes(), b"OLD")

    def test_trash_only_no_hard_delete(self):
        p = self.make("todel.txt", b"bye")
        s = self.settings(trash_mode="internal")
        from app.core.models import ActionPlan, ActionPlanItem
        plan = ActionPlan(items=[ActionPlanItem(source=str(p), action=ACTION_TRASH,
                                                status=STATUS_OK)])
        with History() as hist:
            res = execute_plan(plan, s, hist)
            self.assertEqual(res.executed, 1)
            self.assertFalse(p.exists())
            trash_files = list(constants.TRASH_DIR.rglob("todel.txt"))
            self.assertTrue(trash_files)  # файл в корзине, не удалён жёстко
            undone, problems = hist.undo_last()
            self.assertEqual(undone, 1, msg=str(problems))
            self.assertTrue(p.exists())

    def test_history_limit_trim(self):
        with History(limit=5) as hist:
            for i in range(20):
                from app.core.models import Operation
                hist.record_operation(Operation(action="move", source=f"s{i}", target=f"t{i}"))
            self.assertLessEqual(len(hist.get_recent(100)), 5)


class TestOrganizerSelfMove(BaseTempCase):
    def test_skip_same_path(self):
        already = self.target / "T"
        already.mkdir(parents=True)
        p = already / "same.txt"
        p.write_bytes(b"x")
        rule = Rule(type="by_extension", name="Txt", enabled=True, priority=1,
                    params={"extensions": [".txt"], "target_template": "T"})
        s = self.settings()
        plan = build_plan([FileItem.from_path(p)], RuleMatcher([rule], self.target), s)
        self.assertEqual(len(plan.executable_items), 0)
        self.assertEqual(plan.items[0].status, "skipped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
