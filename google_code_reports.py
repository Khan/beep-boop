import contextlib
import copy
import json
import time
import urllib2

import hipchat_message
import util

# Threshold of average to report an elevated rate
change_threshold = 1.10


def get_errors(old_reports):
    '''Given an old dict (contents of google_code), get new issues from Google
    Code and return an updated version of the dict with information about
    the new bug reports.
    '''

    # Use a list because otherwise we couldn't access issue_count in get_issues
    issue_count = [0]

    def get_issues(page, stop_id):
        url = ("http://code.google.com/p/khanacademy/issues/csv"
               "?can=2&q=&colspec=ID+ModifiedTimestamp&sort=-ID&start=%d"
               % (page * 100))
        with contextlib.closing(urllib2.urlopen(url)) as request:
            issues = request.read()

        # Parse the CSV file
        issues = issues.rstrip().split("\n")
        # Ignore trailing commas
        issues = [issue.split(",") for issue in issues]
        issues = issues[1:]  # Ignore column headers
        issues = issues[:-1]  # Strip junk from the end
        issues = [[int(x.replace('"', '')) for x in issue] for issue in issues]
        # Note: We don't need to explicitly sort here because the request
        # to Google specified we sort by -ID

        should_continue = True
        for issue in issues:
            if issue[0] > stop_id:
                issue_count[0] += 1
            else:
                should_continue = False
                break

        if should_continue and stop_id != -1:
            get_issues(page + 1, stop_id)

        if stop_id == -1:
            # Indicate first time in range if necessary
            return (issues[0][0], issues[-1][1])
        else:
            # max is in case of no new issues
            return max(issues[0][0], stop_id)

    result = get_issues(0, old_reports["last_id"])

    cur_time = time.time()

    if isinstance(result, tuple):
        max_id, first_time = result
        time_this_period = cur_time - first_time
    else:
        max_id = result
        time_this_period = cur_time - old_reports["last_time"]

    issue_count = issue_count[0]

    old_reports["last_id"] = max_id
    old_reports["issue_count"] += issue_count
    old_reports["elapsed_time"] += time_this_period
    old_reports["last_time"] = cur_time
    # Just for temporary use
    old_reports["issues_this_period"] = issue_count
    old_reports["time_this_period"] = time_this_period

    return old_reports


def main():
    try:
        google_code_file = open(util.relative_path("google_code"), 'r+')
        old_reports = json.loads(google_code_file.read())
    except IOError:
        google_code_file = open(util.relative_path("google_code"), 'w')
        # elapsed_time is filler value: doesn't matter what it is
        # since issue_count is 0.
        old_reports = {"elapsed_time": 1,
                       "last_id": -1,
                       "issue_count": 0,
                       "last_time": 0}

    new_reports = get_errors(copy.deepcopy(old_reports))

    time_this_period = new_reports["time_this_period"]

    mean, probability = util.probability(old_reports["issue_count"],
                                         old_reports["elapsed_time"],
                                         new_reports["issues_this_period"],
                                         time_this_period)

    if (mean != 0 and probability > 0.99):
        # Too many errors!
        hipchat_message.send_message(
            "Elevated bug report rate on"
            " <a href='http://code.google.com/p/khanacademy/issues/'>Google"
            " code!</a>"
            " We saw %s in the last %s minutes,"
            " while the mean indicates we should see around %s."
            " Probability that this is abnormally elevated: %.4f."
            % (util.thousand_commas(new_reports["issues_this_period"]),
               util.thousand_commas(int(time_this_period / 60)),
               util.thousand_commas(round(mean, 2)),
               probability))

    # Delete fields we don't need anymore
    del(new_reports["issues_this_period"])
    del(new_reports["time_this_period"])

    google_code_file.seek(0)
    google_code_file.truncate()
    google_code_file.write(json.dumps(new_reports))

    google_code_file.close()

if __name__ == "__main__":
    main()
