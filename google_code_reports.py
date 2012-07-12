import copy
import json
import urllib2

import hipchat_message

change_threshold = 1.10

def get_errors(old_reports):

    last_id = old_reports["last_id"]

    issue_count = [0]

    def get_issues(page, last_id):
        request = urllib2.urlopen(
            "http://code.google.com/p/khanacademy/issues/csv?can=2&q=&colspec=ID&sort=-ID&start=%d"
            % (page*100))
        issues = request.read()
        request.close()

        # Parse the CSV file
        issues = issues.split("\n")
        issues = [issue.split(",") for issue in issues]
        issues = issues[1:]  # Ignore column headers
        issues = issues[:-2]  # Strip junk from the end
        issues = [int(x[0].replace('"', '')) for x in issues]
        # Make sure we cut off at the right point
        issues = sorted(issues, reverse=True)

        should_continue = True
        for issue in issues:
            if issue > last_id:
                issue_count[0] += 1
            else:
                should_continue = False
                break

        if should_continue and last_id != -1:
            get_issues(page + 1, last_id)

        return max(issues[0], last_id)

    first_id = get_issues(0, last_id)
    issue_count = issue_count[0]

    old_reports["last_id"] = first_id
    old_reports["issue_count"] += issue_count
    old_reports["issues_this_period"] = issue_count

    return old_reports
    
def main():
    try:
        google_code_file = open("google_code", 'r+')
        old_reports = json.loads(google_code_file.read())
    except IOError:
        google_code_file = open("google_code", 'w')
        old_reports = {"num_periods": 0,
                       "last_id": -1,
                       "issue_count": 0,
                       "issues_this_period": 0}

    old_reports["num_periods"] += 1
    new_reports = get_errors(copy.deepcopy(old_reports))

    old_rate = old_reports["issue_count"]/old_reports["num_periods"]
    if (old_rate != 0 and
            change_threshold * old_rate < new_reports["issues_this_period"]:)
        # Too many errors!
        hipchat_message.message_ones_and_zeros(
            "Elevated bug report rate on Google code!")

    google_code_file.seek(0)
    google_code_file.truncate()
    google_code_file.write(json.dumps(new_reports))

    google_code_file.close()

if __name__ == "__main__":
    main()
