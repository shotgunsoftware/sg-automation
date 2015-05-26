#!/usr/bin/env python -u

import json
import os
import sys

from pprint import pprint


class AppPrefs:
    def __init__(self, prefs_file):
        self.prefs_file = prefs_file
        self.load_prefs()

    def load_prefs(self):
        self.prefs = {}
        if os.path.exists(self.prefs_file):
            with open(self.prefs_file) as data_file:
                self.prefs = json.load(data_file)
        else:
            print "WARNING: File %s does not exist" % self.prefs_file

    def save_prefs(self):
        prefs_folder = os.path.dirname(self.prefs_file) or "."
        if not os.path.exists(prefs_folder):
            print "Creating folder %s" % prefs_folder
            os.makedirs(prefs_folder)
        with open(self.prefs_file, "w") as data_file:
            json.dump(self.prefs, data_file)

    def get_prefs(self):
        return self.prefs.keys()

    def get_pref(self, key):
        value = None
        try:
            value = self.prefs[key]
        except KeyError, e:
            pass
        return value

    def set_pref(self, key, value):
        self.prefs[key] = value

    def set_pref(self, key, value):
        self.prefs[key] = value

def main(argv):
    print "Hello"
    prefs = AppPrefs(argv[0])
    pprint(prefs.get_prefs())
    prefs.set_pref('grrr', 33)
    pprint(prefs.get_prefs())
    prefs.get_pref('fff')
    pprint(prefs.get_prefs())
    prefs.save_prefs()

if __name__ == "__main__":
    main(sys.argv[1:])
