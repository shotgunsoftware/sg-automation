#!/usr/bin/env python -u
"""
SeleniumSandbox application.
"""

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


def ppjson(doc):
    """
    Pretty print json.
    """
    print json.dumps(doc, sort_keys=True, indent=4, separators=(',', ': '))


def get_site_version(url):
    """
    Get site version.
    """
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


def locate_files(pattern, root=os.curdir):
    """
    Locate all files matching supplied filename pattern in and below
    supplied root directory.
    """
    pattern = re.compile(pattern)
    for path, dirs, files in os.walk(os.path.abspath(root)):
        filenames = [f for f in files if pattern.match(f)]
        for filename in filenames:
            yield os.path.join(path, filename)


def locate_dirs(pattern, root=os.curdir):
    """
    Locate all folders matching supplied filename pattern in and below
    supplied root directory.
    """
    pattern = re.compile(pattern)
    for path, dirs, files in os.walk(os.path.abspath(root)):
        dirnames = [d for d in dirs if pattern.match(d)]
        for dirname in dirnames:
            yield os.path.join(path, dirname)


class SuiteNotFound(Exception):
    """
    Suite not found exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(SuiteNotFound, self).__init__(message)


class WorkFolderDoesNotExists(Exception):
    """
    Working folder does not exists exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(WorkFolderDoesNotExists, self).__init__(message)


class GitHubError(Exception):
    """
    GitHub error exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(GitHubError, self).__init__(message)


class TestRailError(Exception):
    """
    TestRail error exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(TestRailError, self).__init__(message)


class TestRailInternalServerError(Exception):
    """
    TestRail internal server error exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(TestRailInternalServerError, self).__init__(message)


class TestRailServerNotFound(Exception):
    """
    TestRail server not found exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(TestRailServerNotFound, self).__init__(message)


class TestRailInvalidCredentials(Exception):
    """
    TestRail invalid credentials exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(TestRailInvalidCredentials, self).__init__(message)


class TestRailShotgunProjectNotFound(Exception):
    """
    TestRail project not found exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(TestRailShotgunProjectNotFound, self).__init__(message)


class TestRailRunInvalid(Exception):
    """
    TestRail run invalid exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(TestRailRunInvalid, self).__init__(message)


class TestRailPlanInvalid(Exception):
    """
    TestRail plan invalid exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(TestRailPlanInvalid, self).__init__(message)


