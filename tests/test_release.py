"""Exercise release guards using real temporary Git histories."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.release_metadata import read_version, validate_tag


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Release test')
        self.git('config', 'user.email', 'release-test@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')
        (self.root / 'maxcraft').mkdir()
        self.version_file = self.root / 'maxcraft/__init__.py'
        self.version_file.write_text('__version__ = "1.2.3"\n', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-m', 'Versioned source')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args],
                                       text=True, stderr=subprocess.STDOUT).strip()

    def test_annotated_tag_on_main_is_accepted(self):
        self.git('tag', '-a', 'v1.2.3', '-m', 'Release')
        self.assertEqual(validate_tag(self.root, 'v1.2.3'), self.git('rev-parse', 'HEAD'))

    def test_older_commit_still_on_main_is_accepted(self):
        self.git('tag', 'v1.2.3')
        self.git('commit', '--allow-empty', '-m', 'Main advanced')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.git('checkout', '--detach', 'v1.2.3')
        validate_tag(self.root, 'v1.2.3')

    def test_unmerged_feature_tag_is_rejected(self):
        self.git('switch', '-c', 'feature/unmerged')
        self.git('commit', '--allow-empty', '-m', 'Unmerged')
        self.git('tag', 'v1.2.3')
        with self.assertRaisesRegex(ValueError, 'reachable'):
            validate_tag(self.root, 'v1.2.3')

    def test_wrong_checkout_is_rejected(self):
        self.git('tag', 'v1.2.3')
        self.git('commit', '--allow-empty', '-m', 'Another commit')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        with self.assertRaisesRegex(ValueError, 'checked-out'):
            validate_tag(self.root, 'v1.2.3')

    def test_mismatched_or_malformed_tags_are_rejected(self):
        for tag in ('v1.2.4', '1.2.3', 'v1.2', 'v01.2.3', 'v1.2.3;bad'):
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, 'match'):
                validate_tag(self.root, tag)

    def test_version_is_validated_without_importing_plugin(self):
        for version in ('0.2.0-rc.1', '1.0.0+build.5'):
            self.version_file.write_text(f'raise RuntimeError()\n__version__ = "{version}"\n', encoding='utf-8')
            self.assertEqual(read_version(self.root), version)
        self.version_file.write_text('__version__ = "01.2.3"\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            read_version(self.root)
