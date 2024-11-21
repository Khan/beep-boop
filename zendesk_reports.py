#!/usr/bin/env python3

"""Warn if the bug-report rate has increased recently, on Zendesk.

While we used to ask users to report problems on a google code issues
page, and then UserVoice, we now use Zendesk:
   https://khanacademy.zendesk.com/

Zendesk supports an API for getting all the tickets ever opened, but
we use the incremental API to get all tickets reported since last time.

In case of sudden surge / decrease in traffic, you can reset the mean using:

  ./sendesk_reports.py --reset_weekend <X1> --reset_weekday <X2>

Where the expected value can be obtained by looking at previous alerts to
establish a sensible value.
"""

import base64
import pickle
import datetime
import json
import http.client
import logging
import re
import socket
import time
import urllib.request
import urllib.error
import argparse

import util

# In theory, you can use an API key to access zendesk data, but I
# couldn't get it to work in my tests (I got 'access denied'), so we
# use the real password instead. :-(
ZENDESK_USER = 'prod-read@khanacademy.org'
ZENDESK_PASSWORD_FILE = util.relative_path("zendesk.cfg")
ZENDESK_PASSWORD = None     # set lazily

# This is the currently defined boundary for what is considered
# 'significant' in number of new tickets. Used as threshold to determine
# when to send alerts.
SIGNIFICANT_TICKET_COUNT = 5

# We have a higher ticket boundary for paging someone.
MIN_TICKET_COUNT_TO_PAGE_SOMEONE = 7


def _parse_time(s):
    """Convert a string of the form "YYYY-MM-DD HH:MM:SS -0700" to time_t.

    We ignore the -0700; it looks like all times (and time_t's!)
    reported by the API are given as PDT times, so I'm assuming
    they'll change appropriately when daylight savings time ends.
    """
    # We could use strptime, but this is just as easy.
    (yyyy, mm, dd, HH, MM, SS) = (int(s[0:4]), int(s[5:7]), int(s[8:10]),
                                  int(s[11:13]), int(s[14:16]), int(s[17:19]))
    return time.mktime((yyyy, mm, dd, HH, MM, SS, 0, 0, -1))


def get_ticket_data(start_time_t):
    """Given start_time to export from, call Zendesk API for ticket data."""
    global ZENDESK_PASSWORD
    if ZENDESK_PASSWORD is None:
        with open(ZENDESK_PASSWORD_FILE) as f:
            ZENDESK_PASSWORD = f.read().strip()

    # According to
    #   http://developer.zendesk.com/documentation/rest_api/ticket_export.html
    # "Requests with a start_time less than 5 minutes old will also
    # be rejected."
    if int(time.time()) - start_time_t <= 300:
        return None

    url = ('https://khanacademy.zendesk.com/api/v2/exports/tickets.json'
           '?start_time=%s' % start_time_t)
    request = urllib.request.Request(url)
    # This is the best way to set the user, according to
    #    http://stackoverflow.com/questions/2407126/python-urllib2-basic-auth-problem
    encoded_password = base64.standard_b64encode(
        ('%s:%s' % (ZENDESK_USER, ZENDESK_PASSWORD)).encode('utf-8'))
    request.add_unredirected_header(
        'Authorization', 'Basic %s' % encoded_password.decode('utf-8'))

    def _should_retry(exc):
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
            # quota limits: try again, but wait first.
            print("Got 429, waiting %s seconds" % exc.headers['Retry-After'])
            time.sleep(int(exc.headers['Retry-After']))
        return isinstance(exc, (socket.error, urllib.error.HTTPError,
                                http.client.HTTPException))

    data = util.retry(lambda: urllib.request.urlopen(request, timeout=60),
                      'loading zendesk ticket data',
                      _should_retry, 15)

    return json.load(data)


def get_tickets_between(start_time_t, end_time_t):
    """Return the number of tickets created between start and end time.

    Also return the time of the oldest ticket seen, as a time_t, which
    is useful for getting an actual date-range when start_time is 0.
    """
    tickets = []
    oldest_ticket_time_t = None

    while start_time_t < end_time_t:
        ticket_data = get_ticket_data(start_time_t)
        if not ticket_data:
            break

        for ticket in ticket_data['results']:
            # we only care about technical issues
            if 'technical_issue' not in ticket['current_tags']:
                continue

            # Ignore translation advocate tickets. They can be used
            # for testing and don't indicate a user-visible problem.
            if 'translation_advocate' in ticket['current_tags']:
                continue

            # We dont care about spam and dont want them to trigger alert
            if 'spam' in ticket['current_tags']:
                continue

            # Skip tickets created by user-support, since they are
            # submitted in batches and cause false alarms
            if 'Request created from:' in ticket['subject']:
                continue

            ticket_time_t = _parse_time(ticket['created_at'])
            if ticket_time_t > end_time_t or ticket_time_t <= start_time_t:
                continue
            tickets += [ticket]
            # See if we're the oldest ticket
            if (oldest_ticket_time_t is None or
                    oldest_ticket_time_t > ticket_time_t):
                oldest_ticket_time_t = ticket_time_t

        if not ticket_data['next_page']:
            break
        start_time_t = ticket_data['end_time']

    # Sort tickets in order by date to make things easier later
    tickets = sorted(tickets,
                     key=lambda ticket: _parse_time(ticket["created_at"]))

    return (tickets, oldest_ticket_time_t)