class GitError(Exception):
    """
    Git error exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(GitError, self).__init__(message)


class UnsupportedBranch(Exception):
    """
    Unsupported branch exception.
    """

    def __init__(self, message):
        """
        Constructor.
        """
        super(UnsupportedBranch, self).__init__(message)


class SeleniumSandbox:
    """
    Selenium Sandbox.
    """

    __version__ = "1.0"

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
        "Darwin": 30,  # a.k.a. OSX
        "iOS": 40,
    }
    testrail_browsers = {
        "Chrome": 10,
        "Firefox": 20,
        "FirefoxESR": 30,
        "Safari": 40,
    }

    def __init__(self, git_token, testrail_token=None, debugging=False, testrail_server="https://meqa.autodesk.com", testrail_project="Shotgun"):
        """
        Constructor.
        """
        self.command_file = "runTest.command"
        self.git_token = git_token
        self.testrail = None
        self.testrail_user = None
        self.testrail_runs = {}
        self.testrail_plans = {}
        self.testrail_suites = {}
        if testrail_token:
            if ':' in testrail_token:
                (testrail_email, testrail_api_key) = testrail_token.split(':')
            self.testrail = testrail.APIClient(testrail_server)
            self.testrail.user = testrail_email
            self.testrail.password = testrail_api_key
            try:
                self.testrail_user = self.testrail.send_get('get_user_by_email&email=%s' % testrail_email)
            except testrail.APIError as e:
                if e.code == 401:
                    raise TestRailInvalidCredentials("Invalid credentials for TestRail")
                elif e.code == 500:
                    raise TestRailInternalServerError("Internal server error for TestRail")
                else:
                    raise TestRailError("Unhandled server error %s" % e.code)
            except urllib2.URLError:
                raise TestRailServerNotFound("TestRail server not found. Enable VPN or use on the Autodesk Network.")

            self.testrail_project_id = None
            for project in self.testrail.send_get('get_projects'):
                if project['name'] == testrail_project:
                    self.testrail_project_id = project['id']
                    break
            if self.testrail_project_id is None:
                raise TestRailShotgunProjectNotFound('Project %s cannot be found on TestRail' % testrail_project)
            self.testrail_runs = self.get_testrail_runs()
            self.testrail_plans = self.get_testrail_plans()
            self.testrail_suites = self.get_testrail_suites()
        self.debugging = debugging
        self.available_cases = {}
        self.available_suites = {}
        self.target_url = None
        self.target_version_name = None
        self.target_version_hash = None
        self.shotgun_version = None
        self.github_user = self.get_elems("https://api.github.com/user")

    def update_targets(self):
        """
        Update tartgets.
        """
        self.available_suites = {}
        for target in locate_files(self.command_file, os.path.join(self.work_folder, 'suites')):
            key = target[len(self.work_folder) + 1:]
            key = key[:-len(self.command_file) - 1]
            self.available_suites[key] = target

        self.available_cases = {}
        for target in locate_dirs("^C[0-9]+$", os.path.join(self.work_folder, 'suites')):
            if os.path.exists(os.path.join(target, self.command_file)):
                case_id = os.path.basename(target)
                case_id = int(case_id.lstrip('C'))
                self.available_cases[case_id] = target

    def set_work_folder(self, work_folder):
        """
        Set work folder.
        """
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
        """
        Get work folder.
        """
        return self.work_folder

    def get_github_user(self):
        """
        Get GitHub user.
        """
        return self.github_user['login']

    def get_testrail_user(self):
        """
        Get TestRail user.
        """
        if self.testrail_user:
            return self.testrail_user['name']
        else:
            return ""

    def is_using_testrail(self):
        """
        Is using TestRail?
        """
        return self.testrail is not None

    def get_testrail_runs(self):
        """
        Get TestRail runs.
        """
        runs = {}
        if self.testrail_project_id:
            for run in self.testrail.send_get('get_runs/%d&is_completed=0' % self.testrail_project_id):
                runs[run['id']] = run
        return runs

    def get_testrail_plans(self):
        """
        Get TestRail plans.
        """
        plans = {}
        if self.testrail_project_id:
            for plan in self.testrail.send_get('get_plans/%d&is_completed=0' % self.testrail_project_id):
                plans[plan['id']] = plan
        return plans

    def get_testrail_suites(self):
        """
        Get TestRail suites.
        """
        suites = {}
        if self.testrail_project_id:
            for suite in self.testrail.send_get('get_suites/%d' % self.testrail_project_id):
                suites[suite['id']] = suite
        return suites

    def get_target_version(self, target_url):
        """
        Get target version.
        """
        self.target_url = target_url
        (self.target_version_name, self.target_version_hash) = get_site_version(target_url)
        self.shotgun_version = self.get_tree(self.target_version_hash)["sha"]

    def fetch_shotgun_files(self, target_url):
        """
        Fecth shotgun files.
        """
        self.get_target_version(target_url)
        head_file = open(self.git_folder + os.path.sep + "HEAD", "w")
        head_file.write("%s\n" % self.shotgun_version)
        head_file.close()

        self.fetch_tree(self.find_tree(self.shotgun_version, "test/selenium"))
        print(".")

    def get_elems(self, url):
        """
        Get elems from GitHub.
        """
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
        """
        Get git object folder.
        """
        return self.git_objects_folder + os.path.sep + sha[:2]

    def get_git_object_file(self, sha):
        """
        Get git object file.
        """
        return self.get_git_object_folder(sha) + os.path.sep + sha[2:]

    def has_git_object(self, sha):
        """
        Get git object.
        """
        return len(glob.glob(self.get_git_object_file(sha) + "*")) == 1

    def get_tree(self, sha):
        """
        Get tree.
        """
        if self.has_git_object(sha):
            tree_file = glob.glob(self.get_git_object_file(sha) + "*")[0]
            json_file = os.fdopen(os.open(tree_file, os.O_RDONLY))
            elems = json.load(json_file)
        else:
            elems = self.get_elems("https://api.github.com/repos/shotgunsoftware/shotgun/git/trees/%s" % sha)
            if elems["truncated"]:
                raise GitError("Items in folder too high to use the GitHub API. No workaround yet... other than local cloning.")

            tree_file = self.get_git_object_file(elems["sha"])
            tree_file_folder = self.get_git_object_folder(elems["sha"])

            if self.debugging:
                print("DEBUG: Getting tree %s" % tree_file)

            if not os.path.exists(tree_file_folder):
                os.mkdir(tree_file_folder)

            data_file = os.fdopen(os.open(tree_file, os.O_WRONLY | os.O_CREAT, 0644), "w")
            json.dump(elems, data_file)
            data_file.close()
        return elems

    def get_blob(self, elem):
        """
        Get blob.
        """
        if self.has_git_object(elem["sha"]):
            pass
        else:
            mode = elem["mode"]
            blob = self.get_elems(elem["url"])
            data = base64.b64decode(blob["content"])

            blob_file = self.get_git_object_file(elem["sha"])
            blob_file_folder = self.get_git_object_folder(elem["sha"])

            if self.debugging:
                print("DEBUG: Getting blob %s" % blob_file)
            else:
                print ".",

            if not os.path.exists(blob_file_folder):
                os.mkdir(blob_file_folder)
            if mode[:2] == "10" or mode[:2] == "12":  # File or symlink
                data_file = os.fdopen(os.open(blob_file, os.O_WRONLY | os.O_CREAT, 0644), "w")
                data_file.write(data)
                data_file.close()
            else:
                raise Exception("Unable to process %s, do not know how to handle mode %s." % (blob_file, mode))

    def find_tree(self, sha, path):
        """
        Find tree.
        """
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
        """
        Getch tree.
        """
        tree = self.get_tree(sha)

        for elem in tree["tree"]:
            if elem["type"] == "tree":
                self.fetch_tree(elem["sha"])
            elif elem["type"] == "blob":
                self.get_blob(elem)
            else:
                raise Exception("Do not know how to handle object type %s for object %s" % (elem["type"], elem["path"]))

    def sync_filesystem(self, sha=None, prefix=None):
        """
        Sync filesystem.
        """
        update_targets = False
        if sha is None:
            sha = self.find_tree(self.shotgun_version, "test/selenium")
            update_targets = True

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
            if os.path.islink(obj):
                print("Removing symlink: %s" % obj)
                os.remove(obj)
            # Do not delete the build folder
            elif os.path.isdir(obj):
                if os.path.join(self.work_folder, "build") != obj:
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
                if not os.path.exists(path):
                    print("creating folder: " + path)
                    os.mkdir(path)
                self.sync_filesystem(sha, path + os.path.sep)
            elif elem["type"] == "blob":
                mode = elem["mode"][:2]
                perm = int(elem["mode"][2:], 8)
                if mode == "10":
                    if os.path.exists(path):
                        stat_info = os.stat(path)
                        file_sha1 = hashlib.sha1("blob " + str(stat_info.st_size) + "\0" + open(path, "rb").read()).hexdigest()
                        if file_sha1 != sha:
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
        if update_targets:
            self.update_targets()

    def generate_config(self, options):
        """
        Generate config.
        """
        config_folder = os.path.join(self.work_folder, "suites", "config")
        if 'sg_config__url' in options and options['sg_config__url'] != self.target_url:
            print "WARNING: overriding option sg_config__url of\n    %s\n  with\n    %s" % (options['sg_config__url'], self.target_url)
        options['sg_config__url'] = self.target_url

        if "sg_config__check_shotgun_version" not in options:
            options["sg_config__check_shotgun_version"] = "true"

        if os.path.exists(config_folder):
            config_file = open(os.path.join(config_folder, "config.xml"), "w")
            config_file.write(
                """<?xml version="1.0" encoding="UTF-8"?>
