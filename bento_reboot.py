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

import bento_classpath

myname = os.path.split(sys.argv[0])[-1]
description = \
  "This script will re-install your Bento Box and symlink some JAR files. " + \
  "It assumes the kiji-bento-...-release.tar.gz file is in the pwd. " + \
  "If you wish to symlink JAR files, checkouts for those targets should also be in the pwd " + \
  "and they should already be built."

# Regex to get the bento version, assumes for now that each part of the version is only one digit
# (makes getting the most-recent version easy - just sort lexographically).
p_bento = re.compile(r'kiji-bento-(?P<name>\w+)-(?P<version>\d\.\d\.\d)-release\.tar\.gz')

def run(cmd):
  return subprocess.check_output(cmd, shell=True)

class BentoRebooter(object):

  # List of commands available to the user.
  possible_actions = [
      'help-actions',
      'install-bento',
      'link-jars',
      'setup-classpath',
  ]

  actions_help = {
      'install-bento':
        "Will set up a bento box for you.  Assumes you are in a directory with a .tar.gz file "
        "for the appropriate bento build.  If you don't specify a specific build, this script "
        "will use the most-recent tar file in the current directory.  The scripts will rm -rf "
        "your current bento directory, kill any stale java processes, and untar the .tar.gz file.",

      'link-jars':
        "Will create symlinks from locally-built JARs to the JARs in your Bento Box.  The "
        "script will search your Bento Box's directory structure for all occurrences of JAR "
        "files for the projects that you specify.",

      'setup-classpath':
        "Will use the mvn dependency:build-classpath command to get the Maven classpaths used for "
        "building the collection of locally-built JARs that you indicate.  This can be useful if "
        "you have added an external dependency for a new version of one of the Kiji projects that "
        "was not present in the older version used in the Bento Box.  The command produces a bash "
        "file that you can source to set an env var to contain the extra JARs.  Note that if one "
        "the new versions of a Kiji project does something really different from the Bento Box "
        "(e.g., uses a different version of Scala), then this will really hose you.",
    }

  def _create_parser(self):
    """ Returns a parser for the script """

    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument(
        "action",
        nargs='*',
        help="Action to take")

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

  def _parse_options(self, cmd_line_args):
    # ----------------------------------------------------------------------------------------------
    # Parse command-line arguments
    args = self.create_parser().parse_args(cmd_line_args)

    if args.verbose:
      logging.basicConfig(level=logging.INFO)

    if args.debug:
      logging.basicConfig(level=logging.DEBUG)

    if args.link_modules == None:
      link_modules = []
    else:
      link_modules = args.link_modules.split(',')

    self.actions = opts.action
    for action in self.actions:
      assert action in self.possible_actions

    if 'help-actions' in self.actions: self._help_actions()

    # ----------------------------------------------------------------------------------------------
    # Kill any stale processes from the previous Bento Box.

    # ----------------------------------------------------------------------------------------------
    # Find the appropriate bento file.
    bento_tgz = self.find_bento_tgz(args.bento_version)
    logging.info("Using bento tgz file " + bento_tgz)

    m_bento = p_bento.match(bento_tgz)
    assert m_bento
    bento_dir = 'kiji-bento-' + m_bento.group('name')

    # ----------------------------------------------------------------------------------------------
    # Untar the bento box, possibly deleting the previous install.
    self.untar_bento(bento_dir, bento_tgz)

    # ----------------------------------------------------------------------------------------------
    # Optionally sym link some JAR files
    self.sym_link_target_jars(bento_dir, link_modules)

    # ----------------------------------------------------------------------------------------------
    # Create a classpath variable with the classpaths for *all* of the different modules that we
    # symlinked.
    dependency_jars = self.get_dependency_jars(link_modules)
    var_name = 'EXTRA_CLASSPATH'
    src_file = 'SOURCE_ME.sh'
    self.write_file_that_sets_classpath(dependency_jars, var_name, src_file)
    assert os.path.isfile(src_file)

    msg = \
      "Source the file '%s' to set the env var '%s' to contain all JARs needed to build the " + \
      "locally-built Kiji projects you specified.  Note that if those locally-build " + \
      "have vastly different dependencies than your bento box (e.g., different scala " + \
      "versions), then sourcing '%s' may hose everything."
    print msg % (src_file, var_name, src_file)
  def find_bento_tgz(self, bento_version_or_none):
    """
    Return a pointer to the tgz file to use to install the bento box.  Use the most-recent version in
    the pwd, unless the user specfied otherwise.
    """

    # Get all of the tgz files in the pwd.
    all_bento_tgz = [f for f in os.listdir(os.getcwd()) if f.endswith('.tar.gz') and f.startswith('kiji-bento')]
    assert len(all_bento_tgz) > 0, "Could not find any bento tgz files!"

    # For now we are assuming that none of the "versions" ever get to more than one digit - make it
    # easy to get the most recent version, just by doing a reverse sort.

    if (bento_version_or_none == None):
      return sorted(all_bento_tgz)[-1]


    for bento in all_bento_tgz:
      m_bento = p_bento.match(bento)
      assert m_bento, "Could not regex match bento " + bento
      if m_bento.group('version') == bento_version_or_none:
        return bento
      logging.debug(m_bento.group('version'))

    assert False, "Could not find a bento tgz file with version " + bento_version_or_none

  def untar_bento(self, bento_dir, bento_tgz):
    """ Untar the bento box. """
    if (os.path.isdir(bento_dir)):
      shutil.rmtree(bento_dir)

    assert not os.path.exists(bento_dir)

    cmd = 'tar -zxvf %s' % bento_tgz
    run(cmd)

    assert os.path.exists(bento_dir)

  def get_locally_built_jar_for_target(self, kiji_target):
    """
    Return the JAR created by maven for this Kiji target.  Some of the Kiji projects have submodules
    that may contain the JAR files.
    """

    # If you are building locally, the the JAR should look like:
    # <kiji target>-x.y.z-SNAPSHOT.jar
    p_jar = re.compile(kiji_target + r'-(?P<version>\d+\.\d+\.\d+)-SNAPSHOT.jar')

    # Hopefully we'll get only one of these!
    matching_jars = set()

    # TODO: Make this more efficient?
    for (dirpath, _, filenames) in os.walk(os.getcwd()):
      # Only count JARs found within target/ (not within target/something/lib, for example).
      assert os.path.split(dirpath)[1] != ''
      if os.path.split(dirpath)[1] != 'target':
        continue

      for fname in filenames:
        m_jar = p_jar.match(fname)
        if m_jar:
          matching_jars.add(os.path.join(dirpath, fname))

    logging.info("Matching JARs for Kiji target " + kiji_target + ":")
    for jar in sorted(matching_jars):
      logging.info("\t" + jar)

    assert len(matching_jars) != 0, "Did not find any JARs built by Maven for %s!" % kiji_target
    assert len(matching_jars) == 1, \
      "Found multiple potential matches for JARs built by Maven for target %s!" % kiji_target

    return list(matching_jars)[0]

  def sym_link_target_jars(self, bento_dir, link_modules):
    """ Link all of the modules specified here to the appropriate <bento location>/lib/*.jar file. """

    def _get_bento_jars_for_target(kiji_target):
      """
      Go into the bento lib directory and find the JAR file for this target (some of these, like
      kiji-mapreduce, are tricky and will need hard-coding).
      """

      all_jars = set()

      for (dirpath, _, filenames) in os.walk(bento_dir):

        for fname in filenames:
          if fname.startswith(kiji_target) and fname.endswith('.jar'):
            all_jars.add(os.path.join(dirpath, fname))

      logging.info("Bento Box JARs found for Kiji target " + kiji_target + ":")
      for bento_jar in all_jars:
        logging.info('\t' + bento_jar)

      return all_jars


    def _backup_bento_jar(bento_jar):
      """
      Back up this Bento Box JAR to a .bak file.  If the current JAR file is a sym link, remove that
      link (since we are about to relink).
      """
      backup_jar = bento_jar.replace('.jar', '.bak')

      # If the current JAR is a symlink, then it should already have been backed up.  Just delete the
      # symlink and return.
      if os.path.islink(bento_jar):
        assert os.path.isfile(backup_jar)
        os.remove(bento_jar)
        logging.info("Bento JAR %s is already backed up.  Remove symlink." % bento_jar)
        return

      logging.info("Backing up JAR file %s to %s..." % (bento_jar, backup_jar))
      os.rename(bento_jar, backup_jar)
      assert os.path.isfile(backup_jar)

    def _symlink_local_jar_to_bento(local_jar, bento_jar):
      assert not os.path.isfile(bento_jar), \
          "Bento JAR %s should not exist - it should have already been moved to *.bak" % bento_jar
      logging.info("Creating symlink %s pointing to %s..." % (bento_jar, local_jar))
      os.symlink(local_jar, bento_jar)


    for module in link_modules:
      kiji_target = 'kiji-' + module

      # Get the JAR file location in the target's target/ directory
      local_jar = self.get_locally_built_jar_for_target(kiji_target)

      # Get all of the JAR files for this target in the bento box.
      # There can be more than one JAR for each target (bento redundancies).
      bento_jar_list = _get_bento_jars_for_target(kiji_target)

      # Back up the bento file and symlink the new file!
      for bento_jar in bento_jar_list:
        _backup_bento_jar(bento_jar)
        _symlink_local_jar_to_bento(local_jar, bento_jar)

  def get_dependency_jars(self, link_modules):
    """
    For every one of the modules that we are linking, add more stuff to the classpath.

    """

    def _get_dependencies_for_building_target(local_jar):
      """
      Use the Bento classpath script to get the dependencies for building this JAR.  The build
      directory should just be the root directory of this JAR file.
      """
      assert os.path.isfile(local_jar)
      assert local_jar.endswith('.jar')

      target_dir = os.path.dirname(local_jar)
      assert os.path.isdir(target_dir)
      assert target_dir.endswith('target')

      dirs = target_dir.split('/')
      assert dirs[-1] == 'target'
      build_dir = '/'.join(dirs[:-1])
      assert os.path.isdir(build_dir)

      logging.info("Getting dependency JARs from %s..." % build_dir)

      # Cache the current PWD, switch directories for the call to this script, then switch back.
      cwd = os.getcwd()
      os.chdir(build_dir)

      # Run the script that puts all of the dependencies into a file.
      bentocp = bento_classpath.BentoClasspath()
      bentocp.go('-f'.split())

      os.chdir(cwd)

      logging.info("...Done")

      return bentocp.dependencies

    # Capture all of the JARs in the classpaths for all of these projects in a big set.  If the
    # ordering of these JARs matters, then we may need to do something smarter here (and we are
    # probably dead).
    dependency_jars = []

    for module in link_modules:
      kiji_target = 'kiji-' + module

      # Get the JAR file location in the target's target/ directory
      local_jar = self.get_locally_built_jar_for_target(kiji_target)

      #dependency_jars.update(_get_dependencies_for_building_target(local_jar))
      dependency_jars.extend(_get_dependencies_for_building_target(local_jar))

    logging.info("Found %s unique dependencies." % len(dependency_jars))

    return dependency_jars

  def write_file_that_sets_classpath(self, dependencies, var_name, ofile):
    """
    Output a file that the user can source to set up the entire maven build classpath for all of the
    locally-built JARs.
    """
    #deps_to_write = [x for x in dependencies if x.find('scala') == -1]
    deps_to_write = dependencies

    myfile = open(ofile, 'w')
    myfile.write('export %s=%s\n' % (var_name, ':'.join(deps_to_write)))

    for dep in deps_to_write:
      myfile.write("# %s\n" % dep)

    myfile.close()

  def _exit_if_bento_still_running(self):
    jps_results = run('jps')
    if jps_results.lower().find('minicluster') != -1 and not self.b_kill_bento:
      assert False, "Please kill all bento-related jobs (run 'jps' to get a list)"

    # Kill all of the bento processes
    for line in jps_results.splitlines():
      toks = line.split()
      if len(toks) == 1: continue
      assert len(toks) == 2, toks
      (pid, job) = toks
      if job == 'Jps': continue
      cmd = "kill -9 " + pid
      run(cmd)

  def _help_actions(self):
    """ Print detailed information about how the different actions work """
    actions_str = ""
    for (key,value) in self.actions_help.items():
      actions_str += "command: %s\n%s\n\n" % (key, value)
    print(actions_str)
    sys.exit(0)

  def _parse_options(self, cmd_line_args):
    # ----------------------------------------------------------------------------------------------
    # Parse command-line arguments
    args = self.create_parser().parse_args(cmd_line_args)

    if args.verbose:
      logging.basicConfig(level=logging.INFO)

    if args.debug:
      logging.basicConfig(level=logging.DEBUG)

    if args.link_modules == None:
      link_modules = []
    else:
      link_modules = args.link_modules.split(',')

    self.actions = opts.action
    for action in self.actions:
      assert action in self.possible_actions

    if 'help-actions' in self.actions: self._help_actions()

    # ----------------------------------------------------------------------------------------------
    # Kill any stale processes from the previous Bento Box.

    # ----------------------------------------------------------------------------------------------
    # Find the appropriate bento file.
    bento_tgz = self.find_bento_tgz(args.bento_version)
    logging.info("Using bento tgz file " + bento_tgz)

    m_bento = p_bento.match(bento_tgz)
    assert m_bento
    bento_dir = 'kiji-bento-' + m_bento.group('name')

    # ----------------------------------------------------------------------------------------------
    # Untar the bento box, possibly deleting the previous install.
    self.untar_bento(bento_dir, bento_tgz)

    # ----------------------------------------------------------------------------------------------
    # Optionally sym link some JAR files
    self.sym_link_target_jars(bento_dir, link_modules)

    # ----------------------------------------------------------------------------------------------
    # Create a classpath variable with the classpaths for *all* of the different modules that we
    # symlinked.
    dependency_jars = self.get_dependency_jars(link_modules)
    var_name = 'EXTRA_CLASSPATH'
    src_file = 'SOURCE_ME.sh'
    self.write_file_that_sets_classpath(dependency_jars, var_name, src_file)
    assert os.path.isfile(src_file)

    msg = \
      "Source the file '%s' to set the env var '%s' to contain all JARs needed to build the " + \
      "locally-built Kiji projects you specified.  Note that if those locally-build " + \
      "have vastly different dependencies than your bento box (e.g., different scala " + \
      "versions), then sourcing '%s' may hose everything."
    print msg % (src_file, var_name, src_file)

  def go(self, cmd_line_args):
    self._parse_options(cmd_line_args)
    self._run_actions()


if __name__ == "__main__":
  foo = BentoRebooter()
  foo.go(sys.argv[1:])
