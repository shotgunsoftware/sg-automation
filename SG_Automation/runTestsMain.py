#!/Applications/Shotgun.app/Contents/Frameworks/Python/bin/python

import copy
import fnmatch
import os
import re
import signal
import subprocess
import sys

from PySide.QtCore import *
from PySide.QtGui import *

from runTestsGUI import *
from prefsGUI import *

import SeleniumSandbox
import appPrefs

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
        self.dialog.credsRadioButton.toggled.connect(self.radio_toggled)
        self.get_prefs()

    def radio_toggled(self, value):
        if self.dialog.credsRadioButton.isChecked():
            self.dialog.userNameEdit.setEnabled(True)
            self.dialog.userPasswordEdit.setEnabled(True)
            self.dialog.apiKeyEdit.setEnabled(False)
        else:
            self.dialog.userNameEdit.setEnabled(False)
            self.dialog.userPasswordEdit.setEnabled(False)
            self.dialog.apiKeyEdit.setEnabled(True)

    def get_prefs(self):
        password = self.prefs.get_pref("git_userpassword")
        if password == "x-oauth-basic":
            self.dialog.apiKeyRadioButton.setChecked(True)
            self.dialog.apiKeyEdit.setText(self.prefs.get_pref("git_username"))
        else:
            self.dialog.credsRadioButton.setChecked(True)
            self.dialog.userNameEdit.setText(self.prefs.get_pref("git_username"))
            self.dialog.userPasswordEdit.setText(self.prefs.get_pref("git_userpassword"))

        work_folder = self.prefs.get_pref("work_folder") or os.path.expanduser("~/sg_automation")
        self.dialog.workFolderEdit.setText(work_folder)
        seen = set()
        web_sites = self.prefs.get_pref("web_sites") or [u"https://6-3-develop.shotgunstudio.com"]
        web_sites = [i for i in map(unicode.strip, web_sites)  if not (i in seen or seen.add(i))]
        self.dialog.sitesList.setText("\n".join(item for item in web_sites))

    def set_prefs(self):
        if self.dialog.credsRadioButton.isChecked():
            self.prefs.set_pref("git_username", self.dialog.userNameEdit.text())
            self.prefs.set_pref("git_userpassword", self.dialog.userPasswordEdit.text())
        else:
            self.prefs.set_pref("git_username", self.dialog.apiKeyEdit.text())
            self.prefs.set_pref("git_userpassword", "x-oauth-basic")
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
        self.ui.runTestsButton.clicked.connect(self.runTests)
        self.ui.stopTestsButton.clicked.connect(self.stopTests)

        # QProcess object for external app
        self.process = QtCore.QProcess(self)

        # QProcess emits `readyRead` when there is data to be read
        self.process.readyRead.connect(self.dataReady)
        self.process.readyReadStandardError.connect(self.dataReadyErr)

        # Just to prevent accidentally running multiple times
        # Disable the button when process starts, and enable it when it finishes
        self.process.started.connect(lambda: self.ui.actionPrefs.setEnabled(False))
        self.process.started.connect(lambda: self.ui.siteList.setEnabled(False))
        self.process.started.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.process.started.connect(lambda: self.ui.stopTestsButton.setEnabled(True))

        self.process.finished.connect(lambda: self.ui.actionPrefs.setEnabled(True))
        self.process.finished.connect(lambda: self.ui.siteList.setEnabled(True))
        self.process.finished.connect(lambda: self.ui.runTestsButton.setEnabled(True))
        self.process.finished.connect(lambda: self.ui.stopTestsButton.setEnabled(False))

        self.process.finished.connect(lambda: self.consoleOutput("%s" % "<font color=\"green\">Success</font>\n" if self.process.exitCode() == 0 else "<font color=\"red\">Failed !</font>\n"))
        self.process.finished.connect(self.updateSuitesList)

        # Get the prefs panel
        self.ui.actionPrefs.triggered.connect(self.updatePrefs)

        # Ensure that we control the opening of links in the text browswer
        self.ui.runOutput.anchorClicked.connect(self.openLinks)

        self.ui.siteList.lineEdit().setPlaceholderText('Please enter the URL here')
        self.ui.siteList.activated.connect(lambda: self.ui.targetList.setEnabled(False))
        self.ui.siteList.activated.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.ui.siteList.currentIndexChanged.connect(self.validateURL)
        self.ui.siteList.editTextChanged.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.ui.siteList.editTextChanged.connect(lambda: self.ui.targetList.setEnabled(False))


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

    def validatePrefs(self):
        return_value = ""
        try:
            self.sandbox = SeleniumSandbox.SeleniumSandbox("%s:%s" % (self.prefs.get_pref("git_username"), self.prefs.get_pref("git_userpassword")))
            self.sandbox.set_work_folder(self.prefs.get_pref("work_folder"))
            message = 'Logged to GitHub as user %s, working out of folder %s' % (self.sandbox.get_user_login(), self.sandbox.get_work_folder())
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
            self.consoleOutput(return_value)
            self.ui.statusbar.showMessage(return_value)
        except SeleniumSandbox.WorkFolderDoesNotExists as e:
            self.consoleOutput("Error: %s\n" % e)
            return_value = "Please enter an existing folder as work folder\n"
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

    _patternClearLine = re.compile("\x1B\[2K")
    _patternGreen = re.compile("\x1B\[01;32m(.*)\x1B\[00m")
    _patternRed = re.compile("\x1B\[01;31m(.*)\x1B\[00m")
    _patternHttp = re.compile(r"\s(https?:/(/\S+)+)")
    _patternFileReport = re.compile(r"You can consult build report: (/\S+)/report.html")
    _patternFailed = re.compile(r"(.*/test_rail/.*/C([0-9]+) failed)")

    def consoleOutput(self, text, color=None):
        # Doing some filtering and markup
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
        self.process.start(os.path.join(self.currentLocation, "SeleniumSandbox.py"), [
            "-t", "%s:%s" % (self.prefs.get_pref("git_username"), self.prefs.get_pref("git_userpassword")),
            "-w", self.prefs.get_pref("work_folder"),
            "-s", self.ui.targetList.currentText(),
#            "-c", "sg_config__timeout=30000",
            self.ui.siteList.currentText()
            ])

    def openLinks(self, url):
        QDesktopServices.openUrl(url)


    def stopTests(self):
        self.process.terminate()
        self.process.waitForFinished()

    def getFiles(self):
        self.process.start(os.path.join(self.currentLocation, "SeleniumSandbox.py"), [
            "-t", "%s:%s" % (self.prefs.get_pref("git_username"), self.prefs.get_pref("git_userpassword")),
            "-w", self.prefs.get_pref("work_folder"),
#            "-v",
            self.ui.siteList.currentText()
            ])

    def updateSuitesList(self):
        workfolderLocation = os.path.join(self.currentLocation, self.prefs.get_pref("work_folder"))
        fileList = locateFiles('runTest.command', workfolderLocation)
        suiteList = []
        currentSuite = self.ui.targetList.currentText()
        suitePattern = re.compile("%s/(suites.*)/runTest.command" % workfolderLocation)
        for filename in fileList:
            suiteList.append(suitePattern.sub(r'\1', filename))

        self.ui.targetList.clear()
        self.ui.targetList.addItems(suiteList)
        if self.ui.targetList.count() > 0:
            self.ui.targetList.setEnabled(True)
            self.ui.runTestsButton.setEnabled(True)
            idx = self.ui.targetList.findText(currentSuite)
            if idx != -1:
                self.ui.targetList.setCurrentIndex(idx)

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

def main():
    prefs = appPrefs.AppPrefs(os.path.expanduser("~/.sg_automation.json"))
    app = QtGui.QApplication(sys.argv)
    ui = MyMainGUI(prefs)
    ui.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
