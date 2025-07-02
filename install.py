#!/usr/bin/env python

import argparse
import doctest
import json
import logging
import os
import platform
import sys
import tarfile
import tempfile
from typing import Optional
from urllib import request


def retrieve_latest_tag():
    """
    Retrieve the tag of a WASI SDK artifact from the latest GitHub releases.

    >>> retrieve_latest_tag()
    'wasi-sdk-25'
    """
    url = 'https://api.github.com/repos/WebAssembly/wasi-sdk/releases/latest'
    req = request.Request(url)
    if 'GITHUB_TOKEN' in os.environ:
        req.add_header('Authorization', f'token {os.environ["GITHUB_TOKEN"]}')
    with request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        return data['tag_name']


def calculate_version_and_tag(version: str):
    """
    Normalize the passed version string into a valid version number and release tag.

    >>> calculate_version_and_tag('25')
    ('25.0', 'wasi-sdk-25')
    >>> calculate_version_and_tag('25.0')
    ('25.0', 'wasi-sdk-25')
    >>> calculate_version_and_tag('25.1')
    ('25.1', 'wasi-sdk-25.1')
    """
    if version == 'latest':
        tag = retrieve_latest_tag()
        version = tag.replace('wasi-sdk-', '')
    else:
        stripped = version.rstrip('.0')
        tag = f'wasi-sdk-{stripped}'

    if '.' not in version:
        version = f'{version}.0'

    return version, tag


def calculate_artifact_url(version: str, tag: str, arch: str, os: str):
    """
    Generate the artifact URL based on the version, architecture, and operating system.

    >>> calculate_artifact_url('25.0', 'wasi-sdk-25', 'x86_64', 'Linux')
    'https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-25/wasi-sdk-25.0-x86_64-linux.tar.gz'
    >>> calculate_artifact_url('25.1', 'wasi-sdk-25.1', 'arm64', 'Darwin')
    'https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-25.1/wasi-sdk-25.1-arm64-macos.tar.gz'
    """
    base = 'https://github.com/WebAssembly/wasi-sdk/releases/download'
    if os == 'Darwin':
        os = 'macos'
    else:
        os = os.lower()
    return f'{base}/{tag}/wasi-sdk-{version}-{arch}-{os}.tar.gz'


def install(url: str, install_dir: str):
    """
    Download the file from the given URL and extract it to a directory.
    """
    logging.info(f'Downloading {url}')
    file = tempfile.NamedTemporaryFile(delete=False)
    request.urlretrieve(url, file.name)
    logging.info(f'Successfully downloaded {file.name}')
    os.makedirs(install_dir, exist_ok=True)
    with tarfile.open(file.name, 'r:gz') as tar:
        for member in tar.getmembers():
            # Strip off the first path component (i.e., `--strip-components=1`).
            parts = member.name.split('/')
            if len(parts) > 1:
                member.name = '/'.join(parts[1:])
                tar.extract(member, path=install_dir, filter='tar')
    logging.info(f'Extracted to {install_dir}')
    os.unlink(file.name)


def write_variables(install_dir: str, output_file: Optional[str], env_file: Optional[str]):
    """
    Write variables to output files; this is useful to write out data for GitHub Actions.
    """
    clang_path = f'{install_dir}/bin/clang'
    logging.info(f'Clang executable: {clang_path}')
    assert os.path.isfile(clang_path), f'clang not found at {clang_path}'

    sysroot_path = f'{install_dir}/share/wasi-sysroot'
    logging.info(f'WASI sysroot: {clang_path}')
    assert os.path.isdir(sysroot_path), f'sysroot not found at {sysroot_path}'

    if output_file:
        logging.info(f'Writing output variables to {output_file}')
        with open(output_file, 'a') as f:
            f.write(f'wasi-sdk-path={install_dir}\n')
            f.write(f'wasi-sdk-version={version}\n')
            f.write(f'clang-path={clang_path}\n')
            f.write(f'sysroot-path={sysroot_path}\n')

    if env_file:
        logging.info(f'Writing environment variables to {env_file}')
        with open(env_file, 'a') as f:
            f.write(f'WASI_SDK_PATH={install_dir}\n')
            f.write(f'WASI_SDK_VERSION={version}\n')
            f.write(f'CC={clang_path} --sysroot={sysroot_path}\n')
            f.write(f'CXX={clang_path}++ --sysroot={sysroot_path}\n')


def main(version: str, install_dir: str, output_file: Optional[str], env_file: Optional[str]):
    version, tag = calculate_version_and_tag(version)
    url = calculate_artifact_url(
        version, tag, platform.machine(), platform.system())
    install(url, install_dir)
    write_variables(install_dir, output_file, env_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Install a version of WASI SDK.')
    parser.add_argument(
        '--version', help='The version to install (e.g., `25.0`).', default='latest')
    parser.add_argument(
        '--install-dir', help='The directory to install to; defaults to the current directory', default='.')
    parser.add_argument(
        '--output-file', help='Write GitHub action output variables to this .env-like file (e.g., `$GITHUB_PATH`).', default=None)
    parser.add_argument(
        '--env-file', help='Write a new wasi-sdk environment to this .env-like file (e.g., `$GITHUB_ENV`).', default=None)
    parser.add_argument(
        '-v', '--verbose', help='Increase the logging level.', action='count', default=0)
    parser.add_argument(
        '--test-only', help='Run the script\'s doctests and exit', action='store_true', default=False)
    args = parser.parse_args()

    # Setup logging.
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    logging.getLogger().name = os.path.basename(__file__)

    # Override any CLI arguments using GitHub Action inputs.
    version = os.getenv('INPUT_VERSION', args.version)
    install_dir = os.getenv('INPUT_INSTALL_DIR', args.install_dir)
    add_to_path = os.getenv('INPUT_ADD_TO_PATH', 'false').lower() == 'true'
    output_file = os.getenv(
        'GITHUB_PATH', args.output_file) if add_to_path else args.output_file
    env_file = os.getenv(
        'GITHUB_ENV', args.env_file) if add_to_path else args.env_file

    if args.test_only:
        failures, _ = doctest.testmod()
        if failures:
            sys.exit(1)
    else:
        main(version, install_dir, output_file, env_file)