<testdata>
  <vars
"""
            )
            for key in options.keys():
                config_file.write('    %s="%s"\n' % (key, options[key]))
            config_file.write(
                """  />
</testdata>
"""
            )
            config_file.close()
        else:
            raise UnsupportedBranch("This site does not support Selenium tests")

    def is_valid_suite(self, test_suite):
        """
        Is valid suite?
        """
        return test_suite in self.available_suites

    def execute_suite(self, test_suite):
        """
        Execute suite.
        """
        if self.is_valid_suite(test_suite):
            code = -1
            self.subProc = subprocess.Popen(self.available_suites[test_suite], preexec_fn=os.setsid)
            try:
                code = self.subProc.wait()
            except (KeyboardInterrupt, SystemExit):
                os.killpg(self.subProc.pid, signal.SIGTERM)
            except Exception:
                os.killpg(self.subProc.pid, signal.SIGTERM)
                raise
            return code
        else:
            raise SuiteNotFound("Non existent test suite %s" % test_suite)

    def get_testrail_runs_from_plan(self, test_plan):
        """
        Get TestRail runs from plan.
        """
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

    def is_testrail_plan(self, testrail_plan):
        """
        Is TestRail plan?
        """
        if testrail_plan in self.testrail_plans:
            return True
        elif testrail_plan in self.testrail_runs:
            return False
        else:
            try:
                plan = self.testrail.send_get('get_plan/%s' % testrail_plan)
                if plan['project_id'] == self.testrail_project_id:
                    self.testrail_plans[plan['project_id']] = plan
                    return True
            except Exception:
                pass
            #     raise TestRailPlanInvalid('TestRail plan %s does not exist' % testrail_plan)
            # else:
            #     raise TestRailPlanInvalid('TestRail plan %s does not belong to project Shotgun' % testrail_plan)
        return False

    def is_testrail_run(self, testrail_run):
        """
        Is TestRail run?
        """
        if testrail_run in self.testrail_runs:
            return True
        elif testrail_run in self.testrail_plans:
            return False
        else:
            try:
                run = self.testrail.send_get('get_run/%s' % testrail_run)
                if run['project_id'] == self.testrail_project_id:
                    self.testrail_runs[run["id"]] = run
                    return True
            except Exception:
                pass
            #     raise TestRailRunInvalid('TestRail run %s does not exist' % testrail_run)
            # else:
            #     raise TestRailRunInvalid('TestRail run %s does not belong to project Shotgun' % testrail_run)
        return False

    def execute_run(self, testrail_run, commit=False, run_all=False):
        """
        Execute run.
        """
        results = {"results": []}

        if not self.is_testrail_run(testrail_run):
            raise TestRailRunInvalid('TestRail run %s does not exist' % testrail_run)

        tests = {}

        for test in self.testrail.send_get('get_tests/%s' % testrail_run):
            if test['title'].startswith('[Automation] '):
                if test['case_id'] not in self.available_cases:
                    warning = "WARNING: skipping test: T%s - %s (C%s) as it is not present in this codebase/version" % (
                        test['id'], test['title'], test['case_id']
                    )
                    print warning
                    result = {
                        'case_id': test['case_id'],
                        'status_id': 4,  # 4 = Retest
                        'comment': "from Automation on %s\n%s" % (self.target_url, warning),
                        'custom_os': [SeleniumSandbox.testrail_os[platform.system()]],
                        'custom_webbrowser': [SeleniumSandbox.testrail_browsers['Firefox']],
                        'version': "v%s (build %s)" % (self.target_version_name, self.target_version_hash)
                    }
                    results['results'].append(result)
                else:
                    if run_all or test['status_id'] != 1:
                        tests[test["id"]] = test

        netloc = ""
        if self.target_url:
            netloc = urlparse.urlparse(self.target_url).netloc

        build_folder = os.path.join(
            self.get_work_folder(),
            "build",
            netloc,
            datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss"))
        if not os.path.exists(build_folder):
            os.makedirs(build_folder)

        for test in tests:

            test_suite = self.available_cases[tests[test]['case_id']]
            test_suite = os.path.join(test_suite, self.command_file)

            if os.path.exists(test_suite):
                start_time = time.time()
                stop_time = None
                self.subProc = subprocess.Popen(test_suite, env={"BUILD_FOLDER": build_folder}, preexec_fn=os.setsid)
                code = -1
                try:
                    code = self.subProc.wait()
                    stop_time = time.time()
                except (KeyboardInterrupt, SystemExit):
                    os.killpg(self.subProc.pid, signal.SIGTERM)
                except Exception:
                    os.killpg(self.subProc.pid, signal.SIGTERM)
                    raise
                if code == 0 or code == 1 or code == -1:
                    result = {
                        'case_id': tests[test]['case_id'],
                        'status_id': SeleniumSandbox.testrail_statuses[code],
                        'comment': "from Automation on %s" % self.target_url,
                        'custom_os': [SeleniumSandbox.testrail_os[platform.system()]],
                        'custom_webbrowser': [SeleniumSandbox.testrail_browsers['Firefox']],
                        'version': "v%s (build %s)" % (self.target_version_name, self.target_version_hash)
                    }
                    if code == 0 or code == 1:
                        elapsed = int(stop_time - start_time + 0.5)
                        if elapsed > 0:
                            result['elapsed'] = '%ds' % elapsed
                    if code == -1:
                        result['comment'] += " **Test aborted by user**"
                    results['results'].append(result)
                else:
                    raise Exception("Unexpected return code from Selenium: %d" % code)
            else:
                raise SuiteNotFound("Non existent test suite %s" % test_suite)
        if commit and len(results['results']) > 0:
            self.testrail.send_post('add_results_for_cases/%s' % testrail_run, results)

    def signal_handler(self, sig, frm):
        """
        Signal handler.
        """
        sys.exit(1)


def main(argv):
    """
    Main function.
    """
    parser = OptionParser(usage="usage: %prog [options] url")
    parser.add_option(
        "--git-token",
        help="API key or credentials user:password or token:x-oauth-basic"
    )
    parser.add_option(
        "--testrail-token",
        help="API key or credentials user:password or email:api-key (OPTIONAL)"
    )
    parser.add_option(
        "--testrail-targets",
        help="Comma-separated list of TestRail runs or plans to execute (OPTIONAL, requires --testrail-token)"
    )
    parser.add_option(
        "--testrail-commit", action="store_true", dest="testrail_commit",
        help="Output debugging information"
    )
    parser.add_option(
        "--testrail-run-all", action="store_true", dest="testrail_run_all",
        help="Run all the tests instead of only those that have not passed (OPTIONAL)"
    )
    parser.add_option(
        "--suites",
        help="Comma-separated list of path to Test suites to execute (OPTIONAL)"
    )
    parser.add_option(
        "--work-folder",
        help="Work folder. Will be created if required"
    )
    parser.add_option(
        "--config-options",
        help="Comma separated list of key=value to be added to the config.xml (OPTIONAL)"
    )
    parser.add_option(
        "--config-xml-file",
        help="Base config.xml to use, usually will contain passwords (OPTIONAL)"
    )
    parser.add_option(
        "--no-sync",
        action="store_true",
        dest="no_sync",
        help="The local work folder files will not be synchronized, usually for debugging puroses (OPTIONAL)"
    )
    parser.add_option(
        "--no-fetch",
        action="store_true",
        dest="no_fetch",
        help="The git files are not updated from GitHub, usually for debugging puroses (OPTIONAL)"
    )
    parser.add_option(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        help="Output debugging information"
    )
    (options, args) = parser.parse_args()

    if options.verbose is None:
        options.verbose = False

    if options.no_sync is None:
        options.no_sync = False

    if options.no_fetch is None:
        options.no_fetch = False

    if options.testrail_token is None:
        options.testrail_token = ''

    if options.suites is None:
        options.suites = []
    else:
        options.suites = options.suites.split(',')

    if options.testrail_targets is None:
        options.testrail_targets = []
    else:
        targets = options.testrail_targets.split(',')
        options.testrail_targets = []
        for target in targets:
            if re.match('^[1-9][0-9]*$', target):
                options.testrail_targets.append(int(target))
            else:
                parser.error("Target '%s' invalid. A testrail-targets argument must be a number." % target)

    if options.testrail_commit is None:
        options.testrail_commit = False

    if options.testrail_run_all is None:
        options.testrail_run_all = False

    if options.config_options is None:
        options.config_options = ""

    if options.config_xml_file is None:
        options.config_xml_file = ""

    if (options.suites and options.testrail_targets):
        parser.error("Options --suites and --testrail-targets are mutually exclusive.")

    if options.testrail_targets and not options.testrail_token:
        parser.error("A testrail-targets argument requires a valid TestRail token.")

    if None in vars(options).values():
        parser.error("Missing required option for Shotgun API connection.")

    if len(args) != 1:
        parser.error("incorrect number of arguments")

    if not (args[0].startswith("https://") or args[0].startswith("http://")):
        print "INFO: protocol scheme not indicated, assuming http"
        args[0] = "http://%s" % args[0]

    url = urlparse.urlparse(args[0])
    if url.netloc == "":
        parser.error("need to specify a Shotgun site URL")

    shotgun_url = "%s://%s" % (url.scheme, url.netloc)

    if options.testrail_token:
        print "INFO: Connecting to GitHub and TestRail"
    else:
        print "INFO: Connecting to GitHub"
    sandbox = SeleniumSandbox(options.git_token, options.testrail_token, options.verbose)
    signal.signal(signal.SIGINT, sandbox.signal_handler)
    signal.signal(signal.SIGTERM, sandbox.signal_handler)
    print "INFO:     Connected to GitHub as user %s" % sandbox.get_github_user()
    if options.testrail_token:
        print "INFO:     Connected to TestRail as user %s" % sandbox.get_testrail_user()

    for target in options.testrail_targets:
        if not (sandbox.is_testrail_run(target) or sandbox.is_testrail_plan(target)):
            parser.error("ERROR: Invalid TestRail run or plan: %s" % target)

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

    if options.no_fetch:
        print("INFO: not fetching files from repo")
        sandbox.get_target_version(shotgun_url)
    else:
        print("INFO: Getting Shotgun files from repo for site  %s ... Please wait" % shotgun_url)
        sandbox.fetch_shotgun_files(shotgun_url)
        print("INFO:     Found version to be %s (%s)" % (sandbox.target_version_name, sandbox.target_version_hash))
        print("INFO:     Done getting files")

    if options.no_sync:
        print("INFO: Local work folder files will not be updated.")
        sandbox.update_targets()
    else:
        print("INFO: Synchronizing filesystem with git files")
        sandbox.sync_filesystem()
        print("INFO:     Done synchronizing")

    for suite in options.suites:
        if not (sandbox.is_valid_suite(suite)):
            parser.error("ERROR: Invalid test suite: %s" % suite)

    try:
        if options.suites or options.testrail_targets:
            print("INFO: Generating config.xml")
            run_options = {}
            try:
                if os.path.exists(options.config_xml_file):
                    print("INFO: Injecting base configuration from %s" % options.config_xml_file)
                    import xml.etree.ElementTree
                    root = xml.etree.ElementTree.parse(options.config_xml_file).getroot()
                    vars_sections = root.findall('vars')
                    for vars_section in vars_sections:
                        for k, v in vars_section.attrib.iteritems():
                            print("INFO:     Adding config options %s=%s to run config" % (k, v))
                            run_options[k] = v

                else:
                    print("WARNING: no default config.xml file set, or non-existing file (%s)" % options.config_xml_file)

            except xml.etree.ElementTree.ParseError as e:
                print("ERROR: %s is not an xml file: %s" % (options.config_xml_file, e))

            if len(options.config_options) > 0 and '=' in options.config_options:
                for kv in options.config_options.split(","):
                    (k, v) = kv.split("=")
                    run_options[k] = v
                    if options.verbose:
                        print("INFO:     Adding config options %s=%s to run config" % (k, v))
            sandbox.generate_config(run_options)

        if options.suites:
            for suite in options.suites:
                print("INFO:")
                print("INFO: Running tests from %s" % suite)
                sandbox.execute_suite(suite)
            print("INFO:     Test completed")
        elif options.testrail_targets:
            if options.testrail_run_all:
                print("WARNING: Executing all of the tests regardless of their prior results")
            else:
                print("WARNING: Executing only tests that have not been successful")
            for target in options.testrail_targets:
                print("INFO:")
                runs = []
                if sandbox.is_testrail_plan(target):
                    runs = sandbox.get_testrail_runs_from_plan(target)
                    print("INFO: Using TestRail test plan: R%s - %s" % (target, sandbox.testrail_plans[target]['name']))
                elif sandbox.is_testrail_run(target):
                    plan_id = sandbox.testrail_runs[target]["plan_id"]
                    if plan_id:
                        print("INFO: Using test run from TestRail test plan: R%s - %s" % (plan_id, sandbox.testrail_plans[plan_id]['name']))
                    runs = [target]

                for run in runs:
                    print("INFO: Using TestRail test run: R%s - %s" % (run, sandbox.testrail_runs[run]['name']))
                    sandbox.execute_run(run, options.testrail_commit, options.testrail_run_all)
            print("INFO:     Testing completed")
            if options.testrail_targets and not options.testrail_commit:
                print("WARNING: results have not been committed to TestRail")
        else:
            # Not tests were run, which is okay
            pass
    except UnsupportedBranch:
        print("ERROR: This Shotgun site does not support Selenium automation!")
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
