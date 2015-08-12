all: runTestsGUI.py prefsGUI.py SG_Automation.app

%.py: %.ui
	/Applications/Shotgun.app/Contents/Frameworks/Python/bin/python /Applications/Shotgun.app/Contents/Frameworks/Python/bin/pyside-uic $< -o $@

SG_Automation.app: \
	SG_Automation.app/Contents/MacOS/SG_Automation \
	SG_Automation.app/Contents/MacOS/SeleniumSandbox.py \
	SG_Automation.app/Contents/MacOS/testrail.py \
	SG_Automation.app/Contents/MacOS/appPrefs.py \
	SG_Automation.app/Contents/MacOS/prefsGUI.py \
	SG_Automation.app/Contents/MacOS/runTestsGUI.py \
	SG_Automation.app/Contents/MacOS/darkorange.stylesheet

SG_Automation.app/Contents/MacOS/SG_Automation: runTestsMain.py
	@cp -v $< $@

SG_Automation.app/Contents/MacOS/%.py: %.py
	@cp -v $< $@

SG_Automation.app/Contents/MacOS/%.stylesheet: %.stylesheet
	@cp -v $< $@

dmg: Installer.dmg

Installer.dmg:
	rm -rvf $@ build
	mkdir build
	cp -R SG_Automation.app build
	cp resources/background.png resources/volume.icns build
	chflags -v hidden build/background.png build/volume.icns
	create-dmg \
		--volname "SG_Automation Installer" \
		--volicon  build/volume.icns \
		--window-pos 121 93 \
		--window-size 503 349 \
		--icon-size 110 \
		--app-drop-link 386.5 164 \
		--icon SG_Automation.app 128.5 168 \
		--background build/background.png \
		--hide-extension SG_Automation.app \
		--text-size 12 \
		$@ build

clean:
	rm -rvf build Installer.dmg runTestsGUI.py prefsGUI.py SG_Automation.app.zip rw.Installer.dmg *.pyc SG_Automation.app/Contents/MacOS/*.pyc
