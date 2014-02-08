#!/usr/bin/env python2.7

"""
Simple Python script to set up your classpath for you.

Runs mvn dependency:build-classpath, grabs the classpath, removes all of the Kiji stuff, and then
writes out a file that you can source at the command line.

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
description = """This script will set up your classpath appropriately."""

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
      '-f',
      '--blow-away-existing-lib-dir',
      action='store_true',
      default=False,
      help='Blow away an existing lib directory')

  parser.add_argument(
      '--output-file',
      type=str,
      default='SOURCE_ME.sh',
      help='Output file that will set up classpath for you')

  parser.add_argument(
      '--env-var',
      type=str,
      default='KIJI_CLASSPATH',
      help='Name of environment variable to set [KIJI_CLASSPATH]')

  return parser

# ------------------------------------------------------------------------------
# Parse command-line arguments

args = create_parser().parse_args()

# Output file location
output_file = args.output_file

# Name of environment variable to set
env_var = args.env_var

b_blow_away = args.blow_away_existing_lib_dir

lib_dir_name = 'mylib'

if args.verbose:
  logging.basicConfig(level=logging.INFO)


def get_classpath_from_maven():
  """ Run maven to gather the classpath.  Return as a list of strings. """
  maven_output = run("mvn dependency:build-classpath")

  dependencies = None

  b_expect_on_next_line = False

  for line in maven_output.splitlines():
    if line.startswith('[INFO]'):
      print(line)

    if line == '[INFO] Dependencies classpath:':
      # Should be the next line
      assert dependencies == None
      b_expect_on_next_line = True

    elif b_expect_on_next_line:
      assert dependencies == None
      assert not line.startswith('[INFO]')
      dependencies = line.split(':')
      print("Found %d dependencies" % len(dependencies))
      b_expect_on_next_line = False

  assert dependencies != None
  return dependencies

def remove_kiji_dependencies(dependencies):
  """ Remove any of the Kiji stuff to avoid CLASSPATH hell... """
  return [dep for dep in dependencies if dep.find('kiji') == -1]

def write_classpath_file(ofile, var_name, dependencies):
  """ Write out all of the dependencies to a classpath file """
  myfile = open(ofile, 'w')
  myfile.write('export %s=%s\n' % (var_name, ':'.join(dependencies)))

  for dep in dependencies:
    myfile.write("# %s\n" % dep)

  myfile.close()

def create_kiji_mr_lib_directory(dependencies):
  """ Create a "lib" directory with symlinks to all of the dependencies needed on the cluster. """
  if os.path.exists(lib_dir_name) and not b_blow_away:
    assert False, \
        "Do not want to overwrite existing directory '%s'.  Use -f option to overwrite." % lib_dir_name

  if os.path.exists(lib_dir_name):
    shutil.rmtree(lib_dir_name)

  os.mkdir(lib_dir_name)

  for dep in dependencies:
    jar_name = os.path.basename(dep)

    link = os.path.join(lib_dir_name, jar_name)

    # Create a symlink!
    os.symlink(dep, link)


dependencies = get_classpath_from_maven()
dependencies_without_kiji = remove_kiji_dependencies(dependencies)
write_classpath_file(output_file, env_var, dependencies_without_kiji)
print("source '%s' to set up your KIJI_CLASSPATH." % output_file)
create_kiji_mr_lib_directory(dependencies_without_kiji)
