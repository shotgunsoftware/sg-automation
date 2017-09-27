#!/Applications/Shotgun.app/Contents/Frameworks/Python/bin/python
"""
Main module for SG Automation application.
"""
import copy
import fnmatch
import os
import platform
import re
import sys

import PySide
from PySide import QtGui, QtCore

from runTestsGUI import Ui_MainWindow
from prefsGUI import Ui_Dialog

import SeleniumSandbox
import appPrefs


__version__ = "1.8"


def locate_files(pattern, root=os.curdir):
    """
    Locate all files matching supplied filename pattern in and below supplied root directory.
    """
    for path, dirs, files in os.walk(os.path.abspath(root)):
        for filename in fnmatch.filter(files, pattern):
            yield os.path.join(path, filename)


class MyPrefsGUI(QtGui.QDialog):
    """
    UI preferences for the application.
    """

    def __init__(self, prefs):
        """
        Constructor.
        """
        super(MyPrefsGUI, self).__init__()
        self.prefs = prefs
        self.dialog = Ui_Dialog()
        self.dialog.setupUi(self)
        self.dialog.browseWorkFolderButton.clicked.connect(self.browse_work_folder_dialog)
        self.dialog.browseConfigFileButton.clicked.connect(self.browse_config_xml_dialog)
        self.get_prefs()

    def get_prefs(self):
        """
        Get user preferences.
        """
        self.dialog.githubApiKeyEdit.setText(self.prefs.get_pref("github_api_key"))

        self.dialog.emailAddressEdit.setText(self.prefs.get_pref("testrail_email_address"))
        self.dialog.testrailApiKeyEdit.setText(self.prefs.get_pref("testrail_api_key"))

        work_folder = self.prefs.get_pref("work_folder") or os.path.expanduser("~/sg_automation")
        self.dialog.workFolderEdit.setText(work_folder)
        config_xml_file = self.prefs.get_pref("config_xml_file") or os.path.expanduser("~/sg_automation.config.xml")
        self.dialog.configFileEdit.setText(config_xml_file)
        seen = set()
        web_sites = self.prefs.get_pref("web_sites") or [u"https://6-3-develop.shotgunstudio.com"]
        web_sites = [i for i in map(unicode.strip, web_sites) if not (i in seen or seen.add(i))]
        self.dialog.sitesList.setText("\n".join(item for item in web_sites))

    def set_prefs(self):
        """
        Set user preferences.
        """
        self.prefs.set_pref("github_api_key", self.dialog.githubApiKeyEdit.text())

        self.prefs.set_pref("testrail_email_address", self.dialog.emailAddressEdit.text())
        self.prefs.set_pref("testrail_api_key", self.dialog.testrailApiKeyEdit.text())

        work_folder = self.dialog.workFolderEdit.text()
        if not os.path.exists(work_folder):
            os.makedirs(work_folder)
        self.prefs.set_pref("work_folder", work_folder)

        config_xml_file = self.dialog.configFileEdit.text()
        self.prefs.set_pref("config_xml_file", config_xml_file)

        lines = self.dialog.sitesList.toPlainText().split("\n")
        web_sites = []
        for line in lines:
            line = line.strip()
            if len(line) > 0 and line not in web_sites:
                web_sites.append(line)
        self.prefs.set_pref("web_sites", web_sites)

    def browse_work_folder_dialog(self):
        """
        Browse to the work folder.
        """
        start_folder = self.dialog.workFolderEdit.text() or os.path.expanduser("~/.")
        folder = QtGui.QFileDialog.getExistingDirectory(self, "Select the local folder where files will be downloaded", start_folder)
        if folder:
            self.dialog.workFolderEdit.setText(folder)

    def browse_config_xml_dialog(self):
        """
        Browse to the work folder.
        """
        config_xml_file = self.dialog.workFolderEdit.text()
        start_folder = os.path.dirname(config_xml_file) or os.path.expanduser("~/.")
        (config_xml_file, file_filter) = QtGui.QFileDialog.getOpenFileName(self, "Select the config.default.xml file", start_folder, "Any Files (.* *)")
        print config_xml_file
        if config_xml_file:
            self.dialog.configFileEdit.setText(config_xml_file)


