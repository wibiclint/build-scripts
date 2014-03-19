#!/usr/bin/env python2.7

"""
Simple Python script to blow away a Bento Box and restart it again.

Also symlinks some JARs.

"""

import argparse
import collections
import functools
import logging
import os
import re
import shutil
import subprocess
import sys

myname = os.path.split(sys.argv[0])[-1]
description = \
  "This script will re-install your Bento Box and symlink some JAR files. " + \
  "It assumes the kiji-bento-...-release.tar.gz file is in the pwd. " + \
  "If you wish to symlink JAR files, checkouts for those projects should also be in the pwd " + \
  "and they should already be built."

def run(cmd):
  return subprocess.check_output(cmd, shell=True)

def create_parser():
  """ Returns a parser for the script """

  parser = argparse.ArgumentParser(
      description=description,
      formatter_class=argparse.RawTextHelpFormatter)

  parser.add_argument(
      '-v',
      '--verbose',
      action='store_true',
      default=False,
      help='Verbose mode (turn on logging.info)')

  parser.add_argument(
      '-d',
      '--debug',
      action='store_true',
      default=False,
      help='Debug (turn on logging.debug)')

  parser.add_argument(
      '-b',
      '--bento-version',
      type=str,
      default=None,
      help='Bento version to install (e.g., "1.4.3") [latest tgz in pwd]')

  parser.add_argument(
      '-l',
      '--link-modules',
      type=str,
      default=None,
      help='CSV of modules whose JAR files should get symlinked to Bento lib/*.jar locations (e.g., "model-repository,modeling") [None].')

  return parser

def _find_bento_tgz(bento_version_or_none):
  """ Return a pointer to the tgz file to use to install the bento box.  Use the most-recent version
  in the pwd, unless the user specfied otherwise. """

  # Get all of the tgz files in the pwd.
  all_bento_tgz = [f for f in os.listdir(os.getcwd()) if f.endswith('.tar.gz') and f.startswith('kiji-bento')]
  assert len(all_bento_tgz) > 0, "Could not find any bento tgz files!"

  # For now we are assuming that none of the "versions" ever get to more than one digit - make it
  # easy to get the most recent version, just by doing a reverse sort.

  if (bento_version_or_none == None):
    return sorted(all_bento_tgz)[-1]

  # Regex to get the bento version
  p_bento = re.compile(r'kiji-bento-(?P<name>\w+)-(?P<version>\d\.\d\.\d)-release\.tar\.gz')

  for bento in all_bento_tgz:
    m_bento = p_bento.match(bento)
    assert m_bento, "Could not regex match bento " + bento
    if m_bento.group('version') == bento_version_or_none:
      return bento
    logging.debug(m_bento.group('version'))

  assert False, "Could not find a bento tgz file with version " + bento_version_or_none


# ------------------------------------------------------------------------------
# Parse command-line arguments

args = create_parser().parse_args()

if args.verbose:
  logging.basicConfig(level=logging.INFO)

if args.debug:
  logging.basicConfig(level=logging.DEBUG)


# ------------------------------------------------------------------------------
# Find the appropriate bento file.
bento_tgz = _find_bento_tgz(args.bento_version)

logging.info("Using bento tgz file " + bento_tgz)



if False:
  bento_dir = 'kiji-bento-dashi'
  bento_tar = 'kiji-bento-dashi-1.4.0-release.tar.gz'

  # Make sure that we can find the bento directory
  assert(os.path.isdir(bento_dir))
  assert(os.path.isfile(bento_tar))

  shutil.rmtree(bento_dir)

  cmd = 'tar -zxvf %s' % bento_tar

  os.system(cmd)

  assert(os.path.isdir(bento_dir))

  cmd = 'source %s/bin/kiji-env.sh; bento start' % bento_dir
  os.system(cmd)

