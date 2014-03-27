#!/usr/bin/env python2.7

"""
Runs all of the steps necessary to build a PMML model in R and attach it to a scoring server.

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

import bento_reboot

myname = os.path.split(sys.argv[0])[-1]
description = """
This script runs a short example that goes through the end-to-end process of taking a
machine-learning model from R into production with Kiji.  The steps are the following:
  - train a machine learning model in R
  - export the model into a PMML file
  - create a Kiji PMML scoring function from the model
  - register that score function in the model repo
  - run sample data through the score function

You should run this script from the root directory of the PMML example.
"""

def run(cmd):
  result = ""
  try:
    result = subprocess.check_output(cmd, shell=True)
  except subprocess.CalledProcessError as e:
    sys.stderr.write("Error running command '%s':\n" % cmd)
    sys.stderr.write("\tExit code = %s\n" % e.returncode)
    sys.stderr.write("\tOutput = %s\n" % e.output)
    raise e
  return result

class PmmlRunner(object):

  def _run_kiji(self, cmd, directory=None, kiji_classpath=None, env_vars=None):
    """ Run a Kiji command for the bento box in a particular directory, with a special classapth. """

    assert self._bento_dir != None
    assert os.path.isdir(self._bento_dir)

    # Change location.
    cmd_change_dir = "" if directory == None else "cd %s;" % directory

    # Possibly add to the default KIJI_CLASSPATH.
    if kiji_classpath == None:
      kiji_classpath = self._kiji_classpath

    cmd_cp = "export KIJI_CLASSPATH=$KIJI_CLASSPATH:" + kiji_classpath + ";"

    # Possibly set up a bunch of environment variables.
    cmd_env_vars = "" if env_vars == None \
     else "export " + \
        " ".join(["%s=%s" % (k,v) for k,v in env_vars.items()]) + \
        ";"

    full_command = '{change_dir} {kiji_env} {cmd_cp} {env_vars} {cmd}'.format(
        change_dir=cmd_change_dir,
        kiji_env = 'source %s/bin/kiji-env.sh;' % self._bento_dir,
        cmd_cp = cmd_cp,
        env_vars = cmd_env_vars,
        cmd = cmd
    )
    logging.debug("Running Kiji command: '%s'" % full_command)
    return run(full_command)

  # List of commands available to the user.
  # TODO: Add something to unlink JARs
  possible_actions = [
      'help-actions',
      'bento-setup',
      'r-xml',
      'kiji-init',
      'repo-init',
      'scoring-server-init',
      'pmml-wizard',
      'repo-deploy',
      'repo-fresh',
      'kiji-bulk-import',
  ]

  actions_help = {
      'bento-setup':
        "Untar the Bento Box, symlink some JAR files, and start the Bento Box.",
      'r-xml':
        "Run R to dump out XML for a PMML model.",
      'kiji-init':
        "Install a Kiji instance and create a Kiji table.",
      'repo-init':
        "Create a model repository (die if one already exists).",
      'scoring-server-init':
        "Run the scoring server (die if it is not running).",
      'pmml-wizard' :
        "Run the model-repo pmml command to create a JSON description of the PMML model.",
      'repo-deploy':
        "Run the model-repo deploy command to deploy the model onto the server.",
      'repo-fresh':
        "Attach the score function to the appropriate table column.",
      'kiji-bulk-import':
        "Bulk-import data for this test case.",
    }

  def __init__(self):
    super(PmmlRunner, self).__init__()

    # List of different actions for this tool to execute.
    self._actions = None

    # Root bento box directory.
    self._bento_dir = None

    # Kiji JARs to symlink from local builds to the Bento Box lib directories.
    self._link_modules = None

    self._kiji = 'kiji://localhost:2181/default'

    self._user_table = 'ozone'

    # Working directory for files created by this script.
    self._work = 'work'

    self._pmml_file = 'RegressionOzone.pmml'

    #self._model_name = 'Linear_Regression_Model'
    self._model_name = 'artifact.ozone_model'

    # TODO: Is this supposed to be in the R file?
    self._model_version = '0.0.1'

    self._model_container_json = 'ozone.json'

  def _create_parser(self):
    """ Returns a parser for the script """

    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument(
        "action",
        nargs='*',
        help="Action to take (%s)" % self.possible_actions)

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
        '-r',
        '--root-dir',
        type=str,
        default=os.getcwd(),
        help='Root directory (containing tgz for bento) [pwd]')

    return parser

  def _help_actions(self):
    """ Print detailed information about how the different actions work """
    actions_str = ""
    for action in self.possible_actions:
      actions_str += "command: %s\n%s\n\n" % (action, self.actions_help[action])
    print(actions_str)
    sys.exit(0)

  def _parse_options(self, cmd_line_args):
    """ Parse all of the command-line arguments and assign member variables appropriately. """

    args = self._create_parser().parse_args(cmd_line_args)

    # Set up logging.
    if args.verbose:
      logging.basicConfig(level=logging.INFO)

    if args.debug:
      logging.basicConfig(level=logging.DEBUG)

    # Root directory of Bento Box .tar.gz file and kiji checkouts.
    self._root_dir = args.root_dir
    assert os.path.isdir(self._root_dir)

    # Figure out what actions (steps) to perform.
    self._actions = args.action
    for action in self._actions:
      assert action in self.possible_actions, \
        "Action '%s' is not one of %s" % (action, self.possible_actions)

    if 'help-actions' in self._actions: self._help_actions()

    # Useful information for the user about what we are going to do!
    logging.info("Running the following steps:")
    for action in self.possible_actions:
      if action in self._actions:
        logging.info("\t" + action)

  # ------------------------------------------------------------------------------------------------
  # Useful utility functions.
  def _is_bento_box_running(self):
    """ Return true if the bento box is running, false otherwise. """
    assert None != self._bento_dir
    assert os.path.isdir(self._bento_dir)

    bento_status = self._run_kiji('bento status')

    p_bento_running = re.compile(r'bento-cluster: Running as \d+\.')

    logging.debug('Result of bento status command = ' + bento_status)

    return None != p_bento_running.search(bento_status)

  def _is_kiji_instance_installed(self):
    assert None != self._bento_dir
    assert os.path.isdir(self._bento_dir)

    kiji_ls = self._run_kiji('kiji ls')

    return kiji_ls.find(self._kiji) != -1

  def _is_kiji_user_table_present(self):
    assert None != self._bento_dir
    assert os.path.isdir(self._bento_dir)

    kiji_ls = self._run_kiji('kiji ls %s' % self._kiji)

    return kiji_ls.find(self._kiji + "/" + self._user_table) != -1

  def _is_scoring_server_running(self):
    """ Return true if the scoring server is running, false otherwise. """
    assert None != self._bento_dir
    assert os.path.isdir(self._bento_dir)

    jps_results = self._run_kiji('jps')

    p_ss = re.compile(r'\d+ ScoringServer')

    logging.debug('Result of jps = ' + jps_results)

    return None != p_ss.search(jps_results)

  def _create_work_dir(self):
    if not os.path.exists(self._work):
      os.mkdir(self._work)

  def _set_kiji_classpath(self):
    # Hard-coded (yikes!) big classpath...
    mvn_repo = os.path.join(os.environ['HOME'], '.m2', 'repository')

    deps = [
        'org/jpmml/pmml-evaluator/1.1-SNAPSHOT/pmml-evaluator-1.1-SNAPSHOT.jar',
        'org/jpmml/pmml-manager/1.1-SNAPSHOT/pmml-manager-1.1-SNAPSHOT.jar',
        'org/jpmml/pmml-model/1.1.3/pmml-model-1.1.3.jar',
        'com/sun/xml/bind/jaxb-impl/2.2.6/jaxb-impl-2.2.6.jar',
        'org/jpmml/pmml-schema/1.1.3/pmml-schema-1.1.3.jar',
        'joda-time/joda-time/2.2/joda-time-2.2.jar',
        'org/apache/maven/shared/maven-invoker/2.1.1/maven-invoker-2.1.1.jar',
        'org/codehaus/plexus/plexus-utils/3.0.8/plexus-utils-3.0.8.jar',
        'org/codehaus/plexus/plexus-component-annotations/1.5.5/plexus-component-annotations-1.5.5.jar',
    ]

    self._kiji_classpath = ":".join([mvn_repo + '/' + d for d in deps])
    self._kiji_classpath += ":" + "target/kiji-pmml-1.0-SNAPSHOT.jar"
    self._kiji_classpath += ":" + \
    "{root}/kiji-modeling/kiji-modeling/target/kiji-modeling-0.8.0-SNAPSHOT.jar:{root}/kiji-model-repository/kiji-model-repository/target/kiji-model-repository-0.7.0-SNAPSHOT.jar".format(root=self._root_dir)

  # ------------------------------------------------------------------------------------------------
  # Set up the bento box.
  def _do_action_bento_setup(self):
    """ Untar the bento box, symlink JARs, start the Bento Box, etc. """
    bento_rebooter = bento_reboot.BentoRebooter()

    # Set up all of the command line options.
    root_dir = self._root_dir
    link_modules = 'model-repository,scoring'
    rebooter_args = \
        "install-bento link-jars run-bento -r {root_dir} -l {link_modules} -v ".format(
            root_dir=root_dir,
            link_modules=link_modules
        )
    bento_rebooter.go(rebooter_args.split())

  def _set_bento_dir(self):
    """ Find the Bento directory from within root. """

    full_paths_in_root_dir = [os.path.join(self._root_dir, d) for d in os.listdir(self._root_dir)]

    logging.debug(sorted(full_paths_in_root_dir))

    potential_bento_dirs = [
        d for d in full_paths_in_root_dir if
          os.path.isdir(os.path.abspath(d)) and os.path.basename(d).startswith('kiji-bento-')
    ]

    assert len(potential_bento_dirs) > 0, \
        "Could not find a bento box directory in %s!" % self._root_dir

    assert len(potential_bento_dirs) == 1, \
        "Multiple potential bento directories! %s" % potential_bento_dirs

    self._bento_dir = potential_bento_dirs[0]

  # ------------------------------------------------------------------------------------------------
  # Produce an XML file with a PMML model for something.
  def _do_action_r_produce_pmml_xml(self):
    """ Call R with a script to make a PMML model. """
    cmd = 'cd r_stuff; R CMD BATCH ozone.R'
    run(cmd)
    assert os.path.isfile(os.path.join(self._work, self._pmml_file))

    # TODO: May have to post-process the PMML file (or change the original R script) to make the
    # model name something that the model repo likes (e.g., from 'mymodel' to 'foo.mymodel-0.1').

  # ------------------------------------------------------------------------------------------------
  # Initialize Kiji.
  def _do_action_kiji_init(self):
    """ Install a Kiji instance, create a Kiji table """
    assert None != self._bento_dir
    assert os.path.isdir(self._bento_dir)
    assert self._is_bento_box_running()

    # Possibly delete the kiji instance...
    if self._is_kiji_instance_installed():
      self._run_kiji(cmd = 'kiji delete  --target=%s --interactive=false ' % self._kiji)

    # Install the Kiji instance.
    self._run_kiji(cmd = 'kiji install --kiji=%s' % self._kiji)
    assert self._is_kiji_instance_installed()

    # Create the Kiji table.
    self._run_kiji(cmd =
      'kiji-schema-shell --kiji={kiji} --file=src/main/layout/table_desc.ddl'.format(
        kiji=self._kiji
    ))

  # ------------------------------------------------------------------------------------------------
  # Create a model repo.
  def _do_action_repo_init(self):
    """ Create a directory for the model repo (if it does not already exist). """
    assert None != self._bento_dir
    assert os.path.isdir(self._bento_dir)
    assert self._is_bento_box_running()
    assert self._is_kiji_instance_installed()

    repo_dir = os.path.join(self._work, 'my_model_repo')

    if not os.path.exists(repo_dir): os.mkdir(repo_dir)

    cmd = 'kiji model-repo init file://{repo_dir} --kiji={kiji}'.format(
        repo_dir = os.path.abspath(repo_dir),
        kiji = self._kiji
    )

    res = self._run_kiji(cmd, kiji_classpath=self._kiji_classpath)
    logging.info(res)

  # ------------------------------------------------------------------------------------------------
  # Start the scoring server.
  def _do_action_scoring_server_init(self):
    """
    Start up the scoring server, remembering to fix the typo on line 24 of the scoring server bash
    script!
    """
    assert None != self._bento_dir
    assert os.path.isdir(self._bento_dir)
    assert self._is_bento_box_running()
    assert self._is_kiji_instance_installed()

    if self._is_scoring_server_running():
      logging.info("Scoring server is already running, skipping...")
      return

    scoring_server_script = \
        os.path.join(self._bento_dir, 'scoring-server', 'bin', 'kiji-scoring-server')

    # Read in the current version of the script.
    scoring_server_file = open(scoring_server_script, 'r')
    scoring_server_text = scoring_server_file.read()
    scoring_server_file.close()

    # Fix a typo!
    p_typo = re.compile(r'0\]')
    new_scoring_server_text = p_typo.sub('0 ]', scoring_server_text)

    if new_scoring_server_text != scoring_server_text:
      logging.info("Fixing bug on line 24 of scoring server bash script...")
      scoring_server_file = open(scoring_server_script, 'w')
      scoring_server_file.write(new_scoring_server_text)
      scoring_server_file.close()

    logging.info("Running scoring server...")
    self._run_kiji(cmd = scoring_server_script, directory = self._bento_dir)

    assert self._is_scoring_server_running()

  # ------------------------------------------------------------------------------------------------
  # Create a JSON file that contains a description of the model.
  def _do_action_pmml_wizard(self):
    """ Run Robert's PMML command-line wizard! """

    if os.path.isfile(os.path.join(self._work, self._model_container_json)):
      os.remove(os.path.join(self._work, self._model_container_json))

    cmd_raw = \
      " kiji model-repo pmml " + \
      " --table={table} " + \
      " --model-file=file://{pmml} --model-name={model_name} " + \
      " --model-version={version} --predictor-column=info:predictor --result-column=info:predicted " + \
      " --result-record-name=OzonePredicted --model-container={container} "

    cmd = cmd_raw.format(
      table = self._kiji + "/" + self._user_table,
      pmml = os.path.abspath(os.path.join(self._work, self._pmml_file)),
      model_name = self._model_name,
      version = self._model_version,
      container = os.path.join(self._work, self._model_container_json)
    )

    self._run_kiji(cmd)

    assert os.path.isfile(os.path.join(self._work, self._model_container_json))

  # ------------------------------------------------------------------------------------------------
  # Deploy the repo
  def _do_action_repo_deploy(self):
    self._run_kiji(cmd = 'touch foo', directory = self._work)
    self._run_kiji(cmd = 'jar cf empty.jar foo', directory = self._work)
    cmd_raw = 'kiji model-repo deploy {model} {jar}  --kiji={kiji} ' + \
        ' --deps-resolver=maven --production-ready=true --model-container={container} ' + \
        ' --message="Initial deployment of model."'
    cmd = cmd_raw.format(
        model = self._model_name,
        kiji = self._kiji,
        container = os.path.join(self._work, self._model_container_json),
        jar = os.path.join(self._work, 'empty.jar'),
    )
    self._run_kiji(cmd)

    # TODO: Check that we see the appropriate row in the kiji table now?

  def _do_action_repo_fresh(self):
    cmd_raw = 'kiji model-repo fresh-model {kiji} {model}-{version} org.kiji.scoring.lib.AlwaysFreshen'
    cmd = cmd_raw.format(kiji=self._kiji, model=self._model_name, version=self._model_version)

    self._run_kiji(cmd)

  def _run_actions(self):

    self._create_work_dir()
    self._set_kiji_classpath()

    if 'bento-setup' in self._actions:
      self._do_action_bento_setup()

    self._set_bento_dir()

    if 'bento-setup' in self._actions:
      assert self._is_bento_box_running()

    if 'r-xml' in self._actions:
      self._do_action_r_produce_pmml_xml()

    if 'kiji-init' in self._actions:
      self._do_action_kiji_init()

    if 'repo-init' in self._actions:
      self._do_action_repo_init()

    if 'scoring-server-init' in self._actions:
      self._do_action_scoring_server_init()

    if 'pmml-wizard' in self._actions:
      self._do_action_pmml_wizard()

    if 'repo-deploy' in self._actions:
      self._do_action_repo_deploy()

    if 'repo-fresh' in self._actions:
      self._do_action_repo_fresh()

  def go(self, cmd_line_args):
    self._parse_options(cmd_line_args)
    self._run_actions()

if __name__ == "__main__":
  foo = PmmlRunner()
  foo.go(sys.argv[1:])