class MyMainGUI(QtGui.QMainWindow):
    """
    Main GUI for the application.
    """

    def __init__(self, prefs):
        """
        Constructor.
        """
        super(MyMainGUI, self).__init__()
        self.prefs = prefs
        self.overwrite_last_line = True
        self.currentLocation = os.path.dirname(os.path.realpath(__file__))

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.ui.runTestsButton.clicked.connect(self.run_tests)
        self.ui.stopTestsButton.clicked.connect(self.stop_tests)
        self.ui.clearLogButton.clicked.connect(lambda: self.ui.runOutput.clear())

        # QProcess object for external app
        self.process = QtCore.QProcess(self)

        # QProcess emits `readyRead` when there is data to be read
        self.process.readyRead.connect(self.data_ready)
        self.process.readyReadStandardError.connect(self.data_ready_err)

        # Menu setup
        self.aboutAction = QtGui.QAction("&About", self, triggered=self.about)
        self.preferencesAction = QtGui.QAction("&Preferences", self)
        self.preferencesAction.triggered.connect(self.update_prefs)

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

        self.process.finished.connect(lambda: self.console_output("%s" % "<font color=\"green\">Completed</font>\n" if self.process.exitCode() == 0 else "<font color=\"red\">Failed !</font>\n"))
        self.process.finished.connect(self.update_test_suites_target_list)
        self.process.finished.connect(self.update_test_rail_target_list)

        # Ensure that we control the opening of links in the text browswer
        self.ui.runOutput.anchorClicked.connect(self.open_links)

        self.ui.siteList.lineEdit().setPlaceholderText('Please enter the URL here')
        self.ui.siteList.activated.connect(lambda: self.ui.testSuitesTargetList.setEnabled(False))
        self.ui.siteList.activated.connect(lambda: self.ui.testRailTargetList.setEnabled(False))
        self.ui.siteList.activated.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.ui.siteList.currentIndexChanged.connect(self.validate_url)
        self.ui.siteList.editTextChanged.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.ui.siteList.editTextChanged.connect(lambda: self.ui.testSuitesTargetList.setEnabled(False))
        self.ui.siteList.editTextChanged.connect(lambda: self.ui.testRailTargetList.setEnabled(False))

    def __del__(self):
        """
        Destructor.
        """
        if self.process.state() is QtCore.QProcess.ProcessState.Running:
            self.process.terminate()
            self.process.waitForFinished()

    def validate_url(self, idx):
        """
        Validate the Shotgun URL.
        """
        self.ui.siteList.blockSignals(True)
        if idx != -1:
            url = self.ui.siteList.itemText(idx).strip()
            alt_idx = self.ui.siteList.findText(url)
            if idx != alt_idx and alt_idx != -1:
                self.ui.siteList.removeItem(idx)
                self.ui.siteList.setCurrentIndex(alt_idx)
            else:
                self.ui.siteList.setItemText(idx, url)
                web_sites = self.prefs.get_pref("web_sites")
                if url not in web_sites:
                    web_sites.append(url)
                    self.prefs.set_pref("web_sites", web_sites)
                self.get_files()
        self.ui.siteList.blockSignals(False)

    def validate_prefs(self, use_testrail=True):
        """
        Validate the user preferences.
        """
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
            message += ' - Working out of folder %s' % self.sandbox.get_work_folder()
            self.console_output(message + "\n")
            self.ui.statusbar.showMessage(message)
            seen = set()
            web_sites = [i for i in map(unicode.strip, self.prefs.get_pref("web_sites")) if not (i in seen or seen.add(i))]
            current_url = self.ui.siteList.currentText()
            if current_url in web_sites:
                self.ui.siteList.blockSignals(True)
            self.ui.siteList.clear()
            self.ui.siteList.addItems(web_sites)
            if current_url in web_sites:
                self.ui.siteList.blockSignals(False)

            if self.ui.siteList.count() > 0 and len(self.ui.siteList.currentText()) > 0:
                idx = self.ui.siteList.findText(current_url)
                if idx != -1:
                    self.ui.siteList.setCurrentIndex(idx)
        except SeleniumSandbox.GitHubError as e:
            self.console_output_error("Error: %s" % e)
            return_value = "Unable to login to GitHub. Please enter valid GitHub credentials\n"
        except SeleniumSandbox.WorkFolderDoesNotExists as e:
            self.console_output_error("Error: %s\n" % e)
            return_value = "Please enter an existing folder as work folder\n"
        except SeleniumSandbox.TestRailServerNotFound as e:
            self.console_output_error("Error: %s\n" % e)
            return_value = "TestRail server not found. Disabling TestRail functionalities\n"
            self.console_output_warning(return_value)
            return self.validate_prefs(False)
        except SeleniumSandbox.TestRailInvalidCredentials as e:
            self.console_output_error("Error: %s\n" % e)
            return_value = "Please enter valid TestRail credentials or leave blank\n"
        except SeleniumSandbox.TestRailInternalServerError as e:
            self.console_output_error("Error: %s\n" % e)
            return_value = "TestRail server not available. Disabling TestRail functionalities\n"
            self.console_output_warning(return_value)
            return self.validate_prefs(False)
        except SeleniumSandbox.TestRailError as e:
            self.console_output_error("Error: %s\n" % e)
            return_value = "TestRail server not available. Disabling TestRail functionalities\n"
            self.console_output_warning(return_value)
            return self.validate_prefs(False)

        if return_value:
            self.console_output(return_value)
            self.ui.statusbar.showMessage(return_value)
        return return_value

    def prefs_dialog(self):
        """
        Starts the Preferences dialog.
        """
        return_code = None
        dialog = MyPrefsGUI(self.prefs)
        if dialog.exec_():
            dialog.set_prefs()
            return_code = self.validate_prefs()
            if return_code is not None and len(return_code) == 0:
                self.prefs.save_prefs()
        return return_code

    def update_prefs(self):
        """
        Update the user Preferences.
        """
        old_prefs = copy.deepcopy(self.prefs)
        while True:
            message = self.prefs_dialog()
            if message is None or len(message) == 0:
                break
        if message is None:
            self.prefs = old_prefs
            self.validate_prefs()
        else:
            self.update_test_suites_target_list()
            self.update_test_rail_target_list()

    _patternClearLine = re.compile("\x1B\[2K")
    _patternGreen = re.compile("\x1B\[01;32m(.*)\x1B\[00m")
    _patternRed = re.compile("\x1B\[01;31m(.*)\x1B\[00m")
    _patternHttp = re.compile(r"\s(https?:/(/\S+)+)")
    _patternWarning = re.compile("(WARNING: .*)\n")
    _patternFileReport = re.compile(r"You can consult the build report: (/\S+)/(\S+report.html)")
    _patternFailed = re.compile(r"(.* test )(/.*/test_rail/.*/)C([0-9]+)( failed)")
    _patternTest = re.compile(r"(test: )T([0-9]+) ")
    _patternTestCase = re.compile(r"C([0-9]+)")
    _patternTestRun = re.compile(r"(test run: )R([0-9]+) ")
    _patternTestplan = re.compile(r"(test plan: )R([0-9]+) ")

    def console_output_error(self, text):
        """
        Outputs messages in red.
        """
        self.console_output(text, "red")

    def console_output_warning(self, text):
        """
        Outputs messages in orange.
        """
        self.console_output(text, "orange")

    def console_output(self, text, color=None):
        """
        Outputs messages to the text console.
        """
        # Doing some filtering and markup
        text = self._patternClearLine.sub("", text)
        text = self._patternHttp.sub(r'<a href="\1">\1</a>', text)
        text = self._patternGreen.sub(r'<font color="green">\1</font>', text)
        text = self._patternRed.sub(r'<font color="red">\1</font>', text)
        text = self._patternWarning.sub(r'<font color="orange">\1</font>\n', text)
        while '  ' in text:
            text = text.replace("  ", u"\u00A0\u00A0")

        cursor = self.ui.runOutput.textCursor()
        cursor.movePosition(cursor.End)
        if self.overwrite_last_line:
            cursor.movePosition(cursor.StartOfLine, QtGui.QTextCursor.KeepAnchor)
            self.overwrite_last_line = False
        if text[-1] == '\r':
            self.overwrite_last_line = True
        if color is not None:
            text = '<font color="%s">%s</font>' % (color, text)

        result = self._patternTestRun.search(text)
        if result:
            url = "https://meqa.autodesk.com/index.php?/runs/view/%s" % result.group(2)
            message = '<a href="%s">R%s</a>' % (url, result.group(2))
            text = self._patternTestRun.sub(r'\1%s ' % message, text)
        result = self._patternTestplan.search(text)
        if result:
            url = "https://meqa.autodesk.com/index.php?/plans/view/%s" % result.group(2)
            message = '<a href="%s">R%s</a>' % (url, result.group(2))
            text = self._patternTestplan.sub(r'\1%s ' % message, text)
        result = self._patternTest.search(text)
        if result:
            url = "https://meqa.autodesk.com/index.php?/tests/view/%s" % result.group(2)
            message = '<a href="%s">T%s</a>' % (url, result.group(2))
            text = self._patternTest.sub(r'\1%s ' % message, text)
        # Patch to add link to TestRails
        # result = self._patternFailed.search(text)
        # if result:
        #     url = "http://meqa.autodesk.com/index.php?/cases/view/%s" % result.group(2)
        #     message = '<font color="red">The TestRail case can seen here: <a href="%s">%s</a></font>' % (url, url)
        #     text = self._patternFailed.sub(r'\1\n%s' % message, text)
        # result = self._patternFailed.search(text)
        # if result:
        #     # ppjson(self.sandbox.)
        #     url_case = "http://meqa.autodesk.com/index.php?/cases/view/%s" % result.group(3)
        #     url_test = "http://meqa.autodesk.com/index.php?/tests/view/%s" % result.group(3)
        #     message = '<a href="%s">T%s</a> (<a href="%s">C%s</a>)' % (url_test, result.group(3), url_case, result.group(3))
        #     text = self._patternFailed.sub(r'\1%s\4' % message, text)
        result = self._patternFileReport.search(text)
        if result:
            # shortName = result.group(1).replace(self.currentLocation + "/", "")
            message = '<font color="red">The failure report can seen here: <a href="file:/%s/%s">%s</a></font>' % (result.group(1), result.group(2), result.group(2))
            text = self._patternFileReport.sub(message, text)
        # result = self._patternTestCase.search(text)
        # if result:
        #     url = "http://meqa.autodesk.com/index.php?/cases/view/%s" % result.group(1)
        #     message = '<a href="%s">C%s</a>' % (url, result.group(1))
        #     text = self._patternTestCase.sub(r'%s' % message, text)

        cursor.insertHtml(text.replace('\n', '<br>'))
        self.ui.runOutput.ensureCursorVisible()
        cursor.movePosition(cursor.End)

    def data_ready(self):
        """
        Callback for when data is ready to be printed.
        """
        data = unicode(self.process.readAll(), "UTF8")
        self.console_output(data)

    def data_ready_err(self):
        """
        Callback for when data is ready from stderr.
        """
        self.console_output(str(self.process.readAllStandardError()), "red")

    def run_tests(self):
        """
        Run the tests.
        """
        current_tab_index = self.ui.tabTestModes.currentIndex()
        args = [
            "--git-token", "%s:x-oauth-basic" % self.prefs.get_pref("github_api_key"),
            "--work-folder", self.prefs.get_pref("work_folder"),
            "--no-fetch", "--no-sync",
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
                "--testrail-token", "%s:%s" % (self.prefs.get_pref("testrail_email_address"), self.prefs.get_pref("testrail_api_key")),
                "--testrail-targets", "%d" % run_id
            ]
            if testrail_commit:
                args.append("--testrail-commit")
            if testrail_run_all:
                args.append("--testrail-run-all")
        else:
            raise Exception("Unexpect Tab Index for tabTestModes")
        # "--config-options", "sg_config__timeout=30000",
        config_xml_file = self.prefs.get_pref("config_xml_file")
        if os.path.exists(config_xml_file):
            args += [
                '--config-xml-file',
                config_xml_file
            ]
        self.process.start(os.path.join(self.currentLocation, "SeleniumSandbox.py"), args)

    def open_links(self, url):
        """
        Open links when clicked on.
        """
        QtCore.QDesktopServices.openUrl(url)

    def stop_tests(self):
        """
        Stop ongoing tests.
        """
        self.process.terminate()
        self.process.waitForFinished()

    def get_files(self):
        """
        Get the files from the GitHub.
        """
        self.process.start(os.path.join(self.currentLocation, "SeleniumSandbox.py"), [
            "--git-token", "%s:x-oauth-basic" % self.prefs.get_pref("github_api_key"),
            # "--no-fetch", "--no-sync",
            "--work-folder", self.prefs.get_pref("work_folder"),
            # "--verbose",
            self.ui.siteList.currentText()
        ])

    def update_test_rail_target_list(self):
        """
        Connect to the TestRail server to update the targets.
        """
        testrail_tests = {}
        current_selection = self.ui.testRailTargetList.currentText()

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
            idx = self.ui.testRailTargetList.findText(current_selection)
            if idx != -1:
                self.ui.testRailTargetList.setCurrentIndex(idx)

    def update_test_suites_target_list(self):
        """
        Update the tagets.
        """
        workfolder_location = os.path.join(self.currentLocation, self.prefs.get_pref("work_folder"))
        file_list = locate_files('runTest.command', workfolder_location)
        suite_list = []
        current_selection = self.ui.testSuitesTargetList.currentText()
        suite_pattern = re.compile("%s/(suites.*)/runTest.command" % workfolder_location)
        for filename in file_list:
            suite_list.append(suite_pattern.sub(r'\1', filename))

        self.ui.testSuitesTargetList.clear()
        self.ui.testSuitesTargetList.addItems(suite_list)
        if self.ui.testSuitesTargetList.count() > 0:
            self.ui.testSuitesTargetList.setEnabled(True)
            self.ui.testSuitesTargetList.setEnabled(True)
            idx = self.ui.testSuitesTargetList.findText(current_selection)
            if idx != -1:
                self.ui.testSuitesTargetList.setCurrentIndex(idx)

    def show(self):
        """
        Show the UI.
        """
        super(MyMainGUI, self).show()

        # Ensure that there are valid settings in place before we proceed
        message = self.validate_prefs()
        while True:
            if len(message) > 0:
                message = self.prefs_dialog()
                if message is None:
                    self.close()
                    QtCore.QCoreApplication.instance().quit()
                    sys.exit(2)
                    break
            else:
                break

    def about(self):
        """
        Popup a box with about message.
        """
        QtGui.QMessageBox.about(
            self, "About ",
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
                platform.system()
            )
        )


def main():
    """
    Main function.
    """
    current_location = os.path.dirname(os.path.realpath(__file__))
    prefs = appPrefs.AppPrefs(os.path.expanduser("~/.sg_automation.json"))
    app = QtGui.QApplication(sys.argv)
    app.setStyle("plastique")
    with open(os.path.join(current_location, "darkorange.stylesheet"), "r") as f:
        read_data = f.read()
        read_data = read_data.replace(":resources/", os.path.join(current_location, "resources/"))
        app.setStyleSheet(read_data)
    ui = MyMainGUI(prefs)
    ui.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

# TODO LIST:
# @TODO: ensure that the stop tests button works