def handle_alerts(new_tickets,
                  time_this_period,
                  mean,
                  probability,
                  start_time,
                  end_time):
    """Determine which alerts to send at various thresholds.

    If probability of elevated ticket count is high, a notification
    is sent to Slack. A Pagerduty alert is only sent out
    if a significantly elevated rate is detected.
    """
    # TODO(jacqueline): Including SIGNIFICANT_TICKET_COUNT hard
    # threshold here so as to catch false positives, especially during
    # transition. Maybe consider removing this once change in mean
    # starts flattening out; August 2017?
    num_new_tickets = len(new_tickets)
    message = (
        "We saw %s in the last %s minutes,"
        " while the mean indicates we should see around %s."
        " *Probability that this is abnormally elevated: %.4f.*"
        % (util.thousand_commas(num_new_tickets),
           util.thousand_commas(int(time_this_period / 60)),
           util.thousand_commas(round(mean, 2)),
           probability))

    if (mean != 0 and probability > 0.999 and
            num_new_tickets >= SIGNIFICANT_TICKET_COUNT):
        # Too many errors!  Point people to the slack channel.
        message = ("Elevated Zendesk report rate (#zendesk-technical)\n"
                   + message)

        # Generated a list of tickets that we will send to Slack along with the
        # original message
        ticket_list = ''
        for ticket in new_tickets:
            created_at = _parse_time(ticket['created_at'])
            created_at = datetime.datetime.fromtimestamp(created_at)
            ticket_list += "\n*[%s][Ticket #%d]:* %s" % (
                created_at.strftime("%I:%M %p"),
                ticket['id'],
                # Strip any non-safe characters from the subject line
                re.sub(r"[^\w\-\.'%&:,\[\]/\\\(\)\" ]", '', ticket['subject']))

        logging.warning("Sending message: {}".format(message))
        # TODO (Boris, INFRA-4451): Re-evaluate if we want to alert the team
        #    We will still send to slack, and create pager duty if number
        #    of tickets are *abnormally* high
        util.send_to_slack(message + ticket_list,
                           channel='#infrastructure-sre')
        # TODO (Boris, INFRA-4451) At Laurie's request
        # https://khanacademy.slack.com/archives/C8XGW76FQ/p1585321100055200?thread_ts=1585320913.054500&cid=C8XGW76FQ
        # we have allowed noisy alerts to go to #user-issues
        # we should restore this back to list below once we have confidence.
        util.send_to_slack(message + ticket_list, channel='#user-issues')

        # Before we start texting people, make sure we've hit higher threshold.
        # TODO(benkraft/jacqueline): Potentially could base this off more
        # historical data from analogous dow/time datapoints, but doesn't look
        # like Zendesk API has a good way of doing this, running into request
        # quota issues. Readdress this option if threshold is too noisy.
        if (probability > 0.9995 and
                num_new_tickets >= MIN_TICKET_COUNT_TO_PAGE_SOMEONE):
            util.send_to_slack(message + ticket_list, channel='#1s-and-0s')
            util.send_to_pagerduty(message, service='beep-boop')


def _is_off_hours(dt):
    """Returns whether we consider this time to be "off hours".

    We consider weekends and evenings to be off-hours, and track separate
    metrics for them, so that we aren't oversensitive during the weekday and
    undersensitive otherwise.

    Arguments: dt should be a datetime.datetime object, in Pacific Time (PDT or
    PST, whichever is currently active).

    TODO(benkraft): Something smarter and more adaptive to what the real data
    looks like.
    """
    if dt.weekday() in [5, 6]:
        return True
    # These times were chosen by the very precise method of "eyeballing it" on
    # number of tickets per hour in the week I happened to look.  We follow US
    # Daylight Savings Time because we figure that's where most users are.
    elif 6 <= dt.hour <= 19:
        return False
    else:
        return True


