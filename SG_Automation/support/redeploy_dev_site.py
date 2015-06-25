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
    parser.add_option("-t", "--rundeck-token",
        help="API key")
    parser.add_option("-s", "--site-name",
        help="Site to redeploy, without the com_shotgunstudio_ prefix.")
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose",
        help="Output debugging information")
    (options, args) = parser.parse_args()

    if options.verbose is None:
        options.verbose = False

    if None in vars(options).values():
        print "Missing required option for Shotgun API connection."
        parser.print_help()
        sys.exit(2)

    try:
        rd = Rundeck(api_token=options.rundeck_token, server='test:test007@rundeck.shotgunsoftware.com', protocol='http', port=80)

        print "INFO: Redeploying to site %s" % options.site_name
        job_id = rd.get_job_id('Shotgun', name='Redeploy a dev site')
        res = rd.run_job('16653d20-77aa-42e5-afe7-9fbe509d4225', argString={'sitename': options.site_name, 'dbbackup': 'false'}, timeout=1)
        job_id = res['id']
        retry = 0
        while res['status'] == 'running' and retry < 20:
            retry += 1
            print "INFO: Waiting for the job to complete..."
            time.sleep(15)
            res = rd.execution_status(job_id)

        if res['status'] != 'succeeded':
            print "ERROR: Job failed : %s" % res
            sys.exit(1)
        else:
            print "INFO: Job succeeded"

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
