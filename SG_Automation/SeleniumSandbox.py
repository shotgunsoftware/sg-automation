#!/usr/bin/env python -u

import base64
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import urllib2
import urlparse

from optparse import OptionParser
from pprint import pprint as pp

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
    def __init__(self, git_token, debugging=False):
        self.command_file = "runTest.command"
        self.git_token = git_token
        self.debugging = debugging
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

    def fetch_shotgun_files(self, shotgun_version):
        self.shotgun_version = self.get_tree(shotgun_version)["sha"]
        head_file = open(self.git_folder + os.path.sep + "HEAD", "w")
        head_file.write("%s\n" % self.shotgun_version)
        head_file.close()

        self.selenium_version = self.find_tree(self.shotgun_version, "test/selenium")
        self.fetch_tree(self.selenium_version)

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
            if os.path.isdir(obj):
                print("Removing folder: %s" % obj)
                shutil.rmtree(obj)
            else:
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
                        statInfo = os.stat(path)
                        fileSha1 = hashlib.sha1("blob " + str(statInfo.st_size) + "\0" + open(path, "rb").read()).hexdigest()
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


    def run_tests(self, test_suite):
        if not test_suite.endswith(self.command_file):
            test_suite = os.path.join(test_suite, self.command_file)
        if not test_suite.startswith(self.work_folder):
            test_suite = os.path.join(self.work_folder, test_suite)

        if os.path.exists(test_suite):
            self.subProc = subprocess.Popen(test_suite)
            code = -1
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


    def signal_handler(self, sig, frm):
        sys.exit(1)


def main(argv):
    parser = OptionParser(usage="usage: %prog [options] url")
    parser.add_option("-t", "--git-token",
        help="API key or credentials user:password or token::x-oauth-basic")
    parser.add_option("-w", "--work-folder",
        help="Work folder. Will be created if required")
    parser.add_option("-s", "--suite",
        help="Test suite to run")
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose",
        help="Output debugging information")
    parser.add_option("-c", "--config-options",
        help="Comma separated list of key=value to be added to the config.xml")
    (options, args) = parser.parse_args()

    if options.verbose is None:
        options.verbose = False

    if options.suite is None:
        options.suite = False

    if options.config_options is None:
        options.config_options = ""

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

    print "INFO: Connecting to GitHub"
    sandbox = SeleniumSandbox(options.git_token, options.verbose)
    signal.signal(signal.SIGINT, sandbox.signal_handler)
    print "INFO:     Connected as user %s" % sandbox.user["login"]

    print "INFO: Setting work folder to %s" % options.work_folder
    if not os.path.exists(options.work_folder):
        print "INFO:    Creating work folder %s" % options.work_folder
        os.makedirs(options.work_folder)
    sandbox.set_work_folder(options.work_folder)

    print("INFO: Getting version of site %s" % shotgun_url)
    (version_name, version_hash) = get_site_version(shotgun_url)
    print("INFO:     Found version to be %s" % version_hash)

    print("INFO: Getting Shotgun files from repo")
    sandbox.fetch_shotgun_files(version_hash)
    print("INFO:     Done getting files")

    print("INFO: Synchronizing filesystem with git files")
    sandbox.sync_filesystem()
    print("INFO:     Done synchronizing")

    print("INFO: Generating config.xml")
    run_options = {
        "sg_config__url": shotgun_url,
        "sg_config__check_shotgun_version": "true"
    }
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
            return_value = sandbox.run_tests(options.suite)
            print("INFO:     Test completed")
    except UnsupportedBranch as e:
        print("ERROR: This Shotgun site does not support Selenium automation!")
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