def main():
    try:
        zendesk_status_file = util.relative_path("zendesk")
        with open(zendesk_status_file, 'rb') as f:
            old_data = pickle.load(f)
    except (IOError, EOFError):
        old_data = {"elapsed_time_weekday": 0.0001,   # avoid a divide-by-0
                    "elapsed_time_weekend": 0.0001,   # avoid a divide-by-0
                    "ticket_count_weekday": 0,
                    "ticket_count_weekend": 0,
                    "last_time_t": None,
                    "last_time_t_weekday": None,
                    "last_time_t_weekend": None,
                    }

    # We compare the number of tickets in the last few minutes against
    # the historical average for all time.  But we don't start "all
    # time" at AD 1, we start it a week ago.  Longer than that and it
    # takes forever due to quota issues.  That's still plenty of
    # historical data. :-)
    #
    # Zendesk seems to wait 5 minutes to update API data :-(, so we
    # ask for data that's a bit time-lagged
    end_time = int(time.time()) - 300
    start_time = old_data['last_time_t']
    print("start_time: %s, end_time: %s" % (start_time, end_time))

    # Set flag to track if current time period is a weekend. Separate
    # ticket_count/elapsed_time stats are kept for weekend vs. weekday
    # to improve sensitivity to increases during low-traffic periods
    is_off_hours = _is_off_hours(datetime.datetime.fromtimestamp(end_time))

    (new_tickets, oldest_ticket_time_t) = get_tickets_between(
        start_time or (end_time - 86400 * 7), end_time)
    num_new_tickets = len(new_tickets)

    # The first time we run this, we take the starting time to be the
    # time of the first bug report.

    if start_time is None:
        start_time = oldest_ticket_time_t

    time_this_period = end_time - start_time

    if is_off_hours:
        # To simplify backcompat we still use "weekend" and "weekday" in the
        # saved data; really they mean "on hours" and "off hours" now.
        ticket_count = old_data['ticket_count_weekend']
        elapsed_time = old_data['elapsed_time_weekend']
    else:
        ticket_count = old_data['ticket_count_weekday']
        elapsed_time = old_data['elapsed_time_weekday']

    (mean, probability) = util.probability(ticket_count,
                                           elapsed_time,
                                           num_new_tickets,
                                           time_this_period)

    print("%s] TOTAL %s/%ss; %s-: %s/%ss; m=%.3f p=%.3f"
          % (time.strftime("%Y-%m-%d %H:%M:%S %Z"),
             ticket_count, int(elapsed_time),
             start_time,
             num_new_tickets, time_this_period,
             mean, probability))

    handle_alerts(new_tickets, time_this_period, mean, probability,
                  start_time, end_time)

    if is_off_hours:
        new_data = {"elapsed_time_weekend": (
            old_data["elapsed_time_weekend"] + time_this_period),
            "ticket_count_weekend": (
            old_data["ticket_count_weekend"] + num_new_tickets),
            "elapsed_time_weekday": old_data["elapsed_time_weekday"],
            "ticket_count_weekday": old_data["ticket_count_weekday"],
        }
    else:
        new_data = {"elapsed_time_weekend": old_data["elapsed_time_weekend"],
                    "ticket_count_weekend": old_data["ticket_count_weekend"],
                    "elapsed_time_weekday": (
                        old_data["elapsed_time_weekday"] + time_this_period),
                    "ticket_count_weekday": (
                        old_data["ticket_count_weekday"] + num_new_tickets),
                    }

    new_data['last_time_t'] = end_time

    with open(zendesk_status_file, 'wb') as f:
        pickle.dump(new_data, f)


def reset_mean(weekday_mean=None, weekend_mean=None):
    zendesk_status_file = util.relative_path("zendesk")
    try:
        with open(zendesk_status_file) as f:
            data = pickle.load(f)
    except (IOError, EOFError):
        data = {"elapsed_time_weekday": 0.0001,   # avoid a divide-by-0
                "elapsed_time_weekend": 0.0001,   # avoid a divide-by-0
                "ticket_count_weekday": 0,
                "ticket_count_weekend": 0,
                "last_time_t": None,
                "last_time_t_weekday": None,
                "last_time_t_weekend": None,
                }

    if weekday_mean is not None:
        # Note: on python 2.7
        print("Resetting from weekday from {} to {}".format(
            1.0 * data['ticket_count_weekday'] / data['elapsed_time_weekday'],
            weekday_mean
        ))
        data['ticket_count_weekday'] = weekday_mean * \
            data['elapsed_time_weekday']

    if weekend_mean is not None:
        print("Resetting from weekend from {} to {}".format(
            1.0 * data['ticket_count_weekend'] / data['elapsed_time_weekend'],
            weekend_mean
        ))
        data['ticket_count_weekend'] = weekend_mean * \
            data['elapsed_time_weekend']

    with open(zendesk_status_file, 'w') as f:
        pickle.dump(data, f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Script to predict abnormal zendesk alerts.'
    )
    parser.add_argument('--reset_weekday', type=int,
                        help='Hard reset weekday mean to expected value.')
    parser.add_argument('--reset_weekend', type=int,
                        help='Hard reset weekend mean to expected value.')
    args = parser.parse_args()
    if (args.reset_weekday is not None) or (args.reset_weekend is not None):
        reset_mean(args.reset_weekday, args.reset_weekend)

    main()
