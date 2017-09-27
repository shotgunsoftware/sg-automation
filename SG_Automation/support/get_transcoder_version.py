#!/usr/bin/env python -u

import requests
import sys
import rundeck
import time
import traceback

from optparse import OptionParser
from pprint import pprint as pp
from rundeck.client import Rundeck

# This is to disable SSL warnings
requests.packages.urllib3.disable_warnings()


def main(argv):
    parser = OptionParser(usage="usage: %prog [options] url")
    parser.add_option("--rundeck-token",
        help="API key")
    parser.add_option("--verbose", action="store_true", dest="verbose",
        help="Output debugging information")
    parser.add_option("--timeout", type="int", default=300,
        help="Number of seconds to wait for a deploy (defaults to 300 seconds, e.g. 5 minutes)")
    (options, args) = parser.parse_args()

    if options.verbose is None:
        options.verbose = False

    if None in vars(options).values():
        print "Missing required option for Shotgun API connection."
        parser.print_help()
        sys.exit(2)

    try:
        rd = Rundeck(api_token=options.rundeck_token, server='rundeck-staging.shotgunsoftware.com', protocol='http', port=4440)

        print "INFO: Get Transcoder Version"
        job_id = rd.get_job_id('Shotgun', name='Get Transcoder Version')
        res = rd.run_job('f10a8435-81f9-47cf-a378-eb394327437a', argString={}, timeout=6)
        job_id = res['id']
        ts = time.time()
        while res['status'] == 'running' and (time.time() - ts) < options.timeout:
            print "INFO: Waiting for the job to complete..."
            time.sleep(5)
            res = rd.execution_status(job_id)

        if res['status'] != 'succeeded':
            print "ERROR: Job failed : %s" % res
            sys.exit(1)
        else:
            print "INFO: Job succeeded"
            print rd.get_execution_output(job_id, fmt='text')

    except requests.exceptions.HTTPError as e:
        print "ERROR: Unable to contact Rundeck: %s" % e
        if options.verbose:
            traceback.print_exc()
    except rundeck.exceptions.JobNotFound as e:
        print "ERROR: Rundeck error: %s" % e
        if options.verbose:
            traceback.print_exc()
    except Exception as e:
        print "ERROR: Unknown error: %s" % e
        if options.verbose:
            traceback.print_exc()
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
