#!/usr/bin/env python
import time

import github_reports
import google_code_reports

while True:
    github_reports.main()
    google_code_reports.main()
    print("Sleeping...")
    time.sleep(60 * 10)
