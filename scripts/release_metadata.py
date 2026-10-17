"""Read the package version and validate a release tag against main."""
import argparse
import ast
from pathlib import Path
import re
import subprocess


# SemVer, including prereleases (e.g. 0.2.0-rc.1) and build metadata.
NUMBER = r'(?:0|[1-9][0-9]*)'
IDENTIFIER = r'(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)'
VERSION = re.compile(
    rf'{NUMBER}\.{NUMBER}\.{NUMBER}(?:-{IDENTIFIER}(?:\.{IDENTIFIER})*)?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
)


def read_version(root):
    tree = ast.parse((Path(root) / 'maxcraft/__init__.py').read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == '__version__'
                for target in node.targets):
            version = ast.literal_eval(node.value)
            if isinstance(version, str) and VERSION.fullmatch(version):
                return version
            break
    raise ValueError('maxcraft/__init__.py must define a valid SemVer __version__')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def validate_tag(root, tag, main_ref='refs/remotes/origin/main'):
    version = read_version(root)
    if tag != f'v{version}':
        raise ValueError(f'Release tag must match the package version: v{version}')
    commit = git(root, 'rev-parse', '--verify', f'refs/tags/{tag}^{{commit}}')
    if commit != git(root, 'rev-parse', 'HEAD'):
        raise ValueError('The checked-out commit must be the tagged commit')
    check = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor',
                            commit, main_ref], check=False)
    if check.returncode:
        raise ValueError('The tagged commit must already be reachable from origin/main')
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', help='Validate this existing release tag')
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = read_version(root)
    commit = validate_tag(root, args.tag) if args.tag else git(root, 'rev-parse', 'HEAD')
    values = dict(version=version, commit=commit,
                  prerelease=str('-' in version.split('+')[0]).lower(),
                  archive=f'MaxCraft-{version}.zip')
    output = ''.join(f'{key}={value}\n' for key, value in values.items())
    print(output, end='')
    if args.github_output:
        with args.github_output.open('a', encoding='utf-8') as stream:
            stream.write(output)


if __name__ == '__main__':
    main()
