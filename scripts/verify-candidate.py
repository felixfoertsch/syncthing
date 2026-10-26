#!/usr/bin/env python3
"""Validate candidate data before signing. Never execute candidate code."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def check(candidate, control, channel):
	candidate = Path(candidate)
	metadata = json.loads((candidate / 'candidate.json').read_text())
	assert set(metadata) == {'control', 'channel', 'upstream_tag', 'upstream', 'source', 'tag', 'main', 'assets'}
	assert metadata['control'] == control and metadata['channel'] == channel
	for key in ('control', 'upstream', 'source', 'main'):
		assert re.fullmatch('[0-9a-f]{40}', metadata[key]), key
	assert re.fullmatch(r'v\d+\.\d+\.\d+(-nightly\.[0-9a-f]{40})?', metadata['upstream_tag'])
	assert re.fullmatch(re.escape(metadata['upstream_tag']) + r'-\d{4}\.\d{2}\.\d{2}\.[1-9]\d*', metadata['tag'])
	assert ('-nightly.' in metadata['tag']) == (channel == 'nightly')
	expected = {f'syncthing-{platform}-{metadata["tag"]}{extension}' for platform, extension in
		(('macos-arm64', '.zip'), ('linux-amd64', '.tar.gz'), ('linux-arm64', '.tar.gz'))}
	assert set(metadata['assets']) == expected
	assert {p.name for p in candidate.iterdir()} == expected | {'candidate.json', 'source.bundle', 'SHA256SUMS', 'release-notes.md'}
	for name, digest in metadata['assets'].items():
		assert re.fullmatch('[0-9a-f]{64}', digest)
		assert hashlib.sha256((candidate / name).read_bytes()).hexdigest() == digest
		archive = candidate / name
		if name.endswith('.zip'):
			with zipfile.ZipFile(archive) as z:
				members = [(i.filename, not i.is_dir(), (i.external_attr >> 16) & 0o170000) for i in z.infolist()]
		else:
			with tarfile.open(archive) as t:
				members = [(i.name, i.isfile(), 0 if i.isfile() or i.isdir() else -1) for i in t.getmembers()]
		seen = set()
		for path, regular, kind in members:
			p = PurePosixPath(path)
			assert not p.is_absolute() and '..' not in p.parts and '\\' not in path
			assert path not in seen and kind not in (-1, 0o120000)
			seen.add(path)
		root = name.removesuffix('.zip').removesuffix('.tar.gz')
		assert sum(regular and path == f'{root}/syncthing' for path, regular, _ in members) == 1
		assert all(PurePosixPath(path).parts[0] == root for path, _, _ in members)
		assert all(kind in (0, 0o040000, 0o100000) for _, _, kind in members)
	return metadata


def verify_build_info(candidate, metadata):
	# Go reads build metadata; candidate executable never runs in publisher.
	with tempfile.TemporaryDirectory() as tmp:
		for name in metadata['assets']:
			root = name.removesuffix('.zip').removesuffix('.tar.gz')
			member = f'{root}/syncthing'
			if name.endswith('.zip'):
				with zipfile.ZipFile(Path(candidate) / name) as z:
					data = z.read(member)
			else:
				with tarfile.open(Path(candidate) / name) as t:
					data = t.extractfile(member).read()
			binary = Path(tmp) / 'syncthing'
			binary.write_bytes(data)
			info = subprocess.check_output(['go', 'version', '-m', str(binary)], text=True)
			# -trimpath omits linker flags from Go build info; inspect embedded tag bytes.
			assert metadata['tag'].encode() in data
			assert f'vcs.revision={metadata["source"]}' in info
			assert 'vcs.modified=false' in info
			platform = 'darwin' if name.endswith('.zip') else 'linux'
			arch = 'amd64' if '-amd64-' in name else 'arm64'
			assert f'GOOS={platform}' in info and f'GOARCH={arch}' in info
			if platform == 'darwin':
				assert 'CGO_ENABLED=1' in info and 'modernc.org/sqlite' not in info


def verify_signature(archive):
	with tempfile.TemporaryDirectory() as tmp:
		with zipfile.ZipFile(archive) as z:
			binary = Path(tmp) / 'syncthing'
			binary.write_bytes(z.read(archive.name.removesuffix('.zip') + '/syncthing'))
		subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
		details = subprocess.run(['codesign', '-dv', '--verbose=4', str(binary)], capture_output=True, text=True, check=True)
		assert 'TeamIdentifier=NG5W75WE8U' in details.stderr


def sign(candidate, metadata):
	name = next(n for n in metadata['assets'] if n.endswith('.zip'))
	archive = Path(candidate) / name
	if os.environ.get('CUSTOM_RELEASE_REUSE_DARWIN') == '1':
		verify_signature(archive)
		write_checksums(candidate, metadata)
		return
	with tempfile.TemporaryDirectory() as tmp:
		with zipfile.ZipFile(archive) as z:
			z.extractall(tmp)
		binary = next(Path(tmp).rglob('syncthing'))
		binary.chmod(0o755)
		subprocess.run(['codesign', '--force', '--sign', os.environ['CUSTOM_RELEASE_CODESIGN_IDENTITY'],
			'--keychain', os.environ['CUSTOM_RELEASE_KEYCHAIN_PATH'], '--options', 'runtime', '--timestamp', str(binary)], check=True)
		subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
		details = subprocess.run(['codesign', '-dv', '--verbose=4', str(binary)], capture_output=True, text=True, check=True)
		assert 'TeamIdentifier=NG5W75WE8U' in details.stderr
		with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
			for p in sorted(Path(tmp).rglob('*')):
				if p.is_file():
					z.write(p, p.relative_to(tmp))
	write_checksums(candidate, metadata)


def write_checksums(candidate, metadata):
	with (Path(candidate) / 'SHA256SUMS').open('w') as sums:
		for name in sorted(metadata['assets']):
			sums.write(f'{hashlib.sha256((Path(candidate) / name).read_bytes()).hexdigest()}  {name}\n')


if __name__ == '__main__':
	metadata = check(sys.argv[1], sys.argv[2], sys.argv[3])
	if len(sys.argv) == 5:
		assert sys.argv[4] == 'sign'
		sign(sys.argv[1], metadata)
	else:
		verify_build_info(sys.argv[1], metadata)
		for key in ('upstream_tag', 'upstream', 'source', 'tag', 'main'):
			print(f'{key}={metadata[key]}')
