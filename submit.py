#!/usr/bin/env python

import sys
sys.path.append("./devtools")

import presubmit_support
import PRESUBMIT

def main(argv = None):
 change = presubmit_support.InputApi("", "./devtools", False, None, True)
 PRESUBMIT.CheckChangeOnUpload(change)

