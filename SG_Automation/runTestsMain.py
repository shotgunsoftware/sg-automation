#!/Applications/Shotgun.app/Contents/Frameworks/Python/bin/python

import copy
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


class MyPrefsGUI(QtGui.QDialog):
    def __init__(self, prefs):
        super(MyPrefsGUI, self).__init__()
        self.prefs = prefs
        self.dialog = Ui_Dialog()
        self.dialog.setupUi(self)
        self.dialog.browseButton.clicked.connect(self.browseDialog)
        self.get_prefs()

    def get_prefs(self):
        self.dialog.userNameEdit.setText(self.prefs.get_pref("git_username"))
        self.dialog.userPasswordEdit.setText(self.prefs.get_pref("git_userpassword"))
        self.dialog.workFolderEdit.setText(self.prefs.get_pref("work_folder"))
        web_sites = self.prefs.get_pref("web_sites") or []
        self.dialog.sitesList.setText("\n".join(item for item in web_sites))

    def set_prefs(self):
        self.prefs.set_pref("git_username", self.dialog.userNameEdit.text())
        self.prefs.set_pref("git_userpassword", self.dialog.userPasswordEdit.text())
        self.prefs.set_pref("work_folder", self.dialog.workFolderEdit.text())
        self.prefs.set_pref("web_sites", self.dialog.sitesList.toPlainText().split("\n"))

    def browseDialog(self):
        start_folder = self.dialog.workFolderEdit.text() or os.path.expanduser("~/.")
        folder = QtGui.QFileDialog.getExistingDirectory(self, "Select folder where files will be downloaded", start_folder)
        if folder:
            self.dialog.workFolderEdit.setText(folder)


class MyMainGUI(QtGui.QMainWindow):
    def __init__(self, prefs):
        super(MyMainGUI, self).__init__()
        self.prefs = prefs
        self.overwrite_last_line = True
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.ui.runTestsButton.clicked.connect(self.runTests)
        self.ui.stopTestsButton.clicked.connect(self.stopTests)
        self.ui.stopTestsButton.setEnabled(True)

        web_sites = self.prefs.get_pref("web_sites") or []
        self.ui.siteList.addItems(web_sites)

        # QProcess object for external app
        self.process = QtCore.QProcess(self)

        # QProcess emits `readyRead` when there is data to be read
        self.process.readyRead.connect(self.dataReady)
        self.process.readyReadStandardError.connect(self.dataReadyErr)

        # Just to prevent accidentally running multiple times
        # Disable the button when process starts, and enable it when it finishes
        self.process.started.connect(lambda: self.ui.runTestsButton.setEnabled(False))
        self.process.finished.connect(lambda: self.ui.runTestsButton.setEnabled(True))
        self.process.started.connect(lambda: self.ui.stopTestsButton.setEnabled(True))
        self.process.finished.connect(lambda: self.ui.stopTestsButton.setEnabled(False))

        self.process.finished.connect(lambda: self.consoleOutput("%s" % "Success" if self.process.exitCode() == 0 else "Failed !"))

        # Get the prefs panel
        self.ui.actionPrefs.triggered.connect(self.updatePrefs)

        # Ensure that we control the opening of links in the text browswer
        self.ui.runOutput.anchorClicked.connect(self.openLinks)



    def __del__(self):
        if self.process.state() is QtCore.QProcess.ProcessState.Running:
            self.process.terminate()
            self.process.waitForFinished()

    def validatePrefs(self):
        return_value = ""
        try:
            self.sandbox = SeleniumSandbox.SeleniumSandbox("%s:%s" % (self.prefs.get_pref("git_username"), self.prefs.get_pref("git_userpassword")))
            self.sandbox.set_work_folder(self.prefs.get_pref("work_folder"))
            message = 'Logged to GitHub as user %s, working out of folder %s' % (self.sandbox.get_user_login(), self.sandbox.get_work_folder())
            self.consoleOutput(message + "\n")
            self.ui.statusbar.showMessage(message)
            web_sites = self.prefs.get_pref("web_sites") or []
            self.ui.siteList.clear()
            self.ui.siteList.addItems(web_sites)
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
    _patternFile = re.compile(r"\s((/\S+)+)")

    def consoleOutput(self, text, color=None):
        # Doing some filtering and markup
        text = self._patternClearLine.sub("", text)
        text = self._patternHttp.sub(r'<a href="\1">\1</a>', text)
        text = self._patternFile.sub(r'<a href="file:/\1">\1</a>', text)
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
        cursor.insertHtml(text.replace('\n', '<br>'))
        self.ui.runOutput.ensureCursorVisible()

    def dataReady(self):

        data = unicode(self.process.readAll(), "UTF8")
        # data = self._patternClearLine.sub("", data)
        # data = self._patternHttp.sub(r'<a href="\1">\1</a>', data)
        # data = self._patternFile.sub(r'<a href="file:/\1">\1</a>', data)
        # data = self._patternGreen.sub(r'<font color="green">\1</font>', data)
        # data = self._patternRed.sub(r'<font color="red">\1</font>', data)

        self.consoleOutput(data)

    def dataReadyErr(self):
        self.consoleOutput(str(self.process.readAllStandardError()), "red")

    def runTests(self):
        currentLocation = os.path.dirname(os.path.realpath(__file__))
        self.process.start(os.path.join(currentLocation, "SeleniumSandbox.py"), [
            "-t", "%s:%s" % (self.prefs.get_pref("git_username"), self.prefs.get_pref("git_userpassword")),
            "-w", self.prefs.get_pref("work_folder"),
            "-s", "suites/runTest.command",
            self.ui.siteList.currentText()
            ])

    def openLinks(self, url):
        # print "->%s<-" % url
        QDesktopServices.openUrl(url)


    def stopTests(self):
        self.process.terminate()
        self.process.waitForFinished()

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
    prefs = appPrefs.AppPrefs(os.path.expanduser("~/sg_selenium_prefs.json"))
    app = QtGui.QApplication(sys.argv)
    ui = MyMainGUI(prefs)
    ui.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
