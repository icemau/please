#!/usr/bin/env python3
"""Script to create Github releases & generate release notes."""

import json
import logging
import os
import subprocess
import sys
import zipfile

from third_party.python import colorlog, requests
from third_party.python.absl import app, flags

logging.root.handlers[0].setFormatter(colorlog.ColoredFormatter('%(log_color)s%(levelname)s: %(message)s'))


flags.DEFINE_string('github_token', None, 'Github API token')
flags.DEFINE_bool('dry_run', False, "Don't actually do the release, just print it.")
flags.mark_flag_as_required('github_token')
FLAGS = flags.FLAGS


PRERELEASE_MESSAGE = """
This is a prerelease version of Please. Bugs and partially-finished features may abound.

Caveat usor!
"""


class ReleaseGen:

    def __init__(self, github_token:str):
        self.url = 'https://api.github.com'
        self.releases_url = self.url + '/repos/thought-machine/please/releases'
        self.session = requests.Session()
        self.session.verify = '/etc/ssl/certs/ca-certificates.crt'
        if not FLAGS.dry_run:
            self.session.headers.update({
                'Accept': 'application/vnd.github.v3+json',
                'Authorization': 'token ' + github_token,
            })
        self.version = self.read_file('VERSION').strip()
        self.version_name = 'Version ' + self.version
        self.is_prerelease = 'a' in self.version or 'b' in self.version
        self.known_content_types = {
            '.gz': 'application/gzip',
            '.xz': 'application/x-xz',
            '.asc': 'text/plain',
        }

    def get_latest_release_version(self):
        """Gets the latest released version from Github."""
        response = self.session.get(self.releases_url + '/latest')
        response.raise_for_status()
        return json.loads(response.text).get('tag_name').lstrip('v')

    def needs_release(self):
        """Returns true if the current version is not yet released to Github."""
        return self.get_latest_release_version() != self.version

    def release(self):
        """Submits a new release to Github."""
        data = {
            'tag_name': 'v' + self.version,
            'target_commitish': os.environ['CIRCLE_SHA1'],
            'name': 'Please v' + self.version,
            'body': ''.join(self.get_release_notes()),
            'prerelease': self.is_prerelease,
            'draft': not self.is_prerelease,
        }
        if FLAGS.dry_run:
            logging.info('Would post the following to Github: %s' % json.dumps(data, indent=4))
            return
        response = self.session.post(self.releases_url, json=data)
        response.raise_for_status()
        data = response.json()
        self.release_id = data['id']

    def upload(self, artifact:str):
        """Uploads the given artifact to the new release."""
        filename = os.path.basename(artifact)
        _, ext = os.path.splitext(filename)
        content_type = self.known_content_types[ext]
        url = '%s/%s/assets?name=%s' % (self.releases_url, self.release_id, filename)
        with open(artifact, 'rb') as f:
            if FLAGS.dry_run:
                logging.info('Would upload %s to %s as %s' % (filename, url, content_type))
                return
            response = self.session.post(url, files={filename: (filename, f, content_type)})
            response.raise_for_status()
        print('%s uploaded' % filename)

    def get_release_notes(self):
        """Yields the changelog notes for a given version."""
        found_version = False
        for line in self.read_file('ChangeLog').split('\n'):
            if line.startswith(self.version_name):
                found_version = True
                yield 'This is Please v%s' % self.version
            elif line.startswith('------'):
                continue
            elif found_version:
                if line.startswith('Version '):
                    return
                elif line.startswith('   '):
                    # Markdown comes out nicer if we remove some of the spacing.
                    line = line[3:]
                yield line
        if self.is_prerelease:
            logging.warning("No release notes found, continuing anyway since it's a prerelease")
            yield PRERELEASE_MESSAGE.strip()
        else:
            raise Exception("Couldn't find release notes for " + self.version_name)

    def read_file(self, filename):
        """Read a file from the .pex."""
        with zipfile.ZipFile(sys.argv[0]) as zf:
            return zf.read(filename).decode('utf-8')


def main(argv):
    r = ReleaseGen(FLAGS.github_token)
    if not r.needs_release():
        logging.info('Current version is latest release, nothing to be done!')
        return
    r.release()
    for artifact in argv[1:]:
        r.upload(artifact)


if __name__ == '__main__':
    app.run(main)
