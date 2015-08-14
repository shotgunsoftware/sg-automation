#!/usr/bin/env python -u

import base64
import datetime
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib2
import urlparse

import testrail

from optparse import OptionParser
from pprint import pprint as pp

def ppjson(doc):
    # print json.dumps(doc, sort_keys=True, indent=4, separators=(',', ': '))
    pp(doc, indent=4, width=1)

def get_site_version(url):
    try:
        request = urllib2.Request(url)
        response = urllib2.urlopen(request)
        results = response.read()
    except Exception as e:
        sys.stderr.write("Unexpected exception: %s \n" % e)
        sys.exit(1)
    pattern = re.search("v([a-zA-Z0-9-.]+) \(build ([0-9a-f]{7})\)", results)
    version_name = pattern.group(1)
    version_hash = pattern.group(2)
    return (version_name, version_hash)

class SuiteNotFound(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return str(self.message)

class WorkFolderDoesNotExists(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return str(self.message)

class GitHubError(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return str(self.message)

class TestRailError(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return str(self.message)

class TestRailRunInvalid(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return str(self.message)

class GitError(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return str(self.message)

class UnsupportedBranch(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return str(self.message)

class SeleniumSandbox:
    def __init__(self, git_token, testrail_token=None, debugging=False):
        self.command_file = "runTest.command"
        self.git_token = git_token
        if testrail_token:
            if ':' in  testrail_token:
                (user, password) = testrail_token.split(':')
            self.testrail = testrail.APIClient('http://meqa.autodesk.com')
            self.testrail.user = user
            self.testrail.password = password
            self.testrail_project_id = None
            for project in self.testrail.send_get('get_projects'):
                if project['name'] == 'Shotgun':
                    self.testrail_project_id = project['id']
                    break
            if self.testrail_project_id is None:
                raise TestRailError('Project Shotgun cannot be found on TestRail')
            self.testrail_runs = self.get_testrail_runs()
            self.testrail_plans = self.get_testrail_plans()
        self.debugging = debugging
        self.testrail_available_cases = {}
        self.target_url = None
        self.target_version_name = None
        self.target_version_hash = None
        self.testrail_suites = {}
        self.user = self.get_elems("https://api.github.com/user")

    def set_work_folder(self, work_folder):
        if not os.path.exists(work_folder):
            raise WorkFolderDoesNotExists("Path to '%s' does not exists" % work_folder)
        self.work_folder = work_folder
        self.git_folder = work_folder + os.path.sep + ".git"
        self.git_objects_folder = self.git_folder + os.path.sep + "objects"
        self.git_refs_folder = self.git_folder + os.path.sep + "refs"

        if not os.path.exists(self.git_objects_folder):
            os.makedirs(self.git_objects_folder)

        # Even if we do not use the refs folder yet, it has to be there to
        # simulate a git repo.
        if not os.path.exists(self.git_refs_folder):
            os.makedirs(self.git_refs_folder)

    def get_work_folder(self):
        return self.work_folder

    def get_user_login(self):
        return self.user['login']

    def get_testrail_runs(self):
        runs = {}
        if self.testrail_project_id:
            for run in self.testrail.send_get('get_runs/%d&is_completed=0' % self.testrail_project_id):
                runs[run['id']] = run
        return runs

    def get_testrail_plans(self):
        plans = {}
        if self.testrail_project_id:
            for plan in self.testrail.send_get('get_plans/%d&is_completed=0' % self.testrail_project_id):
                plans[plan['id']] = plan
        return plans

    def fetch_shotgun_files(self, target_url):
        self.target_url = target_url
        (self.target_version_name, self.target_version_hash) = get_site_version(target_url)
        self.shotgun_version = self.get_tree(self.target_version_hash)["sha"]
        head_file = open(self.git_folder + os.path.sep + "HEAD", "w")
        head_file.write("%s\n" % self.shotgun_version)
        head_file.close()

        self.selenium_version = self.find_tree(self.shotgun_version, "test/selenium")
        self.fetch_tree(self.selenium_version)
        print(".")

    def get_elems(self, url):
        # base64string = base64.encodestring("%s:%s" % (self.git_token, "x-oauth-basic")).strip()
        base64string = base64.encodestring("%s" % self.git_token).strip()
        authheader = "Basic %s" % base64string
        results = {}
        try:
            request = urllib2.Request(url)
            request.add_header("Authorization", authheader)
            response = urllib2.urlopen(request)
            results = json.loads(response.read())
            if self.debugging:
                print("DEBUG: GitHub API X-RateLimit-Remaining: %s" % response.info().getheader("X-RateLimit-Remaining"))
        except Exception as e:
            raise GitHubError("GitHub Unexpected exception: %s\n" % e)
        return results

    def get_git_object_folder(self, sha):
        return self.git_objects_folder + os.path.sep + sha[:2]

    def get_git_object_file(self, sha):
        return self.get_git_object_folder(sha) + os.path.sep + sha[2:]

    def has_git_object(self, sha):
        return len(glob.glob(self.get_git_object_file(sha) + "*")) == 1

    def get_tree(self, sha):
        if self.has_git_object(sha):
            treeFile = glob.glob(self.get_git_object_file(sha) + "*")[0]
            jsonFile = os.fdopen(os.open(treeFile, os.O_RDONLY))
            elems = json.load(jsonFile)
        else:
            elems = self.get_elems("https://api.github.com/repos/shotgunsoftware/shotgun/git/trees/%s" % sha)
            if elems["truncated"]:
                raise GitError("Items in folder too high to use the GitHub API. No workaround yet... other than local cloning.")

            treeFile = self.get_git_object_file(elems["sha"])
            treeFileFolder = self.get_git_object_folder(elems["sha"])

            if self.debugging:
                print("DEBUG: Getting tree %s" % treeFile)

            if not os.path.exists(treeFileFolder):
                os.mkdir(treeFileFolder)

            dataFile = os.fdopen(os.open(treeFile, os.O_WRONLY | os.O_CREAT, 0644), "w")
            json.dump(elems, dataFile)
            dataFile.close()
        return elems

    def get_blob(self, elem):
        if self.has_git_object(elem["sha"]):
            pass
        else:
            mode = elem["mode"]
            blob = self.get_elems(elem["url"])
            data = base64.b64decode(blob["content"])

            blobFile = self.get_git_object_file(elem["sha"])
            blobFileFolder = self.get_git_object_folder(elem["sha"])

            if self.debugging:
                print("DEBUG: Getting blob %s" % blobFile)
            else:
                print ".",

            if not os.path.exists(blobFileFolder):
                os.mkdir(blobFileFolder)
            if mode[:2] == "10" or mode[:2] == "12": # File or symlink
                dataFile = os.fdopen(os.open(blobFile, os.O_WRONLY | os.O_CREAT, 0644), "w")
                dataFile.write(data)
                dataFile.close()
            else:
                raise Exception("Unable to process %s, do not know how to handle mode %s." % (filename, mode))

    def find_tree(self, sha, path):
        dirs = path.split("/")
        for dir in dirs:
            elems = self.get_tree(sha)
            shas = [x["sha"] for x in elems["tree"] if x["path"] == dir]
            if len(shas) == 1:
                sha = shas[0]
            else:
                raise Exception("Path to %s not found")
        return sha

    def fetch_tree(self, sha):
        tree = self.get_tree(sha)

        for elem in tree["tree"]:
            if elem["type"] == "tree":
                self.fetch_tree(elem["sha"])
            elif elem["type"] == "blob":
                self.get_blob(elem)
            else:
                raise Exception("Do not know how to handle object type %s for object %s" % (elem["type"], elem["path"]))

    def sync_filesystem(self, sha=None, prefix=None):
        if sha is None:
            sha = self.selenium_version
            self.testrail_available_cases = {}

        tree = self.get_tree(sha)

        prefix = prefix or self.work_folder + os.path.sep
        expected = [x['path'] for x in tree["tree"]]
        # We want to avoir deleting our .git folder.
        expected.append(".git")

        actual = os.listdir(prefix)

        # Cleanup any extra files or folders
        diff = [x for x in actual if x not in expected]
        for i in diff:
            obj = prefix + i
            # Do not delete the build folder
            if os.path.isdir(obj):
                if os.path.join(self.work_folder, "suites", "build") != obj:
                    print("Removing folder: %s" % obj)
                    shutil.rmtree(obj)
            # do not delete the config.xml file
            elif os.path.join(self.work_folder, "suites", "config", "config.xml") != obj:
                print("Removing file: %s" % obj)
                os.remove(obj)

        # And now sync our files.
        for elem in tree["tree"]:
            path = prefix + elem["path"]
            sha = elem["sha"]
            if elem["type"] == "tree":
                is_case = re.match('^C([0-9]+)$', elem["path"])
                # If it is a folder matching a test case ID, and it is in test_rail
                # @FIXME: this is a very brittle test...
                if is_case and path.startswith(os.path.join(self.work_folder, "suites", "test_rail", "")):
                    self.testrail_available_cases[int(is_case.group(1))] = path
                if not os.path.exists(path):
                    print("creating folder: " + path)
                    os.mkdir(path)
                self.sync_filesystem(sha, path + os.path.sep)
            elif elem["type"] == "blob":
                mode = elem["mode"][:2]
                perm = int(elem["mode"][2:], 8)
                if mode == "10":
                    if os.path.exists(path):
                        statInfo = os.stat(path)
                        fileSha1 = hashlib.sha1("blob " + str(statInfo.st_size) + "\0" + open(path, "rb").read()).hexdigest()
                        # @FIXME: DO NOT SUBMIT THE FOLLOWING TWO LINES !!! WORK CODE ONLY
                        if os.path.join("suites", "runTest.command") in path:
                           continue
                        if fileSha1 != sha:
                            print("updating file: " + path)
                            shutil.copy(self.get_git_object_file(sha), path)
                            os.chmod(path, perm)
                    else:
                        print("creating file: " + path)
                        shutil.copy(self.get_git_object_file(sha), path)
                        os.chmod(path, perm)
                elif mode == "12":
                    if not os.path.exists(path):
                        print("creating symlink: " + path)
                        lines = [line.strip() for line in open(self.get_git_object_file(sha))]
                        os.symlink(lines[0], path)
                    pass
                else:
                    raise Exception("Unable to process %s, do not know how to handle mode %s." % (path, mode))
            else:
                raise Exception("Do not know how to handle object type %s for object %s" % (elem["type"], elem["path"]))

    def generate_config(self, options):
        configFolder = os.path.join(self.work_folder, "suites", "config")
        if 'sg_config__url' in options and options['sg_config__url'] != self.target_url:
            print "WARNING: overriding option sg_config__url of\n    %s\n  with\n    %s" % (options['sg_config__url'], self.target_url)
        options['sg_config__url'] = self.target_url

        if "sg_config__check_shotgun_version" not in options:
            options["sg_config__check_shotgun_version"] = "true"

        if os.path.exists(configFolder):
            configFile = open(os.path.join(configFolder, "config.xml"), "w")
            configFile.write(
"""<?xml version="1.0" encoding="UTF-8"?>
<testdata>
  <vars
""")
            for key in options.keys():
                configFile.write('    %s="%s"\n' % (key, options[key]))
            configFile.write(
"""  />
</testdata>
""")
            configFile.close()
        else:
            raise UnsupportedBranch("This site does not support Selenium tests")


    def execute_suite(self, test_suite):
        if not test_suite.endswith(self.command_file):
            test_suite = os.path.join(test_suite, self.command_file)
        if not test_suite.startswith(self.work_folder):
            test_suite = os.path.join(self.work_folder, test_suite)

        if os.path.exists(test_suite):
            code = -1
            self.subProc = subprocess.Popen(test_suite)
            try:
                code = self.subProc.wait()
            except (KeyboardInterrupt, SystemExit):
                self.subProc.kill()
            except Exception as e:
                self.subProc.kill()
                raise
            return code
        else:
            raise SuiteNotFound("Non existent test suite %s" % test_suite)

    def get_testrail_runs_from_plan(self, test_plan):
        runs = []
        if test_plan not in self.testrail_plans:
            raise TestRailRunInvalid('TestRail plan %s does not exist' % test_plan)
        plan = self.testrail.send_get('get_plan/%s' % test_plan)
        for entry in plan['entries']:
            for run in entry['runs']:
                # @FIXME: Okay... not to sure about that... perhaps a separate data member...
                self.testrail_runs[run['id']] = run
                runs.append(run['id'])
        return runs

    def execute_run(self, test_run, commit=False, run_all=False):
        targets = []
        tests = {}

        # @TODO: These settings should be obtained from the TestRail server.
        # @FIXME: values are hardcoded for the moment.
        testrail_statuses = {
            0: 1,
            1: 5,
            -1: 6
        }
        testrail_os = {
            "Windows": 10,
            "Linux": 20,
            "Darwin": 30, # a.k.a. OSX
            "iOS": 40,
        }
        testrail_browsers = {
            "Chrome": 10,
            "Firefox": 20,
            "FirefoxESR": 30,
            "Safari": 40,
        }

        if test_run in self.testrail_runs:
            targets = [test_run]
        elif test_run in self.testrail_plans:
            targets = self.get_testrail_runs_from_plan(test_run)
        else:
            raise TestRailRunInvalid('TestRail run or plan %s does not exist' % test_run)

        for target in targets:
            tests[target] = {}
            for test in self.testrail.send_get('get_tests/%s' % target):
                if test['title'].startswith('[Automation] '):
                    if test['case_id'] not in self.testrail_available_cases:
                        print "WARNING: skipping test case %s (%s) as it is not present in this codebase/version" % (
                            test['case_id'], test['title']
                        )
                    else:
                        if run_all or test['status_id'] != 1:
                            tests[target][test['id']] = test

        netloc = ""
        if self.target_url:
            netloc = urlparse.urlparse(self.target_url).netloc

        build_folder = os.path.join(
            self.get_work_folder(),
            "suites",
            "build",
            netloc,
            datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss"))

        targets.sort()
        for target in targets:
            suite_id = self.testrail_runs[target]["suite_id"]
            if suite_id not in self.testrail_suites:
                self.testrail_suites[suite_id] = self.testrail.send_get('get_suite/%s' % suite_id)
            print("INFO: Running TestRail test suite: %s - %s" % (
                self.testrail_suites[suite_id]['id'],
                self.testrail_suites[suite_id]['name']))
            # ppjson(tests[target])
            keys = tests[target].keys()
            keys.sort()

            results = {"results": []}
            for test in keys:

                test_suite = self.testrail_available_cases[tests[target][test]['case_id']]
                test_suite = os.path.join(test_suite, self.command_file)

                if os.path.exists(test_suite):
                    startTime = time.time()
                    stopTime = None
                    self.subProc = subprocess.Popen(test_suite, env={"BUILD_FOLDER": build_folder})
                    code = -1
                    try:
                        code = self.subProc.wait()
                        stopTime = time.time()
                    except (KeyboardInterrupt, SystemExit):
                        self.subProc.kill()
                    except Exception as e:
                        self.subProc.kill()
                        raise
                    if code == 0 or code == 1 or code == -1:
                        result = {
                            'case_id': tests[target][test]['case_id'],
                            'status_id': testrail_statuses[code],
                            'comment': "from Automation on %s" % self.target_url ,
                            'custom_os': [testrail_os[platform.system()]],
                            'custom_webbrowser': [testrail_browsers['Firefox']],
                            'version': "v%s (build %s)" % (self.target_version_name, self.target_version_hash)
                        }
                        if code == 0 or code == 1:
                            result['elapsed'] = '%ds' % int(stopTime - startTime + 0.5)
                        if code == -1:
                            result['comment'] += " **Test aborted by user**"
                        results['results'].append(result)
                    else:
                        raise Exception("Unexpected return code from Selenium: %d" % code)
                else:
                    raise SuiteNotFound("Non existent test suite %s" % test_suite)
            if commit and len(results['results']) > 0:
                self.testrail.send_post('add_results_for_cases/%s' % target, results)

    def signal_handler(self, sig, frm):
        sys.exit(1)


def main(argv):
    parser = OptionParser(usage="usage: %prog [options] url")
    parser.add_option("--git-token",
        help="API key or credentials user:password or token:x-oauth-basic")
    parser.add_option("--testrail-token",
        help="API key or credentials user:password or email:api-key (OPTIONAL)")
    parser.add_option("--testrail-run",
        help="TestRail run or plan to execute (OPTIONAL, requires --testrail-token)")
    parser.add_option("--testrail-commit", action="store_true", dest="testrail_commit",
        help="Output debugging information")
    parser.add_option("--testrail-run-all", action="store_true", dest="testrail_run_all",
        help="Run all the tests instead of only those that have not passed (OPTIONAL)")
    parser.add_option("--suite",
        help="Test suite to execute (OPTIONAL)")
    parser.add_option("--work-folder",
        help="Work folder. Will be created if required")
    parser.add_option("--config-options",
        help="Comma separated list of key=value to be added to the config.xml (OPTIONAL)")
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose",
        help="Output debugging information")
    (options, args) = parser.parse_args()

    if options.verbose is None:
        options.verbose = False

    if options.testrail_token is None:
        options.testrail_token = ''

    if options.suite is None:
        options.suite = False

    if options.testrail_run is None:
        options.testrail_run = False

    if options.testrail_commit is None:
        options.testrail_commit = False

    if options.testrail_run_all is None:
        options.testrail_run_all = False

    if options.config_options is None:
        options.config_options = ""

    if (options.suite and options.testrail_run):
        print "Options --suite and --testrail-run are mutually exclusive."
        parser.print_help()
        sys.exit(2)

    if options.testrail_run:
        if re.match('^[1-9][0-9]*$', options.testrail_run):
            options.testrail_run = int(options.testrail_run)
        else:
            print "A testrail-run argument must be a number."
            parser.print_help()
            sys.exit(2)

    if options.testrail_run and not options.testrail_token:
        print "A testrail-run argument requires a valid TestRail token."
        parser.print_help()
        sys.exit(2)

    if None in vars(options).values():
        print "Missing required option for Shotgun API connection."
        parser.print_help()
        sys.exit(2)

    if len(args) != 1:
        parser.error("incorrect number of arguments")
        parser.print_help()
        sys.exit(2)

    if not (args[0].startswith("https://") or args[0].startswith("http://")):
        print "scheme not indicated, assuming http"
        args[0] = "http://%s" % args[0]

    url = urlparse.urlparse(args[0])
    if url.netloc == "":
        parser.error("need to specify a Shotgun site URL")
        parser.print_help()
        sys.exit(2)

    shotgun_url = "%s://%s" % (url.scheme, url.netloc)

    if options.testrail_token:
        print "INFO: Connecting to GitHub and TestRail"
    else:
        print "INFO: Connecting to GitHub"
    sandbox = SeleniumSandbox(options.git_token, options.testrail_token, options.verbose)
    signal.signal(signal.SIGINT, sandbox.signal_handler)
    print "INFO:     Connected to GitHub as user %s" % sandbox.user["login"]

    if options.testrail_run and (
            options.testrail_run not in sandbox.testrail_runs and
            options.testrail_run not in sandbox.testrail_plans):
        print("ERROR: Invalid TestRail run or plan: %s" % options.testrail_run)
        sys.exit(2)
        pass

    if options.testrail_token and options.verbose:
        print "  Runs"
        for res_id in sandbox.testrail_runs.keys():
            print "     %s - %s" % (sandbox.testrail_runs[res_id]['name'], res_id)
        print "  Plans"
        for res_id in sandbox.testrail_plans.keys():
            print "     %s - %s" % (sandbox.testrail_plans[res_id]['name'], res_id)

    print "INFO: Setting work folder to %s" % options.work_folder
    if not os.path.exists(options.work_folder):
        print "INFO:    Creating work folder %s" % options.work_folder
        os.makedirs(options.work_folder)
    sandbox.set_work_folder(options.work_folder)

    print("INFO: Getting Shotgun files from repo for site %s. Please wait" % shotgun_url)
    sandbox.fetch_shotgun_files(shotgun_url)
    print("INFO:     Found version to be %s (%s)" % (sandbox.target_version_name, sandbox.target_version_hash))
    print("INFO:     Done getting files")

    print("INFO: Synchronizing filesystem with git files")
    sandbox.sync_filesystem()
    print("INFO:     Done synchronizing")

    print("INFO: Generating config.xml")
    run_options = {}
    if len(options.config_options) > 0 and '=' in options.config_options:
        for kv in options.config_options.split(","):
            (k, v) = kv.split("=")
            run_options[k] = v
            if options.verbose:
                print("INFO:     Adding config options %s=%s to run config" % (k, v))

    try:
        sandbox.generate_config(run_options)

        if options.suite:
            print("INFO: Running tests from %s" % options.suite)
            return_value = sandbox.execute_suite(options.suite)
            print("INFO:     Test completed")
        elif options.testrail_run:
            if options.testrail_run in sandbox.testrail_plans:
                print("INFO: Running TestRail test plan: %s - %s" % (options.testrail_run, sandbox.testrail_plans[options.testrail_run]['name']))
            else:
                print("INFO: Running TestRail test run: %s - %s" % (options.testrail_run, sandbox.testrail_runs[options.testrail_run]['name']))
            if options.testrail_run_all:
                print("INFO: Executing all of the tests regardless of their prior result")
            else:
                print("INFO: Executing only tests that have not been successful")
            return_value = sandbox.execute_run(options.testrail_run, options.testrail_commit, options.testrail_run_all)
            print("INFO:     Test completed")
    except UnsupportedBranch as e:
        print("ERROR: This Shotgun site does not support Selenium automation!")
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
