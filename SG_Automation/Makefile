all: runTestsGUI.py prefsGUI.py SG_Automation.app

%.py: %.ui
	/Applications/Shotgun.app/Contents/Frameworks/Python/bin/python /Applications/Shotgun.app/Contents/Frameworks/Python/bin/pyside-uic $< -o $@

SG_Automation.app: \
	SG_Automation.app/Contents/MacOS/SG_Automation \
	SG_Automation.app/Contents/MacOS/SeleniumSandbox.py \
	SG_Automation.app/Contents/MacOS/appPrefs.py \
	SG_Automation.app/Contents/MacOS/prefsGUI.py \
	SG_Automation.app/Contents/MacOS/runTestsGUI.py

SG_Automation.app/Contents/MacOS/SG_Automation: runTestsMain.py
	@cp -v $< $@

SG_Automation.app/Contents/MacOS/%.py: %.py
	@cp -v $< $@
