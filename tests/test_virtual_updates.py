from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_virtual_clawdy as updater


CURRENT = "1" * 40
NEXT = "2" * 40


class VirtualUpdateTests(unittest.TestCase):
    def test_only_the_checked_main_descendant_is_available(self):
        ref = {"object": {"sha": NEXT}}
        compare = {"status": "ahead", "merge_base_commit": {"sha": CURRENT}}
        approved = {"head_sha": NEXT, "head_branch": "main", "event": "push",
                    "conclusion": "success", "head_repository": {"id": updater.REPOSITORY_ID}}
        with patch.object(updater, "github", side_effect=[ref, compare, {"workflow_runs": [approved]}]):
            self.assertEqual(updater.candidate_revision(CURRENT), NEXT)
        for unexpected in ({"head_sha": CURRENT}, {"head_branch": "other"}, {"event": "pull_request"},
                           {"conclusion": "cancelled"}, {"head_repository": {"id": 123}}):
            runs = {"workflow_runs": [{**approved, **unexpected}]}
            with self.subTest(unexpected=unexpected), patch.object(updater, "github", side_effect=[ref, compare, runs]):
                with self.assertRaisesRegex(updater.UpdateUnavailable, "waiting"):
                    updater.candidate_revision(CURRENT)

    def test_current_and_diverged_installs_do_not_offer_an_update(self):
        with patch.object(updater, "github", return_value={"object": {"sha": CURRENT}}) as github:
            self.assertIsNone(updater.candidate_revision(CURRENT))
            github.assert_called_once()
        results = [{"object": {"sha": NEXT}}, {"status": "diverged", "merge_base_commit": {"sha": CURRENT}}]
        with patch.object(updater, "github", side_effect=results):
            with self.assertRaisesRegex(updater.UpdateUnavailable, "outside"):
                updater.candidate_revision(CURRENT)

    def test_failed_or_moved_source_preserves_existing_app(self):
        for returned_sha, exception in ((CURRENT, updater.UpdateUnavailable), (NEXT, subprocess.CalledProcessError)):
            with self.subTest(returned_sha=returned_sha), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                app = root / "VirtualClawdy.app"
                app.mkdir()
                sentinel = app / "keep"
                sentinel.write_text("running")
                cache = root / "Library/Caches/ClawdyPrototype/Updates"
                with patch.object(updater.platform, "system", return_value="Darwin"), \
                        patch.object(updater.Path, "home", return_value=root), \
                        patch.object(updater.shutil, "which", return_value="git"), \
                        patch.object(updater, "run", side_effect=[
                            "", returned_sha, "", "", subprocess.CalledProcessError(1, "build")
                        ]) as run:
                    with self.assertRaises(exception):
                        updater.stage_update(NEXT, CURRENT, app)
                self.assertEqual(sentinel.read_text(), "running")
                self.assertEqual(list(cache.iterdir()), [])
                self.assertEqual(run.call_count, 2 if returned_sha == CURRENT else 5)

    def test_successful_stage_is_reused_without_touching_running_app(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "VirtualClawdy.app"
            app.mkdir()
            executable = Path("VirtualClawdy.app/Contents/MacOS/VirtualClawdy")

            def run(args, *, env=None, timeout=None):
                if "rev-parse" in args:
                    return NEXT
                if args[0] == "/bin/bash":
                    output = Path(env["CLAWDY_BUILD_DIR"]) / executable
                    output.parent.mkdir(parents=True)
                    output.write_text("built")
                return ""

            with patch.object(updater.platform, "system", return_value="Darwin"), \
                    patch.object(updater.Path, "home", return_value=root), \
                    patch.object(updater.shutil, "which", return_value="git"), \
                    patch.object(updater, "run", side_effect=run) as invocation:
                staged = updater.stage_update(NEXT, CURRENT, app)
                self.assertEqual(updater.stage_update(NEXT, CURRENT, app), staged)
            self.assertEqual(invocation.call_count, 6)
            self.assertEqual(Path(staged).name, app.name)
            self.assertEqual((Path(staged).parent / executable).read_text(), "built")
            self.assertEqual((Path(staged).parents[1] / "pending" / CURRENT).read_bytes(), (NEXT + "\n").encode())
            self.assertEqual(list(app.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
