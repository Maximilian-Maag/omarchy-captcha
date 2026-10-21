import contextlib
import importlib.util
import io
import os
import pathlib
import tempfile
import unittest

TOOL = pathlib.Path(__file__).resolve().parent.parent / "tools" / "check_bindings.py"
_spec = importlib.util.spec_from_file_location("check_bindings", TOOL)
assert _spec is not None and _spec.loader is not None
cb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cb)


class CheckBindings(unittest.TestCase):
    """The guard for the bug that shipped: ,ca/,cc/,cs silently made the platform's ,c dead."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def test_a_clean_fragment_under_a_free_prefix_passes(self):
        frag = self.write("frag.py", 'config.bind(",vc", "spawn --userscript qute-captcha")\n')
        cfg = self.write("cfg.py", 'config.bind(",c", "reader-factcheck")\n')
        self.assertEqual(cb.collisions(cb.parse(frag) + cb.parse(cfg)), [])

    def test_a_prefix_is_a_collision(self):
        frag = self.write("frag.py",
                          'config.bind(",cc", "x")\n'
                          'config.bind(",ca", "x")\n'
                          'config.bind(",cs", "x")\n')
        cfg = self.write("cfg.py", 'config.bind(",c", "reader-factcheck")\n')
        problems = cb.collisions(cb.parse(frag) + cb.parse(cfg))
        self.assertTrue(any("prefix" in p and "',c'" in p for p in problems), problems)
        self.assertEqual(len(problems), 1, problems)

    def test_the_fragment_against_itself_is_enough(self):
        # ,v and ,vc in one file is the same bug without any other config involved
        frag = self.write("frag.py",
                          'config.bind(",v", "x")\nconfig.bind(",vc", "y")\n')
        problems = cb.collisions(cb.parse(frag))
        self.assertTrue(any("prefix" in p for p in problems), problems)

    def test_a_duplicate_is_a_collision(self):
        a = self.write("a.py", 'config.bind(",vc", "one")\n')
        b = self.write("b.py", 'config.bind(",vc", "two")\n')
        problems = cb.collisions(cb.parse(a) + cb.parse(b))
        self.assertTrue(any("duplicate" in p for p in problems), problems)

    def test_different_modes_do_not_collide(self):
        frag = self.write("frag.py",
                          'config.bind(",vc", "x", mode="normal")\n'
                          'config.bind(",v", "y", mode="insert")\n')
        self.assertEqual(cb.collisions(cb.parse(frag)), [])

    def test_cli_exit_zero_when_clean(self):
        frag = self.write("frag.py", 'config.bind(",vc", "x")\n')
        cfg = self.write("cfg.py", 'config.bind(",c", "y")\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cb.main(["--fragment", frag, "--config", cfg]), 0)
        self.assertIn("no collisions", out.getvalue())

    def test_cli_exit_one_when_colliding(self):
        frag = self.write("frag.py", 'config.bind(",cc", "x")\n')
        cfg = self.write("cfg.py", 'config.bind(",c", "y")\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cb.main(["--fragment", frag, "--config", cfg]), 1)
        self.assertIn("REFUSING", err.getvalue())
        self.assertIn("prefix", err.getvalue())


if __name__ == "__main__":
    unittest.main()
