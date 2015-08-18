#!/Applications/Shotgun.app/Contents/Frameworks/Python/bin/python

import copy
import fnmatch
import os
import platform
import re
import signal
import subprocess
import sys

import PySide
from PySide.QtCore import *
from PySide.QtGui import *

from runTestsGUI import *
from prefsGUI import *

import SeleniumSandbox
import appPrefs


__version__ = "1.0"

def locateFiles(pattern, root=os.curdir):
    '''Locate all files matching supplied filename pattern in and below
    supplied root directory.'''
    for path, dirs, files in os.walk(os.path.abspath(root)):
        for filename in fnmatch.filter(files, pattern):
            yield os.path.join(path, filename)

class MyPrefsGUI(QtGui.QDialog):
    def __init__(self, prefs):
        super(MyPrefsGUI, self).__init__()
        self.prefs = prefs
        self.dialog = Ui_Dialog()
        self.dialog.setupUi(self)
        self.dialog.browseButton.clicked.connect(self.browseDialog)
        self.get_prefs()

    def get_prefs(self):
        self.dialog.githubApiKeyEdit.setText(self.prefs.get_pref("github_api_key"))

        self.dialog.emailAddressEdit.setText(self.prefs.get_pref("testrail_email_address"))
        self.dialog.testrailApiKeyEdit.setText(self.prefs.get_pref("testrail_api_key"))

        work_folder = self.prefs.get_pref("work_folder") or os.path.expanduser("~/sg_automation")
        self.dialog.workFolderEdit.setText(work_folder)
        seen = set()
        web_sites = self.prefs.get_pref("web_sites") or [u"https://6-3-develop.shotgunstudio.com"]
        web_sites = [i for i in map(unicode.strip, web_sites)  if not (i in seen or seen.add(i))]
        self.dialog.sitesList.setText("\n".join(item for item in web_sites))

    def set_prefs(self):
        self.prefs.set_pref("github_api_key", self.dialog.githubApiKeyEdit.text())

        self.prefs.set_pref("testrail_email_address", self.dialog.emailAddressEdit.text())
        self.prefs.set_pref("testrail_api_key", self.dialog.testrailApiKeyEdit.text())

        work_folder = self.dialog.workFolderEdit.text()
        if not os.path.exists(work_folder):
            os.makedirs(work_folder)
        self.prefs.set_pref("work_folder", work_folder)
        lines = self.dialog.sitesList.toPlainText().split("\n")
        web_sites = []
        for line in lines:
            line = line.strip()
            if len(line) > 0 and line not in web_sites:
                web_sites.append(line)
        self.prefs.set_pref("web_sites", web_sites)

    def browseDialog(self):
        start_folder = self.dialog.workFolderEdit.text() or os.path.expanduser("~/.")
        folder = QtGui.QFileDialog.getExistingDirectory(self, "Select the local folder where files will be downloaded", start_folder)
        if folder:
            self.dialog.workFolderEdit.setText(folder)


