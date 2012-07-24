import copy
import json
import time
import urllib2

import hipchat_message

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
        request = urllib2.urlopen(
            "http://code.google.com/p/khanacademy/issues/csv?can=2&q=&colspec=ID+ModifiedTimestamp&sort=-ID&start=%d"
            % (page * 100))
        issues = request.read()
        request.close()

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

        if stop_id > issues[0][0]:
            # Indicate first time in range if necessary
            return (stop_id, issues[len(issues) - 1][1])
        else:
            return issues[0][0]

    result = get_issues(0, old_reports["last_id"])

    cur_time = time.time()

    if len(result) == 2:
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
        google_code_file = open("google_code", 'r+')
        old_reports = json.loads(google_code_file.read())
    except IOError:
        google_code_file = open("google_code", 'w')
        old_reports = {"elapsed_time": 0,
                       "last_id": -1,
                       "issue_count": 0,
                       "last_time": 0}

    new_reports = get_errors(copy.deepcopy(old_reports))

    old_rate = old_reports["issue_count"] / old_reports["elapsed_time"]
    new_rate = (new_reports["issues_this_period"] /
                    new_reports["time_this_period"])

    if (old_rate != 0 and change_threshold * old_rate < new_rate):
        # Too many errors!
        hipchat_message.send_message(
            "Elevated bug report rate on"
            " <a href='http://code.google.com/p/khanacademy/issues/'>Google"
            " code!</a>"
            " Current rate: %.3f per hour. Average rate: %.3f per hour."
            " (Current is %.2f%% of average)"
            % (new_rate * 60 * 60,
               old_rate * 60 * 60,
               (new_rate / old_rate) * 100))

    # Delete fields we don't need anymore
    del(new_reports["issues_this_period"])
    del(new_reports["time_this_period"])

    google_code_file.seek(0)
    google_code_file.truncate()
    google_code_file.write(json.dumps(new_reports))

    google_code_file.close()

if __name__ == "__main__":
    main()
