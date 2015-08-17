#!/usr/bin/env python -u

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import SeleniumSandbox


class TestPlansAndCases(unittest.TestCase):
    sandbox = None
    known_run = None
    known_plan = None
    maya_project_id = 7
    maya_run = None
    maya_plan = None

    @classmethod
    def setUpClass(cls):
        github_token = os.environ["GITHUB_TOKEN"]
        testrail_token = os.environ["TESTRAIL_TOKEN"]
        cls.sandbox = SeleniumSandbox.SeleniumSandbox(github_token, testrail_token)
        cls.known_run = cls.sandbox.testrail_runs.keys()[0]
        cls.known_plan = cls.sandbox.testrail_plans.keys()[0]

        known_plan_runs = cls.sandbox.testrail.send_get('get_plan/%d' % cls.known_plan)
        assert(len(known_plan_runs["entries"]) > 0)
        assert(len(known_plan_runs["entries"][0]["runs"]) > 0)
        cls.known_plan_run = known_plan_runs["entries"][0]["runs"][0]["id"]

        maya_runs = cls.sandbox.testrail.send_get('get_runs/%d&is_completed=0' % cls.maya_project_id)
        assert(len(maya_runs) > 0)
        maya_plans = cls.sandbox.testrail.send_get('get_plans/%d&is_completed=0' % cls.maya_project_id)
        assert(len(maya_plans) > 0)
        cls.maya_run = maya_runs[0]['id']
        cls.maya_plan = maya_plans[0]['id']

        maya_plan_runs = cls.sandbox.testrail.send_get('get_plan/%d' % cls.maya_plan)
        assert(len(maya_plan_runs["entries"]) > 0)
        assert(len(maya_plan_runs["entries"][0]["runs"]) > 0)
        cls.maya_plan_run = maya_plan_runs["entries"][0]["runs"][0]["id"]

    @classmethod
    def tearDownClass(cls):
        pass


    def test_id_is_a_run(self):
        cls = self.__class__
        self.assertTrue(cls.sandbox.is_testrail_run(cls.known_run))

    def test_id_is_a_plan(self):
        cls = self.__class__
        self.assertTrue(cls.sandbox.is_testrail_plan(cls.known_plan))

    def test_id_is_a_plan_run(self):
        cls = self.__class__
        self.assertTrue(cls.sandbox.is_testrail_run(cls.known_plan_run))

    def test_id_is_a_not_run(self):
        cls = self.__class__
        self.assertFalse(cls.sandbox.is_testrail_run(cls.known_plan))

    def test_id_is_a_not_plan(self):
        cls = self.__class__
        self.assertFalse(cls.sandbox.is_testrail_plan(cls.known_run))

    def test_id_is_invalid_run(self):
        cls = self.__class__
        # self.assertRaisesRegexp(SeleniumSandbox.TestRailRunInvalid, 'TestRail run 1 does not exist', cls.sandbox.is_testrail_run, 1)
        self.assertFalse(cls.sandbox.is_testrail_run(1))

    def test_id_is_invalid_plan(self):
        cls = self.__class__
        # self.assertRaisesRegexp(SeleniumSandbox.TestRailPlanInvalid, 'TestRail plan 1 does not exist', cls.sandbox.is_testrail_plan, 1)
        self.assertFalse(cls.sandbox.is_testrail_plan(1))

    def test_id_is_maya_run(self):
        cls = self.__class__
        # self.assertRaisesRegexp(SeleniumSandbox.TestRailRunInvalid, 'TestRail run %d does not belong to project Shotgun' % cls.maya_run, cls.sandbox.is_testrail_run, cls.maya_run)
        self.assertFalse(cls.sandbox.is_testrail_run(cls.maya_run))

    def test_id_is_maya_plan(self):
        cls = self.__class__
        # self.assertRaisesRegexp(SeleniumSandbox.TestRailPlanInvalid, 'TestRail plan %d does not belong to project Shotgun' % cls.maya_plan, cls.sandbox.is_testrail_plan, cls.maya_plan)
        self.assertFalse(cls.sandbox.is_testrail_plan(cls.maya_plan))

    def test_id_is_maya_plan_run(self):
        cls = self.__class__
        # self.assertRaisesRegexp(SeleniumSandbox.TestRailRunInvalid, 'TestRail run %d does not belong to project Shotgun' % cls.maya_plan_run, cls.sandbox.is_testrail_run, cls.maya_plan_run)
        self.assertFalse(cls.sandbox.is_testrail_run(cls.maya_plan_run))

if __name__ == '__main__':
    unittest.main()