class MyMainGUI(QtGui.QMainWindow):
    def __init__(self, prefs):
        super(MyMainGUI, self).__init__()
        self.prefs = prefs
        self.overwrite_last_line = True
        self.currentLocation = os.path.dirname(os.path.realpath(__file__))

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        # self.aboutButton.clicked.connect(self.about)
        self.ui.runTestsButton.clicked.connect(self.runTests)
        self.ui.stopTestsButton.clicked.connect(self.stopTests)

        # QProcess object for external app
        self.process = QtCore.QProcess(self)

        # QProcess emits `readyRead` when there is data to be read
        self.process.readyRead.connect(self.dataReady)
        self.process.readyReadStandardError.connect(self.dataReadyErr)

        # Menu setup
        self.aboutAction = QtGui.QAction("&About", self, triggered=self.about)
        # self.preferencesAction = QtGui.QAction("&Preferences", self, triggered=self.prefsDialog)
        self.preferencesAction = QtGui.QAction("&Preferences", self)
        self.preferencesAction.triggered.connect(self.updatePrefs)

        self.helpMenu = self.menuBar().addMenu("")
        self.helpMenu.addAction(self.aboutAction)
        self.helpMenu.addSeparator()
        self.helpMenu.addAction(self.preferencesAction)

        # Just to prevent accidentally running multiple times
        # Disable the button when process starts, and enable it when it finishes
        self.process.started.connect(lambda: self.preferencesAction.setEnabled(False))
        self.process.started.connect(lambda: self.ui.siteList.setEnabled(False))
        self.process.started.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.process.started.connect(lambda: self.ui.stopTestsButton.setEnabled(True))

        self.process.finished.connect(lambda: self.preferencesAction.setEnabled(True))
        self.process.finished.connect(lambda: self.ui.siteList.setEnabled(True))
        self.process.finished.connect(lambda: self.ui.runTestsButton.setEnabled(True))
        self.process.finished.connect(lambda: self.ui.stopTestsButton.setEnabled(False))

        self.process.finished.connect(lambda: self.consoleOutput("%s" % "<font color=\"green\">Completed</font>\n" if self.process.exitCode() == 0 else "<font color=\"red\">Failed !</font>\n"))
        self.process.finished.connect(self.updateTestSuitesTargetList)
        self.process.finished.connect(self.updateTestRailTargetList)

        # Ensure that we control the opening of links in the text browswer
        self.ui.runOutput.anchorClicked.connect(self.openLinks)

        self.ui.siteList.lineEdit().setPlaceholderText('Please enter the URL here')
        self.ui.siteList.activated.connect(lambda: self.ui.testSuitesTargetList.setEnabled(False))
        self.ui.siteList.activated.connect(lambda: self.ui.testRailTargetList.setEnabled(False))
        self.ui.siteList.activated.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.ui.siteList.currentIndexChanged.connect(self.validateURL)
        self.ui.siteList.editTextChanged.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.ui.siteList.editTextChanged.connect(lambda: self.ui.testSuitesTargetList.setEnabled(False))
        self.ui.siteList.editTextChanged.connect(lambda: self.ui.testRailTargetList.setEnabled(False))


    def __del__(self):
        if self.process.state() is QtCore.QProcess.ProcessState.Running:
            self.process.terminate()
            self.process.waitForFinished()

    def validateURL(self, idx):
        self.ui.siteList.blockSignals(True)
        if idx != -1:
            url = self.ui.siteList.itemText(idx).strip()
            altIdx = self.ui.siteList.findText(url)
            if idx != altIdx and altIdx != -1:
                self.ui.siteList.removeItem(idx)
                self.ui.siteList.setCurrentIndex(altIdx)
            else:
                self.ui.siteList.setItemText(idx, url)
                web_sites = self.prefs.get_pref("web_sites")
                if url not in web_sites:
                    web_sites.append(url)
                    self.prefs.set_pref("web_sites", web_sites)
                self.getFiles()
        self.ui.siteList.blockSignals(False)

    def validatePrefs(self, use_testrail=True):
        return_value = ""
        try:
            git_creds = "%s:x-oauth-basic" % self.prefs.get_pref("github_api_key")

            testrail_creds = None
            if use_testrail and self.prefs.get_pref("testrail_email_address") and self.prefs.get_pref("testrail_api_key"):
                testrail_creds = "%s:%s" % (
                    self.prefs.get_pref("testrail_email_address"),
                    self.prefs.get_pref("testrail_api_key"),
                )
            self.sandbox = SeleniumSandbox.SeleniumSandbox(
                git_token=git_creds,
                testrail_token=testrail_creds
            )
            self.sandbox.set_work_folder(self.prefs.get_pref("work_folder"))
            github_user = self.sandbox.get_github_user()
            message = 'Logged to GitHub as user %s' % github_user
            if self.sandbox.is_using_testrail():
                message += ' - Logged to TestRail as user %s' % self.sandbox.get_testrail_user()
                self.ui.tabTestModes.setTabEnabled(1, True)
            else:
                self.ui.tabTestModes.setTabEnabled(1, False)
            message += ' - Working out of folder %s' %self.sandbox.get_work_folder()
            self.consoleOutput(message + "\n")
            self.ui.statusbar.showMessage(message)
            seen = set()
            web_sites = [i for i in map(unicode.strip, self.prefs.get_pref("web_sites")) if not (i in seen or seen.add(i))]
            currentURL = self.ui.siteList.currentText()
            if currentURL in web_sites:
                self.ui.siteList.blockSignals(True)
            self.ui.siteList.clear()
            self.ui.siteList.addItems(web_sites)
            if currentURL in web_sites:
                self.ui.siteList.blockSignals(False)

            if self.ui.siteList.count() > 0 and len(self.ui.siteList.currentText()) > 0:
                idx = self.ui.siteList.findText(currentURL)
                if idx != -1:
                    self.ui.siteList.setCurrentIndex(idx)
        except SeleniumSandbox.GitHubError as e:
            self.consoleOutput("Error: %s" % e)
            return_value = "Unable to login to GitHub. Please enter valid GitHub credentials\n"
        except SeleniumSandbox.WorkFolderDoesNotExists as e:
            self.consoleOutput("Error: %s\n" % e)
            return_value = "Please enter an existing folder as work folder\n"
        except SeleniumSandbox.TestRailServerNotFound as e:
            self.consoleOutput("Error: %s\n" % e)
            return_value = "TestRail server not found. Disabling TestRail functionalities\n"
            self.consoleOutput(return_value)
            return self.validatePrefs(False)
        except SeleniumSandbox.TestRailInvalidCredentials as e:
            self.consoleOutput("Error: %s\n" % e)
            return_value = "Please enter valid TestRail credentials or leave blank\n"

        if return_value:
            self.consoleOutput(return_value)
            self.ui.statusbar.showMessage(return_value)
        return return_value

    def prefsDialog(self):
        return_code = None
        dialog = MyPrefsGUI(self.prefs)
        if dialog.exec_():
            dialog.set_prefs()
            return_code = self.validatePrefs()
            if return_code is not None and len(return_code) == 0:
                self.prefs.save_prefs()
        return return_code

    def updatePrefs(self):
        old_prefs = copy.deepcopy(self.prefs)
        while True:
            message = self.prefsDialog()
            if message is None or len(message) == 0:
                break
        if message is None:
            self.prefs = old_prefs
            self.validatePrefs()
        else:
            self.updateTestSuitesTargetList()
            self.updateTestRailTargetList()

    _patternClearLine = re.compile("\x1B\[2K")
    _patternGreen = re.compile("\x1B\[01;32m(.*)\x1B\[00m")
    _patternRed = re.compile("\x1B\[01;31m(.*)\x1B\[00m")
    _patternHttp = re.compile(r"\s(https?:/(/\S+)+)")
    _patternFileReport = re.compile(r"You can consult the build report: (/\S+)/report.html")
    _patternFailed = re.compile(r"(.*/test_rail/.*/C([0-9]+) failed)")

    def consoleOutput(self, text, color=None):
        # Doing some filtering and markup
        # text = text.replace(" ", u"\u00A0")
        text = self._patternClearLine.sub("", text)
        text = self._patternHttp.sub(r'<a href="\1">\1</a>', text)
        text = self._patternGreen.sub(r'<font color="green">\1</font>', text)
        text = self._patternRed.sub(r'<font color="red">\1</font>', text)

        cursor = self.ui.runOutput.textCursor()
        cursor.movePosition(cursor.End)
        if self.overwrite_last_line:
            cursor.movePosition(cursor.StartOfLine, QTextCursor.KeepAnchor)
            self.overwrite_last_line = False
        if text[-1] == '\r':
            self.overwrite_last_line = True
        if color is not None:
            text = '<font color="%s">%s</font>' % (color, text)
        # Patch to add link to TestRails
        result = self._patternFailed.search(text)
        if result:
            url = "http://meqa.autodesk.com/index.php?/cases/view/%s" % result.group(2)
            message = '<font color="red">The TestRail case can seen here: <a href="%s">%s</a></font>' % (url, url)
            text = self._patternFailed.sub(r'\1\n%s' % message, text)
        result = self._patternFileReport.search(text)
        if result:
            shortName = result.group(1).replace(self.currentLocation + "/", "")
            message = '<font color="red">The failure report can seen here: <a href="file:/%s/report.html">%s</a></font>' % (result.group(1), shortName)
            text = self._patternFileReport.sub(message, text)
        cursor.insertHtml(text.replace('\n', '<br>'))
        self.ui.runOutput.ensureCursorVisible()
        cursor.movePosition(cursor.End)

    def dataReady(self):
        data = unicode(self.process.readAll(), "UTF8")
        self.consoleOutput(data)

    def dataReadyErr(self):
        self.consoleOutput(str(self.process.readAllStandardError()), "red")

    def runTests(self):
        current_tab_index = self.ui.tabTestModes.currentIndex()
        args = [
            "--git-token", "%s:x-oauth-basic" % self.prefs.get_pref("github_api_key"),
            "--work-folder", self.prefs.get_pref("work_folder"),
            self.ui.siteList.currentText()
        ]

        if current_tab_index == 0:
            args += [
                "--suites", self.ui.testSuitesTargetList.currentText()
            ]
        elif current_tab_index == 1:
            run_id = self.ui.testRailTargetList.itemData(self.ui.testRailTargetList.currentIndex())
            testrail_commit = self.ui.checkCommitResults.isChecked()
            testrail_run_all = self.ui.checkRunAllTests.isChecked()
            args += [
                "--testrail-token", "%s:%s" %(self.prefs.get_pref("testrail_email_address"), self.prefs.get_pref("testrail_api_key")),
                "--testrail-targets", "%d" % run_id
            ]
            if testrail_commit:
                args.append("--testrail-commit")
            if testrail_run_all:
                args.append("--testrail-run-all")
        else:
            raise Exception("Unexpect Tab Index for tabTestModes")
        # "--config-options", "sg_config__timeout=30000",
        self.process.start(os.path.join(self.currentLocation, "SeleniumSandbox.py"), args)

    def openLinks(self, url):
        QDesktopServices.openUrl(url)


    def stopTests(self):
        self.process.terminate()
        self.process.waitForFinished()

    def getFiles(self):
        self.process.start(os.path.join(self.currentLocation, "SeleniumSandbox.py"), [
            "--git-token", "%s:x-oauth-basic" % self.prefs.get_pref("github_api_key"),
            "--work-folder", self.prefs.get_pref("work_folder"),
            # "--verbose",
            self.ui.siteList.currentText()
            ])

    def updateTestRailTargetList(self):
        testrail_tests = {}
        currentSelection = self.ui.testRailTargetList.currentText()

        for plan_id, plan in self.sandbox.testrail_plans.iteritems():
            testrail_tests["%s - %d" % (plan["name"], plan_id)] = plan_id

        for run_id, run in self.sandbox.testrail_runs.iteritems():
            testrail_tests["%s - %d" % (run["name"], run_id)] = run_id

        keys = testrail_tests.keys()
        keys.sort()

        self.ui.testRailTargetList.clear()
        for key in keys:
            self.ui.testRailTargetList.addItem(key, testrail_tests[key])

        if self.ui.testRailTargetList.count() > 0:
            self.ui.testRailTargetList.setEnabled(True)
            self.ui.testRailTargetList.setEnabled(True)
            idx = self.ui.testRailTargetList.findText(currentSelection)
            if idx != -1:
                self.ui.testRailTargetList.setCurrentIndex(idx)

    def updateTestSuitesTargetList(self):
        workfolderLocation = os.path.join(self.currentLocation, self.prefs.get_pref("work_folder"))
        fileList = locateFiles('runTest.command', workfolderLocation)
        suiteList = []
        currentSelection = self.ui.testSuitesTargetList.currentText()
        suitePattern = re.compile("%s/(suites.*)/runTest.command" % workfolderLocation)
        for filename in fileList:
            suiteList.append(suitePattern.sub(r'\1', filename))

        self.ui.testSuitesTargetList.clear()
        self.ui.testSuitesTargetList.addItems(suiteList)
        if self.ui.testSuitesTargetList.count() > 0:
            self.ui.testSuitesTargetList.setEnabled(True)
            self.ui.testSuitesTargetList.setEnabled(True)
            idx = self.ui.testSuitesTargetList.findText(currentSelection)
            if idx != -1:
                self.ui.testSuitesTargetList.setCurrentIndex(idx)

    def show(self):
        super(MyMainGUI, self).show()

        # Ensure that there are valid settings in place before we proceed
        message = self.validatePrefs()
        while True:
            if len(message) > 0:
                message = self.prefsDialog()
                if message is None:
                    self.close()
                    QtCore.QCoreApplication.instance().quit()
                    sys.exit(2)
                    break
            else:
                break

    def about(self):
        '''Popup a box with about message.'''
        QMessageBox.about(self, "About ",
        """\
        <p>SG_Automation {}\
        <p>Sandbox {}\
        <p>Python {}\
        <p>PySide version {}\
        <p>Qt version {} on {}""".format(
            __version__,
            self.sandbox.__version__,
            platform.python_version(),
            PySide.__version__,
            PySide.QtCore.__version__,
            platform.system()))

def main():
    currentLocation = os.path.dirname(os.path.realpath(__file__))
    prefs = appPrefs.AppPrefs(os.path.expanduser("~/.sg_automation.json"))
    app = QtGui.QApplication(sys.argv)
    app.setStyle("plastique")
    # with open(os.path.join(currentLocation, "darkorange.stylesheet"), "r") as f:
    #     read_data = f.read()
    #     app.setStyleSheet(read_data)
    ui = MyMainGUI(prefs)
    ui.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

# TODO LIST:
# @TODO: fix size of output to be bigger, and the tab section smaller
# @TODO: ensure that the width of the dropdown is the same in both tabs
# @TODO: prevent update of files if not required.
# @TODO: ensure that the stop tests button works
